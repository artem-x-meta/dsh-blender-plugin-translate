# -*- coding: utf-8 -*-
"""DSH mesh inspection (v0.9.1) + same-name resource auditing -- turning "wrong things a script can decide" into first-class citizens.

Why it exists (external feedback 00-G-1 / 93 §4): airframe-smith wrote its own af_geom.validate(), which **caught 13 self-intersections in the wing box,
39 zero-area faces on the leading-edge flap, 56 non-manifold edges on P03, and a radome ring vertex count of 60 vs 78**; without it those would have gone
into the authoritative scene and needed much later rework. sys-smith / qc-smith each built their own version too. Here it is consolidated into a general capability.

v0.9.1 (rifle-build "93 feedback"): **file-level operators** -- no more "everything must first be registered in the session".
    audit_overlap       cross-part/cross-file face-pair overlap (pairs / pair_count / intersection_bbox / per_object)
    audit_interference  cross-part/cross-file intersection volume in mm³ (Monte-Carlo ray parity, no bpy boolean)
    audit_connectivity / audit_gate / audit_measure all gain file=<.blend> (temporarily load -> run -> delete everything in finally)
API hangs off K.dsh_audit_api; entry points:
    blender_rt_plan(op="audit_mesh",  args={objects:["P01_Fuselage"], envelope:[min,max]})
    blender_rt_plan(op="audit_scene", args={envelope:[min,max]})
    blender_rt_plan(op="audit_overlap", args={file_a:".../05_barrel.blend", file_b:".../07_handguard.blend"})
    blender_rt_plan(op="audit_interference", args={file_a:".../08_magazine.blend", a:"08_magazine",
                                                   file_b:".../01_body_shell.blend", b:"01_body_shell",
                                                   samples:200000})
    blender_rt_plan(op="audit_connectivity", args={file:".../07_handguard.blend"})
    blender_rt_plan(op="audit_duplicates")
    blender_rt_plan(op="audit_purge_orphans")      # lights/cameras/meshes/materials/images with users==0
Headless you can also preload="audit" and then call K.dsh_audit_api["mesh"]({...}) directly, or K.dsh_audit_api("mesh", {...}) (since v0.9.1 the
dict subclass is callable and returns the parsed dict; api["dispatch"](op, json_str) still returns str -- the engine contract is unchanged).

**Hard rules**: 0 meshes in the object set ⇒ ok=false (the external "silent empty output" incident landed exactly on this rule);
file= fails to open / has no mesh / is fully hidden ⇒ ok=false; over the cap ⇒ analyzed=false ("did not run" must never be read as "no problem").
"""

import json as json

import bmesh as bmesh
import bpy
from mathutils import Vector

AUDIT_VERSION = 3


import sys as _sys_kit
_KIT = getattr(_sys_kit.modules.get("dsh_rt_kernel"), "dsh_kit", None)
if _KIT is None:
    raise RuntimeError("audit requires the shared kernel K.dsh_kit (injected by KERNEL_BOOTSTRAP)")


_j = _KIT.j  # shared kernel (the former built-in implementation was removed)
def _kernel():
    import sys
    return sys.modules.get("dsh_rt_kernel")


def _tris(me):
    # v2.6.1 (measured in practice, space elevator 137k faces): per-face len(p.vertices) over RNA costs 54–59 ms;
    # batching loop_total into a list first and then summing takes only 14–15 ms (about 3.8x). Small meshes keep the original path to avoid the fixed overhead.
    n = len(me.polygons)
    if n == 0:
        return 0
    if n >= 256:
        buf = [0] * n
        me.polygons.foreach_get("loop_total", buf)
        return sum(max(0, x - 2) for x in buf)
    total = 0
    for p in me.polygons:
        total += max(0, len(p.vertices) - 2)
    return total


def _bounds(objs):
    mn = Vector((1e30, 1e30, 1e30))
    mx = Vector((-1e30, -1e30, -1e30))
    n = 0
    for ob in objs:
        mw = ob.matrix_world
        for c in ob.bound_box:
            p = mw @ Vector((c[0], c[1], c[2]))
            for i in range(3):
                mn[i] = min(mn[i], p[i])
                mx[i] = max(mx[i], p[i])
        n += 1
    if n == 0:
        return None, None
    return mn, mx


def _pick(objects=None, scope=None):
    """Pick objects: objects=[name] takes precedence; otherwise those in scope (collection name); otherwise the visible meshes of the whole scene.

    Tolerance (v0.8.10): a wrapper dict like {"objects": [...]} passed in directly also works -- do not let the parameter-scope trap bite again.
    """
    if isinstance(objects, dict):
        _w = objects
        objects = _w.get("objects") or _w.get("names") or _w.get("list")
        if scope is None:
            scope = _w.get("scope")
    if objects:
        want = [str(x) for x in (objects if isinstance(objects, (list, tuple)) else [objects])]
        got, missing = [], []
        for n in want:
            ob = bpy.data.objects.get(n)
            if ob is None:
                missing.append(n)
            else:
                got.append(ob)
        return got, missing, None
    coll = None
    if scope:
        coll = bpy.data.collections.get(str(scope))
        if coll is None:
            return [], [], "collection not found: %s" % scope
        objs = [o for o in coll.all_objects if o.type == "MESH"]
    else:
        objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    return objs, [], None


def _box_relation(a, b, tol):
    """Relation of two AABBs: apart / a_in_b / b_in_a / same / cross."""
    if any(a[1][k] < b[0][k] - tol or b[1][k] < a[0][k] - tol for k in range(3)):
        return 'apart'
    a_in_b = all(a[0][k] >= b[0][k] - tol and a[1][k] <= b[1][k] + tol for k in range(3))
    b_in_a = all(b[0][k] >= a[0][k] - tol and b[1][k] <= a[1][k] + tol for k in range(3))
    if a_in_b and b_in_a:
        return 'same'
    if a_in_b:
        return 'a_in_b'
    if b_in_a:
        return 'b_in_a'
    return 'cross'


def _shell_bvh(shell, cache, key):
    """BVH of the faces inside a shell (for containment confirmation). Returns None when it cannot be built -- the caller must degrade, never treat it as passing."""
    if key in cache:
        return cache[key]
    from mathutils.bvhtree import BVHTree
    verts, idx, polys = [], {}, []
    for f in shell['_faces']:
        loop = []
        for v in f.verts:
            i = idx.get(v)
            if i is None:
                i = len(verts)
                idx[v] = i
                verts.append(v.co.copy())
            loop.append(i)
        if len(loop) >= 3:
            polys.append(loop)
    bvh = BVHTree.FromPolygons(verts, polys, all_triangles=False, epsilon=0.0) if polys else None
    cache[key] = bvh
    return bvh


def _ray_parity_inside(bvh, point):
    """Ray parity test for whether a point is inside the shell: one ray per axis, majority vote. Returns True/False (a tie counts as False)."""
    votes = 0
    for d in (Vector((1.0, 0.0, 0.0)), Vector((0.0, 1.0, 0.0)), Vector((0.0, 0.0, 1.0))):
        o = point.copy()
        hits = 0
        for _ in range(512):
            loc = bvh.ray_cast(o, d)[0]
            if loc is None:
                break
            hits += 1
            o = loc + d * 1e-6
        if hits % 2 == 1:
            votes += 1
    return votes >= 2


def _shell_contains(outer, inner, cache, key, max_points=6):
    """Containment confirmation: whether several sample points of the inner shell are **all** inside the outer shell.

    Returns True (nesting confirmed) / False (confirmed not nested -- the two shell surfaces interpenetrate, or the AABBs merely intersect).
    Exceptions propagate up and _shell_normals downgrades them uniformly to unknown.
    """
    bvh = _shell_bvh(outer, cache, key)
    if bvh is None:
        return False
    lo, hi = inner['bounds']
    pts = [Vector([(lo[k] + hi[k]) * 0.5 for k in range(3)])]     # AABB center
    # vertices are collected only here (nested candidates are few; no vertex table on the hot path)
    vs = {}
    for f in inner['_faces']:
        for v in f.verts:
            vs[v.index] = v.co
    idx = sorted(vs)
    step = max(1, len(idx) // max(1, int(max_points)))
    for i in idx[::step][:int(max_points)]:
        pts.append(vs[i])
    return all(_ray_parity_inside(bvh, p) for p in pts)


SHELL_MAX_FACES = 0              # **0 = no cap (run everything by default)**; acceptance does not degrade with scale. Set env DSH_SHELL_MAX_FACES explicitly to enable a cap
# measured in practice (Blender 5.2, this machine): 155k faces ≈ 0.67 s, 618k faces ≈ 11 s (3.5 s connectivity grouping + 7.7 s per-face metrics).
# over the cap ⇒ always unknown/degraded ("not analyzed ≠ pass"), never silently stall a large scene; set the env to force the analysis.


def _shell_max_faces():
    import os
    try:
        v = int(os.environ.get("DSH_SHELL_MAX_FACES", "") or 0)
        return v if v > 0 else SHELL_MAX_FACES
    except Exception:
        return SHELL_MAX_FACES


def _shell_components(bm):
    """Split shells by edge connectivity, then per shell compute signed volume/closedness/winding consistency/AABB (hot path: one pass, no intermediate sets)."""
    pending = set(bm.faces)
    shells = []
    while pending:
        seed = pending.pop()
        faces, stack = [seed], [seed]
        while stack:
            for edge in stack.pop().edges:
                for face in edge.link_faces:
                    if face in pending:
                        pending.remove(face)
                        faces.append(face)
                        stack.append(face)
        origin = faces[0].verts[0].co
        vol = 0.0
        closed = True
        consistent = True
        lo = [float("inf")] * 3
        hi = [float("-inf")] * 3
        for f in faces:
            vol += (f.calc_area() / 3.0) * f.normal.dot(f.calc_center_median() - origin)
            for e in f.edges:
                if len(e.link_faces) != 2:
                    closed = False
                elif not e.is_contiguous:
                    consistent = False
            for v in f.verts:
                co = v.co
                for k in range(3):
                    if co[k] < lo[k]:
                        lo[k] = co[k]
                    if co[k] > hi[k]:
                        hi[k] = co[k]
        eps = max(max(hi[i] - lo[i] for i in range(3)) ** 3 * 1e-12, 1e-30)
        shells.append(dict(faces=len(faces), signed_volume=vol, closed=closed,
                           winding_consistent=bool(closed and consistent), bounds=[lo, hi], eps=eps,
                           nested=False, relation='', state=('unknown' if not closed or abs(vol) <= eps else
                                                             'pass' if consistent and vol > 0 else 'fail'),
                           _faces=faces))
    return shells


def _shell_relations(shells):
    """Pairwise shell AABB relations + containment ray confirmation (budget/dedup cache); returns the ambiguous set."""
    dims = [max(s['bounds'][1][k] - s['bounds'][0][k] for k in range(3)) for s in shells]
    tol = max(dims) * 1e-9 if dims else 0.0
    ambiguous = set()
    cache, budget = {}, 64
    for i, a in enumerate(shells):
        for j in range(i):
            b = shells[j]
            rel = _box_relation(a['bounds'], b['bounds'], tol)
            if rel == 'apart':
                continue
            if rel == 'same' or rel == 'cross':
                shells[i]['relation'] = shells[j]['relation'] = rel
                ambiguous.update((i, j))
                continue
            inner_i, outer_j = (i, j) if rel == 'a_in_b' else (j, i)
            if budget <= 0:
                ambiguous.update((i, j))
                continue
            budget -= 1
            if _shell_contains(shells[outer_j], shells[inner_i], cache, outer_j):
                shells[inner_i]['nested'] = True
                shells[inner_i]['relation'] = 'nested'
            else:
                shells[i]['relation'] = shells[j]['relation'] = 'overlap-unconfirmed'
                ambiguous.update((i, j))
    return ambiguous


def _shell_verdict(shells, ambiguous):
    """Derive (outward, state, reason) from the shell states; anything uncertain is unknown (→ degraded), never guessed as pass."""
    def _self_confirmed(s):
        if not s['closed'] or not s['winding_consistent'] or abs(s['signed_volume']) <= s['eps']:
            return False
        if s['signed_volume'] > 0:
            return True
        return bool(s['nested'])

    ambiguous_unresolved = [i for i in ambiguous if not _self_confirmed(shells[i])]
    for i in ambiguous_unresolved:
        shells[i]['state'] = 'unknown'
    fails = [i for i, s in enumerate(shells)
             if i not in ambiguous_unresolved and not s['nested'] and s['closed'] and s['winding_consistent']
             and s['signed_volume'] < -s['eps']]
    if fails:
        for i in fails:
            shells[i]['state'] = 'fail'
        worst = sorted((i for i in fails), key=lambda i: shells[i]['signed_volume'])[:6]
        return False, 'fail', ("non-nested shell(s) facing inward overall (signed_volume<0): %s -- the aggregated signed volume"
                               " is cancelled into a positive number by 'large outward shell + small inverted shell', so it is judged per shell here"
                               % ", ".join("shell#%d(vol=%.6g, faces=%d)"
                                           % (i, shells[i]['signed_volume'], shells[i]['faces'])
                                           for i in worst))
    if ambiguous_unresolved:
        return None, 'unknown', ("%d shells have intersecting AABBs and their own orientation cannot be decided (not closed / inconsistent winding / zero volume / unconfirmed nesting)"
                                 " -- orientation semantics are unresolved, no pass conclusion is given" % len(ambiguous_unresolved))
    unknown = [i for i, s in enumerate(shells)
               if not s['closed'] or not s['winding_consistent'] or abs(s['signed_volume']) <= s['eps']]
    if unknown:
        for i in unknown:
            shells[i]['state'] = 'unknown'
        return None, 'unknown', ("shell closedness/winding/volume cannot be decided: %s"
                                 % ", ".join("shell#%d" % i for i in unknown[:6]))
    for s in shells:
        s['state'] = 'nested' if s['nested'] else 'pass'
    if len(shells) > 1:
        return True, 'pass_multi_shell', ("multi-shell (%d connected shells), the orientation of every shell is confirmable;"
                                          " multiple shells are not a defect in themselves (legitimate cavities are marked nested)" % len(shells))
    return True, 'pass', ''


def _shell_normals(bm):
    """Judge orientation per connected shell (v0.9.6 review fix).

    Why the overall signed volume is not enough: `bm.calc_volume(signed=True)` **sums** all shells --
    a large positive shell (+8) together with a separate small inverted shell (−1) still totals +7 > 0, so "normals point outward" is falsely reported as true.
    Here it is judged **per shell**, and a conclusion is drawn only for shells that are confirmed to be independent solids:

      * shell = an edge-connected set of faces; each computes signed volume / closedness / winding consistency / AABB.
      * shells whose AABBs are **apart** ⇒ independent solids: closed + consistent winding + volume ≤ 0 ⇒ **confirmed inward (fail)**.
      * shells whose AABBs **contain each other** ⇒ suspected nesting (legitimate cavity / independent part inside a shell): ray parity **confirms** it really is inside;
        confirmed ⇒ the nested shell is exempt (a legitimate cavity must not be reported as inverted); not confirmed ⇒ unknown.
      * AABBs intersect but neither contains the other (interpenetration / partial overlap / coincident duplicates) ⇒ orientation alone cannot decide ⇒ unknown.

    Anything uncertain is unknown (→ audit_mesh concludes verdict=degraded), **never guessed as pass**.
    Returns (normals_outward, state, shells, reason): outward ∈ {True, False, None}.
    """
    nf = len(bm.faces)
    cap = _shell_max_faces()
    if cap > 0 and nf > cap:
        return None, 'unknown', [], ("face count %d exceeds the per-shell orientation analysis cap %d (env DSH_SHELL_MAX_FACES is adjustable)"
                                     " -- per-shell analysis was not done, no pass conclusion is given" % (nf, cap))
    shells = _shell_components(bm)
    if not shells:
        return None, 'unknown', shells, 'no faces'
    if len(shells) > 256:
        return None, 'unknown', shells, 'shell_count exceeds 256; containment not analyzed'
    ambiguous = _shell_relations(shells)
    outward, state, reason = _shell_verdict(shells, ambiguous)
    return outward, state, shells, reason



def _shells_brief(shells, limit=12):
    """Compress the shell details into the small block used in the receipt (drops the internal fields _faces/_verts)."""
    rows = []
    for i, s in enumerate(shells or []):
        if i >= int(limit):
            break
        rows.append({"shell": i, "faces": s.get("faces"), "signed_volume": round(float(s.get("signed_volume") or 0.0), 6),
                     "closed": bool(s.get("closed")), "winding_consistent": bool(s.get("winding_consistent")),
                     "nested": bool(s.get("nested")), "relation": s.get("relation") or "",
                     "state": s.get("state")})
    return rows
#         * large meshes: over the cap always analyzed=false; **not analyzed must never be read as connected**
#         * units: every mm threshold is converted through the scene scale_length, the return carries a units block
# ============================================================================

VISIBLE_SPAN_FRACTION = 0.01
MICRO_GAP_MM = 0.3
CONN_MAX_TRIS = 0                # **0 = no cap (run everything by default)**; only an explicit env DSH_CONN_MAX_TRIS / max_tris parameter enables a cap




__all__ = [name for name in list(globals()) if not name.startswith("__")]
