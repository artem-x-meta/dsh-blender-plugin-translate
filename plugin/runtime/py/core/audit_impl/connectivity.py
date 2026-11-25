# -*- coding: utf-8 -*-
"""Split from audit.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403
from .conn_helpers import _box_fields, _conn_max_tris, _exc_body, _file_extras, _named_boxes, _nm, _objs_with_optional_file, _r, _units, _world_tris
from .drift import BVH_MAX_TRIS, _sample

def _components(tris, precision=5):
    """Build connected components from shared vertices (rounded and deduplicated) → (comp_of_tri, vertex count)."""
    import numpy as np
    flat = tris.reshape(-1, 3)
    uniq, inv = np.unique(np.round(flat, int(precision)), axis=0, return_inverse=True)
    f = inv.reshape(-1, 3).astype(np.int64)
    nv = int(uniq.shape[0])
    e = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]], axis=0)
    e.sort(axis=1)
    e = np.unique(e, axis=0)
    parent = np.arange(nv, dtype=np.int64)
    a, b = e[:, 0], e[:, 1]
    for _ in range(64):
        before = parent.copy()
        np.minimum.at(parent, b, parent[a])
        np.minimum.at(parent, a, parent[b])
        parent = parent[parent]
        if np.array_equal(parent, before):
            break
    _u, comp = np.unique(parent[f[:, 0]], return_inverse=True)
    return comp.reshape(-1).astype(np.int64), nv


def _confirm_micro_with_mesh(tris, comp, cid, radius_units, tree_cache=None, max_pts=400, big_factor=50.0):
    """Take a component flagged micro by bbox and re-check it on the mesh: is the true nearest distance actually below the threshold?

    Why the re-check is mandatory (the key difference between this plugin and upstream): upstream is a **single merged mesh**, so the bboxes of components rarely overlap and the bbox gap carries information; here every part is a separate object, and in a dense assembly bboxes generally overlap each other → the bbox gap is always 0
    → everything is judged micro → the gate always lets it through (fail-open). So a multi-object scene must add one triangle-level confirmation:
      sample ≤max_pts points on the component and look for hits with the global BVH's find_nearest_range(radius=threshold);
      a hit triangle belonging to **another component** → confirmed touching (a true micro); nothing within the radius → it is actually a floater (the bbox lies).
    Returns (confirmed_micro, true_gap_units|None, note); true_gap only gets a value when "another component was found within the larger radius".
    """
    import numpy as np
    from mathutils.bvhtree import BVHTree
    sel = np.nonzero(comp == int(cid))[0]
    if len(sel) == 0:
        return False, None, "empty component"
    # Sampling must land on **faces** (area-weighted), not just vertices: in a 0.2 mm seam between large planes the vertices may be metres apart
    uniq = _sample(tris[sel], int(max_pts), np.random.default_rng(0))
    if len(uniq) > int(max_pts):
        step = max(1, len(uniq) // int(max_pts))
        uniq = uniq[::step][:int(max_pts)]
    if tree_cache is not None and tree_cache.get("tree") is None:
        V = tris.reshape(-1, 3).tolist()
        polys = [(3 * i, 3 * i + 1, 3 * i + 2) for i in range(len(tris))]
        tree_cache["tree"] = BVHTree.FromPolygons(V, polys, all_triangles=True)
    tree = (tree_cache or {}).get("tree")
    if tree is None:
        return None, None, "BVH not built"
    r = float(radius_units)
    r_big = r * float(big_factor)
    hit_other, best = False, None
    for p in uniq:
        pt = (float(p[0]), float(p[1]), float(p[2]))
        for (loc, nor, idx, dist) in tree.find_nearest_range(pt, r):
            if int(comp[int(idx)]) != int(cid):
                hit_other = True
                break
        if hit_other:
            break
        for (loc, nor, idx, dist) in tree.find_nearest_range(pt, r_big):   # also measure how far it actually drifts
            if int(comp[int(idx)]) != int(cid):
                d = float(dist)
                if best is None or d < best:
                    best = d
    if hit_other:
        return True, best, "mesh confirmed: faces of other components within the threshold radius (really touching)"
    return False, best, "mesh re-check: no faces of other components within the threshold radius → the bbox micro verdict does not hold%s" % (
        "" if best is None else " (nearest %.6f units within the larger radius)" % best)


def _snap_pair_mesh(tris, comp, cid, tree_cache=None, max_pts=400):
    """Mesh-level nearest point pair: returns (delta vector [pointing to the nearest neighbour], distance, note).

    The bbox-level gap reads as 0 in a multi-object scene (hence snap must be able to work at mesh level); this is also the only reliable basis for closing out "touching but not coincident".
    """
    import numpy as np
    from mathutils.bvhtree import BVHTree
    sel = np.nonzero(comp == int(cid))[0]
    if len(sel) == 0:
        return None, None, "empty component"
    pts = _sample(tris[sel], int(max_pts), np.random.default_rng(0))   # face sampling (see _confirm_micro_with_mesh)
    if len(pts) > int(max_pts):
        pts = pts[::max(1, len(pts) // int(max_pts))][:int(max_pts)]
    if tree_cache is not None and tree_cache.get("tree") is None:
        V = tris.reshape(-1, 3).tolist()
        polys = [(3 * i, 3 * i + 1, 3 * i + 2) for i in range(len(tris))]
        tree_cache["tree"] = BVHTree.FromPolygons(V, polys, all_triangles=True)
    tree = (tree_cache or {}).get("tree")
    if tree is None:
        return None, None, "BVH not built"
    best = None
    for p in pts:
        pp = (float(p[0]), float(p[1]), float(p[2]))
        hit = tree.find_nearest(pp)
        if hit is None or hit[0] is None:
            continue
        loc, nor, idx, dist = hit
        if int(comp[int(idx)]) == int(cid):
            continue
        if best is None or float(dist) < best[0]:
            best = (float(dist), (float(loc[0]), float(loc[1]), float(loc[2])), pp)
    if best is None:
        return None, None, "no other component among the mesh neighbours (isolated piece)"
    return [best[1][k] - best[2][k] for k in range(3)], best[0], "mesh-level nearest point pair (point to face)"


def _ov(a, b):
    """Overlap volume of two bboxes (a/b are both (lo, hi))."""
    v = 1.0
    for k in range(3):
        d = min(float(a[1][k]), float(b[1][k])) - max(float(a[0][k]), float(b[0][k]))
        if d <= 0:
            return 0.0
        v *= d
    return v


def _boxvol(b):
    return max(0.0, float(b[1][0]) - float(b[0][0])) * max(0.0, float(b[1][1]) - float(b[0][1])) \
        * max(0.0, float(b[1][2]) - float(b[0][2]))


def _conn_header(objs, name_of, micro_gap_mm, mm_per_unit, m_per_unit):
    """Receipt header (everything except units/object names/boxes)."""
    return {"units": {"m_per_unit": _r(m_per_unit, 6), "mm_per_unit": _r(mm_per_unit, 6),
                      "scene_unit": "m" if abs(m_per_unit - 1.0) < 1e-12 else "scaled",
                      "micro_gap_mm": _r(micro_gap_mm, 4),
                      "micro_gap_units": _r(micro_gap_mm / mm_per_unit, 8)},
            "objects": len(objs), "object_names": [_nm(o, name_of) for o in objs],
            "gap_note": "gap is bbox-level → understates the true gap (touching but not coincident reads as 0), biased towards judging micro and letting it through (same criterion as upstream)"}


def _conn_stats(tris, comp, ncomp, owner, objs, name_of, mm_per_unit):
    """Per-component statistics (bbox/volume/owner) → sort + rank + span_fraction; returns (stats, nv, model_span)."""
    import numpy as np
    stats = []
    for c in range(ncomp):
        sel = np.nonzero(comp == c)[0]
        t = tris[sel]
        p = t.reshape(-1, 3)
        lo, hi = p.min(axis=0), p.max(axis=0)
        size = hi - lo
        vol = abs(float(np.einsum("ij,ij->i", t[:, 0], np.cross(t[:, 1], t[:, 2])).sum() / 6.0))
        stats.append({"comp": c, "tris": int(len(sel)), "min": [_r(x) for x in lo], "max": [_r(x) for x in hi],
                      "size": [_r(x) for x in size], "max_dim": _r(size.max()), "volume": _r(vol, 8),
                      "owners": {_nm(objs[int(i)], name_of): int((owner[sel] == i).sum())
                                 for i in np.unique(owner[sel])}})
    all_lo = np.array([s["min"] for s in stats]).min(axis=0)
    all_hi = np.array([s["max"] for s in stats]).max(axis=0)
    model_span = float((all_hi - all_lo).max())
    for s in stats:
        s["span_fraction"] = _r(s["max_dim"] / model_span, 6) if model_span > 0 else 0.0
    stats.sort(key=lambda s: s["volume"], reverse=True)
    for rank, s in enumerate(stats):
        s["rank"] = rank
    return stats, model_span


def _conn_gaps(stats, mm_per_unit, micro_gap_mm, visible_frac):
    """Neighbourhood bbox gaps (mm): the distance from each component to the nearest other component; also writes the initial gap/visible/attached values."""
    gaps = []
    for i, s in enumerate(stats):
        best, bj = None, None
        for j, t2 in enumerate(stats):
            if i == j:
                continue
            d2 = 0.0
            for k in range(3):
                g = max(0.0, max(s["min"][k] - t2["max"][k], t2["min"][k] - s["max"][k]))
                d2 += g * g
            if best is None or d2 < best:
                best, bj = d2, j
        gaps.append({"gap_units": _r((best or 0.0) ** 0.5, 8), "gap_mm": _r(((best or 0.0) ** 0.5) * mm_per_unit, 5),
                     "nearest_rank": (stats[bj]["rank"] if bj is not None else None)})
    # classification happens below: attached=False → a real floater; True → a neighbour within the threshold (tolerated); None → unconfirmed (degraded)
    for s, g in zip(stats, gaps):
        s["gap_mm"] = g["gap_mm"]
        s["gap_units"] = g["gap_units"]
        s["bbox_micro"] = bool(g["gap_mm"] < float(micro_gap_mm))
        s["visible"] = bool(s["span_fraction"] >= float(visible_frac))
        s["attached"] = None
        s["true_gap_units"] = None
        s["mesh_confirmed"] = None


def _conn_mesh(stats, tris, comp, ncomp, micro_units, mesh_mode, micro_gap_mm):
    """Decide per component whether it touches other components: single component/non-micro/bbox-only/mesh re-check."""
    tree_cache = {}
    for s in stats:
        if ncomp == 1:
            # v0.9.6 (field feedback #2 close-out): a floater is defined as "this component touches no other component" —
            # when the whole scope has **only 1 connected component** that criterion cannot hold (enclosed shells either share vertices or **exactly abut**
            # and get welded together by _components via precision). Previously "welded into one piece" was misreported as 1 visible floater:
            # measured in practice, two pieces exactly abutting (gap=0.00 mm) ⇒ the old logic failed; now it passes.
            s["attached"] = True
            s["evidence"] = "single-body"
            s["confirm_note"] = ("only 1 connected component in the scope (%d triangles) → 'touching no other component' does not apply, so no floater verdict; "
                                 "to check whether inner shells fit, use audit_mesh(island_split=true)" % len(tris))
            continue
        if not s["bbox_micro"]:
            s["attached"] = False
            s["evidence"] = "bbox"
            s["confirm_note"] = "bbox gap %.4f mm already exceeds the threshold %.2f mm → drifting (no mesh re-check needed)" % (s["gap_mm"], micro_gap_mm)
            continue
        if mesh_mode == "bbox-only":
            s["attached"] = None
            s["evidence"] = "bbox-only"
            s["confirm_note"] = "face count %d exceeds %d, skipping the mesh re-check → cannot be treated as attached (the gate handles it as degraded)" % (len(tris), BVH_MAX_TRIS)
            continue
        try:
            conf, true_gap, note = _confirm_micro_with_mesh(tris, comp, s["comp"], micro_units, tree_cache)
        except Exception as e:
            conf, true_gap, note = None, None, "mesh re-check failed: %s" % str(e)[:120]
        s["mesh_confirmed"] = conf
        s["true_gap_units"] = true_gap
        s["confirm_note"] = note
        s["evidence"] = "bbox+mesh"
        s["attached"] = conf


def _conn_attrib(stats, boxes):
    """Attribute real floaters only (bbox overlap ratio → which object to edit)."""
    for s in stats:
        if s["attached"] is not False:
            continue
        # attribution: overlap ratio of the floater bbox with each object bbox (Procedura: matchFloatersToBoxes)
        fbox = (s["min"], s["max"])
        fvol = _boxvol(fbox) or 1.0
        scored = []
        for name, b in boxes.items():
            if b is None:
                continue
            frac = _ov(fbox, (list(b[0]), list(b[1]))) / fvol
            if frac > 0.01:
                scored.append((frac, name, _boxvol((list(b[0]), list(b[1])))))
        scored.sort(reverse=True)
        best = scored[0] if scored else None
        s["attribution"] = {
            "object": best[1] if best else None,
            "confidence": _r(min(1.0, best[0]) if best else 0.0, 4),
            "object_fraction": _r(min(1.0, fvol / best[2]) if best and best[2] > 0 else 0.0, 4),
            "also_overlaps": [n for f, n, _ in scored[1:] if f >= 0.2],
            "contains": s["owners"],
            "note": "object_fraction≈1 ⇒ the floater is the whole object (it can be moved as a piece); very small ⇒ only one part of a welded body (moving it tears the weld points apart)",
        }


def _conn_gap_hist(stats, floaters, micro_gap_mm, mm_per_unit):
    """Gap distribution (the criterion is chosen by the caller); returns (hist, gap_range)."""
    def _gap_mm_of(s):
        if s.get("true_gap_units") is not None:
            return float(s["true_gap_units"]) * mm_per_unit
        return float(s.get("gap_mm") or 0.0)

    hist = {}
    for s in stats:
        g = _gap_mm_of(s)
        key = ("<%.2f mm (touching criterion)" % micro_gap_mm) if g < micro_gap_mm else (
            "%.2f-1 mm" % micro_gap_mm if g < 1 else ("1-5 mm" if g < 5 else ("5-20 mm" if g < 20 else ">20 mm")))
        hist[key] = hist.get(key, 0) + 1
    fgaps = [_gap_mm_of(s) for s in floaters]
    gap_range = (round(min(fgaps), 4), round(max(fgaps), 4)) if fgaps else None
    return hist, gap_range


def _conn_result(out, tris, nv, stats, floaters, tolerated, unconfirmed, objs, owner, name_of,
                 mesh_mode, micro_gap_mm, hist, gap_range, visible_f, model_span, limit):
    """Final receipt (counts/histogram/criterion description)."""
    return dict(out, analyzed=True, tris=int(len(tris)), verts=int(nv), components=stats, floaters=floaters,
                tolerated=tolerated, unconfirmed=unconfirmed,
                _raw={"tris": tris, "comp": None},     # reused by snap (never appears in the public op's JSON)
                obj_tris={_nm(objs[k], name_of): int((owner == k).sum()) for k in range(len(objs))},
                micro_confirm=mesh_mode,
                floater_count=len(floaters), visible_floater_count=len(visible_f),
                real_floater_count=len(visible_f),
                micro_floater_count=len([s for s in tolerated if s["visible"]]),
                unconfirmed_floater_count=len([s for s in unconfirmed if s["visible"]]),
                attached_count=len(tolerated),
                gap_histogram=hist, floater_gap_range_mm=gap_range,
                gate_caliber={"micro_gap_mm": _r(micro_gap_mm, 4),
                              "meaning": "'counts as touching' distance criterion: 0.3mm=single solid/3D printing (upstream criterion); "
                                         "for an assembly with a designed gap give it per the process (e.g. 1–2mm)",
                              "how_to_change": "audit_gate(args={micro_gap_mm: 2.0})"},
                max_floater_span_fraction=_r(max([s["span_fraction"] for s in floaters] or [0.0]), 6),
                model_span=_r(model_span), limit=int(limit))


def _conn_analyze(objs, precision=5, visible_frac=VISIBLE_SPAN_FRACTION, micro_gap_mm=MICRO_GAP_MM,
                  max_tris=None, limit=24, name_of=None):
    """Connected-component analysis kernel: returns a dict (with numpy internals, reused by snap; the public op only exposes the formatted result).

    name_of (v0.9.1, optional): {in-session name → reported name}. Objects loaded in file= mode get renamed by Blender
    (a duplicate name gets .001), while the feedback needs "the object name to match the one inside the file" → every outward name goes through this mapping; in session mode it is None,
    and behaviour is byte-identical to the old version.
    """
    m_per_unit, mm_per_unit = _units()
    cap = int(max_tris or _conn_max_tris())
    tris, owner, boxes = _world_tris(objs)
    boxes = _named_boxes(objs, boxes, name_of)
    out = _conn_header(objs, name_of, micro_gap_mm, mm_per_unit, m_per_unit)
    out["boxes"] = boxes
    if tris is None or len(tris) == 0:
        return dict(out, analyzed=False, reason="no triangles in the scope (an empty output must fail)", tris=0)
    if cap > 0 and len(tris) > cap:   # default cap=0 → run everything
        return dict(out, analyzed=False, tris=int(len(tris)),
                    reason="triangles %d exceed the cap %d (tunable via env DSH_CONN_MAX_TRIS) → skipping analysis" % (len(tris), cap),
                    note="not analyzed ≠ connected: the gate stays degraded and gives no pass verdict")
    p_all = tris.reshape(-1, 3)
    out["aabb"] = _box_fields(p_all.min(axis=0), p_all.max(axis=0), mm_per_unit)
    comp, nv = _components(tris, precision)
    ncomp = int(comp.max()) + 1
    stats, model_span = _conn_stats(tris, comp, ncomp, owner, objs, name_of, mm_per_unit)
    _conn_gaps(stats, mm_per_unit, micro_gap_mm, visible_frac)
    # criterion (v0.9.0 fix): no longer "the largest-volume component is the main body and the rest are floaters" — with two equal-sized parts that rule
    # picks one at random as the floater (caught by selftest). Physically the question is: **does this component touch any other component**.
    micro_units = float(micro_gap_mm) / mm_per_unit
    mesh_mode = "mesh(BVH)" if (BVH_MAX_TRIS <= 0 or len(tris) <= BVH_MAX_TRIS) else "bbox-only"
    _conn_mesh(stats, tris, comp, ncomp, micro_units, mesh_mode, micro_gap_mm)
    floaters = [s for s in stats if s["attached"] is False]
    tolerated = [s for s in stats if s["attached"] is True]
    unconfirmed = [s for s in stats if s["attached"] is None]
    # gap distribution: what the criterion (micro_gap_mm) should be depends on what you want — 0.3mm for a single solid / 3D printing (upstream criterion);
    # for an assembly with a designed gap, give it per your own process (1–2mm is common). The distribution is laid out here so the caller picks the criterion.
    hist, gap_range = _conn_gap_hist(stats, floaters, micro_gap_mm, mm_per_unit)
    _conn_attrib(stats, boxes)
    visible_f = [s for s in floaters if s["visible"]]
    res = _conn_result(out, tris, nv, stats, floaters, tolerated, unconfirmed, objs, owner, name_of,
                       mesh_mode, micro_gap_mm, hist, gap_range, visible_f, model_span, limit)
    res["_raw"]["comp"] = comp     # reused by snap (never appears in the public op's JSON)
    return res


def audit_connectivity(objects=None, scope=None, include_hidden=False, visible_frac=VISIBLE_SPAN_FRACTION,
                       micro_gap_mm=MICRO_GAP_MM, precision=5, limit=24, max_tris=None, file=None,
                       per_object=False):
    """Connected-component check: how many pieces do these objects actually form? Which pieces are "visible floaters"? Which object are they attributed to?

    v0.9.1: new file=<.blend path> — **temporarily** appends the objects inside that file into the session, runs the same analysis chain,
    and deletes them cleanly in finally when done (success or failure); source / file_load / cleanup in the response describe the origin, what was loaded and
    what was deleted. In that case objects/scope act as filters on **object names inside the file** (append brings no collection membership).
    Object names in the report are always the **original names in the file** (Blender appends .001 on a duplicate append; check with object_names).
    The old signature and every old return key are untouched; this is purely additive.
    """
    if per_object and not file:
        # v0.9.6 (field feedback #2): 3M faces overall ⇒ globally only bbox-only is possible (degraded). Running per object, each piece is usually
        # within BVH_MAX_TRIS, so a mesh(BVH)-level verdict can be returned instead of a bare "degraded".
        objs0, missing0, err0 = _pick(objects, scope)
        if err0:
            return _j({"ok": False, "error": err0, "missing": missing0})
        rows = []
        for ob in objs0:
            if ob.type != "MESH":
                continue
            sub = json.loads(audit_connectivity(objects=[ob.name], include_hidden=include_hidden,
                                                visible_frac=visible_frac, micro_gap_mm=micro_gap_mm,
                                                precision=precision, limit=limit, max_tris=max_tris))
            g = _gate_from(sub)
            rows.append({"object": ob.name, "state": g.get("state"), "ok": g.get("ok"),
                         "verdict": g.get("verdict"), "tris": sub.get("tris"),
                         "mesh_mode": sub.get("micro_confirm"),
                         "visible_floaters": g.get("visible_floater_count"),
                         "real_floaters": g.get("real_floater_count"),
                         "reason": (g.get("reason") or "")[:200]})
        if not rows:
            return _j({"ok": False, "error": "no mesh objects in the scope", "missing": missing0})
        states = [r["state"] for r in rows]
        verdict = ("fail" if "fail" in states else ("degraded" if any(x != "pass" for x in states) else "pass"))
        payload = {"ok": verdict == "pass", "verdict": verdict, "per_object": True, "count": len(rows),
                   "objects": rows,
                   "failed_objects": [r["object"] for r in rows if r["state"] == "fail"],
                   "degraded_objects": [r["object"] for r in rows if r["state"] == "degraded"],
                   "note": "per-object re-check: use it when the overall face count exceeds the BVH cap; verdict is three-state, degraded ≠ pass"}
        if verdict == "degraded":
            payload["warn"] = "DEGRADED ≠ pass: some objects got no pass verdict (see objects[].reason)"
        return _j(payload)
    S = _objs_with_optional_file(objects, scope, include_hidden, file)
    objs, missing, err, name_of = S["objs"], S["missing"], S["err"], S["name_of"]
    try:
        if err:
            res = {"ok": False, "error": err, "missing": missing, "file": (S["load"] or {}).get("path"),
                   "hint": "file= mode: the file must open and contain visible meshes; any empty output is ok:false"}
        elif not objs:
            res = {"ok": False, "error": "0 meshes in the scope", "missing": missing,
                   "hint": "Check the object/collection name, or include_hidden=True; a silent empty output must fail"}
        else:
            a = _conn_analyze(objs, precision=precision, visible_frac=visible_frac, micro_gap_mm=micro_gap_mm,
                              max_tris=max_tris, limit=limit, name_of=name_of)
            gate = _gate_from(a)
            res = {"ok": True, "analyzed": a["analyzed"], "units": a["units"], "objects": a["objects"],
                   "object_names": a["object_names"], "tris": a.get("tris"), "missing": missing,
                   "aabb": a.get("aabb")}
            if not a["analyzed"]:
                res.update({"reason": a.get("reason"), "note": a.get("note"), "gate": gate})
            else:
                res.update({
                    "components": a["components"][:int(limit)],
                    "floater_count": a["floater_count"],
                    "visible_floater_count": a["visible_floater_count"],
                    "real_floater_count": a["real_floater_count"],
                    "micro_floater_count": a["micro_floater_count"],
                    "unconfirmed_floater_count": a.get("unconfirmed_floater_count", 0),
                    "micro_confirm": a.get("micro_confirm"),
                    "max_floater_span_fraction": a["max_floater_span_fraction"],
                    "model_span": a["model_span"],
                    "gap_note": a.get("gap_note"),
                    "gap_histogram": a.get("gap_histogram"),
                    "floater_gap_range_mm": a.get("floater_gap_range_mm"),
                    "gate_caliber": a.get("gate_caliber"),
                    "attached_count": a.get("attached_count"),
                    "floaters": [{"rank": s["rank"], "tris": s["tris"], "span_fraction": s["span_fraction"],
                                  "gap_mm": s["gap_mm"], "visible": s["visible"],
                                  "bbox_micro": s.get("bbox_micro"), "mesh_confirmed": s.get("mesh_confirmed"),
                                  "true_gap_units": s.get("true_gap_units"), "evidence": s.get("evidence"),
                                  "confirm_note": s.get("confirm_note"),
                                  "bbox_min": s["min"], "bbox_max": s["max"], "size": s["size"],
                                  "attribution": s["attribution"]} for s in a["floaters"][:int(limit)]],
                    "tolerated": [{"rank": s["rank"], "span_fraction": s["span_fraction"],
                                   "gap_mm": s["gap_mm"], "bbox_micro": s.get("bbox_micro"),
                                   "mesh_confirmed": s.get("mesh_confirmed"),
                                   "true_gap_units": s.get("true_gap_units"),
                                   "objects": sorted((s.get("owners") or {}).keys()),
                                   "confirm_note": s.get("confirm_note")}
                                  for s in a.get("tolerated", [])[:int(limit)]],
                    "unconfirmed": [{"rank": s["rank"], "span_fraction": s["span_fraction"],
                                     "objects": sorted((s.get("owners") or {}).keys()),
                                     "confirm_note": s.get("confirm_note")}
                                    for s in a.get("unconfirmed", [])[:int(limit)]],
                    "gate": gate,
                    "verdict_line": _verdict_line(a, visible_frac, micro_gap_mm),
                })
    except Exception as e:
        res = _exc_body(e, "connectivity")
    finally:
        crep = S["cleanup"]() if S.get("cleanup") else None
    return _j(_file_extras(res, S, crep))


def _verdict_of(ok, state):
    """v0.9.6 (field feedback #2): make the three-state **explicit** in one field so consumers always read verdict instead of reading ok/state and inferring it themselves."""
    if ok is True or state == "pass":
        return {"verdict": "pass"}
    if ok is None or state == "degraded":
        return {"verdict": "degraded",
                "warn": "DEGRADED ≠ pass: not analyzed / unconfirmed / beyond the re-check's capability — this gate gave no pass verdict"}
    return {"verdict": "fail"}


def _gate_from(a):
    """Connectivity gate: only looks at floaters that are "visible and confirmed by the mesh re-check not to be touching". Not analyzed/unconfirmed → ok=null (degraded)."""
    if not a.get("analyzed"):
        return dict({"ok": None, "state": "degraded", "reason": a.get("reason") or "not analyzed",
                     "note": "not analyzed must not be read as connected"}, **_verdict_of(None, "degraded"))
    real = a.get("real_floater_count", 0)          # visible and touching no component at all
    micro = a.get("micro_floater_count", 0)        # visible but confirmed touching (touching without coinciding / interpenetration)
    unconf = a.get("unconfirmed_floater_count", 0)
    if real == 0 and unconf > 0:
        return dict({"ok": None, "state": "degraded", "visible_floater_count": a.get("visible_floater_count"),
                "unconfirmed_floater_count": unconf, "micro_tolerated": micro,
                "reason": "%d visible components whose touching state cannot be confirmed (%s) → degraded, no pass verdict" % (unconf, a.get("micro_confirm")),
                "note": "upstream can fail-open inside a single mesh; a multi-object assembly cannot — unconfirmed is unconfirmed"}, **_verdict_of(None, "degraded"))
    if real == 0:
        return dict({"ok": True, "state": "pass", "visible_floater_count": 0, "real_floater_count": 0,
                "unconfirmed_floater_count": 0, "micro_tolerated": micro,
                "reason": "" if micro == 0 else "%d visible components confirmed by the mesh re-check to touch a neighbour (touching without coinciding / interpenetration) → tolerated" % micro},
                    **_verdict_of(True, "pass"))
    worst = [s for s in a.get("floaters", []) if s.get("visible")][:6]
    return dict({"ok": False, "state": "fail", "visible_floater_count": a.get("visible_floater_count"),
            "real_floater_count": real, "micro_tolerated": micro, "unconfirmed_floater_count": unconf,
            "offenders": [{"rank": s["rank"], "span_fraction": s["span_fraction"], "gap_mm": s["gap_mm"],
                           "true_gap_units": s.get("true_gap_units"), "evidence": s.get("evidence"),
                           "edit_hint": (s["attribution"] or {}).get("object")} for s in worst],
            "reason": "%d visible floaters: touching no other component (no neighbour found within the %.2f mm criterion%s)" % (
                real, MICRO_GAP_MM if not a.get("gate_caliber") else a["gate_caliber"].get("micro_gap_mm", MICRO_GAP_MM),
                ("; nearest %.2f–%.2f mm" % (a["floater_gap_range_mm"][0], a["floater_gap_range_mm"][1]))
                if a.get("floater_gap_range_mm") else "")}, **_verdict_of(False, "fail"))


def _verdict_line(a, visible_frac, micro_gap_mm):
    if not a.get("analyzed"):
        return "connectivity: not analyzed (%s) — must not be treated as connected" % (a.get("reason") or "")
    real = a.get("real_floater_count", 0)
    micro = a.get("micro_floater_count", 0)
    unconf = a.get("unconfirmed_floater_count", 0)
    rng = a.get("floater_gap_range_mm")
    if real == 0 and unconf == 0:
        return "connectivity: pass (%d components; %d visible components confirmed by the mesh re-check to touch a neighbour; thresholds visible %.1f%%/touching %.2f mm)" % (
            len(a["components"]), micro, visible_frac * 100, micro_gap_mm)
    if real == 0:
        return "connectivity: degraded — %d components whose touching state cannot be confirmed (%s), no pass verdict" % (unconf, a.get("micro_confirm"))
    names = [((s["attribution"] or {}).get("object") or "UNMATCHED") for s in a["floaters"] if s["visible"]]
    extra = ("; distance to the nearest neighbour %.2f–%.2f mm — if this is a designed gap, raise the criterion (micro_gap_mm)" % (rng[0], rng[1])) if rng else ""
    return "connectivity: fail — %d visible floaters touch no component at all%s, prefer editing %s" % (real, extra, ", ".join(names[:6]))


def audit_gate(objects=None, scope=None, include_hidden=False, envelope=None, visible_frac=VISIBLE_SPAN_FRACTION,
               micro_gap_mm=MICRO_GAP_MM, max_floater_span_fraction=None, max_tris=None, file=None):
    """Shipping gate: connectivity + (optional) envelope + three-state. Any "not analyzed" degrades to degraded and never passes.

    v0.9.1: new file=<.blend path> (temporary load → run the same chain → clean up in finally; source/file_load/
    cleanup report the origin and the close-out). The per-object bbox used by the envelope check is reported in **original file names** in file= mode.
    The old signature and every old return key are untouched; this is purely additive (new object_names / aabb / source / file_load / cleanup).
    """
    S = _objs_with_optional_file(objects, scope, include_hidden, file)
    objs, missing, err, name_of = S["objs"], S["missing"], S["err"], S["name_of"]
    try:
        if err:
            res = {"ok": False, "error": err, "missing": missing, "file": (S["load"] or {}).get("path"),
                   "hint": "file= mode: the file must open and contain visible meshes; any empty output is ok:false"}
        elif not objs:
            res = {"ok": False, "error": "0 meshes in the scope", "missing": missing}
        else:
            a = _conn_analyze(objs, visible_frac=visible_frac, micro_gap_mm=micro_gap_mm, max_tris=max_tris,
                              name_of=name_of)
            conn = _gate_from(a)
            verdicts = {"connectivity": conn}
            ok = conn["ok"]
            if conn["ok"] is None:
                ok = None
            if max_floater_span_fraction is not None and a.get("analyzed"):
                lim = float(max_floater_span_fraction)
                got = float(a.get("max_floater_span_fraction") or 0.0)
                good = got <= lim
                verdicts["floater_span"] = {"ok": good, "max_floater_span_fraction": got, "limit": lim}
                if ok is True and not good:
                    ok = False
            if envelope is not None and len(list(envelope)) == 6:
                lo = [float(x) for x in list(envelope)[:3]]
                hi = [float(x) for x in list(envelope)[3:]]
                bad = []
                for name, b in a["boxes"].items():
                    if b is None:
                        continue
                    over = []
                    for k in range(3):
                        if float(b[0][k]) < lo[k] - 1e-9:
                            over.append(["%s_min" % "xyz"[k], _r(float(b[0][k]) - lo[k])])
                        if float(b[1][k]) > hi[k] + 1e-9:
                            over.append(["%s_max" % "xyz"[k], _r(float(b[1][k]) - hi[k])])
                    if over:
                        bad.append({"name": name, "out_of_envelope": over})
                good = len(bad) == 0
                verdicts["envelope"] = {"ok": good, "violations": len(bad), "objects": bad[:20]}
                if ok is True and not good:
                    ok = False
            res = dict({"ok": True, "ship_ok": ok,
                   "state": ("pass" if ok is True else ("degraded" if ok is None else "fail")),
                   "verdicts": verdicts, "units": a["units"], "objects": len(objs),
                   "object_names": a.get("object_names"), "tris": a.get("tris"), "analyzed": a.get("analyzed"),
                   "aabb": a.get("aabb"),
                   "verdict_line": _verdict_line(a, visible_frac, micro_gap_mm),
                   "note": "ok=true means the analysis all ran (not that the gate passed); read the gate verdict from verdict (ship_ok kept for compatibility)"},
                   **_verdict_of(ok, "pass" if ok is True else ("degraded" if ok is None else "fail")))
    except Exception as e:
        res = _exc_body(e, "gate")
    finally:
        crep = S["cleanup"]() if S.get("cleanup") else None
    return _j(_file_extras(res, S, crep))
