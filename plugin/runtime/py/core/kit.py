# -*- coding: utf-8 -*-
"""DSH shared kernel (kit) — the **single implementation**: JSON/API boilerplate, units, geometry, measurement, receipt skeleton.

Why it exists: previously 26 modules each copied `class _DshApi` / `def _j` / dispatch / unit conversion / BVH / IoU,
~800-1500 lines of the same plumbing, and conventions drifted while being copied (contract.py and deliver.py each hit the same dict-vs-Api pitfall).

How to use: kit is injected by KERNEL_BOOTSTRAP (registered as K.dsh_kit), so **every injection path has it**:
    K = sys.modules.get("dsh_rt_kernel")
    _KIT = getattr(K, "dsh_kit", None)          # None means bootstrap did not run (standalone scripts must handle it themselves)
    _j = _KIT.j ; Api = _KIT.Api ; dispatch = _KIT.dispatch ; units = _KIT.units

Convention: kit holds only what "**every module would otherwise rewrite**"; domain logic always stays in its own module.
"""
import json
import os
import sys
import types

KIT_VERSION = 1

# Domain package layout (Phase E): runtime/py/<domain>/ is the real implementation; runtime/<name>.py keeps only a shim.
RUNTIME_DOMAINS = ("core", "geometry", "assembly", "render", "export")


def _kernel():
    K = sys.modules.get("dsh_rt_kernel")
    if K is None:
        K = types.ModuleType("dsh_rt_kernel")
        sys.modules["dsh_rt_kernel"] = K
    return K


def find_runtime_file(name):
    """Locate a runtime-side file by name: domain packages first, old flat layout as fallback.

    Background: modules no longer all live on the same runtime/ level. qc.py finds qc_render.py, qc_render.py finds montage.py,
    contract.py finds assembly_features.json — all go through here instead of each hardcoding its own path.

    Lookup order:
      1) K.runtime_dir (runtime root injected by the engine): py/<domain>/ → py/ → root;
      2) this file's directory (normal import: py/core): same dir → sibling domain packages → runtime root.
    K.runtime_dir may itself be py/core (the old offline bootstrap usage that passed runtime_dir),
    in which case step 1 misses everything and step 2 catches it by kit.py's actual location.
    """
    name = str(name or "")
    if not name:
        return None
    try:
        K = _kernel()
        rd = getattr(K, "runtime_dir", None)
    except Exception:
        rd = None
    cands = []
    if rd:
        rd = str(rd)
        for d in RUNTIME_DOMAINS:
            cands.append(os.path.join(rd, "py", d, name))
        cands.append(os.path.join(rd, "py", name))
        cands.append(os.path.join(rd, name))
    try:
        here = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        here = ""
    if here:
        cands.append(os.path.join(here, name))
        up = os.path.dirname(here)
        for d in RUNTIME_DOMAINS:
            cands.append(os.path.join(up, d, name))
        cands.append(os.path.join(os.path.dirname(up), name))
    seen = set()
    for c in cands:
        if c in seen:
            continue
        seen.add(c)
        try:
            if os.path.isfile(c):
                return c
        except Exception:
            continue
    return None


# ────────────────────────────── JSON / receipt ──────────────────────────────
def j(obj):
    """Unified JSON serialisation (non-ASCII is not escaped; non-JSON types degrade to str)."""
    return json.dumps(obj, ensure_ascii=False, default=str)


def err(msg, **kw):
    """Unified error receipt."""
    d = {"ok": False, "error": str(msg)[:300]}
    d.update(kw)
    return j(d)


def receipt(ok=None, state=None, verdict=None, **kw):
    """Unified receipt skeleton: the ok / state / verdict / units quartet + any extra fields.

    Relationship between state and verdict (same as gate v3): state is for "did this item succeed", verdict is for the three-state judgement;
    include whichever one the caller supplies, and never invent what is not supplied.
    """
    d = {}
    if ok is not None:
        d["ok"] = bool(ok)
    if state is not None:
        d["state"] = state
    if verdict is not None:
        d["verdict"] = verdict
    d["units"] = {"mm_per_unit": units()}
    d.update(kw)
    return d


# ────────────────────────────── units ──────────────────────────────
def units():
    """mm_per_unit = scene.unit_settings.scale_length * 1000 (Blender default 1 unit = 1 m ⇒ 1000)."""
    try:
        import bpy
        return float(bpy.context.scene.unit_settings.scale_length or 1.0) * 1000.0
    except Exception:
        return 1000.0


def mm(v):
    """Blender units → millimetres."""
    return float(v) * units()


# ────────────────────────────── cross-module API ──────────────────────────────
def api(name):
    """Fetch another module's API (`K.dsh_<name>_api`); returns None when it was not injected."""
    return getattr(_kernel(), "dsh_%s_api" % name, None)


class Api(dict):
    """The standard shape of a module API: indexable as a dict + directly callable (in-process `api(op, args)`).

    Historical pitfall: the API used to be a plain dict ⇒ in-process `api(args)` raised TypeError: dict object is not callable;
    two modules each wrote their own conversion shim. Defined once here — modules must not build their own again.

    default_op is the module-level contract: `api({...})` dispatches through it; when undeclared it keeps the historical help behaviour.
    `api()` is always help, and `api["dispatch"](op, json)` still returns the raw str.
    """

    def __init__(self, *args, default_op="help", **kwargs):
        super().__init__(*args, **kwargs)
        self.default_op = str(default_op or "help")

    def __call__(self, op=None, args=None, **kw):
        if isinstance(op, dict):
            args, op = op, self.default_op
        elif op is None:
            op = "help"
        payload = args if isinstance(args, str) else j(dict(args or {}, **kw))
        out = self["dispatch"](str(op), payload)
        return out if isinstance(out, dict) else json.loads(out)

    def call(self, op, args=None, **kw):
        return self(op, args, **kw)


def register(name, version, ops, dispatch=None, extra=None, default_op="help"):
    """Register `K.dsh_<name>_api` as a standard Api (one line at the end of the module; stop hand-writing _DshApi).

    ops: {"op name": callable}  — they also become the API keys, so `K.dsh_x_api["op"](...)` calls directly.
    """
    def _default_dispatch(op, args_json):
        return dispatch_table(ops, op, args_json)
    d = {"version": version, "dispatch": dispatch or _default_dispatch}
    for k, v in (ops or {}).items():
        d[k] = v
    d.update(extra or {})
    a = Api(d, default_op=default_op)
    setattr(_kernel(), "dsh_%s_api" % name, a)
    return a


def resolve_refs(value, skip_keys=("out", "steps")):
    """Resolve "@artifact[.path]" inside args into real values (recursive over dict/list) — **one-shot ops and pipe_run share the same semantics**.

    The artifact table lives in K.dsh_artifacts (written by pipe_put / pipe_run's out=). A missing reference raises KeyError;
    keys in skip_keys are **not resolved** (e.g. pipe_run's out="@name" is an output name; steps is resolved in order by pipe_run itself).
    The routing layer turns this into a visible error (instead of silently using the string as an argument).
    """
    reg = getattr(_kernel(), "dsh_artifacts", None) or {}

    def _walk(v):
        if isinstance(v, str) and v.startswith("@"):
            body = v[1:]
            parts = body.split(".")
            nm = parts[0]
            if nm not in reg:
                raise KeyError("referenced artifact @%s does not exist (available: %s)" % (nm, ", ".join(sorted(reg.keys())) or "none"))
            cur = reg[nm].get("value") if isinstance(reg[nm], dict) else reg[nm]
            for p in parts[1:]:
                cur = cur[int(p)] if isinstance(cur, list) else cur[p]
            return cur
        if isinstance(v, dict):
            return {k: (x if k in skip_keys else _walk(x)) for k, x in v.items()}
        if isinstance(v, list):
            return [_walk(x) for x in v]
        return v

    return _walk(value)


def kapi(name):
    """One-line module API accessor (K.dsh_<name>_api); when missing it lists loaded modules, so nobody has to guess preload names."""
    K = _kernel()
    api = getattr(K, "dsh_%s_api" % str(name), None)
    if api is None:
        have = sorted(k[len("dsh_"):-len("_api")] for k in dir(K) if k.startswith("dsh_") and k.endswith("_api"))
        raise RuntimeError("the kernel has no K.dsh_%s_api (loaded: %s) — on the online path add it to preload (e.g. preload=%s); on the offline path use runtime/py/core/offline_bootstrap.py" % (name, have, name))
    return api


def install_kernel(ns=None):
    """Install K (and kapi) into a namespace; given none, into the caller's globals.

    Why it is needed: K is injected only into the globals of the executed script, while `import`ed lib/*.py files have their own globals
    ⇒ writing K.dsh_vehicle_api directly raises NameError. Two officially recommended options:
      * one line at the top of the file: `import sys; K = sys.modules["dsh_rt_kernel"]`
      * or call: `K.dsh_kit.install_kernel()` / `K.dsh_kit.kapi("vehicle")`
    """
    K = _kernel()
    target = ns if isinstance(ns, dict) else sys._getframe(1).f_globals
    target["K"] = K
    if getattr(K, "dsh_kit", None) is not None:
        target["kapi"] = K.dsh_kit.kapi
    return K


def comp_tree(scene=None):
    """Get the compositor node tree: scene.node_tree was removed in Blender 5.2 (moved to scene.compositing_node_group).

    Observed in the field: on 5.2, accessing scene.node_tree, or Glare's mix and Mix's blend_type, raises AttributeError deep inside helper functions.
    Fetch it from here only, so version differences are handled in one place; when it cannot be obtained, state the version convention explicitly.
    """
    import bpy
    sc = scene or bpy.context.scene
    for attr in ("compositing_node_group", "node_tree"):
        holder = getattr(sc, attr, None)
        if holder is None:
            continue
        tree = getattr(holder, "node_tree", holder)
        if tree is not None:
            return tree
    raise RuntimeError("cannot get the compositor node tree: Blender 5.2 switched to scene.compositing_node_group (the old scene.node_tree was removed); once you have it, note that Glare's mix and Mix's blend_type/mix were all renamed, so use getattr fallbacks")

def wrap_dispatch(base, extra=None):
    """Attach extra ops (such as selftest) to an existing dispatch: an extra hit goes to the extra table, otherwise it falls back to the original dispatch.

    Purpose: each module's op table is hand-written (shapes differ), so adding an op should not mean rewriting its internals.
    """
    extra = extra or {}

    def _d(op, args_json=None):
        fn = extra.get(str(op))
        if fn is not None:
            return dispatch_table({str(op): fn}, op, args_json)
        if callable(base):
            return base(op, args_json)
        return err("unknown op", op=op, ops=sorted(extra.keys()))

    return _d

def flatten(args):
    """Argument flattening: `{"args": {...}}` is equivalent to top-level keys (both historical spellings are supported)."""
    out = {}
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except Exception:
            args = {}
    for k, v in (args or {}).items():
        if k == "args" and isinstance(v, dict):
            out.update(v)
        else:
            out[k] = v
    return out


def dispatch_table(ops, op, args_json=None):
    """Standard dispatch: resolve → flatten → look up → call → unified error receipt."""
    kw = flatten(args_json)
    try:
        kw = resolve_refs(kw)   # one-shot ops also support "@artifact[.path]"
    except KeyError as e:
        return err("reference resolution failed: %s" % str(e)[:160], op=op)
    fn = ops.get(str(op))
    if fn is None:
        return err("unknown op", op=op, ops=sorted(ops))
    try:
        out = fn(**kw)
        return out if isinstance(out, str) else j(out)
    except TypeError as e:
        return err("argument mismatch: %s" % str(e)[:200], op=op)
    except Exception as e:
        return err("%s: %s" % (type(e).__name__, str(e)[:200]), op=op)


# ────────────────────────────── geometry / measurement ──────────────────────────────
def objects(names, strict=True):
    """Name list → object list; with strict it returns (objs, missing)."""
    import bpy
    if isinstance(names, str):
        names = [names]
    objs = [bpy.data.objects.get(str(n)) for n in (names or [])]
    missing = [n for n, o in zip(names or [], objs) if o is None]
    return (objs, missing) if strict else [o for o in objs if o is not None]


def world_tris(objs, include_hidden=True):
    """**World-space triangles** of a set of objects (uses the evaluated mesh: modifiers/arrays included)."""
    import bpy
    dg = bpy.context.evaluated_depsgraph_get()
    tris = []
    for ob in objs:
        if ob is None or ob.type != "MESH":
            continue
        if not include_hidden:
            try:
                if not ob.visible_get():
                    continue
            except Exception:
                pass
        ev = ob.evaluated_get(dg)
        me = ev.to_mesh()
        try:
            me.calc_loop_triangles()
            mw = ob.matrix_world
            for t in me.loop_triangles:
                tris.append([tuple(mw @ me.vertices[i].co) for i in t.vertices])
        finally:
            ev.to_mesh_clear()
    return tris


def bvh(tris):
    """Triangles → BVH (returns None for empty input)."""
    from mathutils.bvhtree import BVHTree
    if not tris:
        return None
    V = [v for t in tris for v in t]
    polys = [(3 * i, 3 * i + 1, 3 * i + 2) for i in range(len(tris))]
    return BVHTree.FromPolygons(V, polys, all_triangles=True)


def iou(mask_a, mask_b):
    """Boolean-mask IoU — **the single implementation** (imgtools / qc / qc_render should all use this one).

    Returns (iou, inter, union); an empty union returns (None, 0, 0).
    """
    import numpy as np
    a = np.asarray(mask_a).astype(bool)
    b = np.asarray(mask_b).astype(bool)
    inter = int(np.count_nonzero(a & b))
    union = int(np.count_nonzero(a | b))
    return ((inter / union) if union else None), inter, union


def pairwise_clearance(objs_a, objs_b, samples=1200, seed=0):
    """Closest distance between two object sets (metres) and whether they interpenetrate — sampling method (vertices + face centres ↔ the opposing BVH).

    Returns dict: {"gap_m": float|None, "interpenetrating": bool, "overlap_tri_pairs": int}
    Honest boundary: the gap is a sample-point distance (large parallel curved surfaces may be overestimated); interpenetration is exact (triangle intersection).
    """
    import random
    ta, tb = world_tris(objs_a), world_tris(objs_b)
    if not ta or not tb:
        return {"gap_m": None, "interpenetrating": False, "overlap_tri_pairs": 0, "error": "empty_mesh"}
    ba, bb = bvh(ta), bvh(tb)
    ov = ba.overlap(bb) or []
    rng = random.Random(int(seed))
    best = None
    for tris, other in ((ta, bb), (tb, ba)):
        pts = []
        for t in tris:
            pts.append(t[0]); pts.append(t[1]); pts.append(t[2])
            pts.append(((t[0][0] + t[1][0] + t[2][0]) / 3.0,
                        (t[0][1] + t[1][1] + t[2][1]) / 3.0,
                        (t[0][2] + t[1][2] + t[2][2]) / 3.0))
        if len(pts) > int(samples):
            pts = rng.sample(pts, int(samples))
        for p in pts:
            r = other.find_nearest(p)
            if r is None or r[0] is None:
                continue
            import mathutils
            d = (r[0] - mathutils.Vector(p)).length
            if best is None or d < best:
                best = d
    return {"gap_m": best, "interpenetrating": len(ov) > 0, "overlap_tri_pairs": len(ov)}


def selftest():
    """Kernel self-test: JSON/units/receipt/dispatch/geometry/IoU — every entry verified on the spot."""
    ev = {}
    ev["j"] = j({"a": 1}) == '{"a": 1}'
    ev["flatten"] = flatten({"args": {"x": 1}, "y": 2}) == {"x": 1, "y": 2}
    ev["dispatch_unknown"] = '"unknown op"' in dispatch_table({"a": lambda: "{}"}, "nope")
    ev["dispatch_ok"] = dispatch_table({"a": lambda **k: j({"ok": True, **k})}, "a", '{"z": 3}') == '{"ok": true, "z": 3}'
    ev["api_callable"] = isinstance(Api({"dispatch": lambda o, a: '{"ok": true}'}), dict)
    ev["units_positive"] = units() > 0
    m = Api({"dispatch": lambda o, a: '{"ok": true}'})
    ev["api_call"] = m("help", {}) == {"ok": True}
    try:
        import numpy as np
        i, inter, uni = iou(np.array([[1, 0], [1, 0]]), np.array([[1, 1], [0, 0]]))
        ev["iou"] = abs(float(i) - 1.0 / 3.0) < 1e-9 and inter == 1 and uni == 3
    except Exception as e:
        ev["iou"] = "skip: %s" % str(e)[:40]
    ok = all(v is True for v in ev.values())
    return j({"ok": bool(ok), "version": KIT_VERSION, "evidence": ev})


# ────────────────────────────── batched update ──────────────────────────────
class BatchUpdates:
    """Explicit batching tool for multi-step data writes + a single `view_layer.update()` (v2.6.1 performance).

    Usage:
        batch = _KIT.BatchUpdates()
        batch.flush()                    # optional: starting baseline
        for ob in objs: ...              # write data only, no update
        batch.flush()                    # flush again before reading evaluated data

    Discipline: flush is mandatory before any `evaluated_get()/to_mesh()/BVH/bake/render`;
    merging updates reduces how often `depsgraph_update_post` fires (code that depends on that event,
    such as activity tracking, must re-check whether the granularity is still sufficient).
    """

    def __init__(self, view_layer=None):
        import bpy
        self.vl = view_layer or bpy.context.view_layer
        self.stages = 0
        self.updates = 0

    def stage(self, fn, *args, **kwargs):
        """Run one write stage (data only, no update)."""
        result = fn(*args, **kwargs)
        self.stages += 1
        return result

    def flush(self):
        """Push the current batch writes to the dependency graph (call before reading evaluated data)."""
        self.vl.update()
        self.updates += 1
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.flush()
        return False


# Registration: KERNEL_BOOTSTRAP executes this file ⇒ K.dsh_kit exists on every injection path
_K = _kernel()
_K.dsh_kit = types.SimpleNamespace(
    version=KIT_VERSION, j=j, err=err, receipt=receipt, units=units, mm=mm, api=api,
    Api=Api, register=register, flatten=flatten, dispatch_table=dispatch_table,
    objects=objects, world_tris=world_tris, bvh=bvh, iou=iou,
    find_runtime_file=find_runtime_file, RUNTIME_DOMAINS=RUNTIME_DOMAINS,
    pairwise_clearance=pairwise_clearance, selftest=selftest, kernel=_kernel, wrap_dispatch=wrap_dispatch, resolve_refs=resolve_refs, kapi=kapi, install_kernel=install_kernel, comp_tree=comp_tree, BatchUpdates=BatchUpdates,
)