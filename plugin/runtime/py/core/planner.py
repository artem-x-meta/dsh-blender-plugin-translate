# -*- coding: utf-8 -*-
"""DSH planner — object graph (Component / Connection / Feature) + compilation to bpy + dependency diagnostics.

API hangs off the persistent kernel: K.dsh_plan_api. Design rules (matching the "planner" in issue #3):
    * the Planner only touches **generic objects**: Component / Connection / Feature;
    * the concrete Blender operations come from **compiling the object graph** (build() in this module);
    * errors are reported against the **object contract**, with diagnostic codes handed out IDE-style:
        MissingComponent / MissingObject / UnresolvedConnection /
        UnsupportedDestructiveMerge / Cycle / ParamOutOfRange
    * the graph is exportable (mermaid / dot), convenient for humans to read and archive.

plan structure (JSON):
{
  "id": "chair",
  "envelope": {"min": [-0.5,-0.5,0], "max": [0.5,0.5,1.5]},        # optional: build the envelope automatically after compiling
  "components": [
    {"id":"seat","kind":"box","params":{"size":[0.45,0.45,0.05],"loc":[0,0,0.475]},
     "tags":["seat"],"range":{"size":[0.3,0.6]}},
    {"id":"backrest","kind":"box","params":{"size":[0.45,0.03,0.50],"loc":[0,0.25,0.70]}},
    {"id":"tenon","kind":"box","params":{"size":[0.10,0.06,0.06],"loc":[0,0.195,0.465]},
     "hidden_when":{"connection":"joint","candidate":"attach"}}      # exists only under a certain candidate
  ],
  "connections": [
    {"id":"joint","a":"seat","b":"backrest","candidates":["attach","insert"],
     "candidate":"insert","status":"unresolved","forbidden":["boolean_union","weld"],
     "offset":{"translate":[0,0.01,0]}}
  ],
  "features": [
    {"id":"slats","kind":"array","src":"backrest","count":3,"offset":[0,0,0.06],
     "depends_on":["backrest","joint"]}
  ]
}
"""
import bpy, json, math, time

PLAN_VERSION = 1


import sys as _sys_kit
_KIT = getattr(_sys_kit.modules.get("dsh_rt_kernel"), "dsh_kit", None)
if _KIT is None:
    raise RuntimeError("planner needs the shared kernel K.dsh_kit (injected by KERNEL_BOOTSTRAP)")


_j = _KIT.j  # shared kernel (the original built-in implementation has been removed)
def _kernel():
    import sys
    return sys.modules.get("dsh_rt_kernel")


def _store():
    K = _kernel()
    if K is None:
        raise RuntimeError("the persistent kernel K is required (go through the blender_rt_* channel)")
    if not hasattr(K, "dsh_plan"):
        K.dsh_plan = {"plan": None, "build": None, "log": []}
    return K.dsh_plan


def _log(action, detail):
    st = _store()
    st["log"].append({"t": time.strftime("%H:%M:%S"), "action": action, "detail": detail})
    del st["log"][:-200]


# ---------------------------------------------------------------- load / validate

def p_load(plan):
    if isinstance(plan, str):
        s = plan.strip()
        if s.startswith("{"):
            plan = json.loads(s)
        else:
            with open(s, encoding="utf-8") as f:
                plan = json.load(f)
    if not isinstance(plan, dict):
        return _j({"ok": False, "error": "plan must be a JSON object or a path"})
    comps = {c["id"]: c for c in plan.get("components", []) if isinstance(c, dict) and c.get("id")}
    conns = {c["id"]: c for c in plan.get("connections", []) if isinstance(c, dict) and c.get("id")}
    feats = {f["id"]: f for f in plan.get("features", []) if isinstance(f, dict) and f.get("id")}
    st = _store()
    st["plan"] = {"id": plan.get("id", "plan"), "envelope": plan.get("envelope"),
                  "components": comps, "connections": conns, "features": feats,
                  "raw": plan, "loaded": time.strftime("%Y-%m-%d %H:%M:%S")}
    _log("load", {"id": st["plan"]["id"], "components": len(comps), "connections": len(conns), "features": len(feats)})
    d = json.loads(p_diag())
    return _j({"ok": True, "id": st["plan"]["id"], "counts": {"components": len(comps), "connections": len(conns),
                                                              "features": len(feats)},
               "diagnostics": d["diagnostics"]})


def p_diag():
    st = _store()
    pl = st["plan"]
    if not pl:
        return _j({"ok": False, "error": "no plan loaded yet (op=load first)", "diagnostics": []})
    comps, conns, feats = pl["components"], pl["connections"], pl["features"]
    D = []

    def add(code, msg, target=None, fix=None):
        D.append({"code": code, "message": msg, "target": target, "fix": fix})

    for cid, c in comps.items():
        kind = c.get("kind", "box")
        if kind not in ("box", "cylinder", "sphere", "mesh_copy"):
            add("UnknownKind", "component %s has unsupported kind=%s" % (cid, kind), cid, "box/cylinder/sphere/mesh_copy")
        rng = (c.get("range") or {}).get("size")
        sz = (c.get("params") or {}).get("size")
        if rng and sz:
            for v in sz:
                if v < rng[0] or v > rng[1]:
                    add("ParamOutOfRange", "component %s size=%s is outside the declared range %s" % (cid, sz, rng), cid, "shrink/enlarge into the range")
        if kind == "mesh_copy" and not (c.get("params") or {}).get("src"):
            add("MissingComponent", "mesh_copy component %s is missing params.src" % cid, cid, "name a source object")
    for k, cn in conns.items():
        for side in ("a", "b"):
            if cn.get(side) not in comps:
                add("MissingComponent", "connection %s has undefined %s=%s" % (k, side, cn.get(side)), k, "add the component or fix the reference")
        if cn.get("candidate") and cn.get("candidates") and cn["candidate"] not in cn["candidates"]:
            add("MissingComponent", "connection %s candidate=%s is not in candidates" % (k, cn["candidate"]), k, "")
        if cn.get("status") not in ("supported",):
            if cn.get("forbidden"):
                add("UnresolvedConnection",
                    "connection %s is undecided (status=%s) yet declares forbidden items %s" % (k, cn.get("status"), cn["forbidden"]), k,
                    "decide it per the cookbook first (external + probes), or drop the forbidden items")
        if "boolean_union" in (cn.get("forbidden") or []) and (cn.get("apply") or {}).get("boolean_union"):
            add("UnsupportedDestructiveMerge", "connection %s forbids boolean_union yet still asks to run it" % k, k, "delete that apply")
    # dependencies and cycles
    graph = {fid: list(f.get("depends_on") or []) for fid, f in feats.items()}
    for fid, deps in graph.items():
        for d in deps:
            if d not in feats and d not in comps and d not in conns:
                add("MissingComponent", "feature %s depends on %s, which does not exist" % (fid, d), fid, "add the component/connection/feature")
            if d in conns and conns[d].get("status") != "supported":
                add("UnresolvedConnection", "feature %s depends on undecided connection %s" % (fid, d), fid,
                    "decide that connection first, or let the feature not depend on it for now")
    # topological sort to look for cycles
    seen, stack = {}, []

    def visit(n):
        if seen.get(n) == 1:
            add("Cycle", "dependency cycle: " + " -> ".join(stack + [n]), n, "break one dependency")
            return
        if seen.get(n) == 2:
            return
        seen[n] = 1
        stack.append(n)
        for d in graph.get(n, []):
            if d in graph:
                visit(d)
        stack.pop()
        seen[n] = 2

    for fid in graph:
        visit(fid)
    # objects that only appear after compiling (checked once in the scene; at build time the object name = PLAN_<id>)
    for cid, c in comps.items():
        for oname in (c.get("objects") or []):
            if bpy.data.objects.get(oname) is None:
                add("MissingObject", "component %s declares object %s that is not in the scene" % (cid, oname), cid, "build first or fix the object name")
    return _j({"ok": True, "diagnostics": D,
               "summary": {"errors": len([d for d in D if d["code"] != "MissingObject"]),
                           "warnings": len([d for d in D if d["code"] == "MissingObject"])}})


def p_order():
    st = _store()
    if not st["plan"]:
        return _j({"ok": False, "error": "no plan loaded yet"})
    pl = st["plan"]; comps, conns, feats = pl["components"], pl["connections"], pl["features"]
    order = []
    done = set()
    pend_c = list(comps)
    pend_f = list(feats)
    while True:
        progressed = False
        for n in list(pend_c):                      # ① components (no dependencies)
            order.append({"node": n, "kind": "component"}); done.add(n); pend_c.remove(n); progressed = True
        for k, cn in conns.items():                 # ② connections (both end components ready)
            if k not in done and cn.get("a") in done and cn.get("b") in done:
                order.append({"node": k, "kind": "connection"}); done.add(k); progressed = True
        for fid in list(pend_f):                    # ③ features (all dependencies ready; a dependency may be a component/connection/feature)
            deps = list(feats[fid].get("depends_on") or [])
            if all(d in done for d in deps):
                order.append({"node": fid, "kind": "feature"}); done.add(fid); pend_f.remove(fid); progressed = True
        if not progressed:
            break
    blocked = [n for n in (pend_c + pend_f)] + [k for k in conns if k not in done]
    return _j({"ok": True, "order": order, "blocked": blocked,
               "counts": {"components": len(comps), "connections": len(conns), "features": len(feats)}})


# ---------------------------------------------------------------- compile to bpy

def _make_component(cid, c, suffix=""):
    kind = c.get("kind", "box")
    pr = c.get("params") or {}
    name = "PLAN_%s%s" % (cid, suffix)
    loc = pr.get("loc", [0, 0, 0])
    rot = pr.get("rot", [0, 0, 0])
    if kind == "box":
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=loc)
        ob = bpy.context.object
        ob.scale = pr.get("size", [1, 1, 1])
    elif kind == "cylinder":
        bpy.ops.mesh.primitive_cylinder_add(radius=pr.get("radius", 0.1), depth=pr.get("depth", 0.5), location=loc)
        ob = bpy.context.object
    elif kind == "sphere":
        bpy.ops.mesh.primitive_uv_sphere_add(radius=pr.get("radius", 0.1), location=loc)
        ob = bpy.context.object
    elif kind == "mesh_copy":
        src = bpy.data.objects.get(pr.get("src"))
        if src is None:
            raise RuntimeError("mesh_copy source does not exist: %s" % pr.get("src"))
        ob = src.copy(); ob.data = src.data.copy(); bpy.context.scene.collection.objects.link(ob)
    else:
        raise RuntimeError("unknown kind: %s" % kind)
    ob.name = name
    ob.rotation_euler = (math.radians(rot[0]), math.radians(rot[1]), math.radians(rot[2]))
    ob.select_set(False)
    return ob


def p_build(dry_run=True, replace=True):
    st = _store()
    pl = st["plan"]
    if not pl:
        return _j({"ok": False, "error": "no plan loaded yet"})
    d = json.loads(p_diag())
    hard = [x for x in d["diagnostics"] if x["code"] in ("MissingComponent", "Cycle", "UnknownKind")]
    if hard:
        return _j({"ok": False, "blocked": True, "code": "PlanInvalid",
                   "diagnostics": hard, "message": "hard errors are unresolved, refusing to compile (this is the IDE-style report)"})
    comps, conns, feats = pl["components"], pl["connections"], pl["features"]
    created, skipped = [], []
    # hidden_when: the connection candidate decides existence
    for cid, c in comps.items():
        hw = c.get("hidden_when")
        if hw and conns.get(hw.get("connection"), {}).get("candidate") != hw.get("candidate"):
            skipped.append({"component": cid, "why": "hidden_when: connection %s candidate != %s" % (
                hw.get("connection"), hw.get("candidate"))})
            continue
        conn_offset = None
        for k, cn in conns.items():
            if cn.get("b") == cid and cn.get("offset"):
                conn_offset = cn["offset"]
        created.append({"component": cid, "kind": c.get("kind", "box"), "connection_offset": conn_offset,
                        "object": "PLAN_%s" % cid})
    # expand features
    for fid, f in feats.items():
        created.append({"feature": fid, "kind": f.get("kind"), "count": f.get("count") or 1,
                        "src": f.get("src"), "depends_on": f.get("depends_on") or []})
    if dry_run:
        return _j({"ok": True, "dry_run": True, "would_create": created, "skipped": skipped,
                   "diagnostics": d["diagnostics"]})
    if replace:
        for cid in comps:
            for suf in [""] + ["_%d" % i for i in range(1, 33)]:
                ob = bpy.data.objects.get("PLAN_%s%s" % (cid, suf))
                if ob:
                    bpy.data.objects.remove(ob, do_unlink=True)
    # build components
    objs = {}
    for cid, c in comps.items():
        hw = c.get("hidden_when")
        if hw and conns.get(hw.get("connection"), {}).get("candidate") != hw.get("candidate"):
            continue
        try:
            ob = _make_component(cid, c)
        except Exception as e:
            return _j({"ok": False, "error": str(e), "component": cid})
        # connection offset
        for k, cn in conns.items():
            if cn.get("b") == cid and cn.get("offset", {}).get("translate"):
                t = cn["offset"]["translate"]
                ob.location = (ob.location[0] + t[0], ob.location[1] + t[1], ob.location[2] + t[2])
        objs[cid] = ob
    # build features (array / grid / mirror)
    for fid, f in feats.items():
        src = objs.get(f.get("src")) or bpy.data.objects.get(f.get("src"))
        if src is None:
            continue
        kind = f.get("kind")
        count = int(f.get("count") or 1)
        off = f.get("offset") or [0, 0, 0]
        made = []
        if kind == "array":
            for i in range(1, count + 1):
                ob = src.copy(); ob.data = src.data.copy(); bpy.context.scene.collection.objects.link(ob)
                ob.name = "PLAN_%s_%d" % (fid, i)
                ob.location = (src.location[0] + off[0] * i, src.location[1] + off[1] * i, src.location[2] + off[2] * i)
                ob.select_set(False); made.append(ob.name)
        elif kind == "grid":
            nx = int(f.get("nx") or count); ny = int(f.get("ny") or count)
            n = 1
            for ix in range(nx):
                for iy in range(ny):
                    ob = src.copy(); ob.data = src.data.copy(); bpy.context.scene.collection.objects.link(ob)
                    ob.name = "PLAN_%s_%d" % (fid, n); n += 1
                    ob.location = (src.location[0] + off[0] * ix, src.location[1] + off[1] * iy, src.location[2])
                    ob.select_set(False); made.append(ob.name)
        elif kind == "mirror":
            axis = f.get("axis", 0)
            ob = src.copy(); ob.data = src.data.copy(); bpy.context.scene.collection.objects.link(ob)
            ob.name = "PLAN_%s_mirror" % fid
            loc = list(src.location); loc[axis] = -loc[axis]
            ob.location = loc
            ob.scale = list(src.scale); ob.scale[axis] = -ob.scale[axis]
            ob.select_set(False); made.append(ob.name)
    bpy.context.view_layer.update()
    bpy.context.evaluated_depsgraph_get().update()
    st["build"] = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "objects": len(objs)}
    _log("build", {"components": len(objs)})
    # build the envelope automatically after compiling (if the plan declares one)
    env_note = None
    if pl.get("envelope"):
        K = _kernel(); env = pl["envelope"]; scope = [o.name for o in objs.values()]
        if hasattr(K, "dsh_contract_api"):
            K.dsh_contract_api["register_envelope"]("plan_env", env["min"], env["max"], scope, "built by the plan compiler")
            env_note = json.loads(K.dsh_contract_api["check_envelope"]("plan_env"))["envelopes"][0]
    return _j({"ok": True, "created_components": len(objs), "objects": sorted(o.name for o in objs.values()),
               "envelope_check": env_note, "note": "compiled object names are prefixed PLAN_; connection offsets applied; features expanded"})


def p_graph(fmt="mermaid"):
    st = _store()
    pl = st["plan"]
    if not pl:
        return _j({"ok": False, "error": "no plan loaded yet"})
    comps, conns, feats = pl["components"], pl["connections"], pl["features"]
    if fmt == "dot":
        L = ["digraph plan {", '  rankdir="LR";']
        for cid in comps:
            L.append('  "%s" [shape=box];' % cid)
        for k, cn in conns.items():
            L.append('  "%s" -> "%s" [label="%s (%s)"];' % (cn.get("a"), cn.get("b"), k, cn.get("status", "?")))
        for fid, f in feats.items():
            L.append('  "%s" [shape=ellipse];' % fid)
            for d in (f.get("depends_on") or []):
                L.append('  "%s" -> "%s";' % (d, fid))
        L.append("}")
        return _j({"ok": True, "fmt": "dot", "text": "\n".join(L)})
    L = ["graph LR"]
    for cid in comps:
        L.append('  %s["%s (component)"]' % (cid, cid))
    for k, cn in conns.items():
        L.append('  %s -- "%s [%s]" --> %s' % (cn.get("a"), k, cn.get("status", "?"), cn.get("b")))
    for fid, f in feats.items():
        L.append('  %s(("%s (feature)"))' % (fid, fid))
        for d in (f.get("depends_on") or []):
            L.append('  %s --> %s' % (d, fid))
    return _j({"ok": True, "fmt": "mermaid", "text": "\n".join(L)})


def p_status():
    st = _store()
    pl = st["plan"]
    if not pl:
        return _j({"ok": True, "loaded": False})
    d = json.loads(p_diag())
    o = json.loads(p_order())
    return _j({"ok": True, "loaded": True, "id": pl["id"],
               "counts": {"components": len(pl["components"]), "connections": len(pl["connections"]),
                          "features": len(pl["features"])},
               "diagnostics": d["diagnostics"], "build_order": o["order"], "blocked": o["blocked"],
               "last_build": st.get("build")})


def p_help():
    return _j({"version": PLAN_VERSION,
               "ops": {"load": "plan (JSON object / JSON string / file path) → load it and emit diagnostics",
                       "validate": "→ the diagnostic list (MissingComponent / UnresolvedConnection / Cycle / ...)",
                       "order": "→ topological compile order (dependencies first)",
                       "build": "dry_run (default True) / replace → compile into PLAN_* objects; dry_run only shows the plan",
                       "graph": "fmt=mermaid|dot → graph text",
                       "status": "→ overview + diagnostics + compile order"},
               "component_kinds": ["box", "cylinder", "sphere", "mesh_copy"],
               "feature_kinds": ["array", "grid", "mirror"],
               "diagnostic_codes": ["MissingComponent", "MissingObject", "UnresolvedConnection",
                                    "UnsupportedDestructiveMerge", "Cycle", "ParamOutOfRange", "UnknownKind", "PlanInvalid"],
               "docs": "docs/assumption-driven-modeling-cookbook.md (split of duties with the contract layer / inner loop)"})


def p_dispatch(op, args=None):
    """Single entry point: the tool side calls plan_<op> (load/validate/order/build/graph/status/help)."""
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except Exception:
            args = {}
    kw = {}
    for k, v in (args or {}).items():
        if k == "args" and isinstance(v, dict):
            kw.update(v)
        else:
            kw[k] = v
    alias = {"validate": "diag", "help": "help"}
    name = alias.get(str(op), str(op))
    fn = p_ops().get(name)
    if fn is None:
        return _j({"ok": False, "error": "unknown plan op", "op": op, "ops": sorted(p_ops())})
    # the tool side commonly uses "plan" as the parameter name, so accept it as plan=
    if "plan" in kw and name == "load":
        pass
    try:
        return fn(**kw)
    except TypeError as e:
        return _j({"ok": False, "error": "argument mismatch: %s" % e, "op": op, "given": sorted(kw),
                   "sig_hint": p_help()})


def p_ops():
    return {"load": p_load, "diag": p_diag, "validate": p_diag, "order": p_order,
            "build": p_build, "graph": p_graph, "status": p_status, "help": p_help}


import sys as _sys
_K = _sys.modules.get("dsh_rt_kernel")
def p_selftest():
    # planner self-test: status / diag / graph must all return structured receipts
    import json

    def _d(x):
        return json.loads(x) if isinstance(x, str) else x

    ev = {}
    try:
        ev["status_dict"] = isinstance(_d(p_status()), dict)
        ev["diag_dict"] = isinstance(_d(p_diag()), dict)
        ev["graph_dict"] = isinstance(_d(p_graph()), dict)
        return _j({"ok": all(x is True for x in ev.values()), "evidence": ev})
    except Exception as e:
        return _j({"ok": False, "evidence": ev, "error": "%s: %s" % (type(e).__name__, str(e)[:200])})



if _K is not None:
    _K.dsh_plan_api = _KIT.Api({"version": PLAN_VERSION, "dispatch": _KIT.wrap_dispatch(p_dispatch, {"selftest": p_selftest}),
                       "load": p_load, "diag": p_diag, "order": p_order,
                       "build": p_build, "graph": p_graph, "status": p_status, "help": p_help,
        "selftest": p_selftest})
    # add a "planner diagnostics" entry to the contract layer (linked with )
    if hasattr(_K, "dsh_contract_api"):
        _K.dsh_contract_api["plan_diag"] = p_diag

# ---- v0.9.1 (93-B1/B2): make the API callable (swap in a dict subclass instance that returns already-parsed objects) ----
# Background: K.dsh_x_api used to be a plain dict → in-process api(args) raised TypeError: 'dict' object is not callable;
# and dispatch returned a JSON string, so callers had to json.loads it themselves.
# Now: api("op", {…}) or api({…}) → dict; api["dispatch"](op, json_str) still returns str (the engine contract is unchanged).
# Note: dict is a static type, so assigning __class__ on an existing instance does not work (measured TypeError), hence a new instance.
_DshApi = _KIT.Api  # shared kernel (the trailing registration line needs no change)
import sys as _sys_api
_K_api = _sys_api.modules.get("dsh_rt_kernel")
if _K_api is not None and isinstance(getattr(_K_api, "dsh_planner_api", None), dict) \
        and not isinstance(getattr(_K_api, "dsh_planner_api", None), _DshApi):
    _K_api.dsh_planner_api = _DshApi(_K_api.dsh_planner_api)
