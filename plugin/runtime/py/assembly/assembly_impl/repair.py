# -*- coding: utf-8 -*-
"""Split from assembly.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403
from .manifest import _load_manifest, _manifest_validate
from .scan import _pair_key, asm_scan
from .gate import _trim

_REPAIR_METHODS = ("translate", "snap", "subtract")
_REPAIR_HONEST_LIMITS = [
    "Translation is planned by AABB separation: separated AABBs ⇒ triangles cannot intersect; but it may introduce new conflicts with a third part (the rescan reports them, at most max_rounds rounds)",
    "The boolean difference only subtracts the smaller part from the larger one (the cutter is a copy, the original is untouched); topology changes cannot be rolled back with object-level mark/revert, they need a file-level snapshot",
    "Floater plans come from audit_snap_floaters (single-part 1% visibility convention); for assembly interfaces that do not mate use the manifest connectivity graph —— it is a different criterion",
    "Open meshes / inward normals / missing evaluated meshes are never auto-fixed (no guessing on thin evidence); run fix_repair / recalc normals first",
    "dry_run=true is read-only: no moving, no booleans, no writing to disk; depth/volume are sampling-based estimates",
]


def _repair_flag(v, name):
    """JSON / string / 0-1 → bool; a bad value returns (None, error)."""
    if isinstance(v, bool):
        return v, None
    if isinstance(v, (int, float)) and float(v) in (0.0, 1.0):
        return bool(v), None
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "1", "yes", "on"):
            return True, None
        if s in ("false", "0", "no", "off"):
            return False, None
    return None, "%s must be a boolean (true/false), got %r" % (name, v)


def _repair_policy(policy):
    """Normalise policy → (policy, explicit, err).

    The default (None) equals safe, but keeps the old calling semantics: allow_boolean=true is an explicit human authorization, so booleans are still allowed;
    only an **explicit** policy="safe" hard-bans booleans (topology change); manual only plans; aggressive keeps the old allow_boolean path.
    """
    if policy is None:
        return "safe", False, None
    p = str(policy).strip().lower()
    if p in ("safe", "manual", "aggressive"):
        return p, True, None
    return None, False, "policy only supports safe|manual|aggressive, got %r" % (policy,)


def _repair_brief(scan):
    """scan receipt → the slimmed state the repair loop uses (criterion fields only)."""
    if not isinstance(scan, dict):
        return {"ok": False, "verdict": "error", "counts": {}, "offenders": [], "floaters": [],
                "floating_unresolved": [], "coverage": {}, "error": "the scan receipt is not a dict"}
    return {"ok": bool(scan.get("ok")), "verdict": scan.get("verdict"),
            "counts": dict(scan.get("counts") or {}),
            "offenders": list(scan.get("offenders") or []),
            "floaters": list(scan.get("floaters") or []),
            "floating_unresolved": list(scan.get("floating_unresolved") or []),
            "coverage": dict(scan.get("coverage") or {}),
            "verdict_line": scan.get("verdict_line"), "error": scan.get("error")}


def _repair_bad_total(brief):
    """clash + contained + float (float per the scan counts convention: number of floating objects/interfaces)."""
    c = (brief or {}).get("counts") or {}
    return (int(c.get("clash") or 0) + int(c.get("contained") or 0) + int(c.get("float") or 0))


def _repair_residual(brief):
    c = (brief or {}).get("counts") or {}
    return {"clash": int(c.get("clash") or 0), "contained": int(c.get("contained") or 0),
            "float": int(c.get("float") or 0), "unresolved": int(c.get("unresolved") or 0)}


def _repair_pair_row(p):
    """offender → slimmed row (criterion fields, large objects not expanded)."""
    if not isinstance(p, dict):
        return {"raw": str(p)[:160]}
    return {"a": p.get("a"), "b": p.get("b"), "class": p.get("class"),
            "severity": p.get("severity"), "depth_mm": p.get("depth_mm"),
            "volume_mm3": p.get("volume_mm3"), "min_gap_mm": p.get("min_gap_mm"),
            "tri_overlap_pairs": p.get("tri_overlap_pairs"),
            "method": p.get("method"), "reason": str(p.get("reason") or "")[:220]}


def _repair_float_row(f):
    if not isinstance(f, dict):
        return {"raw": str(f)[:160]}
    return {"object": f.get("object"), "objects": [str(x) for x in (f.get("objects") or [])][:12],
            "reason": f.get("reason"), "interface": f.get("interface"),
            "mesh_gap_mm": f.get("mesh_gap_mm"), "why": str(f.get("why") or "")[:200]}


def _repair_brief_out(brief):
    b = brief if isinstance(brief, dict) else {}
    return {"ok": bool(b.get("ok", False)), "verdict": b.get("verdict"),
            "counts": b.get("counts") or {},
            "coverage": b.get("coverage"),
            "offenders": [_repair_pair_row(p) for p in (b.get("offenders") or [])[:20]],
            "floaters": [_repair_float_row(f) for f in (b.get("floaters") or [])[:20]],
            "floating_unresolved": [{"reason": u.get("reason"), "why": str(u.get("why") or "")[:200]}
                                    for u in (b.get("floating_unresolved") or [])[:10] if isinstance(u, dict)],
            "verdict_line": b.get("verdict_line"), "error": b.get("error")}


def _repair_touched(rec):
    """Set of object names a plan/blocked record involves."""
    out = set()
    if not isinstance(rec, dict):
        return out
    pr = rec.get("pair")
    if isinstance(pr, (list, tuple)):
        out.update(str(x) for x in pr if x is not None)
    elif pr:
        out.add(str(pr))
    for k in ("target", "cutter", "object"):
        if rec.get(k):
            out.add(str(rec[k]))
    for o in rec.get("objects") or []:
        out.add(str(o))
    return out


def _dedupe_blocked(items):
    out, seen = [], set()
    for it in items or []:
        try:
            key = _canon(it if isinstance(it, dict) else {"raw": str(it)})
        except Exception:
            key = str(it)
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def _obj_volume_mm3(md, mmu):
    """Evaluated mesh volume (mm³); falls back to AABB volume when the signed volume is unavailable."""
    if not isinstance(md, dict):
        return 0.0
    try:
        v = abs(float(md.get("volume_signed_m3") or 0.0)) * (float(mmu) ** 3)
    except Exception:
        v = 0.0
    if v > 0.0:
        return v
    try:
        lo, hi = md["aabb"][0], md["aabb"][1]
        return abs((float(hi[0]) - float(lo[0])) * (float(hi[1]) - float(lo[1])) *
                   (float(hi[2]) - float(lo[2]))) * (float(mmu) ** 3)
    except Exception:
        return 0.0


def _repair_manifold_ok(md):
    return bool(isinstance(md, dict) and md.get("closed") and md.get("normals_ok"))


def _repair_move_precheck(name):
    """Blocking pre-check for translating a whole part (same convention as audit_snap_floaters)."""
    out = []
    ob = bpy.data.objects.get(str(name))
    if ob is None:
        return ["object does not exist: %s" % name]
    if ob.parent is not None:
        out.append("%s has a parent (a whole-part translation is overridden by the parent; clear the parent first)" % name)
    if ob.animation_data is not None:
        out.append("%s has animation data (keyframes override the translation)" % name)
    return out


def _repair_translate_plan(md, a, b, clearance_mm, mmu):
    """Two AABBs → move the **smaller part** along the axis that needs the least translation (separated AABBs ⇒ triangles cannot intersect).

    Returns (action, None) or (None, blocked_slim). Translation = what AABB separation needs + clearance_mm;
    whether it exceeds max_move_mm is decided by the caller (only required_mm is given here).
    """
    ma, mb = md.get(a), md.get(b)
    if not isinstance(ma, dict) or not isinstance(mb, dict):
        return None, {"pair": sorted([a, b]), "method": "translate",
                      "reason": "evaluated mesh missing (md), cannot plan a translation"}
    va, vb = _obj_volume_mm3(ma, mmu), _obj_volume_mm3(mb, mmu)
    small, big = (a, b) if va <= vb else (b, a)
    ms, mbg = md.get(small), md.get(big)
    try:
        mn_s = [float(x) for x in ms["aabb"][0]]
        mx_s = [float(x) for x in ms["aabb"][1]]
        mn_b = [float(x) for x in mbg["aabb"][0]]
        mx_b = [float(x) for x in mbg["aabb"][1]]
    except Exception as e:
        return None, {"pair": sorted([a, b]), "method": "translate",
                      "reason": "failed to read the AABB: %s: %s" % (type(e).__name__, str(e)[:120])}
    best = None
    for k in range(3):
        if mx_s[k] <= mn_b[k] + 1e-12 or mx_b[k] <= mn_s[k] + 1e-12:
            continue  # this axis is already separated, so it is not a viable separation axis
        d_pos = mx_b[k] - mn_s[k]           # move the small part in the + direction out of the large part AABB
        d_neg = mn_b[k] - mx_s[k]           # move the small part in the - direction out of the large part AABB
        delta = d_pos if abs(d_pos) <= abs(d_neg) else d_neg
        req_mm = abs(delta) * float(mmu)
        overlap_mm = (min(mx_s[k], mx_b[k]) - max(mn_s[k], mn_b[k])) * float(mmu)
        if best is None or req_mm < best["required_mm"] - 1e-12:
            best = {"axis": k, "delta": delta, "required_mm": req_mm, "overlap_mm": overlap_mm}
    if best is None:
        return None, {"pair": sorted([a, b]), "method": "translate",
                      "reason": "all three AABB axes are already separated (inconsistent with the clash/contained classification; the data is anomalous)"}
    axes = "xyz"
    delta_vec = [0.0, 0.0, 0.0]
    delta_vec[best["axis"]] = best["delta"]
    post_mn = [mn_s[k] + delta_vec[k] for k in range(3)]
    post_mx = [mx_s[k] + delta_vec[k] for k in range(3)]
    new_overlaps = []
    for nm, mdo in (md or {}).items():
        if nm in (a, b) or not isinstance(mdo, dict):
            continue
        try:
            on = [float(x) for x in mdo["aabb"][0]]
            ox = [float(x) for x in mdo["aabb"][1]]
        except Exception:
            continue
        if all(min(post_mx[k], ox[k]) - max(post_mn[k], on[k]) > 1e-9 for k in range(3)):
            new_overlaps.append(str(nm))
    need = float(best["required_mm"]) + float(clearance_mm)
    act = {"method": "translate", "target": small, "keep": big, "pair": sorted([a, b]),
           "axis": axes[best["axis"]],
           "delta_units": [_r(x, 8) for x in delta_vec],
           "delta_mm": [_r(x * float(mmu), 4) for x in delta_vec],
           "overlap_mm": _r(best["overlap_mm"], 4),
           "required_mm": _r(need, 4),
           "clearance_mm": _r(clearance_mm, 4),
           "aabb_separated_after": True,
           "new_aabb_overlaps": new_overlaps[:10],
           "risk": ("may create new AABB overlaps with %d parts: %s (the rescan reports them)"
                    % (len(new_overlaps), new_overlaps[:5]) if new_overlaps else "none"),
           "why": ("along the %s axis move the small part %s: translation %.3f mm (AABB overlap %.3f + clearance %.3f) → AABBs separated"
                   "(separated AABBs ⇒ triangles cannot intersect)"
                   % (axes[best["axis"]], small, need, best["overlap_mm"], float(clearance_mm)))}
    return act, None


def _repair_boolean_plan(md, a, b, mmu, cls):
    """Both parts closed manifolds → boolean-subtract the smaller from the larger (the cutter is copied at execution time, the original is untouched)."""
    ma, mb = md.get(a), md.get(b)
    if not isinstance(ma, dict) or not isinstance(mb, dict):
        return None, "evaluated mesh missing"
    if not (_repair_manifold_ok(ma) and _repair_manifold_ok(mb)):
        return None, "the two parts are not both closed manifolds with outward normals (the boolean difference is untrustworthy)"
    va, vb = _obj_volume_mm3(ma, mmu), _obj_volume_mm3(mb, mmu)
    target, cutter = (a, b) if va >= vb else (b, a)
    return {"method": "subtract", "target": target, "cutter": cutter, "pair": sorted([a, b]),
            "class": cls,
            "params": {"op": "DIFFERENCE", "solver": "EXACT", "cutter_copy": True},
            "risk": "the boolean changes the target topology (material slots/UVs may be affected); the cutter is a copy and the original is untouched; rollback relies on a file-level snapshot",
            "why": "both parts are closed manifolds; allow_boolean=true → subtract from %s the intruding body of %s (the cutter original is unchanged)"
                   % (target, cutter)}, None


def _repair_float_plan(scan, names, planned):
    """float → get a plan from audit_snap_floaters(dry_run=true); if none is available, blocked (no guessing)."""
    plan, blocked = [], []
    floaters = [f for f in (scan.get("floaters") or []) if isinstance(f, dict)]
    if not floaters:
        return plan, blocked
    names_all = [str(x) for x in (names or [])]
    sf, err = _call_api("audit", "snap_floaters",
                        {"objects": names_all, "dry_run": True})
    if err or sf is None:
        blocked.append({"kind": "float", "method": "snap",
                        "reason": "no floater repair plan available: %s (include audit in preload on the online path)" % str(err)[:200]})
        return plan, blocked
    if not sf.get("ok"):
        blocked.append({"kind": "float", "method": "snap",
                        "reason": "audit_snap_floaters ok=false: %s" % str(sf.get("error"))[:200]})
        return plan, blocked
    moves = [m for m in (sf.get("moves") or []) if isinstance(m, dict)]
    skipped = [s for s in (sf.get("skipped") or []) if isinstance(s, dict)]
    for mv in moves:
        mobjs = [str(x) for x in (mv.get("objects") or []) if x]
        if not mobjs:
            blocked.append({"kind": "float", "method": "snap", "rank": mv.get("rank"),
                            "reason": "the snap plan lacks objects"})
            continue
        if any(o in planned for o in mobjs):
            blocked.append({"kind": "float", "method": "snap", "rank": mv.get("rank"),
                            "objects": mobjs, "reason": "this object is already planned for this round (multiple floaters/conflicts; the next rescan round handles it)"})
            continue
        pre = []
        for o in mobjs:
            pre.extend(_repair_move_precheck(o))
        pre.extend(str(x) for x in (mv.get("why_not_applied") or []))
        if pre:
            blocked.append({"kind": "float", "method": "snap", "rank": mv.get("rank"),
                            "objects": mobjs, "reason": "; ".join(sorted(set(pre)))})
            continue
        planned.update(mobjs)
        plan.append({"method": "snap", "objects": mobjs, "pair": mobjs[:2],
                     "delta_units": [_r(x, 8) for x in (mv.get("delta_units") or [])],
                     "delta_mm": [_r(x, 4) for x in (mv.get("delta_mm") or [])],
                     "gap_before_mm": mv.get("gap_before_mm"),
                     "snap_method": mv.get("method"), "rank": mv.get("rank"),
                     "risk": "translating the whole floating part changes contact/nearest-neighbour relations with other parts (the rescan reports it); parented/animated ones are blocked",
                     "why": "snap the floater onto the nearest neighbour component (audit_snap_floaters plan; delta is in scene units, delta_mm in millimetres)"})
    for sk in skipped:
        blocked.append({"kind": "float", "method": "snap", "rank": sk.get("rank"),
                        "objects": [str(x) for x in (sk.get("objects") or [])][:10],
                        "reason": str(sk.get("why") or "the snap plan rejected this floater")[:220]})
    if not plan and not blocked:
        blocked.append({"kind": "float", "method": "snap",
                        "objects": [str(f.get("object")) for f in floaters if f.get("object")][:10],
                        "reason": "audit_snap_floaters gave no move plan (an island with no nearest neighbour / the floater is only part of an object) —— connect it by hand or add a manifest interface"})
    return plan, blocked


def _repair_plan_all(scan, names, md, mmu, max_move_mm, clearance_mm, allow_boolean,
                     policy="safe", policy_explicit=False):
    """scan → (plan, blocked). clash/contained go through translation (booleans are considered only when it is not enough / blocked by a parent), float goes through snap.

    policy (the low-risk automatic repair strategy):
      * safe (default): automatic actions may only translate/snap; a boolean is a topology change and needs explicit allow_boolean=true
        (an explicit human authorization, not an automatic choice); scale is not implemented/forbidden.
      * manual: plan only, never execute automatically; **does not plan booleans** (even with dry_run=false it returns a read-only plan).
      * aggressive: keeps the old behaviour (booleans are still controlled by allow_boolean); plans are tagged policy=aggressive.
    """
    plan, blocked = [], []
    planned = set()
    pol = str(policy or "safe").strip().lower()
    if pol not in ("safe", "manual", "aggressive"):
        pol = "safe"

    def _try_boolean(pair, cls):
        if pol == "manual":
            return False, "policy=manual: plans only, no boolean planning (for manual execution use policy=aggressive + allow_boolean=true)"
        if pol == "safe" and policy_explicit:
            return False, ("policy=safe: booleans are banned (topology change; the low-risk strategy only allows translate/snap) ——"
                           "needs explicit policy=aggressive + allow_boolean=true, or handle it by hand")
        if not allow_boolean:
            if pol == "aggressive":
                return False, "allow_boolean=false (even aggressive needs explicit allow_boolean=true to do a boolean)"
            return False, ("allow_boolean=false (policy=%s does not do booleans automatically; a boolean is a topology change"
                           " that needs explicit allow_boolean=true)" % pol)
        act, why = _repair_boolean_plan(md, pair[0], pair[1], mmu, cls)
        if act is None:
            return False, why
        if act["target"] in planned:
            return False, "target %s already has a repair action this round (multiple conflicts; the next rescan round handles it)" % act["target"]
        act["policy"] = pol
        planned.add(act["target"])
        plan.append(act)
        return True, None

    seen = set()
    for p in scan.get("offenders") or []:
        if not isinstance(p, dict):
            continue
        a, b = str(p.get("a") or ""), str(p.get("b") or "")
        cls = p.get("class")
        if not a or not b or cls not in ("clash", "contained"):
            continue
        key = _pair_key(a, b)
        if key in seen:
            continue
        seen.add(key)
        missing = [x for x in (a, b) if x not in md]
        if missing:
            blocked.append({"pair": [a, b], "class": cls, "method": "translate",
                            "reason": "evaluated mesh missing (%s is not in md) —— repair the mesh first" % missing})
            continue
        act, why = _repair_translate_plan(md, a, b, clearance_mm, mmu)
        if act is not None and act["required_mm"] <= float(max_move_mm) + 1e-9:
            target = act["target"]
            if target in planned:
                blocked.append({"pair": [a, b], "class": cls, "method": "translate",
                                "reason": "object %s already has a planned move this round (multiple conflicts; the next rescan round handles it)" % target})
                continue
            pre = _repair_move_precheck(target)
            if pre:
                okb, whyb = _try_boolean([a, b], cls)
                if okb:
                    continue
                blocked.append({"pair": [a, b], "class": cls, "method": "translate",
                                "reason": "; ".join(pre) + "; boolean unavailable: %s" % (whyb or "unknown")})
                continue
            act["class"] = cls
            planned.add(target)
            plan.append(act)
            continue
        if act is None:
            why_txt = str((why or {}).get("reason") if isinstance(why, dict) else (why or "cannot plan a translation"))
        else:
            why_txt = ("needs a %.3f mm translation > max_move_mm %.3f mm (raise max_move_mm / re-check the interface frames / allow booleans)"
                       % (act["required_mm"], float(max_move_mm)))
        okb, whyb = _try_boolean([a, b], cls)
        if okb:
            continue
        if pol == "manual":
            why_txt += "; policy=manual does not plan booleans (plan only)"
        elif pol == "safe" and policy_explicit:
            why_txt += "; policy=safe hard-bans booleans (needs explicit policy=aggressive + allow_boolean=true, or manual handling)"
        elif not allow_boolean:
            why_txt += "; policy=%s does not do booleans automatically (needs explicit allow_boolean=true)" % pol
        else:
            why_txt += "; boolean unavailable: %s" % (whyb or "unknown")
        blocked.append({"pair": [a, b], "class": cls, "method": "translate",
                        "required_mm": (act or {}).get("required_mm"), "reason": why_txt})
    fplan, fblocked = _repair_float_plan(scan, names, planned)
    plan.extend(fplan)
    blocked.extend(fblocked)
    for u in scan.get("floating_unresolved") or []:
        if isinstance(u, dict):
            blocked.append({"kind": "float_unresolved",
                            "reason": str(u.get("why") or u.get("reason") or "floater unresolved")[:240]})
    for nm in (scan.get("coverage") or {}).get("unresolved_objects") or []:
        blocked.append({"kind": "unresolved_object", "object": str(nm),
                        "reason": "mesh not closed / inward normals / missing evaluated mesh → inside-outside and depth are untrustworthy, so automatic repair refuses (run fix_repair / recalc normals first)"})
    # Unified receipt fields: plan[].risk (mandatory per action) + blocked[].blocked_reason (= alias of reason, read directly by weaker models)
    for a in plan:
        if isinstance(a, dict):
            a.setdefault("risk", "none")
            a.setdefault("policy", pol)
    for b in blocked:
        if isinstance(b, dict):
            b.setdefault("blocked_reason", b.get("reason"))
    return plan, blocked


def _repair_expected(brief, plan, blocked):
    """dry_run predicted numbers (clearly labelled as predictions only; the rescan after execution is authoritative)."""
    counts = dict((brief or {}).get("counts") or {})
    pred = {"clash": int(counts.get("clash") or 0),
            "contained": int(counts.get("contained") or 0),
            "float": int(counts.get("float") or 0)}
    n_translate = n_subtract = n_snap = 0
    for a in plan or []:
        m = a.get("method") if isinstance(a, dict) else None
        cls = (a or {}).get("class") if isinstance(a, dict) else None
        if m == "translate":
            n_translate += 1
            if cls in pred:
                pred[cls] = max(0, pred[cls] - 1)
        elif m == "subtract":
            n_subtract += 1
            if cls in pred:
                pred[cls] = max(0, pred[cls] - 1)
        elif m == "snap":
            n_snap += 1
            pred["float"] = max(0, pred["float"] - 1)
    return {"actions": len(plan or []), "translate_pairs": n_translate,
            "subtract_pairs": n_subtract, "snap_floaters": n_snap,
            "blocked": len(blocked or []), "predicted_bad_counts": pred,
            "note": "the prediction only deducts one pair per action and ignores new conflicts/sampling error; the dry_run=false rescan is authoritative"}


def _repair_rescan(names, m, spec):
    try:
        raw = asm_scan(scope=None, objects=list(names), manifest=m, spec=spec, summary_only=False)
        return json.loads(raw) if isinstance(raw, str) else raw
    except Exception as e:
        import traceback
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:240]),
                "traceback": traceback.format_exc()[-500:]}


def _apply_repair_action(act, objs, allow_boolean):
    """Execute a single repair action (translate/snap translation; subtract boolean difference). Returns a per-action record and never raises."""
    if not isinstance(act, dict):
        return {"ok": False, "error": "the action is not a dict", "action": str(act)[:160]}
    method = str(act.get("method") or "")
    if method in ("translate", "snap"):
        targets = [str(act.get("target"))] if method == "translate" \
            else [str(x) for x in (act.get("objects") or []) if x]
        dv = act.get("delta_units") or []
        if len(dv) != 3 or any(_num(x) is None for x in dv):
            return {"ok": False, "method": method, "error": "delta_units is not 3 numbers",
                    "action": act}
        vec = Vector((float(dv[0]), float(dv[1]), float(dv[2])))
        moved = []
        for n in targets:
            ob = objs.get(n) or bpy.data.objects.get(n)
            if ob is None:
                return {"ok": False, "method": method, "error": "object does not exist: %s" % n, "action": act}
            try:
                ob.matrix_world.translation = ob.matrix_world.translation + vec
            except Exception as e:
                return {"ok": False, "method": method, "target": n,
                        "error": "%s: %s" % (type(e).__name__, str(e)[:160]), "action": act}
            moved.append(n)
        return {"ok": True, "method": method, "objects": moved, "pair": act.get("pair"),
                "target": act.get("target"), "delta_units": [_r(x, 8) for x in dv],
                "delta_mm": act.get("delta_mm")}
    if method == "subtract":
        if not allow_boolean:
            return {"ok": False, "method": "subtract", "pair": act.get("pair"),
                    "error": "allow_boolean=false, boolean refused (a topology change needs explicit permission)"}
        geo = _api("geo")
        bfn = None
        try:
            bfn = geo.get("boolean") if geo is not None else None
        except Exception:
            bfn = None
        if not callable(bfn):
            return {"ok": False, "method": "subtract", "pair": act.get("pair"),
                    "error": "K.dsh_geo_api.boolean unavailable (include geo in preload on the online path)"}
        t = bpy.data.objects.get(str(act.get("target") or ""))
        c = bpy.data.objects.get(str(act.get("cutter") or ""))
        if t is None or c is None:
            return {"ok": False, "method": "subtract", "pair": act.get("pair"),
                    "error": "target/cutter objects do not exist (target=%r cutter=%r)"
                             % (act.get("target"), act.get("cutter"))}
        dup, dup_mesh = None, None
        try:
            dup = c.copy()
            if c.data is not None:
                dup.data = c.data.copy()
                dup_mesh = dup.data
            dup.name = "%s__dsh_repair_cut" % str(c.name)[:48]
            coll = (t.users_collection[0] if t.users_collection else bpy.context.scene.collection)
            coll.objects.link(dup)
        except Exception as e:
            if dup is not None:
                try:
                    bpy.data.objects.remove(dup, do_unlink=True)
                except Exception:
                    pass
            if dup_mesh is not None and dup_mesh.users == 0:
                try:
                    bpy.data.meshes.remove(dup_mesh)
                except Exception:
                    pass
            return {"ok": False, "method": "subtract", "pair": act.get("pair"),
                    "error": "failed to copy the cutter: %s: %s" % (type(e).__name__, str(e)[:160])}
        try:
            bfn(t, dup, "DIFFERENCE")
        except Exception as e:
            try:
                if bpy.data.objects.get(dup.name) is not None:
                    bpy.data.objects.remove(dup, do_unlink=True)
            except Exception:
                pass
            if dup_mesh is not None and dup_mesh.users == 0:
                try:
                    bpy.data.meshes.remove(dup_mesh)
                except Exception:
                    pass
            return {"ok": False, "method": "subtract", "target": str(t.name), "cutter": str(c.name),
                    "error": "%s: %s" % (type(e).__name__, str(e)[:240]),
                    "hint": "the boolean degeneracy guard stopped it (self-intersecting/non-manifold body) → run fix_repair first or switch to a translation"}
        try:
            if bpy.data.objects.get(dup.name) is not None:
                bpy.data.objects.remove(dup, do_unlink=True)
        except Exception:
            pass
        if dup_mesh is not None and dup_mesh.users == 0:
            try:
                bpy.data.meshes.remove(dup_mesh)
            except Exception:
                pass
        return {"ok": True, "method": "subtract", "target": str(t.name),
                "cutter": str(c.name), "pair": act.get("pair")}
    return {"ok": False, "method": method or "?", "error": "unknown repair method (only translate/snap/subtract are supported)"}


def _repair_params(dry_run, max_move_mm, allow_boolean, snapshot, max_rounds, clearance_mm, policy):
    """Validate the boolean/numeric arguments and policy; returns (cfg, err)."""
    dry_run, ferr = _repair_flag(dry_run, "dry_run")
    if ferr:
        return None, ferr
    allow_boolean, ferr = _repair_flag(allow_boolean, "allow_boolean")
    if ferr:
        return None, ferr
    snapshot, ferr = _repair_flag(snapshot, "snapshot")
    if ferr:
        return None, ferr
    pol, pol_explicit, perr = _repair_policy(policy)
    if perr:
        return None, perr
    mv, cm = _num(max_move_mm), _num(clearance_mm)
    if mv is None or mv < 0.0:
        return None, "max_move_mm must be a finite number ≥0, got %r" % (max_move_mm,)
    if cm is None or cm < 0.0:
        return None, "clearance_mm must be a finite number ≥0, got %r" % (clearance_mm,)
    try:
        rounds_f = float(max_rounds)
    except Exception:
        rounds_f = None
    if isinstance(max_rounds, bool) or rounds_f is None or not math.isfinite(rounds_f) \
            or abs(rounds_f - round(rounds_f)) > 1e-9:
        return None, "max_rounds must be an integer (1..20), got %r" % (max_rounds,)
    rounds_cap = int(round(rounds_f))
    if rounds_cap < 1 or rounds_cap > 20:
        return None, "max_rounds must be within 1..20, got %r" % (max_rounds,)
    return {"dry_run": bool(dry_run), "allow_boolean": bool(allow_boolean), "snapshot": bool(snapshot),
            "pol": pol, "pol_explicit": bool(pol_explicit), "mv": mv, "cm": cm,
            "rounds_cap": rounds_cap}, None


def _repair_context(manifest, scope, objects, spec):
    """manifest validation + object selection + first asm_scan + mesh map/baseline summary; returns (ctx, err)."""
    m = None
    if manifest is not None:
        m, merr = _load_manifest(manifest)
        if merr:
            return None, merr
        mval = _manifest_validate(m, check_files=False, check_md5=False)
        if not mval["ok"]:
            return None, ("manifest structural validation failed (no repair planning on a bad manifest)",
                          {"errors": mval["errors"][:10], "warnings": mval["warnings"][:10]})
    info = _pick_objects(scope, objects, include_hidden=False)
    if info.get("error"):
        return None, (info["error"], {"objects": info.get("names"), "missing": info.get("missing"),
                                      "hint": "empty output/bad arguments must fail; verify the object/collection names (or pass a manifest)"})
    names = list(info["names"])
    try:
        raw = asm_scan(scope=None, objects=names, manifest=m, spec=spec, summary_only=False)
        scan = json.loads(raw) if isinstance(raw, str) else raw
    except Exception as e:
        return None, "first asm_scan raised: %s: %s" % (type(e).__name__, str(e)[:240])
    if not isinstance(scan, dict) or not scan.get("ok"):
        return None, ("the first asm_scan failed; refusing to plan repairs without a scan result",
                      {"scan": _trim(scan) if isinstance(scan, dict) else None})
    mmu = float(_KIT.units())
    md, md_errors = _mesh_map(info["objects"])
    before = _repair_brief(scan)
    before_bad = _repair_bad_total(before)
    return {"manifest": m, "objects": info["objects"], "names": names, "scan": scan,
            "mmu": mmu, "md": md, "md_errors": md_errors,
            "before": before, "before_bad": before_bad}, None


def _repair_counts_line(before):
    """One line of pre-scan counts (used in verdict_line)."""
    brief_counts = before.get("counts") or {}
    return ("clash=%d contained=%d float=%d unresolved=%d"
            % (int(brief_counts.get("clash") or 0), int(brief_counts.get("contained") or 0),
               int(brief_counts.get("float") or 0), int(brief_counts.get("unresolved") or 0)))


def _repair_params_out(cfg):
    """The params field in the outward receipt (keeps the existing key order/values)."""
    return {"max_move_mm": _r(cfg["mv"], 4), "clearance_mm": _r(cfg["cm"], 4),
            "allow_boolean": cfg["allow_boolean"], "max_rounds": cfg["rounds_cap"],
            "snapshot": cfg["snapshot"], "dry_run": cfg["dry_run"], "policy": cfg["pol"],
            "policy_explicit": cfg["pol_explicit"]}


def _repair_dry_payload(ctx, params, plan, blocked, expected, counts_line):
    """read-only receipt for dry_run=true."""
    before = ctx["before"]
    before_bad = ctx["before_bad"]
    names = ctx["names"]
    md_errors = ctx["md_errors"]
    if plan:
        verdict = "planned"
    elif before_bad:
        verdict = "blocked"
    else:
        verdict = before.get("verdict") or "pass"
    if verdict == "pass" and before.get("verdict") == "degraded":
        verdict = "degraded"
    if plan and blocked:
        hint = "dry_run only plans (scene unchanged): %d actions executable, %d blocked —— handle them per blocked.reason and rerun; once confirmed pass dry_run=false (it snapshots first)"
    elif plan:
        hint = "dry_run only plans (scene unchanged): once confirmed pass dry_run=false to execute (file-level snapshot first, then apply, then rescan)"
    elif before_bad:
        hint = "no automatically fixable actions: check blocked.reason (raise max_move_mm / allow_boolean / clear the parent / preload audit / repair the mesh first)"
    elif before.get("verdict") == "degraded":
        hint = ("no clash/contained/float to auto-fix, but the scan is degraded (unresolved/truncated/not fully judged) —— "
                "repair the mesh/normals or raise the budget and rescan; never read it as no problem")
    else:
        hint = "the scan has no clash/contained/float; nothing to repair"
    verdict_line = ("assembly repair (dry_run, read-only): scanned %d parts %s → planned %d actions / blocked %d → %s"
                    % (len(names), counts_line, len(plan), len(blocked), verdict))
    return {"ok": True, "verdict": verdict, "dry_run": True, "readonly": True,
            "stage": "planned", "method": "asm_repair", "aliases": ["fix_clash"],
            "params": params, "objects": len(names), "object_names": names,
            "before": _repair_brief_out(before),
            "plan": plan[:60], "blocked": _dedupe_blocked(blocked)[:40],
            "expected": expected,
            "verdict_line": verdict_line, "hint": hint,
            "honest_limits": list(_REPAIR_HONEST_LIMITS),
            "md_errors": md_errors, "contract_repairs": _plan_repair_hints(plan)}


def _repair_manual_payload(ctx, params, plan, blocked, expected):
    """policy=manual: plan only, never execute automatically."""
    before = ctx["before"]
    md_errors = ctx["md_errors"]
    return {"ok": False, "verdict": "planned", "dry_run": True, "readonly": True,
            "stage": "manual_policy", "method": "asm_repair", "aliases": ["fix_clash"],
            "params": params, "objects": len(ctx["names"]),
            "before": _repair_brief_out(before),
            "plan": plan[:60], "blocked": _dedupe_blocked(blocked)[:40],
            "expected": expected,
            "error": "policy=manual only plans and never executes automatically (scene unchanged); once confirmed switch to policy=safe/aggressive or execute the plan by hand",
            "verdict_line": "assembly repair (manual, read-only): planned %d actions / blocked %d → scene unchanged"
                            % (len(plan), len(blocked)),
            "hint": "policy=manual does not execute automatically: use policy=safe for translate/snap; policy=aggressive + allow_boolean=true for booleans",
            "honest_limits": list(_REPAIR_HONEST_LIMITS), "md_errors": md_errors}


def _repair_no_plan_payload(ctx, params, blocked):
    """Execution branch with an empty plan: either there was nothing to begin with, or there is no action that can be executed automatically."""
    before = ctx["before"]
    before_bad = ctx["before_bad"]
    names = ctx["names"]
    md_errors = ctx["md_errors"]
    if before_bad == 0:
        return {"ok": True, "verdict": before.get("verdict") or "pass", "dry_run": False,
                "analyzed": True, "stage": "nothing_to_do", "params": params,
                "objects": len(names), "before": _repair_brief_out(before),
                "after": _repair_brief_out(before), "residual": _repair_residual(before),
                "repaired": False, "rounds": 0, "plan": [], "applied": [],
                "blocked": _dedupe_blocked(blocked)[:40], "snapshot": None,
                "verdict_line": "assembly repair: the scan has no clash/contained/float; nothing to repair",
                "hint": "nothing to repair (if unresolved/degraded remains, repair the mesh/normals first and look again)",
                "honest_limits": list(_REPAIR_HONEST_LIMITS), "md_errors": md_errors}
    return {"ok": False, "verdict": "blocked", "dry_run": False, "analyzed": True,
            "stage": "no_executable_action", "params": params,
            "objects": len(names), "before": _repair_brief_out(before),
            "after": _repair_brief_out(before), "residual": _repair_residual(before),
            "repaired": False, "rounds": 0, "plan": [], "applied": [],
            "blocked": _dedupe_blocked(blocked)[:40], "snapshot": None,
            "error": "found %d clash/contained/float issues but no action can be executed automatically" % before_bad,
            "verdict_line": "assembly repair: 0 executable actions → blocked (scene unchanged)",
            "hint": "see blocked.reason: raise max_move_mm / allow_boolean / clear the parent animation / preload audit / repair the mesh first",
            "honest_limits": list(_REPAIR_HONEST_LIMITS), "md_errors": md_errors}


def _repair_snapshot(snapshot):
    """File-level snapshot before execution; returns (snap, snap_ok, err). A failed snapshot must refuse execution."""
    if not snapshot:
        return ({"ok": True, "skipped": True,
                 "note": "snapshot=false: the caller owns the rollback (a boolean topology change cannot be rolled back at object level)"}, False, None)
    if _api("txn") is None:
        snap = {"ok": False, "skipped": True,
                "note": "K.dsh_txn_api unavailable ⇒ no file-level snapshot was taken (boolean actions will be refused; a failed translation cannot be rolled back automatically)"}
    else:
        rec, serr = _call_api("txn", "snapshot",
                              {"label": "asm_repair-%s" % time.strftime("%Y%m%d_%H%M%S"),
                               "note": "snapshot before asm_repair(dry_run=false)"})
        if serr:
            return None, False, "snapshot failed; refusing to repair a scene with no rollback point: %s" % serr
        snap = rec.get("snapshot") if isinstance(rec, dict) else rec
    snap_ok = bool(isinstance(snap, dict) and not snap.get("skipped")
                   and snap.get("ok") is not False
                   and bool(snap.get("label") or snap.get("path") or snap.get("ok") is True))
    return snap, snap_ok, None


def _repair_guard_subtract(plan, blocked, snap_ok):
    """A boolean changes topology but no usable snapshot exists ⇒ downgrade subtract actions to blocked (do not abandon the remaining actions entirely)."""
    if snap_ok or not any(a.get("method") == "subtract" for a in plan):
        return plan, blocked
    keep = []
    exec_blocked = list(blocked)
    for a in plan:
        if a.get("method") == "subtract":
            exec_blocked.append({"pair": a.get("pair"), "class": a.get("class"),
                                 "method": "subtract",
                                 "reason": "the boolean changes topology but no usable file-level snapshot (txn) exists → refusing to execute; make K.dsh_txn_api available and snapshot=true first"})
        else:
            keep.append(a)
    return keep, exec_blocked


def _repair_blocked_all_payload(ctx, params, blocked, snap):
    """The safety gate stopped every action: blocked (scene unchanged)."""
    before = ctx["before"]
    names = ctx["names"]
    md_errors = ctx["md_errors"]
    return {"ok": False, "verdict": "blocked", "dry_run": False, "analyzed": True,
            "stage": "no_executable_action", "params": params,
            "objects": len(names), "before": _repair_brief_out(before),
            "after": _repair_brief_out(before), "residual": _repair_residual(before),
            "repaired": False, "rounds": 0, "plan": [], "applied": [],
            "blocked": _dedupe_blocked(blocked)[:40], "snapshot": snap,
            "error": "every executable action was stopped by the safety gate (booleans need a file-level snapshot)",
            "verdict_line": "assembly repair: 0 executable actions → blocked (scene unchanged)",
            "hint": "preload txn or set snapshot=true and rerun; or handle blocked.reason first",
            "honest_limits": list(_REPAIR_HONEST_LIMITS), "md_errors": md_errors}


def _repair_exec_loop(scan, plan, objs, names, m, spec, rounds_cap, bool_exec,
                      mmu, mv, cm, allow_boolean, pol, pol_explicit, blocked, md_errors):
    """Round by round: apply → update → rescan → replan; returns (cur_scan, applied, blocked, rounds, md_errors)."""
    applied = []
    exec_blocked = list(blocked)
    cur_scan, cur_plan, rounds = scan, plan, 0
    for rnd in range(1, rounds_cap + 1):
        acts = [a for a in cur_plan if isinstance(a, dict) and a.get("method") in _REPAIR_METHODS]
        if not acts:
            break
        rounds = rnd
        n_ok = 0
        for act in acts:
            rec = _apply_repair_action(act, objs, bool_exec)
            rec["round"] = rnd
            if rec.get("ok"):
                applied.append(rec)
                n_ok += 1
            else:
                exec_blocked.append(rec)
        if n_ok == 0:
            break  # nothing moved ⇒ the rescan will not change, do not spin
        try:
            bpy.context.view_layer.update()
        except Exception:
            pass
        rescan = _repair_rescan(names, m, spec)
        cur_scan = rescan
        brief = _repair_brief(rescan)
        if not brief.get("ok"):
            exec_blocked.append({"kind": "rescan", "round": rnd,
                                 "reason": "rescan failed: %s" % str(brief.get("error"))[:240]})
            break
        if _repair_bad_total(brief) == 0:
            break
        if rnd >= rounds_cap:
            break
        md, md_errors = _mesh_map([objs[nm] for nm in names if nm in objs])
        cur_plan, more_blocked = _repair_plan_all(rescan, names, md, mmu, mv, cm, bool(allow_boolean),
                                                 pol, pol_explicit)
        exec_blocked.extend(more_blocked)
    return cur_scan, applied, exec_blocked, rounds, md_errors


def _repair_final_payload(ctx, params, plan, applied, blocked, cur_scan, rounds, snap, counts_line, md_errors):
    """Final receipt after the rescan (verdict three-state + residual counts + repair advice)."""
    before = ctx["before"]
    before_bad = ctx["before_bad"]
    names = ctx["names"]
    scan = ctx["scan"]
    after = _repair_brief(cur_scan if isinstance(cur_scan, dict) else scan)
    final_bad = _repair_bad_total(after)
    residual = _repair_residual(after)
    rescan_broke = any(isinstance(x, dict) and x.get("kind") == "rescan" for x in blocked)
    ok_final = bool(final_bad == 0 and after.get("ok") and not rescan_broke)
    if final_bad > 0:
        verdict = "fail"
    elif not after.get("ok"):
        verdict = "degraded"
    else:
        verdict = after.get("verdict") or "degraded"
    if ok_final:
        hint = "repair complete: clash/contained/float are at zero (rescan verdict=%s); re-run asm_gate/asm_scan to double-check" % verdict
    else:
        hint = ("repair incomplete: residual clash=%d contained=%d float=%d; see blocked and after.offenders, "
                "adjust max_move_mm / allow_boolean / clear the parent animation / repair the mesh first"
                % (residual["clash"], residual["contained"], residual["float"]))
    verdict_line = ("assembly repair (%d rounds executed): scanned %d parts %s → applied %d actions, blocked %d → rescan residual "
                    "clash=%d contained=%d float=%d unresolved=%d → %s"
                    % (rounds, len(names), counts_line, len(applied),
                       len(_dedupe_blocked(blocked)), residual["clash"], residual["contained"],
                       residual["float"], residual["unresolved"], verdict))
    return {"ok": bool(ok_final), "verdict": verdict, "dry_run": False, "analyzed": True,
            "stage": "rechecked", "method": "asm_repair", "aliases": ["fix_clash"],
            "params": params, "objects": len(names), "object_names": names,
            "before": _repair_brief_out(before), "after": _repair_brief_out(after),
            "residual": residual,
            "repaired": bool(before_bad > 0 and final_bad < before_bad),
            "rounds": rounds, "plan": plan[:60],
            "applied": applied[:60], "blocked": _dedupe_blocked(blocked)[:40],
            "snapshot": snap, "verdict_line": verdict_line, "hint": hint,
            "honest_limits": list(_REPAIR_HONEST_LIMITS), "md_errors": md_errors}


def asm_repair(manifest=None, scope=None, objects=None, spec=None, dry_run=True,
               max_move_mm=50.0, allow_boolean=False, snapshot=True,
               max_rounds=3, clearance_mm=0.5, policy=None):
    """Assembly repair (plans only by default): asm_scan → plan → (dry_run=false) snapshot → apply → rescan, at most max_rounds rounds.

    Planning conventions:
      * clash / contained → pick the smaller part and translate it along the axis with the least AABB overlap (by the amount AABB separation needs + clearance_mm),
        beyond max_move_mm ⇒ blocked; a target with a parent/animation ⇒ blocked (a whole-part translation would be overridden).
      * float → when K.dsh_audit_api exists, call audit_snap_floaters(dry_run=true) for a plan, otherwise blocked.
      * allow_boolean=true and both parts closed manifolds (and translation infeasible / blocked by a parent) → boolean-subtract the smaller from the larger
        (the cutter is a copy and the original is untouched); a boolean is refused when no usable file-level snapshot exists.
    Policy (the default equals safe; only an explicit value creates a hard constraint):
      * default None → safe: automatic actions may only translate/snap; a boolean is a topology change, and the old compatible path is kept
        (done only with allow_boolean=true = an explicit human authorization).
      * policy="safe" (explicit): **hard-bans** booleans/scale; only translate/snap are allowed.
      * policy="manual": plan only, never execute automatically (even dry_run=false returns a read-only plan); does not plan booleans.
      * policy="aggressive": keeps the old allow_boolean behaviour; plans are tagged policy=aggressive.
    Execution conventions: dry_run=false takes a file-level snapshot (K.dsh_txn_api) first, then per action apply → view_layer.update →
    rerun asm_scan; if residuals remain, replan from the new scan, at most max_rounds rounds (stop when nothing moves, do not spin).
    Aliases: fix_clash (the executor, dry_run defaults to true); for a pure planner use fix_interference (plan_only=true).
    """
    t0 = time.perf_counter()
    cfg, perr = _repair_params(dry_run, max_move_mm, allow_boolean, snapshot, max_rounds,
                               clearance_mm, policy)
    if perr:
        return _err(perr)
    dry_run, allow_boolean, snapshot = cfg["dry_run"], cfg["allow_boolean"], cfg["snapshot"]
    ctx, cerr = _repair_context(manifest, scope, objects, spec)
    if cerr:
        if isinstance(cerr, tuple):
            return _err(cerr[0], **cerr[1])
        return _err(cerr)
    names, m = ctx["names"], ctx["manifest"]
    scan, mmu, md = ctx["scan"], ctx["mmu"], ctx["md"]
    before, before_bad, md_errors = ctx["before"], ctx["before_bad"], ctx["md_errors"]
    params = _repair_params_out(cfg)
    plan, blocked = _repair_plan_all(scan, names, md, mmu, cfg["mv"], cfg["cm"], allow_boolean,
                                     cfg["pol"], cfg["pol_explicit"])
    expected = _repair_expected(before, plan, blocked)
    counts_line = _repair_counts_line(before)
    if dry_run:
        return _j(_receipt(_repair_dry_payload(ctx, params, plan, blocked, expected, counts_line), t0))
    if cfg["pol"] == "manual":
        return _j(_receipt(_repair_manual_payload(ctx, params, plan, blocked, expected), t0))
    # ---------------- execution ----------------
    bool_exec = bool(allow_boolean) and cfg["pol"] != "manual"
    if not plan:
        return _j(_receipt(_repair_no_plan_payload(ctx, params, blocked), t0))
    snap, snap_ok, serr = _repair_snapshot(snapshot)
    if serr:
        return _err(serr)
    plan, blocked = _repair_guard_subtract(plan, blocked, snap_ok)
    if not plan:
        return _j(_receipt(_repair_blocked_all_payload(ctx, params, blocked, snap), t0))
    objs = {str(o.name): o for o in ctx["objects"]}
    cur_scan, applied, blocked, rounds, md_errors = _repair_exec_loop(
        scan, plan, objs, names, m, spec, cfg["rounds_cap"], bool_exec,
        mmu, cfg["mv"], cfg["cm"], allow_boolean, cfg["pol"], cfg["pol_explicit"], blocked, md_errors)
    return _j(_receipt(_repair_final_payload(ctx, params, plan, applied, blocked, cur_scan, rounds,
                                             snap, counts_line, md_errors), t0))


def _plan_repair_hints(plan):
    """Next steps attached to the dry_run receipt (weaker models can just follow them)."""
    hints = []
    for a in plan or []:
        if not isinstance(a, dict):
            continue
        m = a.get("method")
        if m == "subtract":
            hints.append({"op": "fix_clash",
                          "args": {"a": (a.get("pair") or [None, None])[0],
                                   "b": (a.get("pair") or [None, None])[1],
                                   "allow_boolean": True, "policy": "aggressive", "dry_run": False},
                          "why": a.get("why")})
        elif m == "translate":
            hints.append({"op": "fix_clash",
                          "args": {"a": (a.get("pair") or [None, None])[0],
                                   "b": (a.get("pair") or [None, None])[1],
                                   "policy": "safe", "dry_run": False},
                          "why": a.get("why")})
        elif m == "snap":
            hints.append({"op": "fix_clash",
                          "args": {"objects": a.get("objects"), "policy": "safe", "dry_run": False},
                          "why": a.get("why")})
    return hints[:10]


def fix_interference(a=None, b=None, plan_only=True, manifest=None, scope=None, objects=None,
                     spec=None, max_move_mm=50.0, allow_boolean=False, clearance_mm=0.5,
                     max_rounds=3, policy=None):
    """Assembly interference **planner** (read-only, never changes the scene): the planning view of asm_repair(dry_run=true).

    if a/b are given, only plans involving those two parts (or one of them) are shown; otherwise the whole scope is planned.
    policy: safe (default, automatically uses translate/snap only) / manual (plan only) / aggressive (booleans are controlled by allow_boolean).
    To execute use fix_clash (= asm_repair, dry_run=false); this op rejects plan_only=false.
    """
    t0 = time.perf_counter()
    po, ferr = _repair_flag(plan_only, "plan_only")
    if ferr:
        return _err(ferr)
    if not po:
        return _err("fix_interference is a pure planner (plan_only can only be true; it never changes the scene);"
                    "to execute use fix_clash / asm_repair (dry_run=false)")
    scan_objects = objects
    want = set()
    for x in (a, b):
        if x is not None and str(x).strip():
            want.add(str(x))
    if len(want) >= 2 and objects is None and scope is None:
        scan_objects = sorted(want)   # only look at this pair: lowest scan cost
    res = json.loads(asm_repair(manifest=manifest, scope=scope, objects=scan_objects, spec=spec,
                                dry_run=True, max_move_mm=max_move_mm,
                                allow_boolean=allow_boolean, snapshot=False,
                                max_rounds=max_rounds, clearance_mm=clearance_mm, policy=policy))
    if not isinstance(res, dict):
        return _err("asm_repair returned an anomalous receipt (not a dict)")
    if not res.get("ok"):
        return _j(res)
    if want:
        res["plan"] = [r for r in (res.get("plan") or []) if want & _repair_touched(r)]
        res["blocked"] = [r for r in (res.get("blocked") or []) if want & _repair_touched(r)]
        res["filtered_to"] = sorted(want)
        res["expected"] = _repair_expected(res.get("before") or {}, res.get("plan") or [],
                                           res.get("blocked") or [])
        if not res["plan"] and res.get("verdict") == "planned":
            res["verdict"] = "blocked"
    res["planner"] = "fix_interference"
    res["readonly"] = True
    res["executor"] = "fix_clash(asm_repair, dry_run=false)"
    return _j(_receipt(res, t0))
