# -*- coding: utf-8 -*-
"""DSH sweep along a path (v0.9.6 · upstream integration) — parts that follow a path: pipes/hoses/cables/tracks/guardrails.

In the old runtime, sweep only showed up in qc/motion as "scanning", with **no ability to form geometry along a path**.
Upstream blend-ai has sweep_profile_along_path + analyze_sweep_path (it works out first whether the path's bends are wide enough).
This module reimplements both under the same interface shape: a rotation-minimizing frame, so it neither twists nor flips.

ops:
    blender_rt_plan(op="sweep_analyze", args={path:[[0,0,0],[1,0,0],[1,1,0]], profile:{type:"circle", radius:0.05}})
    blender_rt_plan(op="sweep_build",   args={name:"Hose", path:[[0,0,0],[1,0,0],[1,1,0]],
                                             profile:{type:"rect", width:0.08, height:0.04}, cap:true})
    blender_rt_plan(op="sweep_selftest")

**Analyze before you build**: sweep_build runs sweep_analyze first by default; when the bend radius is below the profile's half-width it refuses outright (force=true makes it do it anyway),
because "the sweep self-intersects" cannot be fixed geometrically — the same discipline as the contract layer's destructive_guard.
"""
import json
import math

import bpy
from mathutils import Vector

SWEEP_VERSION = 1


import sys as _sys_kit
_KIT = getattr(_sys_kit.modules.get("dsh_rt_kernel"), "dsh_kit", None)
if _KIT is None:
    raise RuntimeError("sweep needs the shared kernel K.dsh_kit (injected by KERNEL_BOOTSTRAP)")


_j = _KIT.j  # shared kernel (the bundled implementation has been removed)
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


def _vec3(v, name):
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        raise ValueError("%s needs [x,y,z], got %r" % (name, v))
    return [ _num(v[0], name + "[0]"), _num(v[1], name + "[1]"), _num(v[2], name + "[2]") ]


def _profile(profile):
    """Normalise the profile: returns (point list [(u,v)], max outer size)."""
    p = profile if isinstance(profile, dict) else {"type": "circle", "radius": 0.05}
    t = str(p.get("type") or ("points" if p.get("points") else "circle")).lower()
    if t == "circle":
        r = _num(p.get("radius"), "profile.radius", 1e-6, 1e6)
        seg = int(_num(p.get("segments"), "profile.segments", 3, 256, 16))
        pts = [(r * math.cos(2 * math.pi * i / seg), r * math.sin(2 * math.pi * i / seg)) for i in range(seg)]
        return pts, 2.0 * r
    if t == "rect":
        w = _num(p.get("width"), "profile.width", 1e-6, 1e6)
        h = _num(p.get("height"), "profile.height", 1e-6, 1e6)
        hw, hh = w / 2.0, h / 2.0
        return [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)], max(w, h)
    if t == "points":
        raw = p.get("points")
        if not isinstance(raw, (list, tuple)) or len(raw) < 3:
            raise ValueError("profile.points needs at least 3 points")
        pts = [(_num(q[0], "profile.points[][0]"), _num(q[1], "profile.points[][1]")) for q in raw]
        sz = 2.0 * max(max(abs(a), abs(b)) for a, b in pts)
        return pts, sz
    raise ValueError("unknown profile.type: %s (circle/rect/points)" % t)


def _path_points(path=None, path_object=None):
    """Path source: either an explicit path=[[x,y,z]...] or path_object=<curve/mesh object> (curves are sampled from the evaluated mesh)."""
    if path:
        if not isinstance(path, (list, tuple)) or len(path) < 2:
            raise ValueError("path needs at least 2 points")
        return [Vector(_vec3(p, "path[%d]" % i)) for i, p in enumerate(path)]
    if not path_object:
        raise ValueError("path or path_object is required")
    ob = bpy.data.objects.get(str(path_object))
    if ob is None:
        raise ValueError("object does not exist: %s" % path_object)
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    try:
        pts = [ob.matrix_world @ v.co.copy() for v in me.vertices]
    finally:
        ev.to_mesh_clear()
    if len(pts) < 2:
        raise ValueError("path_object sampled fewer than 2 points (a curve needs geometry)")
    return pts


def _frames(pts, up=None):
    """Rotation-minimizing frame: the normal is carried between adjacent tangents with rotation_difference to avoid twist/flip."""
    n = len(pts)
    tan = []
    for i in range(n):
        if i == 0:
            t = pts[1] - pts[0]
        elif i == n - 1:
            t = pts[-1] - pts[-2]
        else:
            t = pts[i + 1] - pts[i - 1]
        if t.length < 1e-12:
            raise ValueError("path point %d coincides with its neighbour (spacing is 0)" % i)
        tan.append(t.normalized())
    upv = Vector(_vec3(up, "up")) if up else Vector((0.0, 0.0, 1.0))
    n0 = upv - tan[0] * upv.dot(tan[0])
    if n0.length < 1e-9:
        n0 = Vector((1.0, 0.0, 0.0)) - tan[0] * tan[0].x
        if n0.length < 1e-9:
            n0 = Vector((0.0, 1.0, 0.0)) - tan[0] * tan[0].y
    n0.normalize()
    normals = [n0]
    for i in range(1, n):
        q = tan[i - 1].rotation_difference(tan[i])
        nv = (q @ normals[-1])
        nv = nv - tan[i] * nv.dot(tan[i])
        if nv.length < 1e-9:
            nv = normals[-1]
        normals.append(nv.normalized())
    binorm = [tan[i].cross(normals[i]).normalized() for i in range(n)]
    return tan, normals, binorm


def _bend_radii(pts):
    """Bend radius of every interior point (circumradius of the triangle); None when nearly collinear (treated as straight)."""
    out = []
    for i in range(1, len(pts) - 1):
        a, b, c = pts[i - 1], pts[i], pts[i + 1]
        ab = (b - a).length
        bc = (c - b).length
        ca = (a - c).length
        s = (ab + bc + ca) / 2.0
        area2 = s * (s - ab) * (s - bc) * (s - ca)
        area = math.sqrt(area2) if area2 > 0 else 0.0
        if area <= 1e-12 or ab <= 0 or bc <= 0 or ca <= 0:
            out.append(None)
        else:
            out.append((ab * bc * ca) / (4.0 * area))
    return out


def sweep_analyze(path=None, path_object=None, profile=None, min_radius_factor=1.0, up=None):
    """Read-only: path bend radius vs profile half-width — if it is too tight, change the path first instead of sweeping into self-intersection."""
    pts = _path_points(path, path_object)
    prof, size = _profile(profile)
    factor = _num(min_radius_factor, "min_radius_factor", 0.1, 100.0, 1.0)
    radii = _bend_radii(pts)
    req = (size / 2.0) * factor
    worst = None
    for i, r in enumerate(radii):
        if r is None:
            continue
        if worst is None or r < worst[1]:
            worst = (i + 1, r)
    finite = [r for r in radii if r is not None]
    ok = (worst is None) or (worst[1] >= req)
    rec = {"ok": bool(ok), "points": len(pts), "profile_max_size": round(size, 6),
           "required_min_radius": round(req, 6),
           "min_radius": round(min(finite), 6) if finite else None,
           "min_radius_at": worst[0] if worst else None,
           "straight_segments": sum(1 for r in radii if r is None),
           "segment_lengths": [round((pts[i + 1] - pts[i]).length, 6) for i in range(len(pts) - 1)][:64],
           "total_length": round(sum((pts[i + 1] - pts[i]).length for i in range(len(pts) - 1)), 6)}
    if not ok:
        rec["hint"] = ("bend radius at path point %d is %.4f < required %.4f: split the corner into an arc, increase the spacing, or use a smaller profile"
                       % (worst[0], worst[1], req))
    return _j(rec)


def sweep_build(path=None, path_object=None, profile=None, name="Sweep", cap=True, close_path=False,
                up=None, smooth=True, collection=None, min_radius_factor=1.0, force=False,
                keep_original=False):
    """Sweep along the path (rotation-minimizing frame, no twist); analyze runs first by default and a too-tight path is refused (force=true forces it)."""
    pts = _path_points(path, path_object)
    prof, size = _profile(profile)
    anal = json.loads(sweep_analyze(path=[list(p) for p in pts], profile=profile,
                                    min_radius_factor=min_radius_factor, up=up))
    if not anal.get("ok") and not force:
        return _j({"ok": False, "stage": "analyze", "analysis": anal,
                   "error": "the path bends too tightly and the sweep would self-intersect; change the path first, or force=true to do it anyway"})
    if close_path:
        pts = pts + [pts[0]]
    tan, nor, bino = _frames(pts, up)
    m = len(prof)
    verts = []
    for i, p in enumerate(pts):
        for (u, v) in prof:
            q = p + nor[i] * u + bino[i] * v
            verts.append((q.x, q.y, q.z))
    faces = []
    for i in range(len(pts) - 1):
        for j in range(m):
            j2 = (j + 1) % m
            faces.append((i * m + j, i * m + j2, (i + 1) * m + j2, (i + 1) * m + j))
    if close_path:
        for j in range(m):
            j2 = (j + 1) % m
            faces.append(((len(pts) - 1) * m + j, (len(pts) - 1) * m + j2, j2, j))
    elif cap:
        c0 = len(verts)
        verts.append((pts[0].x, pts[0].y, pts[0].z))
        c1 = len(verts)
        verts.append((pts[-1].x, pts[-1].y, pts[-1].z))
        for j in range(m):
            j2 = (j + 1) % m
            faces.append((c0, j2, j))
            faces.append((c1, (len(pts) - 1) * m + j, (len(pts) - 1) * m + j2))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.validate()
    me.update()
    if smooth:
        for p in me.polygons:
            p.use_smooth = True
    ob = bpy.data.objects.new(name, me)
    coll = bpy.data.collections.get(str(collection)) if collection else None
    (coll.objects if coll else bpy.context.scene.collection.objects).link(ob)
    total = sum((pts[i + 1] - pts[i]).length for i in range(len(pts) - 1))
    return _j({"ok": True, "name": ob.name, "verts": len(me.vertices), "faces": len(me.polygons),
               "profile_points": m, "path_points": len(pts), "cap": bool(cap and not close_path),
               "closed": bool(close_path), "length": round(total, 6),
               "smooth": bool(smooth), "analysis": {"ok": anal.get("ok"),
                                                    "min_radius": anal.get("min_radius"),
                                                    "required_min_radius": anal.get("required_min_radius")},
               "note": "rotation-minimizing frame: no twist through bends; UV/material left to uv_smart_project + presets"})


def sweep_selftest():
    """Self-test: sweep a straight pipe and an elbow, assert the vertex/face counts, and check a too-tight path is rejected by analyze."""
    ev = {}
    made = []
    try:
        r1 = json.loads(sweep_build(name="__dsh_sweep_straight", path=[[0, 0, 0], [2, 0, 0], [4, 0, 0]],
                                    profile={"type": "circle", "radius": 0.1, "segments": 12}))
        made.append(r1.get("name"))
        ev["straight"] = {"ok": r1.get("ok"), "verts": r1.get("verts"), "faces": r1.get("faces")}
        r2 = json.loads(sweep_build(name="__dsh_sweep_elbow", path=[[0, 0, 0], [1, 0, 0], [1.05, 0.05, 0]],
                                    profile={"type": "rect", "width": 0.04, "height": 0.04}))
        made.append(r2.get("name"))
        ev["elbow"] = {"ok": r2.get("ok"), "min_radius": r2.get("analysis", {}).get("min_radius")}
        r3 = json.loads(sweep_analyze(path=[[0, 0, 0], [0.02, 0, 0], [0.02, 0.02, 0]],
                                      profile={"type": "rect", "width": 0.4, "height": 0.4}))
        ev["tight_should_fail"] = r3.get("ok")
        # expected: straight pipe 12 segments x 3 stations + 2 centre points = 38 vertices; faces = 12*2 + 12*2 = 48
        ok = (ev["straight"]["ok"] and ev["straight"]["verts"] == 38 and ev["straight"]["faces"] == 48
              and ev["elbow"]["ok"] and ev["tight_should_fail"] is False)
        return _j({"ok": bool(ok), "evidence": ev,
                   "expect": {"verts": 38, "faces": 48, "tight_path_ok": False}})
    except Exception as e:
        return _j({"ok": False, "evidence": ev, "error": "%s: %s" % (type(e).__name__, str(e)[:200])})
    finally:
        for nm in made:
            if not nm:
                continue
            ob = bpy.data.objects.get(nm)
            if ob is not None:
                me = ob.data
                bpy.data.objects.remove(ob, do_unlink=True)
                try:
                    bpy.data.meshes.remove(me, do_unlink=True)
                except Exception:
                    pass


def sweep_help():
    return _j({
        "module": "sweep.py", "version": SWEEP_VERSION,
        "ops": {
            "sweep_analyze": "read-only: path=[[x,y,z]...] or path_object=<curve>; profile={circle|rect|points}; "
                             "min_radius_factor defaults to 1.0; the receipt gives min_radius / required_min_radius / the point index",
            "sweep_build": "name / path|path_object / profile / cap (default true) / close_path / up / smooth / "
                           "collection / force (default false: a too-tight bend is refused outright)",
            "sweep_selftest": "self-test: straight pipe 38 vertices / 48 faces + elbow forming + a too-tight path being rejected",
            "sweep_help": "this table",
        },
        "profile_examples": {"circle": {"type": "circle", "radius": 0.05, "segments": 16},
                             "rect": {"type": "rect", "width": 0.08, "height": 0.04},
                             "custom": {"type": "points", "points": [[0, 0], [0.04, 0.01], [0.02, 0.05]]}},
        "why": "rotation-minimizing frame — no twist or flip through bends; analyze first, then build",
        "limits": "the path is a polyline (a curve object is sampled as its evaluated mesh); at a sharp corner there is one crease even when the radius is sufficient, "
                  "so for a rounded result round the curve first or split the corner into several segments",
    })


def sweep_dispatch(op, args_json):
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
    ops = {"analyze": sweep_analyze, "build": sweep_build, "selftest": sweep_selftest, "help": sweep_help}
    fn = ops.get(str(op))
    if fn is None:
        return _j({"ok": False, "error": "unknown sweep op", "op": op, "ops": sorted(ops)})
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
        return _j({"ok": False, "error": "parameters do not match: %s" % str(e)[:200], "op": op, "help": sweep_help()})
    except Exception as e:
        return _j({"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:220]), "op": op})


_DshApi = _KIT.Api  # shared kernel (the trailing registration line needs no change)
import sys as _sys
_K = _sys.modules.get("dsh_rt_kernel")
if _K is not None:
    _K.dsh_sweep_api = _DshApi({"version": SWEEP_VERSION, "dispatch": sweep_dispatch,
                                "analyze": sweep_analyze, "build": sweep_build,
                                "selftest": sweep_selftest, "help": sweep_help})
