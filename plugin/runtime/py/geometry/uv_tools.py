# -*- coding: utf-8 -*-
"""DSH UV toolkit (v0.9.6 · upstream integration) — delivering OBJ/MTL with textures requires UVs, and the old runtime had
zero hits for unwrap/smart_project across the whole codebase.

ops:
    blender_rt_plan(op="uv_stats",        args={objects:["Body"]})                     # read-only
    blender_rt_plan(op="uv_smart_project",args={objects:["Body"], angle_limit:66, island_margin:0.02})
    blender_rt_plan(op="uv_unwrap",       args={objects:["Body"], method:"SLIM", margin:0.001})
    blender_rt_plan(op="uv_project",      args={objects:["Body"], type:"CUBE"})
    blender_rt_plan(op="uv_pack",         args={objects:["Body"], margin:0.002, rotate:true})
    blender_rt_plan(op="uv_selftest")

**Enums are never guessed**: unwrap's method / pack's shape_method take their candidates from the operator's RNA enum; a wrong value reports
"allowed [..]" instead of letting Blender throw something unreadable.
**Side effects**: UV operators must enter EDIT mode and select all faces — this module restores the original object/mode/selection in finally.
"""
import json
import math

import bpy

UV_VERSION = 1


import sys as _sys_kit
_KIT = getattr(_sys_kit.modules.get("dsh_rt_kernel"), "dsh_kit", None)
if _KIT is None:
    raise RuntimeError("uv_tools requires the shared kernel K.dsh_kit (injected by KERNEL_BOOTSTRAP)")


_j = _KIT.j  # shared kernel (the old bundled implementation was removed)
def _num(v, name, lo=None, hi=None, default=None):
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


def _objs(objects=None, scope="ACTIVE"):
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
            raise ValueError("no active mesh object")
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
    raise ValueError("unknown scope: %s" % scope)


def _enum_items(path, prop):
    """Take enum candidates from the operator's RNA (never guess parameter values — enums change between versions)."""
    try:
        op = bpy.ops
        for k in path.split("."):
            op = getattr(op, k)
        rna = op.get_rna_type()
        items = [it.identifier for it in rna.properties[prop].enum_items]
        default = getattr(rna.properties[prop], "default", None)
        return items, default
    except Exception:
        return [], None


def _view_ctx():
    for w in bpy.context.window_manager.windows:
        if w.screen is None:
            continue
        for a in w.screen.areas:
            if a.type == "VIEW_3D":
                reg = next((r for r in a.regions if r.type == "WINDOW"), None)
                if reg is not None:
                    return w, a, reg
    return None, None, None


def _with_edit(ob, fn):
    """Enter EDIT + select all faces, run fn(); restore the original object/mode/selection whatever happens."""
    prev_active = bpy.context.view_layer.objects.active
    prev_mode = prev_active.mode if prev_active else None
    prev_sel = list(bpy.context.selected_objects)
    try:
        for o in bpy.context.selected_objects:
            o.select_set(False)
        ob.select_set(True)
        bpy.context.view_layer.objects.active = ob
        if ob.mode != "EDIT":
            bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        win, ar, reg = _view_ctx()
        if win and ar and reg:
            with bpy.context.temp_override(window=win, screen=win.screen, area=ar, region=reg):
                return fn()
        return fn()
    finally:
        try:
            if ob.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
        try:
            for o in bpy.context.selected_objects:
                o.select_set(False)
            for o in prev_sel:
                try:
                    o.select_set(True)
                except Exception:
                    pass
            if prev_active is not None:
                bpy.context.view_layer.objects.active = prev_active
            if prev_mode and prev_mode != "OBJECT" and prev_active is not None:
                bpy.ops.object.mode_set(mode=prev_mode)
        except Exception:
            pass


def _uv_stats_one(ob):
    me = ob.data
    layers = [l.name for l in me.uv_layers]
    rec = {"name": ob.name, "uv_layers": layers, "has_uv": bool(layers), "loops": len(me.loops)}
    if not layers:
        return rec
    uvl = me.uv_layers.active
    if uvl is None:
        return rec
    us = [0.0, 0.0, 0.0, 0.0]
    degenerate = 0
    outside = 0
    n = 0
    for p in me.polygons:
        area = 0.0
        pts = []
        for li in p.loop_indices:
            uv = uvl.data[li].uv
            pts.append((float(uv[0]), float(uv[1])))
            us[0] = min(us[0], uv[0]); us[1] = min(us[1], uv[1])
            us[2] = max(us[2], uv[0]); us[3] = max(us[3], uv[1])
            if uv[0] < -1e-6 or uv[0] > 1 + 1e-6 or uv[1] < -1e-6 or uv[1] > 1 + 1e-6:
                outside += 1
        for i in range(len(pts)):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % len(pts)]
            area += x1 * y2 - x2 * y1
        if abs(area) * 0.5 <= 1e-12:
            degenerate += 1
        n += 1
    rec.update({"uv_bbox": [round(x, 6) for x in us], "uv_width": round(us[2] - us[0], 6),
                "uv_height": round(us[3] - us[1], 6),
                "degenerate_uv_faces": degenerate, "faces": n,
                "loops_outside_0_1": outside})
    rec["ok"] = bool(layers) and degenerate == 0
    if degenerate:
        rec["hint"] = "zero-area UV faces present: re-unwrap with uv_unwrap or uv_smart_project first"
    return rec


def uv_stats(objects=None, scope="ACTIVE"):
    obs = _objs(objects, scope)
    rows = [_uv_stats_one(ob) for ob in obs]
    return _j({"ok": all(r.get("ok") for r in rows), "objects": rows,
               "note": "judge criteria: ok only when a UV layer exists and zero-area UV faces == 0"})


def uv_smart_project(objects=None, scope="ACTIVE", angle_limit=66.0, island_margin=0.02,
                     area_weight=0.0, correct_aspect=True, scale_to_bounds=False):
    ang = _num(angle_limit, "angle_limit", 1.0, 89.0)
    mar = _num(island_margin, "island_margin", 0.0, 1.0)
    aw = _num(area_weight, "area_weight", 0.0, 1.0)
    obs = _objs(objects, scope)
    out = []
    for ob in obs:
        rec = {"name": ob.name}
        try:
            r = _with_edit(ob, lambda: str(bpy.ops.uv.smart_project(
                angle_limit=math.radians(ang), island_margin=mar, area_weight=aw,
                correct_aspect=bool(correct_aspect), scale_to_bounds=bool(scale_to_bounds))))
            rec["op"] = r
            rec.update(_uv_stats_one(ob))
        except Exception as e:
            rec["ok"] = False
            rec["error"] = "%s: %s" % (type(e).__name__, str(e)[:180])
        out.append(rec)
    return _j({"ok": all(r.get("ok") for r in out), "objects": out,
               "params": {"angle_limit": ang, "island_margin": mar, "area_weight": aw}})


def uv_unwrap(objects=None, scope="ACTIVE", method=None, margin=0.001, fill_holes=True,
              correct_aspect=True, use_subsurf_data=False):
    allow, default = _enum_items("uv.unwrap", "method")
    m = None
    if method:
        m = str(method).upper()
        if allow and m not in allow:
            return _j({"ok": False, "error": "Unknown unwrap method: %s" % m, "allowed": allow})
    else:
        for cand in ("SLIM", "MINIMUM_STRETCH", "ANGLE_BASED", "CONFORMAL"):
            if (not allow) or cand in allow:
                m = cand
                break
        m = m or (default if isinstance(default, str) else None)
    mar = _num(margin, "margin", 0.0, 1.0)
    obs = _objs(objects, scope)
    out = []
    for ob in obs:
        rec = {"name": ob.name, "method": m}
        try:
            kw = {"margin": mar}
            if m:
                kw["method"] = m
            kw["fill_holes"] = bool(fill_holes)
            kw["correct_aspect"] = bool(correct_aspect)
            try:
                rec["op"] = _with_edit(ob, lambda: str(bpy.ops.uv.unwrap(**kw)))
            except TypeError:
                kw.pop("method", None)
                rec["op"] = _with_edit(ob, lambda: str(bpy.ops.uv.unwrap(**kw)))
                rec["method_note"] = "this Blender version's unwrap does not accept method (using the default algorithm)"
            rec.update(_uv_stats_one(ob))
        except Exception as e:
            rec["ok"] = False
            rec["error"] = "%s: %s" % (type(e).__name__, str(e)[:180])
        out.append(rec)
    return _j({"ok": all(r.get("ok") for r in out), "objects": out, "allowed_methods": allow})


def uv_project(objects=None, scope="ACTIVE", type="CUBE", correct_aspect=True, scale_to_bounds=False,
               cube_size=1.0):
    t = str(type or "CUBE").upper()
    ops_map = {"CUBE": ("uv.cube_project", "cube_size"), "SPHERE": ("uv.sphere_project", None),
               "CYLINDER": ("uv.cylinder_project", None)}
    if t not in ops_map:
        return _j({"ok": False, "error": "unknown type: %s (CUBE/SPHERE/CYLINDER)" % type})
    obs = _objs(objects, scope)
    out = []
    for ob in obs:
        rec = {"name": ob.name, "type": t}
        path, size_kw = ops_map[t]
        fn = bpy.ops
        for k in path.split("."):
            fn = getattr(fn, k)
        try:
            kw = {"correct_aspect": bool(correct_aspect), "scale_to_bounds": bool(scale_to_bounds)}
            if size_kw:
                kw[size_kw] = _num(cube_size, "cube_size", 1e-6, 1e6, 1.0)
            rec["op"] = _with_edit(ob, lambda: str(fn(**kw)))
            rec.update(_uv_stats_one(ob))
        except Exception as e:
            rec["ok"] = False
            rec["error"] = "%s: %s" % (type(e).__name__, str(e)[:180])
        out.append(rec)
    return _j({"ok": all(r.get("ok") for r in out), "objects": out})


def uv_pack(objects=None, scope="ACTIVE", margin=0.001, rotate=True, margin_method=None,
            shape_method=None, scale=True):
    mm, mm_default = _enum_items("uv.pack_islands", "margin_method")
    sm, sm_default = _enum_items("uv.pack_islands", "shape_method")
    mar = _num(margin, "margin", 0.0, 1.0)
    obs = _objs(objects, scope)
    out = []
    for ob in obs:
        rec = {"name": ob.name}
        kw = {"margin": mar, "rotate": bool(rotate), "scale": bool(scale)}
        if margin_method:
            v = str(margin_method).upper()
            if mm and v not in mm:
                return _j({"ok": False, "error": "Unknown margin_method: %s" % v, "allowed": mm})
            kw["margin_method"] = v
        if shape_method:
            v = str(shape_method).upper()
            if sm and v not in sm:
                return _j({"ok": False, "error": "Unknown shape_method: %s" % v, "allowed": sm})
            kw["shape_method"] = v
        try:
            rec["op"] = _with_edit(ob, lambda: str(bpy.ops.uv.pack_islands(**kw)))
            rec.update(_uv_stats_one(ob))
        except Exception as e:
            rec["ok"] = False
            rec["error"] = "%s: %s" % (type(e).__name__, str(e)[:180])
        out.append(rec)
    return _j({"ok": all(r.get("ok") for r in out), "objects": out,
               "allowed": {"margin_method": mm, "shape_method": sm}})


def uv_selftest():
    """Self-test: temp cube → smart project → assert UVs exist and no zero-area UV faces → clean up."""
    import bmesh
    me = bpy.data.meshes.new("__dsh_uv_selftest")
    ob = bpy.data.objects.new("__dsh_uv_selftest", me)
    bpy.context.scene.collection.objects.link(ob)
    ev = {}
    try:
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        bm.to_mesh(me)
        bm.free()
        ev["before_has_uv"] = bool(me.uv_layers)
        r = json.loads(uv_smart_project(objects=[ob.name], angle_limit=66.0, island_margin=0.01))
        ev["project"] = {"ok": r.get("ok"), "uv_layers": r["objects"][0].get("uv_layers"),
                         "degenerate": r["objects"][0].get("degenerate_uv_faces"),
                         "uv_bbox": r["objects"][0].get("uv_bbox"), "op": r["objects"][0].get("op")}
        r2 = json.loads(uv_pack(objects=[ob.name], margin=0.01))
        ev["pack"] = {"ok": r2.get("ok"), "uv_bbox": r2["objects"][0].get("uv_bbox")}
        ok = bool(ev["project"]["uv_layers"]) and ev["project"]["degenerate"] == 0 and ev["pack"]["ok"]
        return _j({"ok": ok, "evidence": ev})
    except Exception as e:
        return _j({"ok": False, "evidence": ev, "error": "%s: %s" % (type(e).__name__, str(e)[:200])})
    finally:
        try:
            bpy.data.objects.remove(ob, do_unlink=True)
            bpy.data.meshes.remove(me, do_unlink=True)
        except Exception:
            pass


def uv_help():
    return _j({
        "module": "uv_tools.py", "version": UV_VERSION,
        "ops": {
            "uv_stats": "read-only: UV layer names / UV bbox / zero-area UV faces / loops outside 0-1 (judge: layer exists and zero-area == 0)",
            "uv_smart_project": "angle_limit (degrees, default 66) / island_margin / area_weight / correct_aspect / scale_to_bounds",
            "uv_unwrap": "method auto-picks SLIM→MINIMUM_STRETCH→ANGLE_BASED→CONFORMAL (candidates read from RNA; a bad value reports allowed)",
            "uv_project": "type=CUBE|SPHERE|CYLINDER (+ cube_size)",
            "uv_pack": "margin / rotate / margin_method / shape_method (enums also read from RNA)",
            "uv_selftest": "self-test: cube smart project + pack, asserting UVs exist and no zero-area faces",
            "uv_help": "this table",
        },
        "workflow": ["uv_stats to see the current state", "uv_smart_project in one pass (mechanical/hardsurface)",
                     "or uv_unwrap (organic/character, SLIM stretches least)", "uv_pack to lay out",
                     "uv_stats re-checks zero-area == 0", "deliver_export produces OBJ/MTL with textures"],
        "side_effects": "UV operators must enter EDIT mode and select all faces; this module restores the original object/mode/selection in finally",
    })


def uv_dispatch(op, args_json):
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
    ops = {"stats": uv_stats, "smart_project": uv_smart_project, "unwrap": uv_unwrap,
           "project": uv_project, "pack": uv_pack, "selftest": uv_selftest, "help": uv_help}
    fn = ops.get(str(op))
    if fn is None:
        return _j({"ok": False, "error": "unknown uv op", "op": op, "ops": sorted(ops)})
    import inspect
    try:
        allowed = set(inspect.signature(fn).parameters)
        unknown = sorted(set(kw) - allowed)
        if unknown:
            return _j({"ok": False, "error": "unknown parameters %s" % unknown, "op": op, "allowed": sorted(allowed)})
    except (TypeError, ValueError):
        pass
    try:
        return fn(**kw)
    except TypeError as e:
        return _j({"ok": False, "error": "argument mismatch: %s" % str(e)[:200], "op": op, "help": uv_help()})
    except Exception as e:
        return _j({"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:220]), "op": op})


_DshApi = _KIT.Api  # shared kernel (the trailing registration line needs no change)
import sys as _sys
_K = _sys.modules.get("dsh_rt_kernel")
if _K is not None:
    _K.dsh_uv_api = _DshApi({"version": UV_VERSION, "dispatch": uv_dispatch, "stats": uv_stats,
                             "smart_project": uv_smart_project, "unwrap": uv_unwrap,
                             "project": uv_project, "pack": uv_pack, "selftest": uv_selftest,
                             "help": uv_help})
