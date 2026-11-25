# -*- coding: utf-8 -*-
"""DSH mesh repair loop (v0.9.6 · upstream consolidation) -- audit_mesh only diagnoses, this module treats.

Status: audit_mesh reports boundary_edges / nonmanifold_edges / degenerate_faces / loose_verts /
self_intersections / normals_inverted, but is **strictly read-only**. Upstream blend-ai has repair_mesh / decimate_mesh;
this module reimplements them with the same interface shape and criteria (no AGPL code is copied, only the idea that "a repair must be able to prove itself").

ops:
    blender_rt_plan(op="fix_repair",   args={objects:["P01"], actions:["merge_doubles","dissolve_degenerate","delete_loose","recalc_normals","fill_holes"]})
    blender_rt_plan(op="fix_decimate", args={objects:["P01"], target_tris:2000})
    blender_rt_plan(op="fix_selftest")

**Hard rules**: 0 meshes ⇒ ok=false; empty actions ⇒ ok=false; repair is a destructive operation ⇒ the receipt must carry
"before/after defect counts", and only a clear drop in nonmanifold_edges + degenerate_faces counts as ok=true (otherwise ok=false +
an explanation of why nothing moved). For a pre-change rollback point use blender_rt_txn(op="snapshot") (object-level mark/revert does not cover topology).
"""
import json
import math

import bpy
import bmesh

FIX_VERSION = 1
ACTIONS = ("merge_doubles", "dissolve_degenerate", "delete_loose", "recalc_normals", "fill_holes")
EPS_AREA = 1e-9


import sys as _sys_kit
_KIT = getattr(_sys_kit.modules.get("dsh_rt_kernel"), "dsh_kit", None)
if _KIT is None:
    raise RuntimeError("mesh_fix requires the shared kernel K.dsh_kit (injected by KERNEL_BOOTSTRAP)")


_j = _KIT.j  # shared kernel (the former built-in implementation was removed)
def _num(v, name, lo=None, hi=None, default=None):
    if v is None:
        if default is None:
            raise ValueError("%s is required" % name)
        return float(default)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError("%s needs a number, got %r" % (name, v))
    f = float(v)
    if not math.isfinite(f):
        raise ValueError("%s must be a finite number (NaN/Inf corrupts the .blend)" % name)
    if lo is not None and f < lo:
        raise ValueError("%s=%g is below the lower bound %g" % (name, f, lo))
    if hi is not None and f > hi:
        raise ValueError("%s=%g is above the upper bound %g" % (name, f, hi))
    return f


def _objs(objects=None, scope="ACTIVE"):
    if objects:
        names = [objects] if isinstance(objects, str) else list(objects)
        out = []
        for n in names:
            ob = bpy.data.objects.get(str(n))
            if ob is None:
                raise ValueError("object does not exist: %s" % n)
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
            raise ValueError("no active mesh object (pass objects=[...] or scope=SELECTED/VISIBLE/ALL)")
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


def _defects_bm(bm, eps_area=EPS_AREA):
    """Defect counts under the same criterion as audit_mesh (bmesh version, measured once before and once after the repair)."""
    return {
        "verts": len(bm.verts), "edges": len(bm.edges), "faces": len(bm.faces),
        "boundary_edges": sum(1 for e in bm.edges if len(e.link_faces) == 1),
        "nonmanifold_edges": sum(1 for e in bm.edges if not e.is_manifold),
        "degenerate_faces": sum(1 for f in bm.faces if f.calc_area() <= float(eps_area)),
        "loose_verts": sum(1 for v in bm.verts if not v.link_edges),
        "loose_edges": sum(1 for e in bm.edges if not e.link_faces),
    }


def _defects_me(me, eps_area=EPS_AREA):
    bm = bmesh.new()
    bm.from_mesh(me)
    d = _defects_bm(bm, eps_area)
    bm.free()
    return d


def fix_repair(objects=None, scope="ACTIVE", actions=None, merge_threshold=1e-4, eps_area=EPS_AREA,
               max_hole_edges=64, preserve_volume=False):
    """Treat the defect list from audit_mesh and give a before/after comparison (ok=false when nothing actually improved)."""
    acts = list(actions) if actions else ["merge_doubles", "dissolve_degenerate", "delete_loose", "recalc_normals"]
    bad = sorted(set(acts) - set(ACTIONS))
    if bad:
        raise ValueError("unknown actions %s (allowed %s)" % (bad, list(ACTIONS)))
    if not acts:
        raise ValueError("actions must not be empty (write exactly what should be fixed)")
    thr = _num(merge_threshold, "merge_threshold", 1e-9, 1.0)
    eps = _num(eps_area, "eps_area", 0.0, 1.0, EPS_AREA)
    mhe = int(_num(max_hole_edges, "max_hole_edges", 3, 100000))
    obs = _objs(objects, scope)
    out = []
    for ob in obs:
        me = ob.data
        if len(me.vertices) == 0:
            out.append({"name": ob.name, "ok": False, "error": "0 vertices"})
            continue
        bm = bmesh.new()
        bm.from_mesh(me)
        before = _defects_bm(bm, eps)
        steps = []
        try:
            for a in acts:
                if a == "merge_doubles":
                    n0 = len(bm.verts)
                    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=thr)
                    steps.append({"action": a, "verts_before": n0, "verts_after": len(bm.verts)})
                elif a == "dissolve_degenerate":
                    n0 = len(bm.faces)
                    bmesh.ops.dissolve_degenerate(bm, dist=thr, edges=list(bm.edges))
                    steps.append({"action": a, "faces_before": n0, "faces_after": len(bm.faces)})
                elif a == "delete_loose":
                    el = [e for e in bm.edges if not e.link_faces]
                    if el:
                        bmesh.ops.delete(bm, geom=el, context="EDGES")
                    vl = [v for v in bm.verts if not v.link_edges]
                    if vl:
                        bmesh.ops.delete(bm, geom=vl, context="VERTS")
                    steps.append({"action": a, "removed_edges": len(el), "removed_verts": len(vl)})
                elif a == "recalc_normals":
                    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
                    steps.append({"action": a})
                elif a == "fill_holes":
                    bd = [e for e in bm.edges if len(e.link_faces) == 1]
                    if bd:
                        bmesh.ops.holes_fill(bm, edges=bd, sides=mhe)
                    steps.append({"action": a, "boundary_edges": len(bd)})
            after = _defects_bm(bm, eps)
            bm.to_mesh(me)
            me.update()
        finally:
            bm.free()
        d_nm = before["nonmanifold_edges"] - after["nonmanifold_edges"]
        d_dg = before["degenerate_faces"] - after["degenerate_faces"]
        d_lv = before["loose_verts"] - after["loose_verts"]
        improved = (d_nm + d_dg + d_lv) > 0
        # a boundary edge (only 1 face) also counts as non-manifold under Blender's is_manifold criterion;
        # but an open shell is a design choice and must not be judged as "not fixed" → the residual is counted as "truly non-manifold" (>2 faces/wire edges).
        real_nonmanifold = max(0, after["nonmanifold_edges"] - after["boundary_edges"])
        residual_bad = real_nonmanifold > 0 or after["degenerate_faces"] > 0
        out.append({"name": ob.name, "ok": bool(improved and not residual_bad),
                    "improved": bool(improved), "residual": residual_bad,
                    "before": before, "after": after, "steps": steps,
                    "tris_after": _tris(me),
                    "real_nonmanifold": real_nonmanifold,
                    "open_shell": bool(after["boundary_edges"] > 0),
                    "note": ("real defects remain (>2-face edges or zero-area faces): deep-dive with audit_mesh first" if residual_bad
                             else ("cleared (an open shell with boundary=%d is a design choice, not force-sealed)" % after["boundary_edges"]
                                   if after["boundary_edges"] else "defects cleared, and the mesh is closed"))})
    ok = all(r.get("ok") for r in out)
    return _j({"ok": bool(ok), "actions": acts, "objects": out,
               "note": "repair is destructive: without a snapshot beforehand there is no way back; do not treat residual defects as if nothing was fixed"})


def fix_decimate(objects=None, scope="ACTIVE", ratio=None, target_tris=None, mode="COLLAPSE"):
    """Decimate: ratio (0<r<=1) or target_tris (ratio derived automatically)."""
    m = str(mode or "COLLAPSE").upper()
    if m not in ("COLLAPSE", "UNSUBDIV", "DISSOLVE"):
        raise ValueError("unknown mode: %s (COLLAPSE/UNSUBDIV/DISSOLVE)" % mode)
    obs = _objs(objects, scope)
    out = []
    for ob in obs:
        me = ob.data
        t0 = _tris(me)
        if t0 <= 0:
            out.append({"name": ob.name, "ok": False, "error": "0 triangles"})
            continue
        if target_tris is not None:
            r = _num(target_tris, "target_tris", 1, 1e9) / float(t0)
            r = max(0.01, min(1.0, r))
        else:
            r = _num(ratio, "ratio", 0.01, 1.0)
        bpy.context.view_layer.objects.active = ob
        md = ob.modifiers.new(name="Decimate", type="DECIMATE")
        md.decimate_type = m
        md.ratio = r
        op = str(bpy.ops.object.modifier_apply(modifier=md.name))
        out.append({"name": ob.name, "ok": True, "mode": m, "ratio": round(r, 6),
                    "tris_before": t0, "tris_after": _tris(me), "verts_after": len(me.vertices), "op": op})
    return _j({"ok": all(r.get("ok") for r in out), "objects": out,
               "note": "decimation changes topology and UV density; to keep UVs, inspect with uv_stats first and uv_pack after"})


def fix_selftest():
    """Self-test: synthesize a defective mesh (boundary hole + zero-area face + loose vertex) → repair → assert the defect count drops → delete it cleanly."""
    me = bpy.data.meshes.new("__dsh_fix_selftest")
    ob = bpy.data.objects.new("__dsh_fix_selftest", me)
    bpy.context.scene.collection.objects.link(ob)
    ev = {}
    try:
        bm = bmesh.new()
        v = [bm.verts.new(c) for c in [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]]
        bm.faces.new(v)                                  # open quad → 4 boundary edges
        v2 = [bm.verts.new(c) for c in [(0, 0, 0), (1, 0, 0), (2, 0, 0)]]
        bm.faces.new(v2)                                 # zero area (collinear)
        bm.verts.new((5, 5, 5))                          # loose vertex
        bm.to_mesh(me)
        bm.free()
        ev["before"] = _defects_me(me)
        r = json.loads(fix_repair(objects=[ob.name],
                                  actions=["dissolve_degenerate", "delete_loose", "merge_doubles"]))
        ev["repair"] = {"ok": r.get("ok"), "before": r["objects"][0]["before"], "after": r["objects"][0]["after"]}
        ok = (ev["repair"]["after"]["degenerate_faces"] < ev["repair"]["before"]["degenerate_faces"]
              and ev["repair"]["after"]["loose_verts"] < ev["repair"]["before"]["loose_verts"])
        return _j({"ok": bool(ok), "evidence": ev})
    except Exception as e:
        return _j({"ok": False, "evidence": ev, "error": "%s: %s" % (type(e).__name__, str(e)[:200])})
    finally:
        try:
            bpy.data.objects.remove(ob, do_unlink=True)
            bpy.data.meshes.remove(me, do_unlink=True)
        except Exception:
            pass


def fix_help():
    return _j({
        "module": "mesh_fix.py", "version": FIX_VERSION,
        "ops": {
            "fix_repair": "actions=[merge_doubles|dissolve_degenerate|delete_loose|recalc_normals|fill_holes], "
                          "merge_threshold (default 1e-4), max_hole_edges (default 64); the receipt carries before/after defect counts",
            "fix_decimate": "ratio=0.01..1 or target_tris=N; mode=COLLAPSE|UNSUBDIV|DISSOLVE",
            "fix_selftest": "self-test: synthesize a defective mesh → repair → assert the defect count drops",
            "fix_help": "this table",
        },
        "workflow": ["audit_mesh to get the defect list", "blender_rt_txn(op=\"snapshot\") to leave a rollback point",
                     "fix_repair (merge+dissolve+delete_loose first, recalc_normals as the safety net)",
                     "re-check with audit_mesh until nonmanifold/degenerate reach zero", "audit_gate to pass"],
        "hard_rules": ["0 meshes ⇒ ok=false", "actions empty ⇒ ok=false",
                       "nothing improved (defect count did not drop) ⇒ ok=false; never treat 'ran' as 'fixed'"],
        "limits": {"open_shell": "shells that are meant to be open by design (thin shells/patches) must not use fill_holes, it seals them shut",
                   "uv": "repair and decimation both change UV density; re-check with uv_stats before delivery"},
    })


def fix_dispatch(op, args_json):
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
    ops = {"repair": fix_repair, "decimate": fix_decimate, "selftest": fix_selftest, "help": fix_help}
    fn = ops.get(str(op))
    if fn is None:
        return _j({"ok": False, "error": "unknown fix op", "op": op, "ops": sorted(ops)})
    import inspect
    try:
        allowed = set(inspect.signature(fn).parameters)
        unknown = sorted(set(kw) - allowed)
        if unknown:
            return _j({"ok": False, "error": "unrecognized parameter %s" % unknown, "op": op, "allowed": sorted(allowed)})
    except (TypeError, ValueError):
        pass
    try:
        return fn(**kw)
    except TypeError as e:
        return _j({"ok": False, "error": "parameter mismatch: %s" % str(e)[:200], "op": op, "help": fix_help()})
    except Exception as e:
        return _j({"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:220]), "op": op})


_DshApi = _KIT.Api  # shared kernel (the registration line at the end needs no change)
import sys as _sys
_K = _sys.modules.get("dsh_rt_kernel")
if _K is not None:
    _K.dsh_fix_api = _DshApi({"version": FIX_VERSION, "dispatch": fix_dispatch, "repair": fix_repair,
                              "decimate": fix_decimate, "selftest": fix_selftest, "help": fix_help})
