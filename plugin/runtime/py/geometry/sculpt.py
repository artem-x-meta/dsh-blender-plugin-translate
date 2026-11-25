# -*- coding: utf-8 -*-
"""DSH procedural sculpting (v0.9.6 · upstream integration) — turns "sculpting" from gesture input into recomputable geometry operations.

Why it exists: a whole-codebase search of this plugin's runtime for sculpt/remesh/multires/dyntopo/voxel/brush returned 0 hits,
while neither upstream project can do procedural sculpting (the blend-ai README itself states "Sculpt strokes cannot be simulated",
and mcp-for-blender has no sculpting at all). Measured on this machine (Blender 5.2.2 LTS), the conclusions are:

  usable (GUI and headless)  object.mode_set(SCULPT), tool_settings.sculpt.brush,
                             brush.size/.strength, use_symmetry_*, dynamic_topology_toggle,
                             data.remesh_voxel_size + object.voxel_remesh (1986→12148 vertices / 0.084 s),
                             multires_subdivide, object.subdivision_set, the .sculpt_mask attribute
  GUI only                   sculpt.mesh_filter / mask_from_cavity / face_sets_init / face_sets_create
                             (needs a real VIEW_3D context; use view.py's _find_view3d + temp_override)
  unusable (5.2 API level)   sculpt.brush_stroke — the context is solved (poll() measured True), but the stroke collection
                             rejects dicts on the RNA side (all 6 formats failed) and OperatorStrokeElement cannot be instantiated

So the workhorse here is the **L2 in-house numpy displacement brush**: foreach_get("co") → falloff → displace along the normal →
foreach_set. Measured: 1986 vertices with 257 vertices affected per stroke / 6 ms; symmetry, mask multiplier and stroke-path
interpolation come for free. It does not depend on sculpt mode, does not change the global mode, runs headless and its result
can be diffed — same origin as generator_* (program as shape).

API hangs off K.dsh_sculpt_api; entry points:
    blender_rt_plan(op="sculpt_scan",   args={objects:["Head"]})
    blender_rt_plan(op="sculpt_setup",  args={object:"Head", mode:"VOXEL", voxel_size:"auto"})
    blender_rt_plan(op="sculpt_apply",  args={object:"Head", strokes:[
        {brush:"draw",   points:[[0,0,1.2],[0.1,0,1.3]], radius:0.35, strength:0.6},
        {brush:"crease", points:[[0.6,0,0.8]], radius:0.12, strength:0.8, symmetry:["x"]}]})
    blender_rt_plan(op="sculpt_filter", args={objects:["Head"], type:"SMOOTH", strength:0.4})
    blender_rt_plan(op="sculpt_mask",   args={objects:["Head"], mode:"sphere", center:[0,0,1], radius:0.5})
    blender_rt_plan(op="sculpt_remesh", args={objects:["Head"], mode:"VOXEL", voxel_size:"auto"})

**Hard rules**: 0 meshes ⇒ ok=false; NaN/Inf arguments are always rejected (they corrupt the .blend); voxel remesh computes a
budget first (cells = Π(dim/v); above max_cells it errors and returns a workable size instead of letting Blender hang until timeout).
After sculpting changes topology, object-level mark/revert cannot go back — to roll back use blender_rt_txn(op="snapshot").
"""
import json
import math
import time

import bpy
import bmesh
from mathutils import Vector

SCULPT_VERSION = 1

# Voxel budget ceiling consistent with blend-ai (idea from its addon/handlers/sculpting.py:137; the implementation is this plugin's own code)
MAX_VOXEL_CELLS = 40_000_000
BRUSHES = ("draw", "inflate", "pinch", "flatten", "smooth", "crease")
FALLOFFS = ("smooth", "linear", "sphere", "constant", "sharp")
FILTERS = ("SMOOTH", "INFLATE", "RELAX", "RELAX_FACE_SETS", "SHARPEN", "ENHANCE_DETAILS", "ERASE_DISPLACEMENT")


import sys as _sys_kit
_KIT = getattr(_sys_kit.modules.get("dsh_rt_kernel"), "dsh_kit", None)
if _KIT is None:
    raise RuntimeError("sculpt requires the shared kernel K.dsh_kit (injected by KERNEL_BOOTSTRAP)")


_j = _KIT.j  # shared kernel (the old bundled implementation was removed)
def _num(v, name, lo=None, hi=None, default=None):
    """Parameter discipline: any non-finite number is rejected (NaN/Infinity written into Blender properties persists into the .blend)."""
    if v is None:
        if default is None:
            raise ValueError("%s is required" % name)
        return float(default)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError("%s needs a number, got %r" % (name, v))
    f = float(v)
    if not math.isfinite(f):
        raise ValueError("%s must be finite (NaN/Inf corrupts the .blend)" % name)
    if lo is not None and f < lo:
        raise ValueError("%s=%g below lower limit %g" % (name, f, lo))
    if hi is not None and f > hi:
        raise ValueError("%s=%g above upper limit %g" % (name, f, hi))
    return f


def _vec3(v, name):
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        raise ValueError("%s needs [x,y,z], got %r" % (name, v))
    return [_num(v[0], name + "[0]"), _num(v[1], name + "[1]"), _num(v[2], name + "[2]")]


def _kernel():
    import sys
    return sys.modules.get("dsh_rt_kernel")


def _objs(objects=None, scope="ACTIVE"):
    """Get mesh objects. 0 ⇒ raise (the external 'silent empty output' incident landed exactly on this)."""
    if objects:
        names = [objects] if isinstance(objects, str) else list(objects)
        out = []
        for n in names:
            ob = bpy.data.objects.get(str(n))
            if ob is None:
                raise ValueError("object not found: %s" % n)
            if ob.type != "MESH":
                raise ValueError("%s is not a mesh (type=%s)" % (n, ob.type))
            out.append(ob)
        if not out:
            raise ValueError("objects is empty")
        return out
    sc = str(scope or "ACTIVE").upper()
    if sc == "ACTIVE":
        ob = bpy.context.view_layer.objects.active
        if ob is None or ob.type != "MESH":
            raise ValueError("no active mesh object (give objects=[...] or scope=SELECTED/VISIBLE/ALL)")
        return [ob]
    if sc == "SELECTED":
        sel = [o for o in bpy.context.selected_objects if o.type == "MESH"]
        if not sel:
            raise ValueError("no selected mesh")
        return sel
    if sc == "VISIBLE":
        vis = [o for o in bpy.context.view_layer.objects if o.type == "MESH" and o.visible_get()]
        if not vis:
            raise ValueError("no visible mesh")
        return vis
    if sc == "ALL":
        allm = [o for o in bpy.data.objects if o.type == "MESH"]
        if not allm:
            raise ValueError("no mesh in the scene")
        return allm
    raise ValueError("unknown scope: %s (ACTIVE/SELECTED/VISIBLE/ALL)" % scope)


def _tris(me):
    return sum(max(0, len(p.vertices) - 2) for p in me.polygons)


def _dims(ob):
    return [max(float(d), 1e-6) for d in ob.dimensions]


def _voxel_plan(ob, voxel_size, max_cells=MAX_VOXEL_CELLS):
    """Budget guard: Blender accepts any voxel_size and then grinds — over budget errors out on the plugin side first."""
    d = _dims(ob)
    if voxel_size in (None, "auto"):
        # Target: cells ≈ max_cells/4 (4x headroom), solve backwards for a voxel size
        v = ((d[0] * d[1] * d[2]) / (max_cells / 4.0)) ** (1.0 / 3.0)
        return round(float(v), 6), True
    v = _num(voxel_size, "voxel_size", 1e-5, 100.0)
    cells = 1.0
    for x in d:
        cells *= x / v
    if cells > max_cells:
        workable = ((d[0] * d[1] * d[2]) / max_cells) ** (1.0 / 3.0)
        raise ValueError(
            "voxel_size %g on a %.2f x %.2f x %.2f object needs about %s voxels, which hangs Blender instead of failing; "
            "use %.4f or larger (or voxel_size=\"auto\")" % (v, d[0], d[1], d[2], format(int(cells), ","), workable))
    return v, False


def _vertex_normals(me):
    """Vertex normals: prefer mesh.vertex_normals, fall back to bmesh when unavailable."""
    import numpy as np
    n = len(me.vertices)
    arr = np.zeros((n, 3), dtype=np.float64)
    try:
        me.vertex_normals  # noqa: B018  4.1+ read-only collection
        for i in range(n):
            v = me.vertex_normals[i].vector
            arr[i] = (v[0], v[1], v[2])
        return arr
    except Exception:
        bm = bmesh.new()
        bm.from_mesh(me)
        bm.verts.ensure_lookup_table()
        for i, v in enumerate(bm.verts):
            arr[i] = (v.normal[0], v.normal[1], v.normal[2])
        bm.free()
        return arr


def _falloff(kind, t):
    import numpy as np
    t = np.clip(t, 0.0, 1.0)
    if kind == "linear":
        return 1.0 - t
    if kind == "sphere":
        return np.sqrt(np.clip(1.0 - t * t, 0.0, 1.0))
    if kind == "constant":
        return np.ones_like(t)
    if kind == "sharp":
        return np.clip(1.0 - t, 0.0, 1.0) ** 4
    s = 1.0 - t  # smooth (default): smoothstep
    return s * s * (3.0 - 2.0 * s)


def _mask_array(me):
    """Read .sculpt_mask (returns a 0..1 mask when present, None otherwise)."""
    import numpy as np
    att = me.attributes.get(".sculpt_mask") if hasattr(me, "attributes") else None
    if att is None:
        return None
    n = len(me.vertices)
    a = np.zeros(n, dtype=np.float64)
    try:
        buf = np.empty(n, dtype=np.float32)
        att.data.foreach_get("value", buf)
        a = buf.astype(np.float64)
    except Exception:
        return None
    return np.clip(a, 0.0, 1.0)


def _dab_points(points, radius, spacing_frac=0.25):
    """Interpolate control points into a dab sequence (points are inserted when the gap between neighbours > radius*spacing_frac)."""
    pts = [Vector(p) for p in points]
    if len(pts) == 1:
        return [[float(c) for c in pts[0]]]
    step = max(float(radius) * float(spacing_frac), 1e-6)
    out = []
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        d = (b - a).length
        k = max(1, int(math.ceil(d / step)))
        for s in range(k):
            p = a + (b - a) * (float(s) / k)
            out.append([p.x, p.y, p.z])
    out.append([float(pts[-1].x), float(pts[-1].y), float(pts[-1].z)])
    return out


def _apply_brush_params(stroke):
    """Validate brush/falloff/points/symmetry and resolve radius/strength; returns the parsed parameter dict (bad values raise ValueError)."""
    brush = str(stroke.get("brush") or "draw").lower()
    if brush not in BRUSHES:
        raise ValueError("unknown brush: %s (allowed %s)" % (brush, list(BRUSHES)))
    radius = _num(stroke.get("radius"), "radius", 1e-6, 1e6)
    strength = _num(stroke.get("strength"), "strength", default=0.5)
    fall = str(stroke.get("falloff") or "smooth").lower()
    if fall not in FALLOFFS:
        raise ValueError("unknown falloff: %s (allowed %s)" % (fall, list(FALLOFFS)))
    raw = stroke.get("points")
    if not isinstance(raw, (list, tuple)) or not raw:
        raise ValueError("stroke.points is required ([[x,y,z], ...])")
    points = [_vec3(p, "points[%d]" % i) for i, p in enumerate(raw)]
    sym = stroke.get("symmetry") or []
    sym = [str(s).lower() for s in (sym if isinstance(sym, (list, tuple)) else [sym])]
    invert = bool(stroke.get("invert"))
    dirn = stroke.get("direction") or "normal"
    return {"brush": brush, "radius": radius, "strength": strength, "fall": fall,
            "points": points, "sym": sym, "invert": invert, "dirn": dirn}


def _apply_stroke_paths(points, sym):
    """Symmetry axis → several paths (mirrored points must be separate paths; appending them to the same polyline would interpolate a false path across the object)."""
    axis_idx = {"x": 0, "y": 1, "z": 2}
    paths = [[list(p) for p in points]]
    for s in sym:
        if s not in axis_idx:
            raise ValueError("unknown symmetry axis: %s (x/y/z)" % s)
        i = axis_idx[s]
        mirrored = []
        for path in paths:
            mirrored.append([[( -p[0] if i == 0 else p[0]), (-p[1] if i == 1 else p[1]), (-p[2] if i == 2 else p[2])] for p in path])
        paths = paths + mirrored
    return paths


def _apply_dab_disp(co, nrm, mask, dabs, pr, me, n, ob):
    """Accumulate displacement per dab by brush rule; returns (disp, affect)."""
    import numpy as np
    brush, radius, strength, fall, invert = pr["brush"], pr["radius"], pr["strength"], pr["fall"], pr["invert"]
    disp = np.zeros((n, 3), dtype=np.float64)
    affect = np.zeros(n, dtype=bool)
    for p in dabs:
        c = np.asarray(p, dtype=np.float64)
        d = np.linalg.norm(co - c, axis=1)
        t = d / radius
        inside = t <= 1.0
        if not bool(inside.any()):
            continue
        f = _falloff(fall, t)
        if mask is not None:
            f = f * (1.0 - mask)
        amp = strength * float(radius) * 0.25  # per-dab displacement cap, proportional to the radius
        if brush == "draw":
            disp += (nrm * (f * amp * (-1.0 if invert else 1.0))[:, None])
        elif brush == "inflate":
            dirv = co - np.array([ob.matrix_world.translation[i] for i in range(3)])
            ln = np.linalg.norm(dirv, axis=1, keepdims=True)
            dirv = dirv / np.maximum(ln, 1e-9)
            disp += dirv * (f * amp * (-1.0 if invert else 1.0))[:, None]
        elif brush == "pinch":
            dirv = c[None, :] - co
            ln = np.linalg.norm(dirv, axis=1, keepdims=True)
            dirv = dirv / np.maximum(ln, 1e-9)
            disp += dirv * (f * amp * 0.6) [:, None]
        elif brush == "flatten":
            # flatten onto the plane along the dab normal: pull back the part that exceeds the plane
            pl = c
            nvec = nrm[inside].mean(axis=0) if bool(inside.any()) else np.array([0.0, 0.0, 1.0])
            ln = float(np.linalg.norm(nvec)) or 1.0
            nvec = nvec / ln
            signed = (co - pl[None, :]) @ nvec
            delta = -signed * f * strength
            disp += nvec[None, :] * delta[:, None] * (-1.0 if invert else 1.0)
        elif brush == "smooth":
            # neighbour average (build the average once from the edge table, then blend by falloff)
            if not hasattr(_apply_dab_disp, "_adj"):
                _apply_dab_disp._adj = {}
            key = (ob.name, n)
            adj = _apply_dab_disp._adj.get(key)
            if adj is None:
                bm = bmesh.new()
                bm.from_mesh(me)
                bm.verts.ensure_lookup_table()
                idx = [np.array([e.other_vert(v).index for e in v.link_edges], dtype=np.int64) for v in bm.verts]
                bm.free()
                adj = idx
                _apply_dab_disp._adj[key] = adj
            avg = co.copy()
            for i in np.nonzero(inside)[0]:
                nb = adj[int(i)]
                if len(nb):
                    avg[i] = co[nb].mean(axis=0)
            disp += (avg - co) * (f * strength)[:, None]
        elif brush == "crease":
            tang = co - c[None, :]
            ln = np.linalg.norm(tang, axis=1, keepdims=True)
            tang = tang / np.maximum(ln, 1e-9)
            proj = nrm - tang * (np.sum(nrm * tang, axis=1, keepdims=True))
            ln2 = np.linalg.norm(proj, axis=1, keepdims=True)
            proj = proj / np.maximum(ln2, 1e-9)
            disp -= proj * (f * amp * (-1.0 if invert else 1.0))[:, None]
        affect |= inside
    return disp, affect


def _apply_one(ob, stroke, use_mask=True):
    """Single stroke: numpy displacement. Returns a stats dict."""
    import numpy as np
    me = ob.data
    n = len(me.vertices)
    if n == 0:
        return {"name": ob.name, "skipped": "0 vertices"}

    pr = _apply_brush_params(stroke)
    co = np.empty(n * 3, dtype=np.float64)
    me.vertices.foreach_get("co", co)
    co = co.reshape(n, 3)
    nrm = _vertex_normals(me)
    mask = _mask_array(me) if use_mask else None

    # Symmetry: a mirror axis produces "several independent strokes" (object local origin, consistent with Blender sculpt symmetry).
    # Mirrored points were once appended to the same polyline — that made _dab_points interpolate
    # a false path straight across the object between +x and -x (measured: 1 point became 39 dabs and smeared the surface).
    paths = _apply_stroke_paths(pr["points"], pr["sym"])
    dabs = []
    for path in paths:
        dabs.extend(_dab_points(path, pr["radius"]))
    used_paths = len(paths)
    t0 = time.time()
    disp, affect = _apply_dab_disp(co, nrm, mask, dabs, pr, me, n, ob)

    dirn = pr["dirn"]
    if dirn not in ("normal", None, "normal_z"):
        dv = np.asarray(_vec3(dirn, "direction"), dtype=np.float64)
        ln = float(np.linalg.norm(dv)) or 1.0
        dv = dv / ln
        # explicit direction: project the computed displacement onto it (keeps the brush shape, unifies the direction)
        mag = np.linalg.norm(disp, axis=1, keepdims=True)
        disp = dv[None, :] * mag * np.sign((disp * nrm).sum(axis=1, keepdims=True) + 1e-12)

    new = co + disp
    me.vertices.foreach_set("co", new.reshape(-1))
    me.update()
    if hasattr(me, "calc_normals_split"):
        pass
    maxd = float(np.abs(new - co).max()) if n else 0.0
    return {"name": ob.name, "brush": pr["brush"], "dabs": len(dabs), "stroke_paths": used_paths, "verts": n,
            "affected_verts": int(affect.sum()), "max_delta": round(maxd, 8),
            "ms": int((time.time() - t0) * 1000)}


def sculpt_scan(objects=None, scope="ACTIVE"):
    """Read-only scan: whether sculpting works, how, the voxel budget, and whether mask/face sets have geometry."""
    obs = _objs(objects, scope)
    rows = []
    for ob in obs:
        me = ob.data
        ts = bpy.context.tool_settings.sculpt
        row = {"name": ob.name, "verts": len(me.vertices), "tris": _tris(me),
               "dimensions": [round(x, 6) for x in _dims(ob)],
               "mode": ob.mode, "modifiers": [m.type for m in ob.modifiers]}
        row["has_multires"] = any(m.type == "MULTIRES" for m in ob.modifiers)
        row["mask_attr"] = bool(hasattr(me, "attributes") and me.attributes.get(".sculpt_mask"))
        att = me.attributes.get(".sculpt_mask") if hasattr(me, "attributes") else None
        if att is not None:
            try:
                import numpy as np
                buf = np.empty(len(me.vertices), dtype=np.float32)
                att.data.foreach_get("value", buf)
                row["mask_coverage"] = round(float((buf > 0.05).mean()), 4)
                row["mask_mean"] = round(float(buf.mean()), 4)
            except Exception:
                pass
        row["symmetry"] = [bool(ts.use_symmetry_x), bool(ts.use_symmetry_y), bool(ts.use_symmetry_z)]
        row["brush"] = ts.brush.name if ts.brush else None
        row["dyntopo"] = bool(getattr(bpy.context.sculpt_object, "use_dynamic_topology_sculpting", False)) if bpy.context.sculpt_object else False
        try:
            vy, auto = _voxel_plan(ob, "auto")
            vx, _ = _voxel_plan(ob, None)
            row["voxel_auto"] = vx
            row["voxel_budget_note"] = "cells = Π(dim/v), ceiling %s" % format(MAX_VOXEL_CELLS, ",")
        except Exception as e:
            row["voxel_error"] = str(e)[:160]
        row["strokes_available"] = "numpy displacement brush (this module)"
        rows.append(row)
    return _j({"ok": True, "scope": str(scope or "ACTIVE").upper(), "count": len(rows), "objects": rows,
               "capability": {"scriptable_free": ["draw", "inflate", "pinch", "flatten", "smooth", "crease"],
                              "scriptable_gui_only": ["mesh_filter", "mask_from_cavity", "face_sets_init"],
                              "not_scriptable": ["sculpt.brush_stroke (5.2 RNA rejects dicts / stroke elements cannot be instantiated)"]},
               "note": "after sculpting changes topology, object-level mark/revert cannot go back; before changing use blender_rt_txn(op=\"snapshot\")"})


def sculpt_setup(object=None, objects=None, mode="KEEP", voxel_size=None, levels=2, detail_size=12.0,
                  detail_mode="RELATIVE", symmetry=None, apply_modifiers=False):
    """Topology preparation: get the base mesh right before sculpting (VOXEL remesh / MULTIRES / SUBDIV / DYNTOPO)."""
    obs = _objs(objects or object)
    m = str(mode or "KEEP").upper()
    if m not in ("KEEP", "VOXEL", "MULTIRES", "SUBDIV", "DYNTOPO"):
        raise ValueError("unknown mode: %s (KEEP/VOXEL/MULTIRES/SUBDIV/DYNTOPO)" % mode)
    out = []
    for ob in obs:
        rec = {"name": ob.name, "mode": m, "verts_before": len(ob.data.vertices)}
        t0 = time.time()
        frm = ob.mode
        if m == "VOXEL":
            v, auto = _voxel_plan(ob, voxel_size)
            ob.data.remesh_voxel_size = v
            if bpy.context.view_layer.objects.active is not ob:
                bpy.context.view_layer.objects.active = ob
            r = bpy.ops.object.voxel_remesh()
            rec["voxel_size"] = v
            rec["auto"] = bool(auto)
            rec["op"] = str(r)
        elif m == "MULTIRES":
            md = ob.modifiers.new(name="Multires", type="MULTIRES")
            lv = int(_num(levels, "levels", 1, 6))
            for _ in range(lv):
                bpy.context.view_layer.objects.active = ob
                bpy.ops.object.multires_subdivide(modifier=md.name, mode="CATMULL_CLARK")
            rec["modifier"] = md.name
            rec["levels"] = lv
            rec["sculpt_levels"] = int(md.sculpt_levels)
        elif m == "SUBDIV":
            lv = int(_num(levels, "levels", 1, 6))
            bpy.context.view_layer.objects.active = ob
            bpy.ops.object.subdivision_set(level=lv, relative=False)
            rec["levels"] = lv
        elif m == "DYNTOPO":
            bpy.context.view_layer.objects.active = ob
            if ob.mode != "SCULPT":
                bpy.ops.object.mode_set(mode="SCULPT")
            if not bpy.context.sculpt_object.use_dynamic_topology_sculpting:
                bpy.ops.sculpt.dynamic_topology_toggle()
            ts = bpy.context.tool_settings.sculpt
            ts.detail_size = _num(detail_size, "detail_size", 0.1, 500.0)
            ts.detail_type_method = str(detail_mode).upper()
            rec["detail_size"] = ts.detail_size
            rec["detail_mode"] = ts.detail_type_method
            bpy.ops.object.mode_set(mode="OBJECT")
        if symmetry:
            s = symmetry if isinstance(symmetry, (list, tuple)) else [symmetry]
            ts = bpy.context.tool_settings.sculpt
            ts.use_symmetry_x = "x" in [str(k).lower() for k in s]
            ts.use_symmetry_y = "y" in [str(k).lower() for k in s]
            ts.use_symmetry_z = "z" in [str(k).lower() for k in s]
            rec["symmetry"] = [bool(ts.use_symmetry_x), bool(ts.use_symmetry_y), bool(ts.use_symmetry_z)]
        try:
            if frm != ob.mode:
                bpy.ops.object.mode_set(mode=frm)
        except Exception:
            pass
        rec["verts_after"] = len(ob.data.vertices)
        rec["tris_after"] = _tris(ob.data)
        rec["ms"] = int((time.time() - t0) * 1000)
        out.append(rec)
    return _j({"ok": True, "objects": out})


def sculpt_apply(object=None, objects=None, strokes=None, use_mask=True):
    """L2 displacement brush: one stroke = one control-point path + a brush + radius/strength/falloff (+ symmetry/mask/direction)."""
    obs = _objs(objects or object)
    if not isinstance(strokes, (list, tuple)) or not strokes:
        raise ValueError("strokes is required ([{brush, points, radius, strength, falloff, symmetry, invert, direction}])")
    allowed = ("brush", "points", "radius", "strength", "falloff", "symmetry", "invert", "direction")
    for i, s in enumerate(strokes):
        if not isinstance(s, dict):
            raise ValueError("strokes[%d] must be an object" % i)
    out = []
    for ob in obs:
        recs = []
        for s in strokes:
            recs.append(_apply_one(ob, s, use_mask=bool(use_mask)))
        out.append({"object": ob.name, "strokes": recs,
                    "verts_after": len(ob.data.vertices), "tris_after": _tris(ob.data)})
    return _j({"ok": True, "results": out,
               "note": "displacement is written to the base mesh (not a multires level); afterwards sculpt_filter can smooth and sculpt_remesh can retopologize"})


def sculpt_filter(objects=None, scope="ACTIVE", type="SMOOTH", strength=0.3, iterations=1, mask=False):
    """GUI filter brush (sculpt.mesh_filter): smooth/inflate/relax the whole block; needs a real 3D viewport context."""
    t = str(type or "SMOOTH").upper()
    if t not in FILTERS:
        raise ValueError("unknown type: %s (allowed %s)" % (type, list(FILTERS)))
    st = _num(strength, "strength", 0.0, 1.0)
    it = int(_num(iterations, "iterations", 1, 50))
    obs = _objs(objects, scope)
    # real UI context: find VIEW_3D the same way as view.py
    win = ar = reg = None
    for w in bpy.context.window_manager.windows:
        if w.screen is None:
            continue
        for a in w.screen.areas:
            if a.type == "VIEW_3D":
                win, ar = w, a
                reg = next((r for r in a.regions if r.type == "WINDOW"), None)
                break
        if win:
            break
    if not (win and ar and reg):
        return _j({"ok": False, "error": "no VIEW_3D area: mesh_filter needs a GUI viewport context (headless -b does not support it)",
                   "hint": "use sculpt_apply instead (numpy displacement, works headless)"})
    out = []
    for ob in obs:
        frm = ob.mode
        t0 = time.time()
        rs = []
        try:
            for o in bpy.context.selected_objects:
                o.select_set(False)
            ob.select_set(True)
            bpy.context.view_layer.objects.active = ob
            if ob.mode != "SCULPT":
                bpy.ops.object.mode_set(mode="SCULPT")
            if mask:
                try:
                    bpy.context.tool_settings.sculpt.use_mask = True
                except Exception:
                    pass
            with bpy.context.temp_override(window=win, screen=win.screen, area=ar, region=reg):
                rs = []
                for _ in range(it):
                    rs.append(str(bpy.ops.sculpt.mesh_filter(type=t, strength=st)))
        finally:
            try:
                if ob.mode != frm:
                    bpy.ops.object.mode_set(mode=frm if frm else "OBJECT")
            except Exception:
                pass
        out.append({"name": ob.name, "type": t, "iterations": it, "strength": st,
                    "op": rs[-1] if rs else None, "ms": int((time.time() - t0) * 1000),
                    "verts": len(ob.data.vertices)})
    return _j({"ok": True, "objects": out})


def sculpt_mask(objects=None, scope="ACTIVE", mode="sphere", center=None, radius=0.3, invert=False,
                value=1.0, smooth_iterations=0):
    """Masking: sphere/box regions write .sculpt_mask directly; from_cavity/init go through GUI operators; clear wipes it."""
    import numpy as np
    m = str(mode or "sphere").lower()
    if m not in ("sphere", "box", "clear", "from_cavity", "init"):
        raise ValueError("unknown mode: %s (sphere/box/clear/from_cavity/init)" % mode)
    obs = _objs(objects, scope)
    out = []
    for ob in obs:
        me = ob.data
        n = len(me.vertices)
        rec = {"name": ob.name, "mode": m, "verts": n}
        if m == "clear":
            att = me.attributes.get(".sculpt_mask") if hasattr(me, "attributes") else None
            if att is not None:
                me.attributes.remove(att)
            rec["cleared"] = True
        elif m in ("sphere", "box"):
            co = np.empty(n * 3, dtype=np.float64)
            me.vertices.foreach_get("co", co)
            co = co.reshape(n, 3)
            c = np.asarray(_vec3(center, "center"), dtype=np.float64)
            if m == "sphere":
                r = _num(radius, "radius", 1e-6, 1e6)
                d = np.linalg.norm(co - c, axis=1)
                val = np.clip(1.0 - d / r, 0.0, 1.0)
            else:
                r = _num(radius, "radius", 1e-6, 1e6)
                val = np.clip(1.0 - np.abs(co - c).max(axis=1) / r, 0.0, 1.0)
            val = val * _num(value, "value", 0.0, 1.0)
            if invert:
                val = 1.0 - val
            att = me.attributes.get(".sculpt_mask") if hasattr(me, "attributes") else None
            if att is None:
                att = me.attributes.new(name=".sculpt_mask", type="FLOAT", domain="POINT")
            att.data.foreach_set("value", val.astype(np.float32))
            me.update()
            rec["coverage"] = round(float((val > 0.05).mean()), 4)
        else:
            # GUI operator path
            win = ar = reg = None
            for w in bpy.context.window_manager.windows:
                if w.screen is None:
                    continue
                for a in w.screen.areas:
                    if a.type == "VIEW_3D":
                        win, ar = w, a
                        reg = next((r for r in a.regions if r.type == "WINDOW"), None)
                        break
                if win:
                    break
            if not (win and ar and reg):
                return _j({"ok": False, "error": "%s needs a GUI 3D viewport (headless -b does not support it)" % m,
                           "hint": "headless can use mode=sphere/box to write .sculpt_mask directly"})
            frm = ob.mode
            try:
                for o in bpy.context.selected_objects:
                    o.select_set(False)
                ob.select_set(True)
                bpy.context.view_layer.objects.active = ob
                if ob.mode != "SCULPT":
                    bpy.ops.object.mode_set(mode="SCULPT")
                with bpy.context.temp_override(window=win, screen=win.screen, area=ar, region=reg):
                    if m == "from_cavity":
                        rec["op"] = str(bpy.ops.sculpt.mask_from_cavity())
                    else:
                        rec["op"] = str(bpy.ops.sculpt.mask_init(mode="RANDOM_PER_VERTEX"))
            finally:
                try:
                    if ob.mode != frm:
                        bpy.ops.object.mode_set(mode=frm if frm else "OBJECT")
                except Exception:
                    pass
            mk = _mask_array(me)
            if mk is not None:
                rec["coverage"] = round(float((mk > 0.05).mean()), 4)
        out.append(rec)
    return _j({"ok": True, "objects": out,
               "note": "mask = the multiplier when use_mask=true in a later sculpt_apply (masked areas stay put)"})


def sculpt_remesh(objects=None, scope="ACTIVE", object=None, mode="VOXEL", voxel_size=None,
                  octree_depth=6, max_cells=MAX_VOXEL_CELLS):
    """Retopology: VOXEL (voxel, with a budget guard) or SHARP/SMOOTH/BLOCKS (REMESH modifier)."""
    obs = _objs(objects or object, scope)
    m = str(mode or "VOXEL").upper()
    if m not in ("VOXEL", "SHARP", "SMOOTH", "BLOCKS"):
        raise ValueError("unknown mode: %s (VOXEL/SHARP/SMOOTH/BLOCKS)" % mode)
    mc = _num(max_cells, "max_cells", 1e3, 2e9, default=MAX_VOXEL_CELLS)
    out = []
    for ob in obs:
        t0 = time.time()
        rec = {"name": ob.name, "mode": m, "verts_before": len(ob.data.vertices), "tris_before": _tris(ob.data)}
        bpy.context.view_layer.objects.active = ob
        if m == "VOXEL":
            v, auto = _voxel_plan(ob, voxel_size, mc)
            ob.data.remesh_voxel_size = v
            rec["voxel_size"] = v
            rec["auto"] = bool(auto)
            rec["op"] = str(bpy.ops.object.voxel_remesh())
        else:
            md = ob.modifiers.new(name="Remesh", type="REMESH")
            md.mode = m
            md.octree_depth = int(_num(octree_depth, "octree_depth", 1, 12))
            rec["op"] = str(bpy.ops.object.modifier_apply(modifier=md.name))
        rec["verts_after"] = len(ob.data.vertices)
        rec["tris_after"] = _tris(ob.data)
        rec["ms"] = int((time.time() - t0) * 1000)
        out.append(rec)
    return _j({"ok": True, "objects": out,
               "note": "voxel remesh loses UVs/material-slot weights (geometry is not lost but attributes may change); snapshot before changing"})


def sculpt_selftest():
    """Self-test: temp sphere → displacement brush → voxel remesh → assert the geometry really changed → clean up."""
    before = set(o.name for o in bpy.data.objects)
    me = bpy.data.meshes.new("__dsh_sculpt_selftest")
    ob = bpy.data.objects.new("__dsh_sculpt_selftest", me)
    bpy.context.scene.collection.objects.link(ob)
    ev = {}
    try:
        bm = bmesh.new()
        try:
            bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=1.0)
        except TypeError:
            bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, diameter=1.0)
        bm.to_mesh(me)
        bm.free()
        ev["verts0"] = len(me.vertices)
        r = json.loads(sculpt_apply(object=ob.name, strokes=[{"brush": "draw", "points": [[0, 0, 1.0], [0.1, 0, 1.02]],
                                                              "radius": 0.4, "strength": 0.8}]))
        ev["apply_ok"] = r.get("ok")
        ev["affected"] = r["results"][0]["strokes"][0]["affected_verts"]
        ev["max_delta"] = r["results"][0]["strokes"][0]["max_delta"]
        r2 = json.loads(sculpt_remesh(object=ob.name, mode="VOXEL", voxel_size=0.08))
        ev["remesh_verts"] = r2["objects"][0]["verts_after"]
        r3 = json.loads(sculpt_mask(objects=[ob.name], mode="sphere", center=[0, 0, 1], radius=0.5))
        ev["mask_coverage"] = r3["objects"][0].get("coverage")
        ev["scan_ok"] = json.loads(sculpt_scan(objects=[ob.name]))["ok"]
        ok = bool(ev["apply_ok"] and ev["affected"] > 0 and ev["max_delta"] > 0 and ev["remesh_verts"] > 0
                  and ev["mask_coverage"] is not None)
        return _j({"ok": ok, "evidence": ev})
    except Exception as e:
        return _j({"ok": False, "evidence": ev, "error": "%s: %s" % (type(e).__name__, str(e)[:200])})
    finally:
        try:
            bpy.data.objects.remove(ob, do_unlink=True)
            bpy.data.meshes.remove(me, do_unlink=True)
        except Exception:
            pass
        left = [o.name for o in bpy.data.objects if o.name not in before]
        if left:
            ev["leftover"] = left


def sculpt_help():
    return _j({
        "module": "sculpt.py", "version": SCULPT_VERSION,
        "ops": {
            "sculpt_scan": "read-only: vertices/tris/dimensions/mode/modifiers/mask coverage/symmetry/voxel budget (on the read-only allowlist)",
            "sculpt_setup": "topology preparation: mode=KEEP|VOXEL|MULTIRES|SUBDIV|DYNTOPO, optionally with symmetry=['x']",
            "sculpt_apply": "displacement brush: strokes=[{brush:draw|inflate|pinch|flatten|smooth|crease, points:[[x,y,z]...], "
                            "radius, strength, falloff:smooth|linear|sphere|constant|sharp, symmetry:['x'], invert, "
                            "direction:[x,y,z]}], use_mask defaults to true",
            "sculpt_filter": "GUI filter: type=SMOOTH|INFLATE|RELAX|..., strength 0..1, iterations (needs a 3D viewport)",
            "sculpt_mask": "masking: mode=sphere|box (headless, writes .sculpt_mask directly) / clear / from_cavity / init (GUI)",
            "sculpt_remesh": "retopology: mode=VOXEL (voxel_size=auto|value, with the 40M cell budget guard) / SHARP / SMOOTH / BLOCKS",
            "sculpt_selftest": "self-test: run apply+remesh+mask+scan on a temp sphere and assert the geometry really changed",
            "sculpt_help": "this table",
        },
        "workflow": ["sculpt_scan to inspect", "sculpt_setup(mode=VOXEL, voxel_size=auto) to set the base mesh",
                     "sculpt_apply a few strokes (large shapes with draw → local crease/pinch)",
                     "sculpt_filter to smooth", "sculpt_mask to restrict the area before sculpting further",
                     "audit_mesh/audit_drift before-vs-after plus qc_render_views for visual acceptance"],
        "hard_rules": ["0 meshes ⇒ ok=false", "NaN/Inf arguments are always rejected",
                       "voxel remesh computes the budget first and errors with a workable size when over the limit",
                       "sculpting changes topology ⇒ object-level mark/revert cannot go back; to roll back use blender_rt_txn(op=\"snapshot\")"],
        "limits": {"brush_stroke": "on Blender 5.2 Python cannot construct the stroke collection (RNA rejects dicts; elements cannot be instantiated); "
                                   "the context itself is fine (poll()=True after temp_override)",
                   "multires_sculpt": "displacement is written to the base mesh; sculpting on multires levels needs GUI gestures and is not scriptable yet",
                   "headless": "sculpt_apply/remesh/mask(sphere|box) work headless; mesh_filter and from_cavity need the GUI"},
    })


def sculpt_dispatch(op, args_json):
    args = {}
    if isinstance(args_json, str) and args_json.strip():
        try:
            args = json.loads(args_json)
        except Exception as e:
            return _j({"ok": False, "error": "args is not valid JSON: %s" % str(e)[:120]})
    if not isinstance(args, dict):
        return _j({"ok": False, "error": "args must be an object"})
    kw = {}
    for k, v in args.items():
        if k == "args" and isinstance(v, dict):
            kw.update(v)
        else:
            kw[k] = v
    ops = {"scan": sculpt_scan, "setup": sculpt_setup, "apply": sculpt_apply, "filter": sculpt_filter,
           "mask": sculpt_mask, "remesh": sculpt_remesh, "selftest": sculpt_selftest, "help": sculpt_help}
    fn = ops.get(str(op))
    if fn is None:
        return _j({"ok": False, "error": "unknown sculpt op", "op": op, "ops": sorted(ops)})
    import inspect
    try:
        allowed = set(inspect.signature(fn).parameters)
        unknown = sorted(set(kw) - allowed)
        if unknown:
            return _j({"ok": False, "error": "unknown parameters %s" % unknown, "op": op,
                       "allowed": sorted(allowed), "hint": "a misspelt parameter name would silently do nothing, so it errors here"})
    except (TypeError, ValueError):
        pass
    try:
        return fn(**kw)
    except TypeError as e:
        return _j({"ok": False, "error": "argument mismatch: %s" % str(e)[:200], "op": op, "help": sculpt_help()})
    except Exception as e:
        return _j({"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:220]), "op": op})


_DshApi = _KIT.Api  # shared kernel (the trailing registration line needs no change)
import sys as _sys
_K = _sys.modules.get("dsh_rt_kernel")
if _K is not None:
    _K.dsh_sculpt_api = _DshApi({"version": SCULPT_VERSION, "dispatch": sculpt_dispatch,
                                 "scan": sculpt_scan, "setup": sculpt_setup, "apply": sculpt_apply,
                                 "filter": sculpt_filter, "mask": sculpt_mask, "remesh": sculpt_remesh,
                                 "selftest": sculpt_selftest, "help": sculpt_help})
