# -*- coding: utf-8 -*-
"""Split from motion.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403



# ============================================================ axis inference (rotational symmetry / contact band)

def _symmetry_evidence(label, V, F, sample_cap=SYMMETRY_SAMPLE_CAP, min_score=SYMMETRY_MIN_SCORE):
    """Rotational symmetry evidence: area-weighted centroid + principal axes of inertia; each axis is scored by the nearest-neighbour distance after a 90°/180° rotation."""
    if len(V) < 4 or len(F) == 0:
        return None
    mn, mx, diag = _bbox(V)
    if not (diag > 1e-12):
        return None
    P = _sample_points(V, F, sample_cap)
    if len(P) < 4:
        return None
    tri = V[F]
    e1 = tri[:, 1] - tri[:, 0]
    e2 = tri[:, 2] - tri[:, 0]
    areas = 0.5 * np.linalg.norm(np.cross(e1, e2), axis=1)
    tot = float(areas.sum())
    cents = tri.mean(axis=1)
    if tot <= 1e-18:
        w = np.full(len(cents), 1.0 / max(1, len(cents)))
    else:
        w = areas / tot
    centroid = (cents * w[:, None]).sum(axis=0)
    d = cents - centroid
    cov = (w[:, None, None] * (d[:, :, None] * d[:, None, :])).sum(axis=0)
    try:
        vals, vecs = np.linalg.eigh(cov)
    except Exception:
        return None
    axes = [vecs[:, 2], vecs[:, 1], vecs[:, 0]]     # eigenvalues in descending order
    cell = SYMMETRY_CELL_FRAC * diag
    cap = SYMMETRY_CAP_FRAC * diag
    scored = []
    for ax in axes:
        s = 0.0
        cnt = 0
        for (c, sn) in ((0.0, 1.0), (-1.0, 0.0)):    # 90° / 180°
            Q = _rot_pts(P, centroid, ax, c, sn)
            dd = np.minimum(_nearest_dists(P, Q, cell, cap), cap)
            s += float(dd.sum())
            cnt += len(Q)
        score = 0.0 if cnt == 0 else max(0.0, min(1.0, 1.0 - (s / cnt) / cap))
        scored.append((score, ax))
    scored.sort(key=lambda t: -t[0])
    best_score, best_axis = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0
    axis_dir = _canon_dir(best_axis)
    radii = np.array([_dist_point_line(p, centroid, axis_dir) for p in P], dtype=np.float64)
    mean_radius = float(radii.mean()) if len(radii) else 0.0
    radius_std = float(radii.std()) if len(radii) else 0.0
    degenerate = (best_score - second_score) <= DEGENERATE_GAP
    ratio = (radius_std / mean_radius) if mean_radius > 1e-12 else float("inf")
    if degenerate:
        confidence = "low"
    elif best_score >= 0.85 and ratio < 0.35:
        confidence = "high"
    elif best_score >= 0.7:
        confidence = "medium"
    else:
        confidence = "low"
    return {
        "label": str(label),
        "samples": int(len(P)),
        "tris": int(len(F)),
        "score": _r(best_score, 6),
        "second_score": _r(second_score, 6),
        "degenerate": bool(degenerate),
        "passed": bool(best_score >= min_score and not degenerate),
        "axis": _rl(axis_dir, 9),
        "anchor": _rl(centroid, 9),
        "snapped": _snap_axis(axis_dir),
        "mean_radius": _r(mean_radius),
        "radius_std": _r(radius_std),
        "radius_ratio": (None if ratio == float("inf") else _r(ratio)),
        "confidence": confidence,
        "diagonal": _r(diag),
        "cell": _r(cell), "cap_dist": _r(cap),
    }


def _contact_evidence(parent_objs, child_objs, dg, max_distance=None, sample_cap=CONTACT_SAMPLE_CAP):
    """Parent↔child contact band evidence: slender (elongation ≥ 2) with a clear direction → hinge axis candidate."""
    pv, pf, _ = _group_tris(parent_objs, dg)
    cv, cf, _ = _group_tris(child_objs, dg)
    if len(pv) == 0 or len(cv) == 0:
        return {"available": False, "reason": "parent/child group has no geometry"}
    mn, mx, diag = _bbox(np.concatenate([pv, cv], axis=0))
    if not (diag > 1e-12):
        return {"available": False, "reason": "assembly diagonal is 0"}
    md = float(max_distance) if max_distance else 0.01 * diag
    A = _dense_samples(pv, pf, sample_cap)
    B = _dense_samples(cv, cf, sample_cap)
    cell = max(md, 1e-9)

    def _close_to(pts, other):
        grid = {}
        for i, p in enumerate(other):
            grid.setdefault((int(math.floor(p[0] / cell)), int(math.floor(p[1] / cell)),
                             int(math.floor(p[2] / cell))), []).append(i)
        hit_pts = []
        for p in pts:
            cx = int(math.floor(p[0] / cell)); cy = int(math.floor(p[1] / cell)); cz = int(math.floor(p[2] / cell))
            hit = False
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        lst = grid.get((cx + dx, cy + dy, cz + dz))
                        if not lst:
                            continue
                        idx = np.asarray(lst, dtype=np.int64)
                        if float(np.sqrt(((other[idx] - p) ** 2).sum(axis=1)).min()) <= md:
                            hit = True
                            break
                    if hit:
                        break
                if hit:
                    break
            if hit:
                hit_pts.append(p)
        return hit_pts

    close = _close_to(A, B) + _close_to(B, A)      # both directions: points on either side of the contact band count
    if len(close) < CONTACT_MIN_POINTS:
        return {"available": False, "reason": "too few contact points (%d < %d): parent↔child barely touch within max_distance=%.6g"
                % (len(close), CONTACT_MIN_POINTS, md),
                "samples_a": int(len(A)), "samples_b": int(len(B)), "max_distance": _r(md),
                "close_points": int(len(close))}
    C = np.asarray(close, dtype=np.float64)
    cen = C.mean(axis=0)
    dc = C - cen
    cov = (dc[:, :, None] * dc[:, None, :]).sum(axis=0) / max(1, len(C))
    try:
        vals, vecs = np.linalg.eigh(cov)
    except Exception:
        return {"available": False, "reason": "contact-band covariance decomposition failed"}
    order = [2, 1, 0]
    exts = np.sqrt(np.maximum(vals, 0.0)) * 2.0
    e_sorted = sorted([float(exts[i]) for i in order], reverse=True)
    denom = max(e_sorted[-1], 1e-12)
    elong = e_sorted[0] / denom
    axis_dir = _canon_dir(vecs[:, order[0]])
    passed = bool(elong >= ELONGATION_THRESHOLD)
    return {
        "available": True,
        "samples_a": int(len(A)), "samples_b": int(len(B)),
        "close_points": int(len(C)),
        "max_distance": _r(md),
        "anchor": _rl(cen, 9),
        "axis": _rl(axis_dir, 9),
        "snapped": _snap_axis(axis_dir),
        "elongation": _r(elong, 4),
        "min_elongation": ELONGATION_THRESHOLD,
        "extent": _rl(e_sorted, 6),
        "passed": passed,
        "reason": ("the contact band is slender (%.3g ≥ %.2g) → usable as hinge-axis evidence" % (elong, ELONGATION_THRESHOLD)) if passed
                  else ("the contact band is not slender (%.3g < %.2g) → not enough to fix an axis" % (elong, ELONGATION_THRESHOLD)),
    }


def _consensus(cands):
    """Multi-candidate consensus: take the highest scorer and collect the passing items pointing the same way (≤ CONSENSUS_ANGLE_DEG)."""
    ok = [c for c in cands if c and c.get("passed")]
    if not ok:
        return None
    ok.sort(key=lambda c: (-float(c.get("score") or 0.0), str(c.get("label"))))
    best = ok[0]
    sup, spread = [], 0.0
    for c in ok:
        a = _angle_deg(c["axis"], best["axis"])
        if a is not None and a <= CONSENSUS_ANGLE_DEG:
            sup.append(c["label"])
            spread = max(spread, a)
    return {
        "axis": best["axis"], "anchor": best["anchor"], "score": best["score"],
        "snapped": best.get("snapped"), "supporters": sup, "support_count": len(sup),
        "angle_tol_deg": CONSENSUS_ANGLE_DEG, "max_spread_deg": _r(spread, 4),
        "source": best.get("source") or best.get("label"),
    }


def _motion_infer_axis_p1(_state):
    jid, max_distance, min_score, objects, parent = (
        _state["jid"], _state["max_distance"], _state["min_score"], _state["objects"], _state["parent"])
    sample_cap = _state["sample_cap"]
    a, child_names, ev, f, ob, parent_names, v = (_state.get("a"), _state.get("child_names"), _state.get("ev"), _state.get("f"), _state.get("ob"), _state.get("parent_names"), _state.get("v"))
    try:
        t0 = time.perf_counter()
        st = _store()
        jrec = None
        if jid is not None:
            jrec = st["joints"].get(str(jid))
            if jrec is None:
                return _j({"ok": False, "error": "joint not registered: %s" % jid, "have": sorted(st["joints"])})
            child_names = jrec["child"]
            parent_names = jrec["parent"] if parent is None else parent
        else:
            child_names = _names(objects)
            parent_names = _names(parent)
        if not child_names:
            return _j({"ok": False, "error": "no input: give jid (to use a registered joint) or objects (the object names whose axis is wanted)"})

        child, miss_c, nonmesh_c = _objs(child_names)
        par, miss_p, nonmesh_p = _objs(parent_names)
        if not child:
            return _j({"ok": False, "error": "child group has no usable mesh objects", "child": _names(child_names),
                       "missing": miss_c, "non_mesh": nonmesh_c})

        dg = bpy.context.evaluated_depsgraph_get()
        per_obj, total_samples = [], 0
        VV, FF, _ = _group_tris(child, dg)
        for ob in child:
            v, f = _mesh_tris_world(ob, dg)
            if len(v) == 0:
                continue
            ev = _symmetry_evidence(ob.name, v, f, sample_cap=sample_cap, min_score=min_score)
            if ev is None:
                per_obj.append({"label": ob.name, "passed": False, "reason": "insufficient geometry (verts<4 or no triangles)",
                                "verts": int(len(v)), "tris": int(len(f))})
                continue
            ev["source"] = "rotational_symmetry"
            per_obj.append(ev)
            total_samples += ev["samples"]

        group_ev = None
        if len(VV) and len(child) > 1:
            group_ev = _symmetry_evidence("group:%s" % _link_name(child_names), VV, FF,
                                          sample_cap=sample_cap, min_score=min_score)
            if group_ev is not None:
                group_ev["source"] = "group_symmetry"

        contact_ev = None
        if par:
            try:
                contact_ev = _contact_evidence(par, child, dg, max_distance=max_distance)
            except Exception as e:
                contact_ev = {"available": False, "reason": "%s: %s" % (type(e).__name__, str(e)[:160])}

        cands = [c for c in per_obj if c.get("passed")]
        if group_ev is not None:
            cands.append(group_ev)
        cons = _consensus(cands)

        contact_ok = bool(contact_ev and contact_ev.get("available") and contact_ev.get("passed"))
        contact_axis = None
        if contact_ok:
            contact_axis = {"label": "contact:%s" % _link_name(child_names), "score": None,
                            "axis": contact_ev["axis"], "anchor": contact_ev["anchor"],
                            "snapped": contact_ev.get("snapped"), "source": "contact_region"}

        # both independent evidence sources (rotational symmetry / contact band) passing: consistent → stronger; inconsistent → report the contradiction honestly, don't force a pick
        conflict = None
        if cons is not None and contact_axis is not None:
            a = _angle_deg(cons["axis"], contact_axis["axis"])
            if a is not None and a > CONSENSUS_ANGLE_DEG:
                conflict = {"symmetry_axis": cons["axis"], "symmetry_score": cons["score"],
                            "symmetry_supporters": cons["supporters"],
                            "contact_axis": contact_axis["axis"],
                            "contact_elongation": contact_ev.get("elongation"),
                            "angle_deg": _r(a, 4), "tol_deg": CONSENSUS_ANGLE_DEG,
                            "note": "the two evidence sources contradict each other (a square plate is rotationally symmetric about its own normal too, while the hinge line lies in the contact band)"}

        hypothesis = None
        hyp_axis = None
        if jrec is not None and jrec.get("axis"):
            hyp_axis = jrec["axis"]
        verdict, reason, chosen = "unresolved", "", None
    finally:
        _state.update((k, v) for k, v in locals().items() if k != "_state")

def _motion_infer_axis_p2(_state):
    child_names, conflict, cons, contact_axis = (
        _state.get("child_names"), _state.get("conflict"), _state.get("cons"), _state.get("contact_axis"))
    anchor = (_state.get("anchor"))
    try:
        if conflict:
            chosen = None
        elif cons is not None:
            # when the two sources agree, anchor at the contact band (the joint interface is closer to joint-frame semantics); with symmetry evidence alone, anchor at the symmetry axis
            anchor = (contact_axis["anchor"] if contact_axis is not None else cons["anchor"])
            chosen = {"axis": cons["axis"], "anchor": anchor, "source": cons["source"],
                      "score": cons["score"], "passers": cons["supporters"],
                      "anchor_source": ("contact_region" if contact_axis is not None else cons["source"])}
        elif contact_axis is not None:
            chosen = {"axis": contact_axis["axis"], "anchor": contact_axis["anchor"],
                      "source": "contact_region", "score": None,
                      "passers": ["contact:%s" % _link_name(child_names)],
                      "anchor_source": "contact_region"}

    finally:
        _state.update((k, v) for k, v in locals().items() if k != "_state")

def _motion_infer_axis_p3(_state):
    conflict, contact_axis, contact_ev, group_ev, hyp_axis = (
        _state.get("conflict"), _state.get("contact_axis"), _state.get("contact_ev"), _state.get("group_ev"), _state.get("hyp_axis"))
    jrec, min_score, per_obj = _state.get("jrec"), _state["min_score"], _state.get("per_obj")
    anchor_line, best_near, c, cand_all, chosen, con_agree, contact_angle, contact_ok, d, disagreeing, hp, hyp_evidence, near, near_miss, nm, passers, reason, sym_agree, top = (_state.get("anchor_line"), _state.get("best_near"), _state.get("c"), _state.get("cand_all"), _state.get("chosen"), _state.get("con_agree"), _state.get("contact_angle"), _state.get("contact_ok"), _state.get("d"), _state.get("disagreeing"), _state.get("hp"), _state.get("hyp_evidence"), _state.get("near"), _state.get("near_miss"), _state.get("nm"), _state.get("passers"), _state.get("reason"), _state.get("sym_agree"), _state.get("top"))
    try:
        if hyp_axis is not None:
            # a hypothesised axis → judge "supported / refuted / insufficient evidence"
            cand_all = [c for c in per_obj if c.get("axis")] + ([group_ev] if group_ev else [])
            near = [(c["label"], _angle_deg(c["axis"], hyp_axis), c.get("score"), c.get("passed"))
                    for c in cand_all if c.get("axis")]
            near = [n for n in near if n[1] is not None]
            near.sort(key=lambda n: n[1])
            best_near = near[0] if near else None
            hyp_evidence = {"candidates": [{"label": a, "angle_deg": _r(b, 4), "score": c, "passed": d}
                                           for (a, b, c, d) in near[:6]]}
            contact_ok = bool(contact_ev and contact_ev.get("available") and contact_ev.get("passed"))
            contact_angle = _angle_deg(contact_ev["axis"], hyp_axis) if contact_ok else None
            if contact_angle is not None:
                hyp_evidence["contact_angle_deg"] = _r(contact_angle, 4)
            sym_agree = (best_near is not None and best_near[3] and best_near[1] <= CONSENSUS_ANGLE_DEG)
            con_agree = (contact_angle is not None and contact_angle <= CONSENSUS_ANGLE_DEG)
            passers = [n for n in near if n[3]]
            near_miss = [n for n in near if (not n[3]) and n[1] is not None and n[1] <= CONSENSUS_ANGLE_DEG]
            disagreeing = [n for n in passers if n[1] > CONSENSUS_ANGLE_DEG]
            if sym_agree or con_agree:
                verdict = "supported"
                reason = "the hypothesised axis agrees with the measured evidence (%s)" % (
                    "rotational symmetry candidate %s at angle %.2f°" % (best_near[0], best_near[1]) if sym_agree
                    else "contact band at angle %.2f°" % contact_angle)
                if conflict:
                    reason += "; note there is also contradicting evidence (%s)" % conflict["note"]
                chosen = {"axis": _rl(np.asarray(hyp_axis, dtype=np.float64), 9),
                          "anchor": jrec.get("anchor") or (best_near and None) or None,
                          "source": "hypothesis_confirmed", "score": (best_near[2] if best_near else None),
                          "passers": [best_near[0]] if best_near else []}
                hp = _canon_dir(np.asarray(hyp_axis, dtype=np.float64))
                anchor_line = None
                if con_agree and contact_ev.get("anchor"):
                    anchor_line = contact_ev["anchor"]
                elif best_near is not None:
                    for c in cand_all:
                        if c.get("label") == best_near[0]:
                            anchor_line = c.get("anchor")
                chosen["anchor"] = anchor_line or jrec.get("anchor") or _rl(hp, 9)
                chosen["anchor_source"] = ("contact_region" if con_agree and contact_ev.get("anchor")
                                           else "rotational_symmetry")
            elif disagreeing and not near_miss:
                # there is an identifiable candidate and nothing at all near the hypothesised direction → an explicit refutation
                d = min(disagreeing, key=lambda n: n[1])
                verdict = "refuted"
                reason = ("the hypothesised axis does not match the measured axis: the identifiable candidate is %s (angle %.1f° > %.1f°), "
                          "and there is no candidate near the hypothesised direction (empty within angle ≤ %.1f°)"
                          % (d[0], d[1], CONSENSUS_ANGLE_DEG, CONSENSUS_ANGLE_DEG))
                chosen = None
            elif disagreeing and near_miss:
                d = min(disagreeing, key=lambda n: n[1])
                nm = near_miss[0]
                verdict = "unresolved"
                reason = ("evidence conflict: there is a candidate near the hypothesised direction, %s (angle %.1f°), but its score %.3f < %.2f (not identifiable), "
                          "while another identifiable candidate %s is at angle %.1f° from the hypothesis → cannot decide, and it is not a refutation either"
                          % (nm[0], nm[1], float(nm[2] or 0.0), min_score, d[0], d[1]))
                chosen = None
            elif contact_ok and contact_angle is not None and contact_angle > CONSENSUS_ANGLE_DEG:
                verdict = "unresolved"
                reason = ("the contact band's direction disagrees with the hypothesis (angle %.1f°), but there is no usable rotational symmetry evidence → "
                          "the contact band alone (a weaker criterion) is not enough to refute the hypothesis" % contact_angle)
                chosen = None
            elif near_miss:
                nm = near_miss[0]
                verdict = "unresolved"
                reason = ("the candidate points the same way as the hypothesis (%.1f°) but its score %.3f < %.2f (or it is degenerate) → insufficient evidence, cannot decide"
                          % (nm[1], float(nm[2] or 0.0), min_score))
            else:
                verdict = "unresolved"
                reason = "no candidate axis passes the threshold and there is no slender contact band → insufficient evidence (missing: identifiable rotationally symmetric geometry or a parent↔child contact band)"
            hypothesis = {"axis": _rl(hyp_axis, 9), "anchor": _rl(jrec.get("anchor"), 9) if jrec.get("anchor") else None,
                          "evidence": hyp_evidence}
        else:
            if conflict:
                verdict = "unresolved"
                reason = ("the two independent sources give different axes: rotational symmetry %s (score %.3f) vs contact band %s (elongation %.3g), "
                          "angle %.1f° > %.1f° → no criterion to separate them, please give axis explicitly"
                          % (_rl(conflict["symmetry_axis"], 4), float(conflict["symmetry_score"] or 0.0),
                             _rl(conflict["contact_axis"], 4), float(conflict["contact_elongation"] or 0.0),
                             conflict["angle_deg"], CONSENSUS_ANGLE_DEG))
            elif chosen is not None:
                verdict = "supported"
                if chosen["source"] == "contact_region":
                    reason = "no rotational symmetry evidence, but the parent↔child contact band is slender (elongation %.3g) with a clear direction → the contact band direction is taken as the axis" % \
                             float(contact_ev.get("elongation") or 0.0)
                elif contact_axis is not None:
                    reason = ("the two sources agree: rotational symmetry %s (score %.3f) + contact band in the same direction (angle ≤ %.1f°)"
                              % (chosen["source"], float(chosen["score"] or 0.0), CONSENSUS_ANGLE_DEG))
                else:
                    reason = ("rotational symmetry evidence passes: %s (score %.3f, %d same-direction candidates collected)"
                              % (chosen["source"], float(chosen["score"] or 0.0), len(chosen.get("passers") or [])))
            else:
                top = max([float(c.get("score") or 0.0) for c in per_obj if c.get("score") is not None] or [0.0])
                verdict = "unresolved"
                reason = ("no object reaches the score threshold %.2f (highest %.3f)%s → insufficient evidence"
                          % (min_score, top,
                             "; and the candidates are degenerate (a sphere/near-cube has no unique axis)" if any(c.get("degenerate") for c in per_obj) else ""))

    finally:
        _state.update((k, v) for k, v in locals().items() if k != "_state")

def _motion_infer_axis_p4(_state):
    FF, VV, child, chosen, conflict = (
        _state.get("FF"), _state.get("VV"), _state.get("child"), _state.get("chosen"), _state.get("conflict"))
    cons, contact_ev, group_ev, hypothesis, jid = (
        _state.get("cons"), _state.get("contact_ev"), _state.get("group_ev"), _state.get("hypothesis"), _state["jid"])
    min_score, miss_c, miss_p, nonmesh_c, nonmesh_p = (
        _state["min_score"], _state.get("miss_c"), _state.get("miss_p"), _state.get("nonmesh_c"), _state.get("nonmesh_p"))
    note, par, per_obj, reason, sample_cap = (
        _state["note"], _state.get("par"), _state.get("per_obj"), _state.get("reason"), _state["sample_cap"])
    t0, total_samples, verdict = _state.get("t0"), _state.get("total_samples"), _state.get("verdict")
    try:
        missing = []
        if verdict == "unresolved":
            if conflict:
                missing.append("missing: a discriminating criterion (the rotational symmetry axis and the contact band direction contradict each other; give axis explicitly or add a third kind of evidence)")
            if not any(c.get("score") is not None for c in per_obj):
                missing.append("the child group has no triangles that can be scored")
            missing.append("missing: a rotationally symmetric part (cylinder/pin/wheel) — a flat plate has no rotational symmetry about the hinge axis")
            if not par:
                missing.append("missing: parent group (without one the parent↔child contact band cannot be computed)")
            elif not (contact_ev and contact_ev.get("available")):
                missing.append("missing: parent↔child near-contact points (points within max_distance < %d)" % CONTACT_MIN_POINTS)
            elif not contact_ev.get("passed"):
                missing.append("missing: a slender contact band (elongation < %.2f)" % ELONGATION_THRESHOLD)

        out = {
            "ok": verdict != "unresolved",
            "op": "infer_axis",
            "jid": (str(jid) if jid is not None else None),
            "child": [o.name for o in child],
            "parent": [o.name for o in par],
            "missing_objects": miss_c + miss_p,
            "non_mesh": nonmesh_c + nonmesh_p,
            "verdict": verdict,
            "reason": reason,
            "missing_evidence": missing,
            "axis": (chosen["axis"] if chosen else None),
            "anchor": (chosen["anchor"] if chosen else None),
            "axis_source": (chosen["source"] if chosen else None),
            "anchor_source": (chosen.get("anchor_source") if chosen else None),
            "axis_conflict": conflict,
            "hypothesis": hypothesis,
            "evidence": {
                "sample_cap": int(sample_cap), "min_score": float(min_score),
                "angle_tol_deg": CONSENSUS_ANGLE_DEG,
                "total_samples": int(total_samples),
                "child_verts": int(len(VV)), "child_tris": int(len(FF)),
                "per_object": per_obj,
                "group": group_ev,
                "contact": contact_ev,
                "consensus": cons,
                "units": {"length": "scene units (1 unit = %g m)" % _scene_mpu(), "angle": "deg"},
                "method": "area-weighted centroid + principal axes of inertia; nearest-neighbour distance over a 27-cell grid scored after 90°/180° rotations (cap=5%% of the diagonal, cell=2%%)",
            },
            "note": str(note),
            "ms": int((time.perf_counter() - t0) * 1000),
        }
        return _j(out)
    finally:
        _state.update((k, v) for k, v in locals().items() if k != "_state")

def motion_infer_axis(jid=None, objects=None, parent=None, sample_cap=SYMMETRY_SAMPLE_CAP,
                      min_score=SYMMETRY_MIN_SCORE, max_distance=None, note=""):
    """Measure the axis and anchor from the geometry and provide **evidence** (sample count / score / candidates / degenerate / contact band).

    evidence = ① per-object rotational symmetry axis (cylinder/pin/wheel) ② the merged group's symmetry axis ③ the parent↔child contact band direction.
    verdict: passing evidence → supported; a hypothesised axis that clearly disagrees with the measurement → refuted; insufficient evidence → unresolved.
    """
    _state = dict(locals())
    for _fn_ in (_motion_infer_axis_p1, _motion_infer_axis_p2, _motion_infer_axis_p3, _motion_infer_axis_p4):
        _r = _fn_(_state)
        if _r is not None:
            return _r


# ============================================================ joint registration

def motion_joint(jid, parent, child, kind="revolute", axis=None, anchor=None, limits=None,
                 note="", verdict=None, snap_axis=False):
    """Register one joint. Without axis/anchor → the module infers them by measurement (with insufficient evidence the joint's axis is unresolved).

    With snap_axis=True the final axis is snapped to the nearest world axis (only when |component| ≥ 0.95); the raw value is recorded in
    axis_snapped_from — by default it does **not** snap and keeps the measured value (in URDF that is exactly the measured slight offset).
    """
    st = _store()
    jid = str(jid)
    k = str(kind or "revolute").lower()
    if not k:
        return _j({"ok": False, "error": "kind cannot be empty", "kinds": list(ALL_KINDS)})
    pn, cn = _names(parent), _names(child)
    if not pn or not cn:
        return _j({"ok": False, "error": "both parent / child are required (an object name, or a list of object names = rigid group)",
                   "parent": pn, "child": cn})
    po, miss_p, nonmesh_p = _objs(pn)
    co, miss_c, nonmesh_c = _objs(cn)
    if not co or not po:
        return _j({"ok": False, "error": "both ends of a joint must have usable mesh objects (empty output is not allowed)",
                   "parent_ok": [o.name for o in po], "child_ok": [o.name for o in co],
                   "missing": miss_p + miss_c, "non_mesh": nonmesh_p + nonmesh_c})

    warnings = []
    if k not in ALL_KINDS:
        warnings.append("unknown kind=%s: registered as given, URDF export will degrade it to fixed" % k)
    elif k in PASSIVE_KINDS:
        warnings.append("kind=%s cannot be expressed in URDF → degraded to fixed on export (sweep/axis inference is meaningless for it)" % k)

    ax = None
    anc = None
    src = "none"
    a_verdict = "unresolved"
    ev = None
    if axis is not None:
        a = np.asarray([float(x) for x in axis], dtype=np.float64)
        n = float(np.linalg.norm(a))
        if n < 1e-12:
            return _j({"ok": False, "error": "axis is a zero vector, the joint axis cannot be defined", "axis": axis})
        ax = (a / n).tolist()
        src = "given"
        a_verdict = "supported"
        if anchor is not None:
            anc = [float(x) for x in anchor]
        else:
            v, _f, _p = _group_tris(co, bpy.context.evaluated_depsgraph_get())
            mn, mx, _diag = _bbox(v)
            if mn is None:
                return _j({"ok": False, "error": "axis given but the child group has no geometry, so anchor cannot be inferred (give anchor explicitly)"})
            cen = (mn + mx) / 2.0
            # anchor = the group centre's projection on the axis (the axis passes through the group centre) — only a deterministic fallback, so record it explicitly as a warning
            anc = cen.tolist()
            warnings.append("only axis was given without anchor: the anchor is taken as the projection of the child group's bbox centre (%.4g, %.4g, %.4g) onto the axis, "
                            "which may not lie on the real hinge line — give anchor explicitly or use measured inference" % tuple(anc))
    elif k in AXIS_KINDS:
        inf = json.loads(motion_infer_axis(objects=cn, parent=pn))
        ev = inf.get("evidence")
        a_verdict = inf.get("verdict")
        if inf.get("ok") and inf.get("axis"):
            ax = inf["axis"]
            anc = inf["anchor"]
            src = inf.get("axis_source") or "measured"
        else:
            warnings.append("axis measurement verdict is %s: %s" % (a_verdict, inf.get("reason")))
            warnings.append("this joint has no usable axis → sweeping will be unresolved, and URDF degrades to placeholder information at the continuous/fixed level")
    else:
        a_verdict = "supported"          # fixed/passive joints need no axis
        src = "not_required"

    lim = None
    if limits is not None:
        try:
            lim = [float(limits[0]), float(limits[1])]
            if lim[1] < lim[0]:
                lim = [lim[1], lim[0]]
                warnings.append("limits lower/upper were reversed, swapped back")
        except Exception:
            return _j({"ok": False, "error": "limits must be [lower, upper] (revolute=deg, prismatic=scene units)",
                       "limits": limits})

    snapped_from = None
    if ax is not None and snap_axis:
        raw = [float(x) for x in ax]
        s = _snap_axis(np.asarray(raw, dtype=np.float64))
        if s is not None:
            tgt = {"X": [1.0, 0.0, 0.0], "Y": [0.0, 1.0, 0.0], "Z": [0.0, 0.0, 1.0]}[s]
            ax = tgt
            snapped_from = _rl(raw, 9)
            src = src + "+snapped"
            warnings.append("snap_axis: axis snapped to %s (raw %s, angle %.3f°) — the raw value is kept in axis_snapped_from"
                            % (s, _rl(raw, 6), _angle_deg(raw, tgt) or 0.0))
        else:
            warnings.append("snap_axis is on but the measured axis has |component| < 0.95 on every world axis → not snapping (keeping the measured value)")

    rec = {
        "id": jid, "parent": pn, "child": cn, "kind": k,
        "axis": (_rl(ax, 9) if ax else None), "anchor": (_rl(anc, 9) if anc else None),
        "axis_source": src, "axis_verdict": a_verdict, "limits": lim, "note": str(note),
        "axis_snapped_from": snapped_from,
        "evidence": ev, "warnings": warnings, "measured": None, "registered": _now(),
        "objects": {"parent": [o.name for o in po], "child": [o.name for o in co]},
    }
    if verdict:
        rec["axis_verdict"] = str(verdict)
    st["joints"][jid] = rec
    st["seq"] = int(st.get("seq", 0)) + 1
    _log("joint", {"id": jid, "kind": k, "parent": pn, "child": cn, "axis": rec["axis"],
                   "axis_verdict": rec["axis_verdict"]})
    return _j({"ok": True, "op": "joint", "id": jid, "kind": k, "parent": pn, "child": cn,
               "axis": rec["axis"], "anchor": rec["anchor"], "axis_source": src,
               "axis_snapped_from": snapped_from,
               "axis_verdict": rec["axis_verdict"], "limits": lim,
               "evidence": ({"verdict": (ev or {}).get("verdict") if isinstance(ev, dict) else None,
                             "consensus": (ev or {}).get("consensus") if isinstance(ev, dict) else None}
                            if ev else None),
               "warnings": warnings,
               "note": "limits units: revolute/continuous = deg; prismatic = scene units"})


def motion_joints():
    st = _store()
    out = []
    for k, v in st["joints"].items():
        out.append({"id": k, "kind": v["kind"], "parent": v["parent"], "child": v["child"],
                    "axis": v.get("axis"), "anchor": v.get("anchor"),
                    "axis_source": v.get("axis_source"), "axis_verdict": v.get("axis_verdict"),
                    "limits": v.get("limits"),
                    "measured": (None if not v.get("measured") else
                                 {"verdict": v["measured"].get("verdict"),
                                  "phases": len(v["measured"].get("phases") or []),
                                  "moved": v["measured"].get("moved")}),
                    "warnings": v.get("warnings") or []})
    return _j({"ok": True, "op": "joints", "joints": out, "count": len(out)})


def _chain_names(jrec, all_joints, chain_depth="full"):
    """This joint's chain: immediate = only the parent+child groups; full = propagate through the registered joints (ancestors + descendants)."""
    chain = set(jrec["parent"]) | set(jrec["child"])
    if str(chain_depth) == "immediate":
        return chain
    changed = True
    while changed:
        changed = False
        for jid, j in all_joints.items():
            if j is jrec:
                continue
            pset, cset = set(j["parent"]), set(j["child"])
            if cset & chain and not pset <= chain:
                chain |= pset
                changed = True
            if pset & chain and not cset <= chain:
                chain |= cset
                changed = True
    return chain
