# -*- coding: utf-8 -*-
"""Split from audit.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403
from .conn_helpers import _box_fields, _exc_body, _file_names, _load_file_objects, _nm, _r, _units, _world_tris
from .connectivity import _boxvol
from .drift import BVH_MAX_TRIS, _sample

# ============================================================================
# v0.9.1: cross-part / cross-file face-pair overlap + intersection volume (rifle-build "93 feedback", grading)
# ----------------------------------------------------------------------------
# Feedback verbatim: "check_interference only recognizes components registered in the current
# session, so passing file= is a direct argument mismatch; interpenetration across parts/*.blend
# can only be handled by a hand-rolled BVH face-pair + boolean intersection volume"; the evidence
# is the member-built lead_bvh_overlap.py / lead_interference.py (**exactly this hand-rolled audit
# caught "magazine floating: well-mouth cover plate 10719.7 mm³" and "handguard / forward grip
# 2536/30319 mm³"**). Here it is narrowed down to two operators:
#     audit_overlap       face-pair overlap (structured: pairs / pair_count / intersection_bbox / per_object)
#     audit_interference  intersection-volume estimate (mm³; Monte-Carlo ray parity, **no bpy boolean**)
# Measured semantics (Blender 5.2; each point is written into the response body - don't ignore it):
#   * BVHTree.overlap = **true triangle-triangle intersection** (face pairs whose AABBs overlap but
#     that do not penetrate are not reported) → method may honestly say "triangles exact";
#   * but **coplanar and mutually covering** face pairs are not reported (the coplanar semantics of
#     isect_tri_tri) → coplanar contact is reported instead by contact_probe;
#   * after a ray_cast hit, advance eps along the direction and shoot again (otherwise you self-hit
#     in place); the iteration cap is hard-coded and reported as unknown.
# ============================================================================

INTERFERENCE_SAMPLES = 200000     # default sample count (relative error ∝ 1/√n; caliber in the returned error_caliber)
MATERIAL_VOLUME_MM3 = 1.0         # actionable floor: interpenetration < 1 mm³ is below mesh chord-error level → not "real interference"
INTERFERENCE_MAX_STEPS = 64       # per-point per-direction ray iteration cap; points over the cap are recorded as unknown (no guessing)
CONTACT_PROBE_PTS = 256           # number of surface sample points per side for contact_probe
PAIRS_BBOX_CAP = 0                # **0 = no cap (run everything by default)**; only an explicit non-zero value truncates (guards against memory blow-up in pathological scenes)


def _box_pair(lo, hi, mm_per_unit, digits=5):
    """(box, box_mm): report both scene units and mm (iron rule: numbers carry units)."""
    f = _box_fields(lo, hi, mm_per_unit, digits)
    return ({"min": f["min"], "max": f["max"], "size": f["size"]},
            {"min": f["min_mm"], "max": f["max_mm"], "size": f["size_mm"]})


def _box_intersect(lo1, hi1, lo2, hi2):
    """Intersection box of two world AABBs; separated on any axis → None (the intersection body must lie in the intersection box, so this is a useful prior)."""
    import numpy as np
    lo = np.maximum(np.asarray(lo1, dtype=np.float64), np.asarray(lo2, dtype=np.float64))
    hi = np.minimum(np.asarray(hi1, dtype=np.float64), np.asarray(hi2, dtype=np.float64))
    if bool(np.any(hi < lo)):
        return None
    return (lo, hi)


def _bvh_from_tris(tris):
    """World triangles (N,3,3) → BVHTree (FromPolygons + all_triangles → indices are the triangle indices)."""
    from mathutils.bvhtree import BVHTree
    V = tris.reshape(-1, 3).tolist()
    polys = [(3 * i, 3 * i + 1, 3 * i + 2) for i in range(len(tris))]
    return BVHTree.FromPolygons(V, polys, all_triangles=True)


def _session_side(sel, include_hidden=False):
    """Session-side source: object name / list of names / collection name → (objs, missing, err)."""
    if isinstance(sel, dict):
        w = sel
        sel = w.get("objects") or w.get("names") or w.get("list")
        if sel is None:
            sel = w.get("scope")
        include_hidden = bool(w.get("include_hidden", include_hidden))
    if sel is None or (isinstance(sel, str) and not sel.strip()):
        return [], [], "this side has no source: give a session object/collection name (a / objects_a), or point file_a / file_b at a .blend"
    got, missing = [], []
    if isinstance(sel, (list, tuple, set)):
        for n in sel:
            ob = bpy.data.objects.get(str(n))
            if ob is None or ob.type != "MESH":
                missing.append(str(n))
            else:
                got.append(ob)
    else:
        s = str(sel)
        ob = bpy.data.objects.get(s)
        if ob is not None:
            if ob.type != "MESH":
                return [], [], "not a mesh object (type=%s): %s" % (ob.type, s)
            got = [ob]
        else:
            coll = bpy.data.collections.get(s)
            if coll is None:
                return [], [], "no such object and no such collection in the session: %s" % s
            got = [o for o in coll.all_objects if o.type == "MESH"]
    if not include_hidden:
        got = [o for o in got if not (o.hide_render or o.hide_viewport)]
    return got, missing, None


def _side_tris(tag, sel=None, file=None, names=None, include_hidden=False):
    """Resolve one side (A/B): session object/collection, or **another .blend** (names/objects_x filter names inside the file).

    Returns {ok, error, tris, owner, objs, names, aabb, source, cleanup, file_info, hint}
    — tris/owner/aabb hold numpy objects, **do not** put them straight into JSON (report via _side_summary).
    """
    import os
    filt = names if names is not None else sel
    if not file and isinstance(sel, str) and sel.strip() and os.path.exists(sel):
        ext = os.path.splitext(sel)[1].lower()
        if ext == ".blend":
            file, filt = sel, (names if names is not None else None)   # a given directly as a .blend path is accepted too
        else:
            return {"ok": False, "side": tag, "source": "path:%s" % sel,
                    "error": "only .blend files are accepted (got %s)" % (ext or "no extension"),
                    "hint": "for pairwise .obj/.stl comparison use audit_drift (the same _src_tris path)"}
    if file:
        objs, cleanup, info = _load_file_objects(file, _file_names(filt), include_hidden)
        name_of = info.pop("_name_of", None)
        src = info.get("source")
        if not info.get("ok"):
            return {"ok": False, "side": tag, "source": src, "error": info.get("error"),
                    "cleanup": cleanup, "file_info": info,
                    "hint": "file= side: the file must exist and contain a visible mesh; empty output must be ok:false"}
        note = "file= loaded temporarily (removed after the run; names are the original ones from the file)"
    else:
        objs, missing, err = _session_side(filt, include_hidden)
        cleanup, info, name_of, src, note = None, None, None, "session", None
        if err:
            return {"ok": False, "side": tag, "source": src, "error": err}
        if not objs:
            return {"ok": False, "side": tag, "source": src, "error": "0 visible meshes on this side", "missing": missing,
                    "hint": "the names/collection name did not match, or everything is blocked by hide_render/hide_viewport (include_hidden=true lets it through)"}
    tris, owner, _boxes = _world_tris(objs)
    nm_list = [_nm(o, name_of) for o in objs]
    if tris is None or len(tris) == 0:
        return {"ok": False, "side": tag, "source": src, "error": "0 triangles on this side (objects exist but have no geometry)",
                "object_names": nm_list, "cleanup": cleanup, "file_info": info}
    p = tris.reshape(-1, 3)
    return {"ok": True, "side": tag, "source": src, "tris": tris, "owner": owner, "objs": objs,
            "names": nm_list, "name_of": name_of, "aabb": (p.min(axis=0), p.max(axis=0)),
            "cleanup": cleanup, "file_info": info, "note": note}


def _side_summary(s, mm_per_unit):
    """Report summary for one side (never carries numpy objects)."""
    out = {"source": s.get("source"), "object_names": s.get("names") or [],
           "objects": len(s.get("objs") or []),
           "tris": (int(len(s["tris"])) if s.get("tris") is not None else 0)}
    if s.get("aabb") is not None:
        out["aabb"] = _box_fields(s["aabb"][0], s["aabb"][1], mm_per_unit)
    if not s.get("ok") and s.get("error"):
        out["error"] = s.get("error")
    if s.get("hint"):
        out["hint"] = s["hint"]
    if s.get("missing"):
        out["missing"] = s["missing"]
    if s.get("file_info"):
        fi = s["file_info"]
        out["file_load"] = {k: fi.get(k) for k in ("path", "requested", "loaded", "mesh", "non_mesh",
                                                   "missing", "hidden_skipped", "renamed", "tmp_collection",
                                                   "name_map_note", "mesh_names") if fi.get(k) is not None}
    return out


def _resolve_two_sides(a, b, file_a, file_b, objects_a, objects_b, include_hidden):
    """Resolve both sides together (the file side is loaded temporarily) → (sides, cleanups). cleanup runs in the caller's finally."""
    sides, cleanups = {}, {}
    for tag, (sel, f, names) in (("a", (a, file_a, objects_a)), ("b", (b, file_b, objects_b))):
        sd = _side_tris(tag, sel, f, names, include_hidden)
        sides[tag] = sd
        if sd.get("cleanup"):
            cleanups[tag] = sd["cleanup"]
    return sides, cleanups


def _sides_error(sides, mm_per_unit):
    """Either side failing → a unified ok:false body (both summaries are included so you can tell which side failed)."""
    bad = {t: sides[t].get("error") for t in ("a", "b") if not sides[t].get("ok")}
    if not bad:
        return None
    return {"ok": False, "analyzed": False,
            "error": "source failed: " + "; ".join("%s: %s" % (t, bad[t]) for t in sorted(bad)),
            "sides": {t: _side_summary(sides[t], mm_per_unit) for t in ("a", "b")},
            "hint": "give each side a source: session object name/collection name (a/objects_a, b/objects_b), "
                    "or a .blend (file_a/file_b, with objects_a/objects_b filtering names inside the file)"}


def _tri_tri_segment(ta, tb):
    """True intersection segment of two triangles → (point[3]|None, length|None, kind).

    Method: intersect the planes the two triangles lie in to get the common line (P, D), then clip that
    line to a t interval using the in-plane half-spaces of the three edges of each triangle; the overlap
    of the two intervals is the true intersection segment (P lies on both planes, so the parameter t is
    consistent for both sides).
    Coplanar/parallel (overlap() does not report coplanar pairs to begin with) or a failed clip → fall
    back to "the midpoint of the two centroids", stated in kind — no fake precision.
    """
    import numpy as np
    a = np.asarray(ta, dtype=np.float64)
    b = np.asarray(tb, dtype=np.float64)
    ca, cb = a.mean(axis=0), b.mean(axis=0)
    mid = (ca + cb) / 2.0
    n1 = np.cross(a[1] - a[0], a[2] - a[0])
    n2 = np.cross(b[1] - b[0], b[2] - b[0])
    l1, l2 = float(np.linalg.norm(n1)), float(np.linalg.norm(n2))
    if l1 <= 1e-12 or l2 <= 1e-12:
        return mid, None, "degenerate triangle (zero area) → using centroid midpoint"
    n1, n2 = n1 / l1, n2 / l2
    d = np.cross(n1, n2)
    dn = float(np.linalg.norm(d))
    if dn <= 1e-9:
        return mid, None, "faces coplanar/parallel → using centroid midpoint (coplanar coverage is not reported by overlap() anyway)"
    d = d / dn
    c1, c2 = float(np.dot(n1, a[0])), float(np.dot(n2, b[0]))
    P = (c1 * np.cross(n2, d) + c2 * np.cross(d, n1)) / (dn * dn)
    t1 = _line_clip(P, d, a, n1)
    t2 = _line_clip(P, d, b, n2)
    if t1 is None or t2 is None:
        return mid, None, "line clipping failed (boundary/degenerate case) → using centroid midpoint"
    lo, hi = max(t1[0], t2[0]), min(t1[1], t2[1])
    if hi < lo - 1e-12:
        return mid, None, "clipped interval is empty → using centroid midpoint"
    return (P + ((lo + hi) / 2.0) * d), max(0.0, hi - lo), "plane intersection + triangle clipping (true intersection segment)"


def _line_clip(P, d, tri, n):
    """t interval [lo,hi] that the line P+t·d (known to lie in the triangle plane) is clipped to; no intersection → None."""
    import numpy as np
    lo, hi = -1e30, 1e30
    for i in range(3):
        u, v, w = tri[i], tri[(i + 1) % 3], tri[(i + 2) % 3]
        m = np.cross(v - u, n)                     # in-plane normal
        if float(np.dot(w - u, m)) < 0:            # ★ use the third vertex for the sign: inside must be ≥0 (winding-independent)
            m = -m
        fu, fd = float(np.dot(P - u, m)), float(np.dot(d, m))
        if abs(fd) < 1e-15:
            if fu < -1e-12:
                return None                        # the whole line is outside this edge
            continue
        t = -fu / fd
        if fd > 0:
            lo = max(lo, t)
        else:
            hi = min(hi, t)
    if lo > hi + 1e-12:
        return None
    return (lo, hi)


def _pairs_bbox(ta, tb, pairs):
    """World bbox of the vertices of the overlapping triangles (= a **superset** box of the intersection body) → (lo, hi, truncated).

    Why this box is valid: the boundary of the intersection body consists of "the part of ∂A inside B +
    the part of ∂B inside A + ∂A∩∂B"; the first two necessarily lie on the **triangles that intersect the
    other side**, and the third is the overlapping face pairs themselves → the intersection body is
    always inside this box.
    """
    import numpy as np
    _pc = int(PAIRS_BBOX_CAP)
    sel = pairs if _pc <= 0 else pairs[:_pc]
    ia = np.fromiter((int(p[0]) for p in sel), dtype=np.int64, count=len(sel))
    ib = np.fromiter((int(p[1]) for p in sel), dtype=np.int64, count=len(sel))
    p = np.concatenate([ta[ia].reshape(-1, 3), tb[ib].reshape(-1, 3)], axis=0)
    return p.min(axis=0), p.max(axis=0), bool(len(pairs) > len(sel))


def _pair_rows(sa, sb, ta, tb, pairs, limit, mm_per_unit):
    """Structured rows for the first limit overlapping face pairs (object names + triangle indices + intersection point/segment length)."""
    rows = []
    for pr in pairs[:max(0, int(limit))]:
        ia, ib = int(pr[0]), int(pr[1])
        pt, seglen, kind = _tri_tri_segment(ta[ia], tb[ib])
        ca = ta[ia].mean(axis=0)
        cb = tb[ib].mean(axis=0)
        rows.append({"a": sa["names"][int(sa["owner"][ia])], "b": sb["names"][int(sb["owner"][ib])],
                     "tri_a": ia, "tri_b": ib,
                     "point": ([_r(float(x), 6) for x in pt] if pt is not None else None),
                     "point_mm": ([_r(float(x) * mm_per_unit, 4) for x in pt] if pt is not None else None),
                     "point_kind": kind,
                     "segment_len_mm": (None if seglen is None else _r(seglen * mm_per_unit, 4)),
                     "centroid_dist_mm": _r(float(((ca - cb) ** 2).sum() ** 0.5) * mm_per_unit, 4)})
    return rows


def _per_object_counts(sa, sb, pairs):
    """Overlap pair count per object per side (only >0 listed)."""
    import numpy as np
    out = {"a": {}, "b": {}}
    if not pairs:
        return out
    arr = np.asarray(pairs, dtype=np.int64)
    ca = np.bincount(sa["owner"][arr[:, 0]], minlength=len(sa["objs"]))
    cb = np.bincount(sb["owner"][arr[:, 1]], minlength=len(sb["objs"]))
    out["a"] = {sa["names"][i]: int(ca[i]) for i in range(len(sa["objs"])) if int(ca[i]) > 0}
    out["b"] = {sb["names"][i]: int(cb[i]) for i in range(len(sb["objs"])) if int(cb[i]) > 0}
    return out


def _ray_limit(lo, hi, p, dr, pad):
    """Ray **parameter** upper bound: a little past this side's own AABB boundary (once outside its own bounding box it can no longer hit any face).

    ★ Must divide by the direction component: dr is not necessarily an axis-aligned unit vector (measured on diag:
      skipping the division truncates oblique rays 1.73× early → every point gets classified as outside).
    """
    lim = None
    for k in range(3):
        dk = float(dr[k])
        if abs(dk) < 1e-15:
            continue
        d = ((float(hi[k]) - p[k]) if dk > 0 else (p[k] - float(lo[k]))) / abs(dk)
        lim = d if lim is None else min(lim, d)
    return pad if lim is None else (lim + pad)


def _inside_mask(tree, pts, lo, hi, dirs=((1.0, 0.0, 0.0),), max_steps=INTERFERENCE_MAX_STEPS):
    """Ray parity check: cast a ray from the point along +X (default); an odd hit count ⇒ inside the closed mesh; multiple directions take a majority vote.

    * Iterate out of the interval: after each hit, advance eps along the direction from the hit point and
      shoot again; the ray-length cap is locked slightly past this side's own AABB → iteration is bounded
      by construction; points still over max_steps are recorded as unknown (**no guessing**, the count goes
      into the response);
    * ★ the advance step eps must be **larger than the coordinate resolution of float32 geometry** (a real
      bug caught by this module's first self-check; measured data: a hit point computed from float32 lands
      **behind** the true plane — 0.499999911 vs 0.5; if eps is only 1e-7, the next ray hits the same face
      again with dist=0 → an even hit count → inside points get classified as outside, measured
      459/50000 = 0.92%, concentrated on the side where the ray travel is t≈1, a **systematic bias**). So
      eps = max(span×1e-6, 8×float32_eps×coordinate magnitude) (0 misclassifications at 1e-6 in practice).
    * hit distance ≤0 (ray origin sits exactly on a face) → that point is recorded as unknown (parity is
      undecidable, no guessing);
    * only valid on closed manifold meshes — the caller is responsible for the manifold check first (_mesh_health).
    Returns (mask, unknown, stats)
    """
    import numpy as np
    n = int(len(pts))
    mask = np.zeros(n, dtype=bool)
    if n == 0:
        return mask, 0, {"points_total": 0}
    span = max(float(hi[0]) - float(lo[0]), float(hi[1]) - float(lo[1]), float(hi[2]) - float(lo[2]))
    mag = max(span, float(np.abs(np.asarray(lo, dtype=np.float64)).max()),
              float(np.abs(np.asarray(hi, dtype=np.float64)).max()))
    eps = max(span * 1e-6, 8.0 * 1.1920929e-07 * mag, 1e-12)
    pad = eps * 4.0
    inside_box = np.ones(n, dtype=bool)
    for k in range(3):
        inside_box &= (pts[:, k] >= float(lo[k]) - 1e-12) & (pts[:, k] <= float(hi[k]) + 1e-12)
    idx = np.nonzero(inside_box)[0]
    unknown, maxhits = 0, 0
    nd = max(1, len(dirs))
    for i in idx:
        p = pts[i]
        votes, bad, on_surface = 0, False, False
        for (dx, dy, dz) in dirs:
            ox, oy, oz = float(p[0]) + dx * eps, float(p[1]) + dy * eps, float(p[2]) + dz * eps
            lim = _ray_limit(lo, hi, (ox, oy, oz), (dx, dy, dz), pad)
            cnt, steps = 0, 0
            while steps < int(max_steps):
                loc, nor, fidx, dist = tree.ray_cast((ox, oy, oz), (dx, dy, dz), lim)
                if loc is None:
                    break
                if dist is not None and float(dist) <= 0.0:
                    on_surface = True               # origin sits on a face → parity undecidable, don't force a call
                    break
                cnt += 1
                steps += 1
                ox, oy, oz = loc[0] + dx * eps, loc[1] + dy * eps, loc[2] + dz * eps
                lim = _ray_limit(lo, hi, (ox, oy, oz), (dx, dy, dz), pad)
                if lim <= 0:
                    break
            else:
                bad = True                       # while ran through max_steps without a break → hit the cap
            if cnt > maxhits:
                maxhits = cnt
            if cnt % 2 == 1:
                votes += 1
        if bad or on_surface:
            unknown += 1
            continue
        mask[i] = bool(votes * 2 > nd)
    return mask, int(unknown), {"points_total": n, "points_in_own_bbox": int(len(idx)),
                               "rays": int(nd), "max_hits": int(maxhits), "eps_units": eps,
                               "eps_note": "advance step = max(span×1e-6, 8×float32_eps×coordinate magnitude)"}


def _mesh_health(objs, name_of=None):
    """Closure health check (same caliber as audit_mesh, based on the object's original mesh): → (rows, closed_all).

    closed = boundary_edges==0 and nonmanifold_edges==0; objects with 0 faces are always closed=False (nothing to verify).
    """
    rows, closed_all = [], True
    for ob in objs:
        me = ob.data
        b, nmk = None, None
        if len(me.polygons) > 0:
            bmw = bmesh.new()
            try:
                bmw.from_mesh(me)
                b = int(sum(1 for e in bmw.edges if len(e.link_faces) == 1))
                nmk = int(sum(1 for e in bmw.edges if not e.is_manifold))
            except Exception:
                b, nmk = None, None
            finally:
                bmw.free()
        closed = bool(b == 0 and nmk == 0)
        rows.append({"name": _nm(ob, name_of), "polys": int(len(me.polygons)),
                     "boundary_edges": b, "nonmanifold_edges": nmk, "closed": closed})
        closed_all = closed_all and closed
    return rows, bool(closed_all)


def _containment_probe(ta, tb, tree_a, tree_b, box_a, box_b):
    """Probe for "one part fully enclosed in another": overlap() reports nothing at all for that case → don't read it as no interference.

    Quick filter: continue only if one side's AABB is contained in the other's (with tolerance); on a hit,
    sample points on the inner surface and use ray parity to see whether any land inside the outer part.
    Returns None (no sign of nesting, don't pay the cost) or a dict.
    """
    import numpy as np
    lo_a, hi_a = box_a
    lo_b, hi_b = box_b
    tol = max(1e-9, 1e-9 * float(max(hi_a[i] - lo_a[i] for i in range(3))))
    inner = None
    if all(lo_a[k] <= lo_b[k] + tol and hi_b[k] <= hi_a[k] + tol for k in range(3)):
        inner, outer = "b", "a"
    elif all(lo_b[k] <= lo_a[k] + tol and hi_a[k] <= hi_b[k] + tol for k in range(3)):
        inner, outer = "a", "b"
    if inner is None:
        return None
    if inner == "b":
        pts = _sample(tb, 64, np.random.default_rng(0))
        tree_o, lo_o, hi_o = tree_a, lo_a, hi_a
    else:
        pts = _sample(ta, 64, np.random.default_rng(0))
        tree_o, lo_o, hi_o = tree_b, lo_b, hi_b
    mask, unk, _st = _inside_mask(tree_o, pts, lo_o, hi_o)
    inside_n = int(mask.sum())
    return {"suspected": bool(inside_n > 0), "inner": inner, "outer": outer,
            "probe_points": int(len(pts)), "inside_points": inside_n, "parity_unknown": int(unk),
            "note": ("no face intersections, but the AABB of %s lies entirely inside %s, and %d/%d inner-surface sample points land inside the outer part → "
                     "possibly 'one part fully enclosed in another' (overlap() never reports this case) → don't read it as no interference"
                     % (inner, outer, inside_n, len(pts))) if inside_n > 0 else
                    ("the AABB of %s lies inside %s, but none of the inner-surface sample points land inside the outer part → no sign of containment"
                     % (inner, outer))}


def _contact_probe(ta, tb, tree_a, tree_b, eps_units, mm_per_unit, max_pts=CONTACT_PROBE_PTS):
    """Whether the parts touch: sample max_pts points on each surface and measure the nearest distance to the **opposite surface** (BVHTree.find_nearest).

    Why this step is added when pair_count=0: in practice overlap() does not report "coplanar and mutually
    covering" faces, while coplanar contact / touching-without-overlap is extremely common in an assembly
    — reading pair_count:0 directly would miss it. Criterion matches micro_gap_mm in _conn_analyze
    (0.3 mm counts as touching by default).
    """
    import numpy as np
    rng = np.random.default_rng(0)
    pa = _sample(ta, int(max_pts), rng)
    pb = _sample(tb, int(max_pts), rng)
    best, within = None, 0
    for pts, tree in ((pa, tree_b), (pb, tree_a)):
        for p in pts:
            hit = tree.find_nearest((float(p[0]), float(p[1]), float(p[2])))
            if hit is None or hit[0] is None or hit[3] is None:
                continue
            d = float(hit[3])
            if best is None or d < best:
                best = d
            if d <= float(eps_units):
                within += 1
    return {"contact": bool(within > 0), "min_dist_units": (None if best is None else _r(best, 8)),
            "min_dist_mm": (None if best is None else _r(best * mm_per_unit, 5)),
            "points_within_eps": int(within), "probe_points": int(len(pa) + len(pb)),
            "eps_mm": _r(float(eps_units) * mm_per_unit, 5),
            "note": "nearest face-to-face distance (approximated by surface sampling, not an exact minimum distance); the eps criterion matches micro_gap_mm used for connections"}


def _estimate_volume(ta, tb, tree_a, tree_b, box, samples, seed, box_a, box_b, rays=1):
    """Scatter points uniformly inside box → ray parity decides "inside both A and B" → (frac, n, stats).

    frac × box volume is an unbiased estimate of the A∩B volume (the box is a superset of the
    intersection; points outside the box can never be inside both anyway).
    """
    import numpy as np
    n = max(1, int(samples))
    lo, hi = box
    rng = np.random.default_rng(int(seed))
    pts = np.asarray(lo, dtype=np.float64) + rng.random((n, 3)) * (
        np.asarray(hi, dtype=np.float64) - np.asarray(lo, dtype=np.float64))
    dirs = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))[:max(1, min(3, int(rays)))]
    ma, unk_a, sa = _inside_mask(tree_a, pts, box_a[0], box_a[1], dirs)
    mb, unk_b, sb = _inside_mask(tree_b, pts, box_b[0], box_b[1], dirs)
    both = ma & mb
    nb = int(both.sum())
    return (float(nb) / float(n), n, {"inside_a": int(ma.sum()), "inside_b": int(mb.sum()),
                                      "inside_both": nb, "unknown_a": int(unk_a), "unknown_b": int(unk_b),
                                      "parity_a": sa, "parity_b": sb, "points": int(len(pts))})


def audit_overlap(a=None, b=None, file_a=None, file_b=None, objects_a=None, objects_b=None,
                  limit=200, include_hidden=False, max_tris=None):
    """Face-pair overlap (structured): do these faces actually penetrate? And in which triangle pairs?

    Each side can be: object name / list of names / collection name of the **current session**
    (a / objects_a), or **another .blend** (file_a + objects_a filters names inside the file; without a
    filter, every visible mesh in the file is taken). Passing a .blend path directly as a/b is also accepted.

    Returns (key keys):
      ok / analyzed / method = bvh-overlap(triangles exact)
      pair_count          **total** number of overlapping face pairs (not truncated by limit; 0 is a conclusion, not "did not run")
      pairs               first limit pairs: [a,b,tri_a,tri_b,point,point_mm,point_kind,segment_len_mm,
                          centroid_dist_mm] (point = a point on the true intersection segment; coplanar/degenerate
                          falls back to the centroid midpoint and says so)
      intersection_bbox   the **intersection box** of the two world AABBs (the intersection body must be inside it; null when they do not intersect)
      overlap_faces_bbox  bbox of the vertices of the overlapping triangles (= the sampling box of audit_interference)
      per_object          overlap pair count per object per side; tris_a/tris_b; aabb_a/aabb_b; sides; units; cleanup
    Three states: no overlap → ok=true + pair_count=0 (a real conclusion); one side empty/file missing → ok=false;
          triangles over the cap (BVH_MAX_TRIS, overridable with max_tris) → ok=false + analyzed=false (must not be read as "no problem").

    ⚠ coverage boundary (measured on Blender 5.2): overlap() is *true* triangle-triangle intersection (face
    pairs whose AABBs overlap but that do not penetrate are not reported), but **coplanar and mutually
    covering** face pairs are not reported either → pair_count=0 does not rule out "coplanar contact"; when
    the two bboxes intersect but no faces do, it automatically runs contact_probe (nearest distance) and
    containment_probe (full containment) once, so a missed report is not read as no problem.
    """
    import time as _t
    t0 = _t.perf_counter()
    m_per_unit, mm_per_unit = _units()
    ub = {"m_per_unit": _r(m_per_unit, 6), "mm_per_unit": _r(mm_per_unit, 6)}
    sides, cleanups = {}, {}

    def _body():
        base = {"method": "bvh-overlap(triangles exact)", "units": ub, "limit": int(limit),
                "include_hidden": bool(include_hidden),
                "sides": {t: _side_summary(sides[t], mm_per_unit) for t in ("a", "b")}}
        err = _sides_error(sides, mm_per_unit)
        if err:
            return dict(base, **err)
        sa, sb = sides["a"], sides["b"]
        ta, tb = sa["tris"], sb["tris"]
        na, nb = int(len(ta)), int(len(tb))
        cap = int(max_tris or BVH_MAX_TRIS)
        over = [(t, v) for t, v in (("a", na), ("b", nb)) if cap > 0 and v > cap]   # cap=0 → no cap (run everything by default)
        if over:
            return dict(base, ok=False, analyzed=False, tris_a=na, tris_b=nb, max_tris=cap,
                        error="triangles over the cap: %s (cap %d, overridable with max_tris) → not analyzed"
                              % ("/".join("%s=%d" % kv for kv in over), cap),
                        note="not analyzed ≠ no overlap: this is 'did not run', not 'no problem'")
        tree_a, tree_b = _bvh_from_tris(ta), _bvh_from_tris(tb)
        pairs = list(tree_a.overlap(tree_b) or [])
        pair_count = len(pairs)
        out = dict(base, ok=True, analyzed=True, tris_a=na, tris_b=nb, pair_count=pair_count,
                   aabb_a=_box_fields(sa["aabb"][0], sa["aabb"][1], mm_per_unit),
                   aabb_b=_box_fields(sb["aabb"][0], sb["aabb"][1], mm_per_unit),
                   point_kind="point = midpoint of the true intersection segment (plane intersection + triangle clipping); degenerate/coplanar falls back to the midpoint of the two centroids (see kind)",
                   coverage="measured overlap() semantics: reports true triangle-triangle intersection (AABB overlap without penetration is not reported); "
                            "coplanar and mutually covering faces are not reported → for coplanar contact see contact_probe")
        inter = _box_intersect(sa["aabb"][0], sa["aabb"][1], sb["aabb"][0], sb["aabb"][1])
        provable_empty = bool(inter is None or _boxvol(inter) <= 0.0)
        if provable_empty:
            out["intersection_bbox"] = None
            out["intersection_bbox_mm"] = None
            out["intersection_bbox_note"] = ("the two world AABBs do not intersect / only touch without overlapping → the intersection body is empty "
                                             "(the intersection body must lie in the intersection box of the two AABBs, so this is provable)")
        else:
            bi, bm = _box_pair(inter[0], inter[1], mm_per_unit)
            out["intersection_bbox"] = bi
            out["intersection_bbox_mm"] = bm
        out["containment_probe"] = None
        out["contact_probe"] = None
        if pair_count == 0:
            out["pairs"] = []
            out["overlap_faces_bbox"] = None
            out["overlap_faces_bbox_mm"] = None
            out["per_object"] = {"a": {}, "b": {}}
            if provable_empty:
                out["note"] = "the two world AABBs do not intersect / only touch without overlapping → face-pair overlap must be 0 (a conclusion, not 'did not run')"
            else:
                cont = _containment_probe(ta, tb, tree_a, tree_b, sa["aabb"], sb["aabb"])
                out["containment_probe"] = cont
                if cont and cont.get("suspected"):
                    out["note"] = cont["note"] + "; for volume use audit_interference"
                else:
                    cp = _contact_probe(ta, tb, tree_a, tree_b, MICRO_GAP_MM / mm_per_unit, mm_per_unit)
                    out["contact_probe"] = cp
                    out["note"] = ("no face intersections (non-coplanar penetration is 0)" +
                                   (", but the two surfaces already touch: nearest %.5f mm (≤ %.2f mm criterion) → coplanar contact / touching without overlap"
                                    % (cp["min_dist_mm"], MICRO_GAP_MM) if cp["contact"] else
                                    "; nearest distance between the two surfaces %.5f mm (no contact)" % (cp["min_dist_mm"] if cp["min_dist_mm"] is not None else -1.0)) +
                                   ". ⚠ overlap() does not report coplanar overlap; a coplanar-coverage case is invisible to this operator")
        else:
            out["pairs"] = _pair_rows(sa, sb, ta, tb, pairs, limit, mm_per_unit)
            fb_lo, fb_hi, trunc = _pairs_bbox(ta, tb, pairs)
            bf, bfm = _box_pair(fb_lo, fb_hi, mm_per_unit)
            out["overlap_faces_bbox"] = bf
            out["overlap_faces_bbox_mm"] = bfm
            if trunc:
                out["overlap_faces_bbox_note"] = ("face pairs exceed %d; the bbox covers only the first %d pairs (pair_count is still the full total)"
                                                  % (PAIRS_BBOX_CAP, PAIRS_BBOX_CAP))
            out["per_object"] = _per_object_counts(sa, sb, pairs)
            seg = [r["segment_len_mm"] for r in out["pairs"] if r["segment_len_mm"] is not None]
            out["max_segment_len_mm"] = (max(seg) if seg else None)
            out["note"] = ("face-pair overlap: %d pairs%s (pair count = face pairs that intersect exactly; AABB overlap without penetration is not counted)"
                           % (pair_count, "" if pair_count <= int(limit) else "; pairs lists only the first %d" % int(limit)))
        return out

    try:
        sides, cleanups = _resolve_two_sides(a, b, file_a, file_b, objects_a, objects_b, include_hidden)
        res = _body()
    except Exception as e:
        res = _exc_body(e, "overlap")
    finally:
        for fn in cleanups.values():
            fn()
    if cleanups:
        res["cleanup"] = {t: cleanups[t]() for t in sorted(cleanups)}
    res["ms"] = int((_t.perf_counter() - t0) * 1000)
    return _j(res)


def audit_interference(a=None, b=None, file_a=None, file_b=None, objects_a=None, objects_b=None,
                       samples=INTERFERENCE_SAMPLES, seed=0, limit=200, include_hidden=False,
                       material_mm3=MATERIAL_VOLUME_MM3, max_tris=None, rays=1):
    """A∩B intersection-volume estimate (mm³) — the operator form of numbers like "magazine floating: well-mouth cover plate 10719.7 mm³".

    Both sides have exactly the same sources as audit_overlap (session objects/collection, or file_a/file_b
    pointing at a .blend; a/b given directly as a .blend path are also accepted). **No bpy boolean**: it runs
    headless too, creates no temporary objects and does not modify the scene.

    Method (narrowed down to the caliber of the hand-built scripts from the feedback):
      ① tree_a.overlap(tree_b) gives the overlapping triangle pairs → sample only inside the world bbox of
         those faces (otherwise it cannot be efficient);
      ② scatter `samples` points uniformly inside that box (numpy.random.default_rng(seed));
      ③ for each point use **ray parity** (cast along +X by default; with rays=3, take the majority vote of
         X/Y/Z) to decide separately whether it is inside A and inside B;
      ④ volume = frac × box volume; ci95 = 1.96·sqrt(frac(1-frac)/n) × box volume.

    ⚠ honest limits (also written into the response as honest_limits / error_caliber):
      * **not an exact boolean**: a Monte-Carlo estimate; relative error (95%) ≈ 1.96·sqrt((1-p)/(p·n))
        (p = share of the box volume occupied by the body).
        Measured caliber: at n=200k, p=0.5 → ±0.44%, p=0.1 → ±1.31%, p=0.01 → ±4.4% (samples×4 → error halves).
      * samples only inside the **bbox of the overlapping triangles** (that box is a superset of the
        intersection body, not the body itself).
      * ray parity is only valid on **closed manifold** meshes: detected boundary/non-manifold edges →
        verdict=unresolved, volume=null (rather than a precise-looking wrong number), with why stating
        exactly which evidence is missing.
      * when one part is fully contained (no face intersections) overlap() returns 0 pairs → caught by
        containment_probe, not misjudged as refuted.

    Three-state verdict: supported (volume>0 and the 95% lower bound>0 and ≥ the actionable floor) /
      refuted (no interference: gives an upper bound in mm³) /
      unresolved (non-manifold, too few samples, upper bound not tight enough → states how far off it is).
    Required keys: volume_mm3 / volume_ci95_mm3 / verdict / why / bbox_mm (plus the full units and mm set).
    """
    import time as _t
    t0 = _t.perf_counter()
    m_per_unit, mm_per_unit = _units()
    mm3 = float(mm_per_unit) ** 3
    floor = float(material_mm3)
    ub = {"m_per_unit": _r(m_per_unit, 6), "mm_per_unit": _r(mm_per_unit, 6),
          "volume_units3_to_mm3": _r(mm3, 6)}
    sides, cleanups = {}, {}


    def _fill_bbox(out, cand, src, mm_per_unit, mm3):
        if cand is None:
            out["bbox"] = None
            out["bbox_mm"] = None
            out["bbox_source"] = "no candidate box (the intersection is provably empty)"
            return
        b, bm = _box_pair(cand[0], cand[1], mm_per_unit)
        out["bbox"] = b
        out["bbox_mm"] = bm
        out["bbox_source"] = src
        out["bbox_volume_mm3"] = _r(float(_boxvol(cand)) * mm3, 4)

    try:
        sides, cleanups = _resolve_two_sides(a, b, file_a, file_b, objects_a, objects_b, include_hidden)
        res = _audit_interference_body(_fill_bbox, floor, include_hidden, limit, max_tris, mm3, mm_per_unit, rays, samples, seed, sides, ub)
    except Exception as e:
        res = _exc_body(e, "interference")
    finally:
        for fn in cleanups.values():
            fn()
    if cleanups:
        res["cleanup"] = {t: cleanups[t]() for t in sorted(cleanups)}
    res["ms"] = int((_t.perf_counter() - t0) * 1000)
    return _j(res)


def _audit_body_p1(_state):
    _fill_bbox, floor, include_hidden, limit, max_tris = (
        _state["_fill_bbox"], _state["floor"], _state["include_hidden"], _state["limit"], _state["max_tris"])
    mm3, mm_per_unit, rays, samples, seed = (
        _state["mm3"], _state["mm_per_unit"], _state["rays"], _state["samples"], _state["seed"])
    sides, ub = _state["sides"], _state["ub"]
    bad, det, fb_hi, fb_lo, rows, t, trunc, who = (_state.get("bad"), _state.get("det"), _state.get("fb_hi"), _state.get("fb_lo"), _state.get("rows"), _state.get("t"), _state.get("trunc"), _state.get("who"))
    try:
        base = {"method": "monte-carlo(ray-parity, sampled only inside the overlap bbox)", "units": ub,
                "samples": int(max(1, int(samples))), "seed": int(seed), "rays": int(max(1, min(3, int(rays)))),
                "include_hidden": bool(include_hidden), "material_mm3": _r(floor, 6), "limit": int(limit),
                "sides": {t: _side_summary(sides[t], mm_per_unit) for t in ("a", "b")},
                "error_caliber": {
                    "formula": "relative error (95%) ≈ 1.96·sqrt((1-p)/(p·n)) (p = total volume / box volume, n = samples_used)",
                    "n_200k": {"p=0.5": "±0.44%", "p=0.1": "±1.31%", "p=0.01": "±4.4%"},
                    "zero_hit_upper": "at frac=0 use the one-sided 95% upper bound 1-0.05^(1/n) ≈ 3/n (× box volume)",
                    "how_to_tighten": "samples×4 → error halves (∝1/√n); the tighter the box around the intersection body, the larger p and the more accurate",
                    "material_mm3": "actionable floor %.3f mm³: below it the figure is mesh chord-error/noise level and is not treated as real interference" % floor}}
        err = _sides_error(sides, mm_per_unit)
        if err:
            return dict(base, **err)
        sa, sb = sides["a"], sides["b"]
        ta, tb = sa["tris"], sb["tris"]
        na, nb = int(len(ta)), int(len(tb))
        cap = int(max_tris or BVH_MAX_TRIS)
        over = [(t, v) for t, v in (("a", na), ("b", nb)) if cap > 0 and v > cap]   # cap=0 → no cap
        if over:
            return dict(base, ok=False, analyzed=False, tris_a=na, tris_b=nb, max_tris=cap,
                        error="triangles over the cap: %s (cap %d, overridable with max_tris) → not analyzed"
                              % ("/".join("%s=%d" % kv for kv in over), cap),
                        note="not analyzed ≠ no interference: no verdict is given, don't read 'did not run' as 'no problem'")
        tree_a, tree_b = _bvh_from_tris(ta), _bvh_from_tris(tb)
        pairs = list(tree_a.overlap(tree_b) or [])
        pair_count = len(pairs)
        out = dict(base, ok=True, analyzed=True, tris_a=na, tris_b=nb, pair_count=pair_count,
                   pairs=_pair_rows(sa, sb, ta, tb, pairs, limit, mm_per_unit),
                   aabb_a=_box_fields(sa["aabb"][0], sa["aabb"][1], mm_per_unit),
                   aabb_b=_box_fields(sb["aabb"][0], sb["aabb"][1], mm_per_unit),
                   honest_limits=[
                       "not an exact boolean: a Monte-Carlo estimate, see error_caliber for the error caliber",
                       "samples only the bbox of the overlapping triangles — that box is a superset of the intersection body, not the body itself",
                       "ray parity is only valid on closed manifold meshes: non-manifold/open meshes are always unresolved (no number given)",
                       "coplanar contact (zero-thickness touching) has volume 0 by definition; overlap() does not report coplanar intersections either → do not take pair_count=0 "
                       "as 'no contact'; for contact see contact_probe in audit_overlap"],
                   why=None, verdict=None, volume_mm3=None, volume_units3=None, volume_ci95_mm3=None)
        health_a, closed_a = _mesh_health(sa["objs"], sa["name_of"])
        health_b, closed_b = _mesh_health(sb["objs"], sb["name_of"])
        out["mesh_health"] = {"a": health_a, "b": health_b, "closed_a": closed_a, "closed_b": closed_b}
        inter = _box_intersect(sa["aabb"][0], sa["aabb"][1], sb["aabb"][0], sb["aabb"][1])
        provable_empty = bool(inter is None or _boxvol(inter) <= 0.0)
        cand = None                    # sampling box
        cand_src = None
        if pair_count > 0:
            fb_lo, fb_hi, trunc = _pairs_bbox(ta, tb, pairs)
            cand, cand_src = (fb_lo, fb_hi), "overlap_faces(world bbox of the overlapping triangles)"
            if trunc:
                out["pairs_bbox_note"] = ("face pairs exceed %d; the sampling box covers only the first %d pairs (pair_count is still the full total)"
                                          % (PAIRS_BBOX_CAP, PAIRS_BBOX_CAP))
        elif not provable_empty:
            cand, cand_src = inter, "aabb_intersect(intersection box of the two world AABBs; a conservative box when no faces intersect)"
        # non-manifold/open → degrade (checked first to skip sampling; bbox and pair count are still reported)
        if pair_count > 0 and not (closed_a and closed_b):
            who = [t for t, c in (("a", closed_a), ("b", closed_b)) if not c]
            det = []
            for t in who:
                rows = health_a if t == "a" else health_b
                bad = [r for r in rows if not r["closed"]]
                det.append("%s: %s" % (t, ", ".join("%s(boundary=%s, nonmanifold=%s)"
                                                    % (r["name"], r["boundary_edges"], r["nonmanifold_edges"])
                                                    for r in bad[:4])))
            out.update({"verdict": "unresolved", "volume_mm3": None, "volume_units3": None,
                        "volume_ci95_mm3": None, "frac": None, "samples_used": 0,
                        "in_overlap_bbox": 0, "inside_a": 0, "inside_b": 0, "inside_both": 0,
                        "why": "ray parity is only valid on closed manifold meshes, and %s is not a closed manifold (%s) → no volume number given. "
                               "Missing evidence: a closed mesh with boundary_edges=0 and nonmanifold_edges=0"
                               % ("/".join(who), " | ".join(det)),
                        "next_step": "repair that part into a closed manifold (or use the face-pair count from audit_overlap) and then estimate volume"})
            _fill_bbox(out, cand, cand_src, mm_per_unit, mm3)
            return out
        if cand is None:               # provably empty (AABBs do not intersect / only touch without overlapping)
            out.update({"verdict": "refuted", "volume_mm3": 0.0, "volume_units3": 0.0,
                        "volume_ci95_mm3": 0.0, "frac": 0.0, "samples_used": 0, "in_overlap_bbox": 0,
                        "inside_a": 0, "inside_b": 0, "inside_both": 0,
                        "upper_bound_mm3": _r(floor, 6),
                        "upper_bound_kind": "the two world AABBs do not intersect / only touch without overlapping → the intersection body is provably empty (the upper bound is the actionable floor)",
                        "why": "face-pair overlap %d pairs, and the two world AABBs do not intersect / only touch without overlapping → A∩B is empty (provable, not sampled)"
                               % pair_count})
            _fill_bbox(out, None, None, mm_per_unit, mm3)
            return out
        box_vol = float(_boxvol(cand))
        frac, n_used, st = _estimate_volume(ta, tb, tree_a, tree_b, cand, samples, seed, sa["aabb"], sb["aabb"],
                                           rays=rays)
    finally:
        _state.update((k, v) for k, v in locals().items() if k != "_state")

def _audit_body_p2(_state):
    _fill_bbox, box_vol, cand, cand_src, floor = (
        _state["_fill_bbox"], _state.get("box_vol"), _state.get("cand"), _state.get("cand_src"), _state["floor"])
    frac, mm3, mm_per_unit, n_used, out = (
        _state.get("frac"), _state["mm3"], _state["mm_per_unit"], _state.get("n_used"), _state.get("out"))
    pair_count, st = _state.get("pair_count"), _state.get("st")
    need = (_state.get("need"))
    try:
        out.update({"samples_used": int(n_used), "in_overlap_bbox": int(st["points"]),
                    "inside_a": st["inside_a"], "inside_b": st["inside_b"], "inside_both": st["inside_both"],
                    "parity_unknown": {"a": st["unknown_a"], "b": st["unknown_b"]},
                    "frac": _r(frac, 8), "box_volume_units3": _r(box_vol, 8),
                    "box_volume_mm3": _r(box_vol * mm3, 4), "parity_stats": {"a": st["parity_a"], "b": st["parity_b"]}})
        _fill_bbox(out, cand, cand_src, mm_per_unit, mm3)
        vol_u3 = frac * box_vol
        vol_mm3 = vol_u3 * mm3
        sd_frac = (frac * (1.0 - frac) / float(n_used)) ** 0.5
        ci95_frac = 1.96 * sd_frac
        up95_frac = min(1.0, frac + 1.645 * sd_frac) if frac > 0 else min(1.0, 1.0 - 0.05 ** (1.0 / float(n_used)))
        out.update({"volume_units3": _r(vol_u3, 8), "volume_mm3": _r(vol_mm3, 4),
                    "volume_ci95_mm3": _r(ci95_frac * box_vol * mm3, 4),
                    "ci95_lower_mm3": _r(max(0.0, (vol_u3 - ci95_frac * box_vol)) * mm3, 4),
                    "ci95_upper_mm3": _r(min(1.0, frac + ci95_frac) * box_vol * mm3, 4),
                    "relative_ci95": (_r(ci95_frac / frac, 6) if frac > 0 else None),
                    "frac_ci95": _r(ci95_frac, 8),
                    "upper_bound_mm3": _r(max(up95_frac * box_vol * mm3, floor), 4),
                    "upper_bound_kind": ("one-sided 95%% statistical upper bound (frac=0: 1-0.05^(1/n) ≈ 3/n × box volume; "
                                         "frac>0: frac+1.645·SE) + not below the actionable floor %.3f mm³" % floor)})
        unk = st["unknown_a"] + st["unknown_b"]
        if unk > 0.05 * 2 * float(n_used):
            out.update({"verdict": "unresolved",
                        "why": "ray parity hit the iteration cap %d on %d/%d points (>5%%) → the inside/outside decision is unreliable; no volume conclusion"
                               % (unk, 2 * n_used, INTERFERENCE_MAX_STEPS)})
            return out
        lower95 = max(0.0, (vol_u3 - ci95_frac * box_vol)) * mm3
        if vol_mm3 > 0 and lower95 > 0:
            if vol_mm3 >= floor:
                out.update({"verdict": "supported",
                            "why": "estimated intersection volume %.1f mm³ (95%% CI ±%.1f mm³, lower bound %.1f mm³ > 0) → real interference; "
                                   "face-pair count %d" % (vol_mm3, out["volume_ci95_mm3"], lower95, pair_count)})
            else:
                out.update({"verdict": "refuted", "sub_material": True,
                            "why": "estimated intersection volume %.4f mm³ < actionable floor %.3f mm³ (mesh chord-error/noise level) → "
                                   "not treated as real interference; upper bound %.4f mm³" % (vol_mm3, floor, out["upper_bound_mm3"])})
        elif out["upper_bound_mm3"] <= floor:
            out.update({"verdict": "refuted",
                        "why": "none of the %d sampled points lies inside both A and B, and the one-sided 95%% upper bound %.4f mm³ ≤ the actionable floor "
                               "%.3f mm³ → no interference (read against the %d overlapping face pairs: the AABBs intersect but the solids do not)"
                               % (n_used, out["upper_bound_mm3"], floor, pair_count)})
        else:
            need = int(box_vol * mm3 * 3.0 / max(floor, 1e-12)) + 1
            out.update({"verdict": "unresolved",
                        "why": "cannot obtain a volume significantly greater than 0: estimate %.4f mm³, upper bound %.4f mm³ is above the actionable floor %.3f mm³ "
                               "→ undecidable (neither 'no interference' nor 'interference')"
                               % (vol_mm3, out["upper_bound_mm3"], floor),
                        "next_step": "samples ≥ %d are needed to push the upper bound down to the floor (currently n=%d; error ∝1/√n)" % (need, n_used),
                        "samples_needed_for_floor": need})
        return out
    finally:
        _state.update((k, v) for k, v in locals().items() if k != "_state")

def _audit_interference_body(_fill_bbox, floor, include_hidden, limit, max_tris, mm3, mm_per_unit, rays, samples, seed, sides, ub):
    _state = dict(locals())
    for _fn_ in (_audit_body_p1, _audit_body_p2):
        _r = _fn_(_state)
        if _r is not None:
            return _r
