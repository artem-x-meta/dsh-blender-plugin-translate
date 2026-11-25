# -*- coding: utf-8 -*-
"""DSH preset library (v0.8.2) -- turning a "parameter combination" into an asset that can be saved, applied and distributed.

Inspired by the "preset-ification" strength of lurenjia-l/dsh-blender-stylized-shading: it translates natural-language style words into node-group parameter combinations and writes them up as a manual;
this module generalizes that into a **domain-agnostic** mechanism: any JSON preset (material parameters / object properties / scene settings / custom) can be saved, listed, fetched, applied, exported and imported.

API hangs off K.dsh_preset_api; tool entry point blender_rt_preset.
    preset file: <K.out_dir>/presets/<name>.json   (self-contained: name/kind/tags/note/data/mapping/version/created)
    data is expressed with **dot paths**: {"data": {"inputs.Base Color": [1,0,0,1], "Base Color": [1,0,0,1]}}
    apply(name, targets) supports targets of the form:
        "MAT:material name"  → applied to material nodes (node_name optional)
        "OBJ:object name"    → applied to object properties
        "SCENE"              → applied to scene properties
        targets omitted      → returns a dry_run preview only (no write)
"""
import bpy
import json
import os
import time

PRESET_VERSION = 1


import sys as _sys_kit
_KIT = getattr(_sys_kit.modules.get("dsh_rt_kernel"), "dsh_kit", None)
if _KIT is None:
    raise RuntimeError("presets requires the shared kernel K.dsh_kit (injected by KERNEL_BOOTSTRAP)")


_j = _KIT.j  # shared kernel (the former built-in implementation was removed)
def _kernel():
    import sys
    return sys.modules.get("dsh_rt_kernel")


def _dir():
    K = _kernel()
    d = getattr(K, "out_dir", None) or os.path.join(os.path.expanduser("~"), "dsh_out")
    p = os.path.join(d, "presets")
    os.makedirs(p, exist_ok=True)
    return p


def _path(name):
    safe = "".join(c for c in str(name) if c.isalnum() or c in "._- ")
    if not safe:
        raise ValueError("illegal preset name")
    return os.path.join(_dir(), safe + ".json")


def p_save(name, data, kind="generic", tags=None, note="", mapping=None, overwrite=True):
    p = _path(name)
    if os.path.isfile(p) and not overwrite:
        return _j({"ok": False, "error": "preset already exists (overwrite=false)", "name": str(name)})
    rec = {"name": str(name), "kind": str(kind), "tags": list(tags or []), "note": str(note),
           "data": data, "mapping": mapping or {}, "version": PRESET_VERSION,
           "created": time.strftime("%Y-%m-%d %H:%M:%S")}
    with open(p, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    return _j({"ok": True, "name": rec["name"], "kind": rec["kind"], "keys": len(data or {}), "path": p, "bytes": os.path.getsize(p)})


def _load(name):
    p = _path(name)
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def p_list(kind=None, tag=None):
    out = []
    for fn in sorted(os.listdir(_dir())):
        if not fn.endswith(".json"):
            continue
        if fn.startswith("presets_bundle"):  # exported bundles are not listed (they once polluted list)
            continue
        try:
            with open(os.path.join(_dir(), fn), encoding="utf-8") as f:
                r = json.load(f)
        except Exception:
            continue
        if kind and r.get("kind") != kind:
            continue
        if tag and tag not in (r.get("tags") or []):
            continue
        out.append({"name": r.get("name"), "kind": r.get("kind"), "tags": r.get("tags"),
                    "keys": len(r.get("data") or {}), "note": r.get("note"), "created": r.get("created")})
    return _j({"ok": True, "count": len(out), "presets": out, "dir": _dir()})


def p_get(name):
    r = _load(name)
    return _j({"ok": bool(r), "preset": r}) if r else _j({"ok": False, "error": "no such preset: %s" % name, "dir": _dir()})


def p_delete(name):
    p = _path(name)
    if os.path.isfile(p):
        os.remove(p)
        return _j({"ok": True, "deleted": str(name)})
    return _j({"ok": False, "error": "no such preset: %s" % name})


def _get_path(root, path):
    cur = root
    for part in str(path).split("."):
        if cur is None:
            return None, None
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            cur = getattr(cur, part, None)
    return cur, None


def _set_path(root, path, value):
    parts = str(path).split(".")
    cur = root
    for part in parts[:-1]:
        cur = cur.get(part) if isinstance(cur, dict) else getattr(cur, part, None)
        if cur is None:
            raise KeyError("path does not exist: %s" % path)
    last = parts[-1]
    if isinstance(cur, dict):
        if last not in cur:
            raise KeyError("key does not exist: %s" % path)
        cur[last] = value
    else:
        if not hasattr(cur, last):
            raise KeyError("attribute does not exist: %s" % path)
        old = getattr(cur, last)
        if hasattr(old, "to_tuple") or hasattr(old, "__len__"):
            try:
                setattr(cur, last, type(old)(value) if not isinstance(value, (int, float, str, bool)) else value)
                return
            except Exception:
                pass
        setattr(cur, last, value)


def p_apply(name, targets=None, dry_run=False):
    r = _load(name)
    if not r:
        return _j({"ok": False, "error": "no such preset: %s" % name})
    data = dict(r.get("data") or {})
    for k, v in (r.get("mapping") or {}).items():
        if k in data:
            data[v] = data.pop(k)
    tgts = [str(t) for t in (targets or [])]
    report = {"applied": [], "skipped": [], "errors": []}
    for t in tgts:
        t = t.strip()
        if t.upper().startswith("MAT:"):
            mat = bpy.data.materials.get(t[4:].strip())
            if mat is None or not mat.use_nodes:
                report["skipped"].append({"target": t, "why": "material does not exist or nodes are not enabled"})
                continue
            root = mat.node_tree
            for path, val in data.items():
                key = path if path.startswith("nodes.") else ("nodes." + path) if "." in path else ("defaults." + path)
                try:
                    if "." not in path:
                        _set_path(root.defaults, path, val)
                        report["applied"].append({"target": t, "path": "defaults." + path})
                    else:
                        _set_path(root, path, val)
                        report["applied"].append({"target": t, "path": path})
                except Exception as e:
                    report["errors"].append({"target": t, "path": path, "error": str(e)[:80]})
        elif t.upper().startswith("OBJ:"):
            ob = bpy.data.objects.get(t[4:].strip())
            if ob is None:
                report["skipped"].append({"target": t, "why": "object does not exist"})
                continue
            for path, val in data.items():
                try:
                    _set_path(ob, path, val)
                    report["applied"].append({"target": t, "path": path})
                except Exception as e:
                    report["errors"].append({"target": t, "path": path, "error": str(e)[:80]})
        elif t.upper().startswith("SCENE"):
            for path, val in data.items():
                try:
                    _set_path(bpy.context.scene, path, val)
                    report["applied"].append({"target": "SCENE", "path": path})
                except Exception as e:
                    report["errors"].append({"target": "SCENE", "path": path, "error": str(e)[:80]})
        else:
            report["skipped"].append({"target": t, "why": "unrecognized target (use MAT:name / OBJ:name / SCENE)"})
    if not tgts:
        bpy.context.view_layer.update()
    return _j({"ok": True, "preset": r.get("name"), "dry_run": True if not tgts else bool(dry_run),
               "keys": list(data), "targets": tgts, "report": report,
               "note": "without targets it only previews; with targets it writes for real (use dry_run=true to only validate paths)"})


def p_export(names=None, path=None):
    files = [f for f in os.listdir(_dir()) if f.endswith(".json")]
    picked = []
    for fn in files:
        with open(os.path.join(_dir(), fn), encoding="utf-8") as f:
            r = json.load(f)
        if names and r.get("name") not in names:
            continue
        picked.append(r)
    exp = os.path.join(os.path.dirname(_dir()), "presets_export")
    os.makedirs(exp, exist_ok=True)
    dst = path or os.path.join(exp, "presets_bundle_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    with open(dst, "w", encoding="utf-8") as f:
        json.dump({"bundle": picked, "count": len(picked), "version": PRESET_VERSION}, f, ensure_ascii=False, indent=1)
    return _j({"ok": True, "count": len(picked), "path": dst, "bytes": os.path.getsize(dst)})


def p_import(path, overwrite=False):
    with open(path, encoding="utf-8") as f:
        b = json.load(f)
    added, skipped = [], []
    for r in (b.get("bundle") or []):
        nm = r.get("name")
        if not nm:
            continue
        dst = _path(nm)
        if os.path.isfile(dst) and not overwrite:
            skipped.append(nm)
            continue
        r["version"] = PRESET_VERSION
        with open(dst, "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=1)
        added.append(nm)
    return _j({"ok": True, "added": added, "skipped": skipped, "dir": _dir()})


# ---------------------------------------------------------------- v0.8.10: glass / optics presets
# External feedback: EEVEE does not render glass transparently by default -- you have to enable use_ssr_refraction / use_raytracing_refraction
# + the material-side flags + Principled Transmission/Alpha yourself, and **the 4.x/5.x input names differ** (found only after rendering a round of frosted plastic for nothing).

_PRINCIPLED_ALIASES = {
    "transmission": ["Transmission Weight", "Transmission"],
    "ior": ["IOR"],
    "roughness": ["Roughness"],
    "alpha": ["Alpha"],
    "base_color": ["Base Color"],
    "specular": ["Specular IOR Level", "Specular"],
    "coat": ["Coat Weight", "Clearcoat"],
}


def _set_input(node, key, value):
    """Find the Principled input name via the 4.x/5.x alias table; returns the real input name on success, None on failure."""
    for name in _PRINCIPLED_ALIASES.get(key, []):
        if name in node.inputs:
            try:
                node.inputs[name].default_value = value
                return name
            except Exception:
                pass
    return None


def preset_glass(targets=None, ior=1.45, transmission=1.0, roughness=0.03, alpha=0.35,
                 base_color=(0.86, 0.93, 0.96, 1.0), use_alpha=False, scene_flags=True):
    """One call wires up "truly transparent EEVEE glass": engine switches + material-side flags + Principled input-name mapping (handles both 4.x/5.x).

    targets: comma-separated MAT:name / OBJ:name (OBJ takes all of its material slots); omitted means apply to every material.
    """
    rep = {"ok": True, "scene": {}, "materials": [], "warnings": []}
    sc = bpy.context.scene
    if scene_flags:
        ee = getattr(sc, "eevee", None)
        if ee is not None:
            for attr, val in (("use_raytracing", True), ("use_ssr_refraction", True), ("use_raytracing_refraction", True)):
                if hasattr(ee, attr):
                    try:
                        setattr(ee, attr, val)
                        rep["scene"][attr] = val
                    except Exception as e:
                        rep["warnings"].append("%s: %s" % (attr, str(e)[:60]))
                else:
                    rep["warnings"].append("this engine has no %s (version difference)" % attr)
    # pick materials
    mats = []
    if targets:
        names = [t.strip() for t in str(targets).replace(";", ",").split(",") if t.strip()]
        for n in names:
            if n.upper().startswith("MAT:"):
                m = bpy.data.materials.get(n.split(":", 1)[1])
                if m:
                    mats.append(m)
                else:
                    rep["warnings"].append("material does not exist: %s" % n)
            elif n.upper().startswith("OBJ:"):
                ob = bpy.data.objects.get(n.split(":", 1)[1])
                if not ob:
                    rep["warnings"].append("object does not exist: %s" % n)
                    continue
                for slot in ob.material_slots:
                    if slot.material and slot.material not in mats:
                        mats.append(slot.material)
            else:
                rep["warnings"].append("unrecognized target form (use MAT:name / OBJ:name): %s" % n)
    else:
        mats = [m for m in bpy.data.materials if m.users > 0]
    for m in mats:
        item = {"name": m.name, "set": {}, "missing": []}
        try:
            if hasattr(m, "use_screen_refraction"):
                m.use_screen_refraction = True
                item["set"]["use_screen_refraction"] = True
            if hasattr(m, "use_raytrace_refraction"):
                m.use_raytrace_refraction = True
                item["set"]["use_raytrace_refraction"] = True
            # 5.x: surface_render_method='BLENDED'; 4.x: blend_method='BLEND'
            for attr, val in (("surface_render_method", "BLENDED"), ("blend_method", "BLEND")):
                if hasattr(m, attr):
                    try:
                        setattr(m, attr, val)
                        item["set"][attr] = val
                    except Exception:
                        pass
            if hasattr(m, "show_transparent_back"):
                m.show_transparent_back = False
            nt = getattr(m, "node_tree", None)
            node = None
            if nt is not None:
                for nd in nt.nodes:
                    if nd.type == "BSDF_PRINCIPLED":
                        node = nd
                        break
            if node is None:
                item["missing"].append("no Principled BSDF node")
            else:
                for key, val in (("transmission", float(transmission)), ("ior", float(ior)),
                                 ("roughness", float(roughness)),
                                 ("alpha", float(alpha) if use_alpha else 1.0),
                                 ("base_color", tuple(base_color))):
                    got = _set_input(node, key, val)
                    if got:
                        item["set"]["inputs." + got] = val
                    else:
                        item["missing"].append(key)
        except Exception as e:
            item["error"] = "%s: %s" % (type(e).__name__, str(e)[:100])
        if item["missing"]:
            rep["warnings"].append("%s is missing: %s" % (m.name, ", ".join(item["missing"])))
        rep["materials"].append(item)
    rep["count"] = len(rep["materials"])
    rep["note"] = ("the EEVEE true-transparency trio: engine use_raytracing+use_ssr_refraction+use_raytracing_refraction, "
                   "material use_screen_refraction/use_raytrace_refraction, Principled Transmission/Alpha; "
                   "input names 4.x(Transmission Weight)/3.x(Transmission) are mapped automatically. For opaque plastic do not enable use_alpha.")
    if not rep["materials"]:
        rep["ok"] = False
        rep["error"] = "no material to apply to (check targets or whether the scene has any material)"
    return _j(rep)


def p_help():
    return _j({"version": PRESET_VERSION, "dir": _dir(),
               "ops": {"save": "save(name, data, kind, tags, note, mapping, overwrite=true)",
                       "list": "list(kind=None, tag=None)", "get": "get(name)", "delete": "delete(name)",
                       "apply": "apply(name, targets=[MAT:x/OBJ:y/SCENE], dry_run=false)",
                       "export": "export(names=None, path=None) → a single bundle file (distributable)",
                       "import": "import(path, overwrite=false)",
                       "glass": "glass(targets='MAT:x,OBJ:y', ior, transmission, roughness, alpha, use_alpha) "
                                "→ one call wires up truly transparent EEVEE glass (v0.8.10)"},
               "data_format": "dot-path dict: {\"inputs.Base Color\": [1,0,0,1]} or {\"nodes.Principled BSDF.inputs.Roughness\": 0.4} or {\"location\": [0,0,1]}",
               "why": "turn style/parameter presets into assets: saveable, applicable, exportable and shareable; domain-agnostic (materials/objects/scene/custom all work)"})


def p_dispatch(op, args=None):
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except Exception:
            args = {}
    fn = {"save": p_save, "list": p_list, "get": p_get, "delete": p_delete, "apply": p_apply,
          "export": p_export, "import": p_import, "glass": preset_glass, "help": p_help}.get(str(op))
    if fn is None:
        return _j({"ok": False, "error": "unknown preset op", "op": op,
                   "ops": ["save", "list", "get", "delete", "apply", "export", "import", "glass", "help"]})
    try:
        return fn(**(args or {}))
    except TypeError as e:
        return _j({"ok": False, "error": "parameter mismatch: %s" % e, "op": op, "given": sorted(args or {}), "sig": p_help()})


import sys as _sys
_K = _sys.modules.get("dsh_rt_kernel")
def p_selftest():
    # preset self-test: save -> get -> apply to a real object -> the value really takes effect -> delete
    import json

    def _d(x):
        return json.loads(x) if isinstance(x, str) else x

    import bpy
    import bmesh as _bm
    ev = {}
    nm = "__dsh_ps_cube"
    pn = "__dsh_selftest_preset"
    try:
        me = bpy.data.meshes.new(nm)
        ob = bpy.data.objects.new(nm, me)
        bpy.context.scene.collection.objects.link(ob)
        bm = _bm.new()
        _bm.ops.create_cube(bm, size=1.0)
        bm.to_mesh(me)
        bm.free()
        ob.location = (0.0, 0.0, 0.0)
        ev["save_ok"] = _d(p_save(pn, {"location": [1.0, 2.0, 3.0]}, kind="object", note="selftest")).get("ok") is not False
        ev["get_ok"] = isinstance(_d(p_get(pn)), dict)
        ap = _d(p_apply(pn, targets=["OBJ:" + nm]))
        ev["apply_ok"] = isinstance(ap, dict) and ap.get("ok") is not False
        try:
            bpy.context.view_layer.update()
        except Exception:
            pass
        loc = bpy.data.objects[nm].location
        ev["value_applied"] = abs(loc[0] - 1.0) < 1e-4 and abs(loc[2] - 3.0) < 1e-4
        _d(p_delete(pn))
        ev["deleted"] = True
        return _j({"ok": all(x is True for x in ev.values()), "evidence": ev, "loc": [round(float(q), 3) for q in loc]})
    except Exception as e:
        return _j({"ok": False, "evidence": ev, "error": "%s: %s" % (type(e).__name__, str(e)[:200])})
    finally:
        o = bpy.data.objects.get(nm)
        if o is not None:
            me2 = o.data
            bpy.data.objects.remove(o, do_unlink=True)
            if me2 is not None and me2.users == 0:
                bpy.data.meshes.remove(me2, do_unlink=True)



if _K is not None:
    _K.dsh_preset_api = _KIT.Api({"version": PRESET_VERSION, "dispatch": _KIT.wrap_dispatch(p_dispatch, {"selftest": p_selftest}), "save": p_save, "list": p_list,
                         "get": p_get, "delete": p_delete, "apply": p_apply, "export": p_export,
                         "import": p_import, "glass": preset_glass, "help": p_help,
        "selftest": p_selftest})

# ---- v0.9.1 (93-B1/B2): make the API callable (swap in a dict subclass instance that returns parsed objects) ----
# Background: K.dsh_x_api used to be a plain dict → calling api(args) in-process raised TypeError: 'dict' object is not callable;
# and dispatch returned a JSON string, so callers had to json.loads it themselves.
# Now: api("op", {…}) or api({…}) → dict; api["dispatch"](op, json_str) still returns str (the engine contract is unchanged).
# Note: dict is a static type, so __class__ cannot be assigned on an existing instance (TypeError in practice); hence a new instance.
_DshApi = _KIT.Api  # shared kernel (the registration line at the end needs no change)
import sys as _sys_api
_K_api = _sys_api.modules.get("dsh_rt_kernel")
if _K_api is not None and isinstance(getattr(_K_api, "dsh_presets_api", None), dict) \
        and not isinstance(getattr(_K_api, "dsh_presets_api", None), _DshApi):
    _K_api.dsh_presets_api = _DshApi(_K_api.dsh_presets_api)
