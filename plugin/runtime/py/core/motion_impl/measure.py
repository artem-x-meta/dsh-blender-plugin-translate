# -*- coding: utf-8 -*-
"""Split from motion.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403
from .infer import _chain_names
from .transforms import TOL_MAT, _mat_of, _phase_values, _restore_transforms, _snap_transforms



def _inside_probe(tree, p):
    """Whether a point is inside a closed mesh (judged by the orientation of the nearest face normal) + the distance to the surface. Approximate but good enough for penetration depth."""
    try:
        hit = tree.find_nearest(Vector((float(p[0]), float(p[1]), float(p[2]))))
    except Exception:
        return False, None
    if not hit or hit[0] is None or hit[3] is None:
        return False, None
    loc, nor, _idx, dist = hit
    inside = False
    if nor is not None:
        inside = (Vector((float(p[0]), float(p[1]), float(p[2]))) - loc).dot(nor) < 0.0
    return inside, float(dist)


def _min_gap_pair(tree_a, pts_a, tree_b, pts_b, max_samples=MAX_DIST_SAMPLES,
                  V_a=None, F_a=None, V_b=None, F_b=None):
    """Two-way sampling for the minimum gap + interference (BVH triangle intersection = exact) + penetration depth (overlapping triangle pairs + sample points, estimated from normal orientation)."""
    def _stride(arr):
        if len(arr) <= max_samples:
            return arr
        st = int(math.ceil(len(arr) / float(max_samples)))
        return arr[::st]

    A = _stride(pts_a)
    B = _stride(pts_b)
    gap = None
    pen = 0.0
    witness = None
    for pts, tree in ((A, tree_b), (B, tree_a)):
        for p in pts:
            hit = tree.find_nearest(Vector((float(p[0]), float(p[1]), float(p[2]))))
            if not hit or hit[0] is None:
                continue
            loc, nor, _idx, dist = hit
            if dist is None:
                continue
            inside = False
            if nor is not None:
                d = (Vector((float(p[0]), float(p[1]), float(p[2]))) - loc).dot(nor)
                inside = d < 0.0
            if gap is None or dist < gap:
                gap = float(dist)
                witness = [float(p[0]), float(p[1]), float(p[2])]
            if inside and float(dist) > pen:
                pen = float(dist)
                witness = [float(p[0]), float(p[1]), float(p[2])]
    over = []
    try:
        over = tree_a.overlap(tree_b) or []
    except Exception:
        over = []
    # use the face centres of intersecting triangle pairs as penetration probes (no sample point may land inside the other mesh)
    if over and V_a is not None and F_a is not None and V_b is not None and F_b is not None:
        probes = []
        for (ia, ib) in over[:64]:
            try:
                probes.append(V_a[F_a[int(ia)]].mean(axis=0))
            except Exception:
                pass
            try:
                probes.append(V_b[F_b[int(ib)]].mean(axis=0))
            except Exception:
                pass
        for p in probes:
            ins_b, d_b = _inside_probe(tree_b, p)      # the probe lies inside B → penetration into B
            if ins_b and d_b is not None and d_b > pen:
                pen = float(d_b)
                witness = [float(p[0]), float(p[1]), float(p[2])]
            ins_a, d_a = _inside_probe(tree_a, p)      # the probe lies inside A → B penetrates into A
            if ins_a and d_a is not None and d_a > pen:
                pen = float(d_a)
                witness = [float(p[0]), float(p[1]), float(p[2])]
    return {"gap": gap, "penetration": pen, "overlap_tris": int(len(over)),
            "overlap_sample": [[int(a), int(b)] for (a, b) in over[:MAX_OVERLAP_REPORT]],
            "witness": (_rl(witness, 6) if witness else None)}


def __measure_one_p1(_state):
    chain_depth, exclude, jrec, margin_frac, max_candidates = (
        _state["chain_depth"], _state["exclude"], _state["jrec"], _state["margin_frac"], _state["max_candidates"])
    max_samples, phases, sweep_deg = _state["max_samples"], _state["phases"], _state["sweep_deg"]
    f, ob, v, why = (_state.get("f"), _state.get("ob"), _state.get("v"), _state.get("why"))
    try:
        st = _store()
        jid = jrec["id"]
        if not jrec.get("axis"):
            why = ("joint type %s does not need an axis (axis_source=%s) → sweeping it is meaningless"
                   % (jrec.get("kind"), jrec.get("axis_source"))
                   if jrec.get("axis_source") == "not_required" else
                   "the joint has no axis (axis_verdict=%s) → run motion_infer_axis first, or pass axis when registering"
                   % jrec.get("axis_verdict"))
            return {"ok": False, "op": "measure", "jid": jid, "verdict": "unresolved",
                    "reason": why, "axis_verdict": jrec.get("axis_verdict"),
                    "moved": None, "phases": [], "axis": None, "anchor": None}
        co, miss_c, nonmesh_c = _objs(jrec["child"])
        if not co:
            return {"ok": False, "op": "measure", "jid": jid, "verdict": "unresolved",
                    "reason": "the child group has no usable mesh objects", "missing": miss_c, "non_mesh": nonmesh_c,
                    "moved": None, "phases": [], "axis": jrec["axis"], "anchor": jrec.get("anchor")}

        axis = np.asarray(jrec["axis"], dtype=np.float64)
        anchor = np.asarray(jrec.get("anchor") or [0.0, 0.0, 0.0], dtype=np.float64)
        dg = bpy.context.evaluated_depsgraph_get()

        all_joints = dict(st["joints"])
        chain = _chain_names(jrec, all_joints, chain_depth=chain_depth)
        excl = set(_names(exclude)) | chain
        cands = []
        skipped_hidden = []
        for ob in bpy.data.objects:
            if ob.type != "MESH" or ob.name in excl:
                continue
            if ob.hide_viewport or ob.hide_render:
                skipped_hidden.append(ob.name)
                continue
            cands.append(ob)
        cands = sorted(cands, key=lambda o: o.name)[:max(1, int(max_candidates or 64))]

        V0, F0, parts0 = _group_tris(co, dg)
        if len(V0) == 0:
            return {"ok": False, "op": "measure", "jid": jid, "verdict": "unresolved",
                    "reason": "the child group evaluated to no triangles (no measurable geometry)", "moved": None, "phases": [],
                    "axis": _rl(axis, 9), "anchor": _rl(anchor, 9)}

        vals, unit, span, err = _phase_values(jrec, phases, sweep_deg, margin_frac, V0)
        if err:
            return {"ok": False, "op": "measure", "jid": jid, "verdict": "unresolved", "reason": err,
                    "moved": None, "phases": [], "axis": _rl(axis, 9), "anchor": _rl(anchor, 9)}

        # candidate BVH / sample points (static objects, built only once)
        ctrees, cpts, cnames, cverts = {}, {}, [], {}
        for ob in cands:
            v, f = _mesh_tris_world(ob, dg)
            if len(v) == 0 or len(f) == 0:
                continue
            try:
                ctrees[ob.name] = BVHTree.FromPolygons([tuple(map(float, p)) for p in v],
                                                       [tuple(int(i) for i in t) for t in f],
                                                       all_triangles=True, epsilon=0.0)
            except Exception:
                continue
            cpts[ob.name] = _sample_points(v, f, max_samples)
            cverts[ob.name] = (v, f)
            cnames.append(ob.name)

        # scene snapshot (all objects: even unrelated ones must be proven untouched)
        all_objs = [o for o in bpy.data.objects]
        snap = _snap_transforms(all_objs)
        rest_mat = {ob.name: _mat_of(snap[ob.name]) for ob in co if ob.name in snap}
        touched = set(rest_mat)
        t0 = time.perf_counter()
        phase_recs, moved_max, rest = [], 0.0, None
        sweep_err = None
        mism, pre_delta, post_delta, wrote = [], 0.0, 0.0, []
        touched = set(rest_mat)
    finally:
        _state.update((k, v) for k, v in locals().items() if k != "_state")

def __measure_one_p2(_state):
    F0, V0, all_objs, anchor, axis = (
        _state.get("F0"), _state.get("V0"), _state.get("all_objs"), _state.get("anchor"), _state.get("axis"))
    cands, cnames, co, cpts, ctrees = (
        _state.get("cands"), _state.get("cnames"), _state.get("co"), _state.get("cpts"), _state.get("ctrees"))
    cverts, dg, jrec, max_samples, moved_max = (
        _state.get("cverts"), _state.get("dg"), _state["jrec"], _state["max_samples"], _state.get("moved_max"))
    mpu, phase_recs, rest_mat, snap, touched = (
        _state["mpu"], _state.get("phase_recs"), _state.get("rest_mat"), _state.get("snap"), _state.get("touched"))
    unit, vals = _state.get("unit"), _state.get("vals")
    Fp, M, R, T, Vp, c, i, names, ob, r, rec, rm, sweep_err, th, tp, val = (_state.get("Fp"), _state.get("M"), _state.get("R"), _state.get("T"), _state.get("Vp"), _state.get("c"), _state.get("i"), _state.get("names"), _state.get("ob"), _state.get("r"), _state.get("rec"), _state.get("rm"), _state.get("sweep_err"), _state.get("th"), _state.get("tp"), _state.get("val"))
    try:
        try:
            # rest pose (phase 0): take the baseline measurement once
            rest = _sweep_at(co, ctrees, cpts, cnames, V0, F0, dg, max_samples, mpu, cverts)
            for i, val in enumerate(vals):
                tp = time.perf_counter()
                if jrec["kind"] in ("revolute", "continuous"):
                    th = math.radians(float(val))
                    R = Matrix.Rotation(th, 4, Vector((float(axis[0]), float(axis[1]), float(axis[2]))))
                    T = Matrix.Translation(Vector((float(anchor[0]), float(anchor[1]), float(anchor[2]))))
                    M = T @ R @ T.inverted()
                else:
                    M = Matrix.Translation(Vector((float(axis[0]), float(axis[1]), float(axis[2]))) * float(val))
                # every phase starts from the "rest pose" (not from the previous phase) → no accumulated error
                for ob in co:
                    rm = rest_mat.get(ob.name)
                    if rm is not None:
                        ob.matrix_world = M @ rm
                bpy.context.view_layer.update()
                Vp, Fp, _ = _group_tris(co, dg)
                if len(Vp):
                    moved_max = max(moved_max, float(np.abs(Vp - V0).max()))
                rec = _sweep_at(co, ctrees, cpts, cnames, Vp, Fp, dg, max_samples, mpu, cverts)
                rec["phase"] = i
                rec["value"] = _r(val, 6)
                rec["unit"] = unit
                rec["ms"] = int((time.perf_counter() - tp) * 1000)
                phase_recs.append(rec)
        except Exception as e:
            sweep_err = "%s: %s" % (type(e).__name__, str(e)[:200])
        finally:
            mism, pre_delta, post_delta, wrote = _restore_transforms(all_objs, snap, touched=touched)

        colls = []
        for r in phase_recs:
            for c in r.get("collisions") or []:
                colls.append({"phase": r["phase"], "value": r["value"], "unit": unit,
                              "other": c["other"], "penetration_m": c["penetration_m"],
                              "penetration_units": c.get("penetration_units"),
                              "min_gap_m": c.get("min_gap_m"), "min_gap_units": c.get("min_gap_units"),
                              "collides": True, "overlap_tris": c["overlap_tris"],
                              "witness": c.get("witness")})
        tol = max(1e-9, 1e-6 * (float(np.linalg.norm(V0.max(axis=0) - V0.min(axis=0))) or 1.0))
        moved = bool(moved_max > tol)
        if not cands:
            verdict = "unresolved"
            reason = ("no non-chain object is available for an interference check → zero interference is hollow evidence (an interference check needs a bystander object); "
                      "moved=%s" % moved)
        elif not moved:
            verdict = "refuted"
            reason = "the child group showed no geometric displacement after driving (max displacement %.3e ≤ %.3e) → it is not actually movable" % (moved_max, tol)
        elif colls:
            names = []
            for c in sorted(colls, key=lambda x: (x["penetration_m"] or 0.0), reverse=True):
                if c["other"] not in names:
                    names.append(c["other"])
            verdict = "refuted"
            reason = ("collided with %s during the sweep (%d phases showed interference, deepest %.4g m, phases %s); the zero-interference-throughout claim does not hold"
                      % (", ".join(names), len({c["phase"] for c in colls}),
                         max([c["penetration_m"] or 0.0 for c in colls] or [0.0]),
                         sorted({c["phase"] for c in colls})))
        else:
            verdict = "supported"
            reason = ("%d phases showed zero interference throughout and it really moved (max %.4g m) → this is the kinematic evidence that it is movable"
                      % (len(phase_recs), moved_max))
        if sweep_err:
            verdict = "unresolved"
            reason = "exception during the sweep (the scene was restored): %s" % sweep_err
    finally:
        _state.update((k, v) for k, v in locals().items() if k != "_state")

def __measure_one_p3(_state):
    all_objs, anchor, axis, chain, chain_depth = (
        _state.get("all_objs"), _state.get("anchor"), _state.get("axis"), _state.get("chain"), _state["chain_depth"])
    cnames, co, colls, jid, jrec = (
        _state.get("cnames"), _state.get("co"), _state.get("colls"), _state.get("jid"), _state["jrec"])
    margin_frac, mism, moved, moved_max, mpu = (
        _state["margin_frac"], _state.get("mism"), _state.get("moved"), _state.get("moved_max"), _state["mpu"])
    phase_recs, post_delta, pre_delta, reason, rest = (
        _state.get("phase_recs"), _state.get("post_delta"), _state.get("pre_delta"), _state.get("reason"), _state.get("rest"))
    skipped_hidden, span, sweep_err, t0, unit = (
        _state.get("skipped_hidden"), _state.get("span"), _state.get("sweep_err"), _state.get("t0"), _state.get("unit"))
    verdict, wrote = _state.get("verdict"), _state.get("wrote")
    try:
        return {
            "ok": verdict != "unresolved",
            "op": "measure", "jid": jid, "kind": jrec["kind"],
            "child": [o.name for o in co], "parent": list(jrec["parent"]),
            "axis": _rl(axis, 9), "anchor": _rl(anchor, 9),
            "axis_source": jrec.get("axis_source"), "axis_verdict": jrec.get("axis_verdict"),
            "sweep": {"phases": len(phase_recs), "unit": unit,
                      "span": _r(span, 6),
                      "span_si": _r(float(span) * (mpu if unit == "scene_unit" else (math.pi / 180.0)), 6),
                      "span_si_unit": ("m" if unit == "scene_unit" else "rad"),
                      "margin_frac": float(margin_frac), "limits": jrec.get("limits")},
            "rest": rest, "phases": phase_recs,
            "moved": moved, "max_displacement": _r(moved_max, 6),
            "max_displacement_m": _r(moved_max * mpu, 6),
            "verdict": verdict, "reason": reason, "error": sweep_err,
            "collisions": colls, "offenders": sorted({c["other"] for c in colls}),
            "chain_excluded": sorted(chain), "chain_depth": str(chain_depth),
            "candidates": cnames, "candidates_total": len(cnames),
            "skipped_hidden": skipped_hidden,
            "restored": {"ok": len(mism) == 0, "checked": len(all_objs), "mismatches": mism,
                         "pre_delta": pre_delta, "max_delta": post_delta, "tol": TOL_MAT,
                         "rewritten": wrote,
                         "note": "after the sweep, matrix_world is compared object by object (all objects, not just the child group); "
                                 "max_delta is the residual deviation after restoring (untouched objects compare equal item by item and are not rewritten)"},
            "units": {"length": "scene_unit (1 unit = %g m)" % mpu, "angle": "deg"},
            "ms": int((time.perf_counter() - t0) * 1000),
        }
    finally:
        _state.update((k, v) for k, v in locals().items() if k != "_state")

def _measure_one(jrec, phases, sweep_deg, margin_frac, exclude, chain_depth,
                 max_candidates, max_samples, mpu):
    _state = dict(locals())
    for _fn_ in (__measure_one_p1, __measure_one_p2, __measure_one_p3):
        _r = _fn_(_state)
        if _r is not None:
            return _r


def _sweep_at(co, ctrees, cpts, cnames, V, F, dg, max_samples, mpu, cverts=None):
    """At one pose: interference pairs between the child group and all candidates + the minimum gap. V/F are the current-pose world triangles already computed by the caller."""
    if V is None or len(V) == 0:
        return {"collisions": [], "nearest": None, "checked": 0,
                "note": "the child group evaluated to no geometry"}
    if F is None or len(F) == 0:
        return {"collisions": [], "nearest": None, "checked": 0, "note": "the child group has no triangles"}
    tree = BVHTree.FromPolygons([tuple(map(float, p)) for p in V],
                                [tuple(int(i) for i in t) for t in F],
                                all_triangles=True, epsilon=0.0)
    pts = _sample_points(V, F, max_samples)
    mn, mx, diag = _bbox(V)
    margin = 0.05 * (diag or 0.0)
    lo = mn - margin
    hi = mx + margin
    collisions, nearest, checked = [], None, 0
    for name in cnames:
        t2 = ctrees.get(name)
        p2 = cpts.get(name)
        if t2 is None or p2 is None or len(p2) == 0:
            continue
        bmn = p2.min(axis=0); bmx = p2.max(axis=0)
        if np.any(bmx < lo) or np.any(bmn > hi):
            continue          # AABB pre-filter: too far apart, so there is no need to even compute the gap
        checked += 1
        vb = cverts.get(name) if cverts else None
        r = _min_gap_pair(tree, pts, t2, p2, max_samples=max_samples,
                          V_a=V, F_a=F, V_b=(vb[0] if vb else None), F_b=(vb[1] if vb else None))
        gap = r["gap"]
        pen = float(r["penetration"] or 0.0)
        collides = (r["overlap_tris"] > 0) or (pen > 0.0)
        entry = {"other": name, "collides": bool(collides),
                 "gap_m": (_r(gap * mpu, 6) if gap is not None else None),
                 "gap_units": (_r(gap, 6) if gap is not None else None),
                 "penetration_m": _r(pen * mpu, 6), "penetration_units": _r(pen, 6),
                 "depth_measured": bool(pen > 0.0),
                 "overlap_tris": int(r["overlap_tris"]), "witness": r["witness"],
                 "samples_self": int(min(len(pts), max_samples)),
                 "samples_other": int(min(len(p2), max_samples))}
        if collides:
            # gap sign convention: <0 means interpenetration (penetration depth is taken as negative).
            # when triangle intersection is proven but the probe measured no depth (a grazing pass), min_gap=0 and depth_measured=false.
            entry["min_gap_m"] = _r(-pen * mpu, 6) if pen > 0 else 0.0
            entry["min_gap_units"] = _r(-pen, 6) if pen > 0 else 0.0
            collisions.append(entry)
        else:
            entry["min_gap_m"] = _r((gap or 0.0) * mpu, 6)
            entry["min_gap_units"] = _r(gap or 0.0, 6)
            if gap is not None and (nearest is None or gap < nearest["gap_units"]):
                nearest = entry
    collisions.sort(key=lambda e: -(e["penetration_units"] or 0.0))
    return {"collisions": collisions, "nearest": nearest, "checked": checked}


def motion_measure(jid=None, phases=8, sweep_deg=60, margin_frac=0.05, exclude=None,
                   chain_depth="full", max_candidates=64, max_samples=MAX_DIST_SAMPLES, note=""):
    """Sweep verification (replacing Isaac): drive N phases, run a BVH interference + minimum-gap check per phase; fully restore the scene at the end.

    verdict: zero interference throughout and it actually moved → supported; it collides as soon as it moves (interference with gap<0) → refuted (naming what it hit);
             no axis / no child geometry / nothing to compare against → unresolved.
    jid=None → measure every registered joint one by one (the aggregate verdict takes the worst).
    """
    st = _store()
    mpu = _scene_mpu()
    if jid is not None:
        jrec = st["joints"].get(str(jid))
        if jrec is None:
            return _j({"ok": False, "op": "measure", "error": "joint not registered: %s" % jid,
                       "have": sorted(st["joints"])})
        rec = _measure_one(jrec, phases, sweep_deg, margin_frac, exclude, chain_depth,
                           max_candidates, max_samples, mpu)
        rec["note"] = str(note)
        if rec.get("ok") or rec.get("verdict"):
            jrec["measured"] = {"verdict": rec.get("verdict"), "ms": rec.get("ms"),
                                "moved": rec.get("moved"), "phases": rec.get("phases"),
                                "reason": rec.get("reason"), "t": _now(),
                                "restored_ok": (rec.get("restored") or {}).get("ok")}
        _log("measure", {"jid": rec.get("jid"), "verdict": rec.get("verdict"),
                         "reason": str(rec.get("reason"))[:200]})
        return _j(rec)

    results, order = {}, {"refuted": 0, "unresolved": 1, "supported": 2}
    worst, worst_jid = "supported", None
    for k, jrec in st["joints"].items():
        r = _measure_one(jrec, phases, sweep_deg, margin_frac, exclude, chain_depth,
                         max_candidates, max_samples, mpu)
        r["note"] = str(note)
        jrec["measured"] = {"verdict": r.get("verdict"), "ms": r.get("ms"), "moved": r.get("moved"),
                            "phases": r.get("phases"), "reason": r.get("reason"), "t": _now(),
                            "restored_ok": (r.get("restored") or {}).get("ok")}
        results[k] = r
        v = r.get("verdict") or "unresolved"
        if worst_jid is None or order.get(v, 1) < order.get(worst, 2):
            worst, worst_jid = v, k
    if not results:
        return _j({"ok": False, "op": "measure", "error": "no registered joints", "verdict": "unresolved"})
    return _j({"ok": worst != "unresolved", "op": "measure", "verdict": worst, "worst_joint": worst_jid,
               "verdicts": {k: (v.get("verdict")) for k, v in results.items()},
               "results": results,
               "units": {"length": "scene_unit (1 unit = %g m)" % mpu, "angle": "deg"}})
