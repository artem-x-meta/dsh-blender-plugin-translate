# -*- coding: utf-8 -*-
"""Split from contract.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403
from .fingerprint import _r4
from .mate import _aabb_pairs, _bvh, _fit_value, _inside_mask, _mesh_data, _nearest, _overlap_estimate, _pt_tri_dist, _r6, _sample_surface, _units, _units_block

def _features_path():
    """Locate assembly_features.json (in runtime/py/assembly/; the old flat layout is still supported).

    Path lookup prefers K.runtime_dir / find_runtime_file, then falls back to
    the module directory, the sibling assembly package, and ../runtime (for
    direct tests). All supported loaders provide the real module path; a
    missing __file__ is treated as an injection contract violation, not masked.
    """
    try:
        p = _KIT.find_runtime_file(FEATURES_JSON_NAME)
        if p:
            return p
    except Exception:
        pass
    cands = []
    if _HERE:
        cands.append(_HERE)
        cands.append(os.path.join(os.path.dirname(_HERE), "assembly"))
        cands.append(os.path.join(os.path.dirname(_HERE), "runtime"))
        cands.append(os.path.join(os.path.dirname(os.path.dirname(_HERE)), "runtime"))
    K = _kernel()
    rd = getattr(K, "runtime_dir", None) if K is not None else None
    if rd:
        cands.insert(0, str(rd))
    for c in cands:
        try:
            if c and os.path.isfile(os.path.join(c, FEATURES_JSON_NAME)):
                return os.path.join(c, FEATURES_JSON_NAME)
        except Exception:
            continue
    return FEATURES_JSON if cands else FEATURES_JSON_NAME


def c_fit_help(fit=None, feature=None, m=None, d=None):
    """Assembly feature library quick reference (reads assembly_features.json from the assembly package, runtime/py/assembly/).

    Why it is a data file instead of numbers copied into code: the number one cause of mating parts not matching is not a wrong tolerance class but a literal
    written in both the male and the female side (change one, forget the other). mate_check / fit_help / generators read **the same** values, so they cannot drift apart.
    Every feature in the response carries "how to build it on the Blender side" (the cylinder/cube + boolean correspondence).
    """
    path = _features_path()
    if not os.path.isfile(path):
        return _j({"ok": False, "error": "feature library file does not exist: %s" % path,
                   "tried": [FEATURES_JSON, "K.runtime_dir"], "file": FEATURES_JSON_NAME,
                   "hint": "assembly_features.json should live in runtime/py/assembly/ (or in the old layout, in the same directory as contract.py)"})
    try:
        with open(path, encoding="utf-8") as f:
            lib = json.load(f)
    except Exception as e:
        return _j({"ok": False, "error": "failed to read the feature library: %s" % e, "path": path})
    out = {"ok": True, "path": path, "schema": lib.get("schema"), "units": lib.get("units"), "schema": lib.get("schema"), "units": lib.get("units"),
           "shared_nominal_rule": lib.get("shared_nominal_rule"),
           "fits": lib.get("fits"), "lead_chamfer": lib.get("lead_chamfer"),
           "iso273_clearance_diameter": lib.get("iso273_clearance_diameter"),
           "fit_default_cls": lib.get("fit_default_cls"),
           "features_index": [{"name": x.get("name"), "kind": x.get("kind"), "cn": x.get("cn"),
                               "pairs_with": x.get("pairs_with"), "blender": x.get("blender")}
                              for x in (lib.get("features") or [])],
           "blender_general": lib.get("blender_general"),
           "source": lib.get("source")}
    if m is not None:
        try:
            mm_ = float(m)
        except Exception:
            return _j({"ok": False, "error": "m must be a number (nominal metric thread diameter, mm)", "m": m})
        br = lib.get("iso273_clearance_diameter", {}).get("branches") or []
        off = None
        for b in br:
            if b.get("m_le") is None or mm_ <= float(b["m_le"]):
                off = float(b["offset_mm"]); break
        out["iso273_query"] = {"m": mm_, "offset_mm": off, "clearance_diameter_mm": (mm_ + off) if off is not None else None,
                               "formula": lib.get("iso273_clearance_diameter", {}).get("formula"),
                               "blender": "cutter = primitive_cylinder_add(radius=clearance_d/2, depth=depth) + cone entry funnel (lead=0.6) → BOOLEAN/DIFFERENCE"}
    if d is not None:
        try:
            dd = float(d)
        except Exception:
            return _j({"ok": False, "error": "d must be a number (diameter at the chamfered point, mm)", "d": d})
        out["lead_query"] = {"d": dd, "lead_mm": round(max(0.6, 0.15 * dd), 4),
                             "formula": "asm_lead(d) = max(0.6, 0.15*d)",
                             "blender": "male tip cone(radius1=d/2, radius2=max(0.2,d-2*lead)/2, depth=lead); female mouth cone(radius1=bore/2, radius2=(bore+2*lead)/2)"}
    if fit is not None:
        v, note = _fit_value(fit)
        out["fit_query"] = {"class": str(fit), "per_side_mm": v, "note": note,
                            "bore_rule": "female bore = nominal + 2×%.2f mm (%.2f per side)" % (v, v),
                            "mate_check_usage": "mate_check(conn_id, fit=\"%s\") → expected per-side gap %.2f mm"
                                                % (str(fit), v),
                            "tol_default_mm": FIT_DEFAULT_TOL_MM}
    if feature is not None:
        hit = [x for x in (lib.get("features") or []) if str(x.get("name")) == str(feature)]
        if not hit:
            return _j({"ok": False, "error": "feature does not exist: %s" % feature,
                       "available": [x.get("name") for x in (lib.get("features") or [])]})
        out["feature"] = hit[0]
    out["usage"] = "fit_help() full quick reference · fit_help(fit=\"location\") one class · fit_help(feature=\"socket\") one feature · fit_help(m=3) ISO clearance hole · fit_help(d=8) lead chamfer"
    return _j(out)


def _declared_index():
    """Design-intent index: object name → [(connection id, side)], and (a name, b name) pairs → [connection ids]. Read-only over K.dsh_contract."""
    st = _store()
    side, pairs, comp_of = {}, {}, {}
    for cid, comp in st["components"].items():
        for nm in comp.get("objects", []):
            comp_of.setdefault(nm, []).append(cid)
    for cid, conn in st["connections"].items():
        na = [o.name for o in _component_objects(conn["a"])]
        nb = [o.name for o in _component_objects(conn["b"])]
        for nm in na:
            side.setdefault(nm, []).append({"connection": cid, "side": "a", "component": conn["a"]})
        for nm in nb:
            side.setdefault(nm, []).append({"connection": cid, "side": "b", "component": conn["b"]})
        for x in na:
            for y in nb:
                pairs.setdefault((x, y), []).append(cid)
                pairs.setdefault((y, x), []).append(cid)
    return side, pairs, comp_of


def _severity(depth_mm, frac):
    """Three severity levels. Threshold rationale: 2 mm ≈ a common printed wall thickness (a 2 mm penetration punches through one wall);
    0.5 mm ≈ the scale of a seam visible to the naked eye; volume share 25% ≈ a quarter of a small part buried; 2% ≈ one small sliver."""
    hi = (depth_mm is not None and depth_mm > SEV_DEPTH_HIGH_MM) or (frac is not None and frac > SEV_FRAC_HIGH)
    med = (depth_mm is not None and depth_mm > SEV_DEPTH_MED_MM) or (frac is not None and frac > SEV_FRAC_MED)
    return "high" if hi else ("medium" if med else "low")


def _c_interference_report_p1(st):
    depth_eps, include_hidden, limit, scope = st["depth_eps"], st["include_hidden"], st["limit"], st["scope"]
    try:
        import numpy as np  # noqa: F401  # handed to the next split stage through st
        t0 = time.perf_counter()
        objs = _scope_objects(scope, include_hidden)
        if not objs:
            return _j({"ok": False, "error": "no visible mesh objects in scope (empty output → not a silent success)",
                       "scope": scope, "include_hidden": bool(include_hidden)})
        m_per_unit, mm_per_unit = _units()
        ub = _units_block(m_per_unit, mm_per_unit)
        eps_mm = float(depth_eps) if depth_eps is not None else MATE_DEPTH_EPS_MM
        side, dpairs, comp_of = _declared_index()
        cand = _aabb_pairs(objs)
        tested = cand[:max(0, int(limit))]
        cache = {}

        def MD(ob):
            if ob.name not in cache:
                cache[ob.name] = _mesh_data([ob])
            return cache[ob.name]

        def gkey(name):
            if name in comp_of:
                return "comp:" + comp_of[name][0]
            ob = bpy.data.objects.get(name)
            if ob is not None and ob.parent is not None:
                return "parent:" + ob.parent.name
            return "self:" + name

        offenders, exempted, skipped = [], [], []
        checked = overlapping = 0
        t1 = time.perf_counter()
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def _c_interference_report_p2(st):
    MD, checked, declared_ok, dpairs, eps_mm = (
        st.get("MD"), st.get("checked"), st["declared_ok"], st.get("dpairs"), st.get("eps_mm"))
    exempted, mm_per_unit, np, objs, offenders = (
        st.get("exempted"), st.get("mm_per_unit"), st.get("np"), st.get("objs"), st.get("offenders"))
    overlapping, samples, side, skipped, tested = (
        st.get("overlapping"), st["samples"], st.get("side"), st.get("skipped"), st.get("tested"))
    use_bvh = st["use_bvh"]
    DA, DB, PA, PB, closed, dby, declared, dep, depth_max, depth_mean, depth_mm, depth_ok, dir_used, frac, frac_proxy, how, i, inA, inB, inside_frac, j, ma, mb, n, oa, ob_, ovr, rec, score, sev, ta, tb, tri_hit = (st.get("DA"), st.get("DB"), st.get("PA"), st.get("PB"), st.get("closed"), st.get("dby"), st.get("declared"), st.get("dep"), st.get("depth_max"), st.get("depth_mean"), st.get("depth_mm"), st.get("depth_ok"), st.get("dir_used"), st.get("frac"), st.get("frac_proxy"), st.get("how"), st.get("i"), st.get("inA"), st.get("inB"), st.get("inside_frac"), st.get("j"), st.get("ma"), st.get("mb"), st.get("n"), st.get("oa"), st.get("ob_"), st.get("ovr"), st.get("rec"), st.get("score"), st.get("sev"), st.get("ta"), st.get("tb"), st.get("tri_hit"))
    try:
        for (i, j) in tested:
            oa, ob_ = objs[i], objs[j]
            ma, mb = MD(oa), MD(ob_)
            if not ma or not mb or ma["tris_n"] == 0 or mb["tris_n"] == 0:
                skipped.append({"a": oa.name, "b": ob_.name, "why": "one side has no triangles"})
                continue
            if MATE_MAX_TRIS > 0 and (ma["tris_n"] > MATE_MAX_TRIS or mb["tris_n"] > MATE_MAX_TRIS):
                skipped.append({"a": oa.name, "b": ob_.name, "why": "mesh too large (> %d faces), not judged" % MATE_MAX_TRIS})
                continue
            checked += 1
            tri_hit = None
            if use_bvh:
                ta, tb = _bvh(ma["tris"]), _bvh(mb["tris"])
                try:
                    tri_hit = bool(ta.overlap(tb)) if (ta is not None and tb is not None) else None
                except Exception as e:
                    tri_hit = None
                    skipped.append({"a": oa.name, "b": ob_.name, "why": "BVH overlap failed: %s (continuing with the AABB candidates)" % e})
                if tri_hit is False:
                    continue
            overlapping += 1
            # --- penetration depth ---
            n = int(max(16, min(int(samples), CONTACT_SAMPLE_CAP)))
            PA = _sample_surface(ma["tris"], n)
            PB = _sample_surface(mb["tris"], n)
            if PA is None or PB is None:
                skipped.append({"a": oa.name, "b": ob_.name, "why": "zero-area mesh, sampling failed"})
                continue
            closed = bool(ma["closed"] and mb["closed"])
            if INSIDE_MAX_TRIS <= 0 or (
                ma["tris_n"] <= INSIDE_MAX_TRIS and mb["tris_n"] <= INSIDE_MAX_TRIS
            ):
                inB = _inside_mask(PA, mb["tris"])
                inA = _inside_mask(PB, ma["tris"])
                if use_bvh:
                    _q, _nn, DA = _nearest(_bvh(mb["tris"]), PA)
                    _q2, _nn2, DB = _nearest(_bvh(ma["tris"]), PB)
                    how = "BVH nearest-point distance + ray-parity inside/outside"
                else:
                    DA = _pt_tri_dist(PA, mb["tris"])
                    DB = _pt_tri_dist(PB, ma["tris"])
                    how = "pure numpy point-triangle nearest distance + ray-parity inside/outside (use_bvh=false)"
                dep = np.concatenate([DA[inB & np.isfinite(DA)], DB[inA & np.isfinite(DB)]])
                depth_max = float(dep.max()) if len(dep) else 0.0
                depth_mean = float(dep.mean()) if len(dep) else 0.0
                dir_used = "A→B" if (inB & np.isfinite(DA)).any() else ("B→A" if (inA & np.isfinite(DB)).any() else "no embedded points")
                inside_frac = float(len(dep)) / float(len(PA) + len(PB))
                depth_ok = True
            else:
                depth_max = depth_mean = None
                inside_frac = None
                dir_used = "skipped"
                how = "mesh exceeds the inside-test cap %d → penetration not judged" % INSIDE_MAX_TRIS
                depth_ok = False
            ovr = _overlap_estimate(ma["tris"], mb["tris"], ma["volume_m3"], mb["volume_m3"],
                                    ma["closed"], mb["closed"], samples=int(max(32, min(int(samples), 4000))))
            frac = ovr.get("frac_of_smaller") if ovr.get("reliable") else None
            frac_proxy = frac if frac is not None else inside_frac
            depth_mm = (depth_max * mm_per_unit) if depth_max is not None else None
            sev = _severity(depth_mm, frac if frac is not None else inside_frac)
            score = _r4((frac_proxy or 0.0) * 1000.0 + (depth_mm or 0.0) * 10.0)
            dby = dpairs.get((oa.name, ob_.name), []) + dpairs.get((ob_.name, oa.name), [])
            dby = sorted(set(dby))
            declared = bool(dby)
            rec = {"a": oa.name, "b": ob_.name, "declared": declared, "declared_by": dby,
                   "declared_sides": [side.get(oa.name, []), side.get(ob_.name, [])] if declared else None,
                   "depth_mm": _r4(depth_mm) if depth_mm is not None else None,
                   "depth_mean_mm": _r4(depth_mean * mm_per_unit) if depth_mean is not None else None,
                   "depth_measured": bool(depth_ok), "depth_direction": dir_used,
                   "overlap_volume_mm3": ovr.get("overlap_volume_mm3"),
                   "overlap_frac_of_smaller": frac,
                   "overlap_frac_of_box": ovr.get("frac_of_box"),
                   "overlap_stderr": ovr.get("stderr_frac"),
                   "surface_inside_frac": _r6(inside_frac) if inside_frac is not None else None,
                   "volume_reliable": bool(ovr.get("reliable")),
                   "severity": sev, "severity_score": score,
                   "aabb_tri_overlap": tri_hit, "method": how,
                   "a_tris": ma["tris_n"], "b_tris": mb["tris_n"], "closed": closed,
                   "volume_mm3": {"a": _r4(ma["volume_m3"] * (mm_per_unit ** 3)),
                                  "b": _r4(mb["volume_m3"] * (mm_per_unit ** 3))}}
            if declared and declared_ok and depth_mm is not None and depth_mm <= eps_mm:
                rec["exempt_reason"] = ("contact within the design: %s are the two ends of connection %s (declared),"
                                        " measured penetration %.3f mm ≤ threshold %.3f mm" % (oa.name, "/".join(dby), depth_mm, eps_mm))
                exempted.append(rec)
            else:
                if declared and declared_ok and depth_mm is not None:
                    rec["exempt_reason"] = None
                    rec["note"] = ("declared, but penetration %.3f mm > threshold %.3f mm → still reported (planned contact does not mean anything may pass through)"
                                   % (depth_mm, eps_mm))
                offenders.append(rec)
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def _c_interference_report_p3(st):
    cand, checked, declared_ok, eps_mm, exempted = (
        st.get("cand"), st.get("checked"), st["declared_ok"], st.get("eps_mm"), st.get("exempted"))
    gkey, objs, offenders, overlapping, samples = (
        st.get("gkey"), st.get("objs"), st.get("offenders"), st.get("overlapping"), st["samples"])
    skipped, t0, t1, tested, ub = st.get("skipped"), st.get("t0"), st.get("t1"), st.get("tested"), st.get("ub")
    use_bvh = st["use_bvh"]
    g, k, order, r, sig = (st.get("g"), st.get("k"), st.get("order"), st.get("r"), st.get("sig"))
    try:
        offenders.sort(key=lambda r: (-(r.get("severity_score") or 0.0), str(r["a"]), str(r["b"])))
        for k, r in enumerate(offenders):
            r["rank"] = k + 1
        groups = {}
        for r in offenders:
            sig = tuple(sorted([gkey(r["a"]), gkey(r["b"])]))
            g = groups.setdefault(sig, {"group_key": list(sig), "members": [], "worst_severity": "low",
                                        "worst_score": 0.0, "max_depth_mm": 0.0, "objects": set(),
                                        "declared_all": True})
            g["members"].append({"a": r["a"], "b": r["b"], "rank": r["rank"], "severity": r["severity"],
                                 "depth_mm": r["depth_mm"], "declared": r["declared"]})
            g["objects"].update([r["a"], r["b"]])
            g["declared_all"] = g["declared_all"] and r["declared"]
            order = {"low": 0, "medium": 1, "high": 2}
            if order[r["severity"]] > order[g["worst_severity"]]:
                g["worst_severity"] = r["severity"]
            g["worst_score"] = max(g["worst_score"], r.get("severity_score") or 0.0)
            g["max_depth_mm"] = max(g["max_depth_mm"], r.get("depth_mm") or 0.0)
        gout = []
        for sig, g in groups.items():
            gout.append({"group_key": g["group_key"], "objects": sorted(g["objects"]),
                         "pairs": len(g["members"]), "worst_severity": g["worst_severity"],
                         "worst_score": _r4(g["worst_score"]), "max_depth_mm": _r4(g["max_depth_mm"]),
                         "declared_all": g["declared_all"],
                         "why": "same group: %s (normalized by same component > same parent > self)" % " / ".join(g["group_key"]),
                         "members": g["members"]})
        gout.sort(key=lambda g: -g["worst_score"])
        ms_total = (time.perf_counter() - t0) * 1000
        res = {"ok": True, "objects": len(objs), "pairs_aabb": len(cand), "pairs_tested": len(tested),
               "pairs_checked": checked, "pairs_overlapping": overlapping,
               "units": ub, "depth_eps_mm": _r4(eps_mm), "declared_ok": bool(declared_ok),
               "use_bvh": bool(use_bvh), "samples": int(samples),
               "count": len(offenders), "offenders": offenders, "groups": gout,
               "exempted_count": len(exempted), "exempted": exempted, "skipped": skipped,
               "severity_rules": {"depth_high_mm": SEV_DEPTH_HIGH_MM, "depth_medium_mm": SEV_DEPTH_MED_MM,
                                  "frac_high": SEV_FRAC_HIGH, "frac_medium": SEV_FRAC_MED,
                                  "score": "volume share×1000 + depth mm×10 (volume as the primary order)"},
               "ms": {"total": round(ms_total, 1), "measure": round((time.perf_counter() - t1) * 1000, 1)},
               "note": "the old op check_interference is untouched (its response structure is unchanged); this op only adds information, it does not replace it",
               "readonly": True}
        if checked == 0 and cand:
            res["warning"] = "every AABB candidate was skipped (mesh too large / no triangles) → there is no usable conclusion from this run; do not read it as 'no interference'"
        elif not cand:
            res["note_clean"] = "the AABB prefilter produced no candidate pairs → no interference (that is a conclusion, not an empty result)"
        _log("interference_report", {"objects": len(objs), "offenders": len(offenders),
                                     "exempted": len(exempted), "eps_mm": _r4(eps_mm)})
        return _j(res)
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def c_interference_report(scope=None, use_bvh=True, limit=60, declared_ok=True,
                          depth_eps=None, include_hidden=False, samples=VOL_SAMPLES):
    """Pairwise interference report: penetration depth (mm) + overlapping volume share + severity ranking + grouping + design-intent allowlist.

    How the work splits with the old op check_interference: the old op only answers "which two pairs intersect" (**its response structure is untouched**, backward compatible);
    this op answers "how deep the intersection is / how much volume / which pair deserves attention most / which ones were inside the design all along".

    How penetration depth is measured (the principle):
      * inside/outside: ray parity (_inside_mask) — globally exact for closed meshes, and it does not invert even when deeply buried in a cavity.
      * magnitude: BVH nearest-point distance (an SDF approximation). The direction is A→B first; when no A-side surface point is embedded but the BVH really does report
        an intersection, B→A is measured as well (when a small part is entirely enclosed by a large one, only B→A has readings).
      * use_bvh=false: falls back to the pure numpy point-triangle nearest distance (_pt_tri_dist) — an independent algorithm, also used to cross-check the BVH.
    How overlapping volume is measured: there is no CSG compiler, so low-discrepancy sampling runs inside the **intersection box** of the A/B world AABBs;
      the ray-parity share of points "inside both" × box volume = an unbiased estimate, reported with its binomial standard error (an estimate, not an exact value).

    Design-intent allowlist (declared): a and b belong to the two ends of some registered connection → declared=true (contact that was planned),
      moved from offenders to exempted by default; but when penetration depth > depth_eps it is **still reported** (planned contact ≠ anything may pass through).
      Why depth_eps defaults to 0.2 mm: the largest of fit's four classes is clearance 0.25 (material relief, which should not penetrate at all),
      and press, the only class that genuinely interferes, is just 0.05 mm → 0.2 mm is enough to let every "in-design" press fit through;
      it is also one notch tighter than audit.py's MICRO_GAP_MM=0.3 (the contact-but-not-coincident reporting line) — so it reports before that grows to a visible defect;
      and it sits far above measurement noise (triangulation chord error ~0.005–0.02 mm), so mesh noise does not cause false reports.

    Severity: score = volume share×1000 + depth mm×10 (volume as the primary order, depth as the secondary), levels in _severity().
    groups: pair clusters keyed by the "same component > same parent > self" normalization (multiple pairs in one group merge into one entry showing the worst pair).

    Read-only: does not change the scene or the contract state. Empty output (no visible mesh in scope) → ok:false.
    """
    st = dict(locals())
    for _fn_ in (_c_interference_report_p1, _c_interference_report_p2, _c_interference_report_p3):
        _r = _fn_(st)
        if _r is not None:
            return _r


def c_help():
    return _j({"version": CONTRACT_VERSION,
               "S1_ops": {"register_component": "id, objects, tags, note",
                          "register_connection": "id, a, b, candidates, params, forbidden, confidence, evidence_required, status",
                          "register_envelope": "id, min, max, scope, note",
                          "check_envelope": "id (optional) → out-of-bounds list",
                          "check_interference": "scope, use_bvh, limit → AABB prefilter + BVH close check",
                          "check_interface": "conn_id, mesh(true), samples(1500) → gap/intrusion between two components: the bbox-level legacy fields (gap_axis_m/gap_m/overlap_bbox) keep their convention + a mesh block (mesh-level per-side gap mm / contact share / penetration mm)",
                          "destructive_guard": "op, targets, conn_ids → allowed/blocked + reason",
                          "evidence": "label, view → render + md5 recording",
                          "ledger/status/report": "evidence ledger / overview / Markdown report"},
               "S2_ops": {"verify": "conn_id, err, tolerance, identifiable, probe_err, probe_tolerance → three-state",
                          "flip": "conn_id, to, why → flip the candidate and record the history",
                          "advance": "conn_id, status(proposed|testing|supported|refuted), why"},
               "V090_ops": {"fingerprint": "objects|scope → geometry fingerprint (objects/faces/points/world bbox + a 12-digit digest); one before and one after the change shows whether the source moved",
                            "ledger": "with_stale=true (default) → every evidence record is matched against the current fingerprint; records whose source changed are marked stale=true + stale_labels",
                            "drift_guard": "verify records a bbox snapshot: center drift >10% of the diagonal or size drift >20% → supported is automatically demoted to unresolved when status/ledger is read (the reason stays in verdict.demoted; objects carrying animation data are skipped)"},
               "S3_ops": {"mate_check": "conn_id, fit(clearance|location|press|snap), nominal(expected per-side gap mm), tol_mm(default 0.15), samples(≤4000), contact_max_mm, depth_eps_mm"
                                        " → mesh-level fit gate: contact area share / contact anchors / contact normals / per-side gap (mm) / penetration depth (mm) → supported|refuted|unresolved",
                          "fit_help": "fit|feature|m|d → assembly feature library quick reference (9 features + asm_fit's four classes + asm_lead + ISO 273 clearance holes + how to build them on the Blender side)",
                          "interference_report": "scope, use_bvh(true), limit(60), declared_ok(true), depth_eps(default 0.2 mm), include_hidden"
                                                 " → pairwise: penetration depth mm + overlapping volume share + severity ranking + groups clustering + exempted (design-intent allowlist)"},
               "S3_rules": "fit gate three-state: samples < 8 points / empty component / no fit·nominal given / the intrusion judgement was not actually made → unresolved; 0 contact points (not mated) or penetration past the threshold or a gap out of band → refuted;"
                           " a gap inside nominal ± tol with no over-deep penetration → supported. Contact distance = 1.5% × the merged bbox diagonal. Shared-nominal discipline: male and female derive from the same nominal ± asm_fit; two independent literals are forbidden.",
               "rules": "insufficient external evidence (parameters not identifiable) must report unresolved; probe error > tolerance means refuted; destructive operations are blocked until judged;"
                        " geometry drifting after a verdict → the verdict is invalidated automatically (V0.9); assembly-level measurements always go through the evaluated mesh (unapplied Booleans count too), numbers always carry units, empty output must be ok:false",
               "docs": "docs/assumption-driven-modeling-cookbook.md · runtime/py/assembly/assembly_features.json (the feature library data)"})