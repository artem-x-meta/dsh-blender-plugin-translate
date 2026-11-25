# -*- coding: utf-8 -*-
"""Split from contract.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403


# ---------------------------------------------------------------- geometry fingerprint / verdict drift (v0.9.0)

def _r4(x):
    try:
        return round(float(x), 4)
    except Exception:
        return x


def _fingerprint(objects=None, scope=None, include_hidden=False):
    """Geometry fingerprint (lightweight): object count / triangle count / vertex count / world bbox + 12-char digest.

    Why not a full-mesh md5: on a large scene one pass takes seconds; while the three things that
    matter ("edited / moved / swapped a part") are already caught by face count + vertex count + bbox
    (vertex-level micro-drift is left to audit_drift's Chamfer distance).
    Evidence and verdicts both bind this digest — once the source changes, old conclusions should
    expire (Procedura state.ts's staleness discipline).
    """
    import hashlib
    if objects:
        want = [str(x) for x in (objects if isinstance(objects, (list, tuple)) else [objects])]
        objs = [bpy.data.objects.get(n) for n in want]
        objs = [o for o in objs if o is not None and o.type == "MESH"]
    else:
        objs = _scope_objects(scope, include_hidden)
    lines, mn, mx, tris, verts = [], None, None, 0, 0
    for ob in sorted(objs, key=lambda o: o.name):
        t, v = len(ob.data.polygons), len(ob.data.vertices)
        tris += t
        verts += v
        (lo, hi) = _bbox(ob)
        lo, hi = [_r4(x) for x in lo], [_r4(x) for x in hi]
        if mn is None:
            mn, mx = list(lo), list(hi)
        else:
            for k in range(3):
                mn[k] = min(mn[k], lo[k])
                mx[k] = max(mx[k], hi[k])
        lines.append("%s:%d:%d:%.4f,%.4f,%.4f:%.4f,%.4f,%.4f" % (ob.name, t, v, lo[0], lo[1], lo[2], hi[0], hi[1], hi[2]))
    return {"objects": len(objs), "tris": int(tris), "verts": int(verts),
            "bbox": {"min": mn, "max": mx},
            "digest": hashlib.md5("|".join(sorted(lines)).encode("utf-8")).hexdigest()[:12] if lines else "empty",
            "scope": scope, "object_names": [o.name for o in objs][:200],
            "rule": "face count/vertex count/world bbox changed → digest changes → evidence and verdicts bound to it count as stale"}


def c_fingerprint(objects=None, scope=None, include_hidden=False):
    """Take the current fingerprint (record one before a change, then one after, to decide "whether it was touched")."""
    fp = _fingerprint(objects, scope, include_hidden)
    return _j({"ok": True, "fingerprint": fp,
               "usage": "fingerprint before the change → fingerprint after: a different digest means 'the source changed'; "
                        "or let the ledger compare for you (both evidence and verify bind the fingerprint)"})


def _conn_objects(conn):
    return _component_objects(conn["a"]) + _component_objects(conn["b"])


def _union_bbox(objs):
    mn = mx = None
    for ob in objs:
        (lo, hi) = _bbox(ob)
        if mn is None:
            mn, mx = list(lo), list(hi)
        else:
            for k in range(3):
                mn[k] = min(mn[k], lo[k])
                mx[k] = max(mx[k], hi[k])
    return mn, mx


def _snapshot_of(objs):
    mn, mx = _union_bbox(objs)
    if mn is None:
        return None
    size = [float(mx[k] - mn[k]) for k in range(3)]
    import math as _m
    return {"min": [_r4(x) for x in mn], "max": [_r4(x) for x in mx],
            "size": [_r4(x) for x in size], "diagonal": _r4(_m.sqrt(sum(s * s for s in size))),
            "t": _now()}


def _drift_of(conn):
    """Compare against the bbox snapshot recorded at verify time → (drifted, detail). Every skip case states its reason; nothing silent."""
    vd = conn.get("verdict") or {}
    snap = vd.get("bbox_snapshot")
    if not snap:
        return False, {"why": "the old verdict has no bbox snapshot → no demotion (rerun verify to establish one)"}
    objs = _conn_objects(conn)
    if not objs:
        return False, {"why": "the objects involved in the connection no longer exist", "objects": 0}
    if any(getattr(ob, "animation_data", None) is not None for ob in objs):
        return False, {"why": "animation data present: position is animation-driven, drift demotion skipped"}
    cur = _snapshot_of(objs)
    if cur is None:
        return False, {"why": "objects have no geometry (0 faces)"}
    diag = float(snap.get("diagonal") or 0) or 1.0
    c0 = [(snap["min"][k] + snap["max"][k]) / 2.0 for k in range(3)]
    c1 = [(cur["min"][k] + cur["max"][k]) / 2.0 for k in range(3)]
    moved = sum((c1[k] - c0[k]) ** 2 for k in range(3)) ** 0.5
    dsz = [abs(float(cur["size"][k]) - float(snap["size"][k])) for k in range(3)]
    size_bad = [k for k in range(3) if dsz[k] > DRIFT_SIZE_FRACTION * max(float(cur["size"][k]), 0.05 * diag)]
    drifted = (moved > DRIFT_CENTER_FRACTION * diag) or bool(size_bad)
    return drifted, {"why": "center drift %.4f (limit %.4f = %.0f%% of diagonal)%s" % (
        moved, DRIFT_CENTER_FRACTION * diag, DRIFT_CENTER_FRACTION * 100,
        ("; size drift %s (limit %.0f%%)" % (["%s %.4f" % ("xyz"[k], dsz[k]) for k in size_bad],
                                        DRIFT_SIZE_FRACTION * 100)) if size_bad else ""),
        "center_moved": _r4(moved), "center_limit": _r4(DRIFT_CENTER_FRACTION * diag),
        "size_delta": [_r4(x) for x in dsz], "snapshot_t": snap.get("t"), "now_t": cur.get("t")}


def _demote_if_drifted(conn, cid):
    """Geometry drift → demote a supported verdict to unresolved (keep the old verdict, record history)."""
    if conn.get("status") not in ("supported",):
        return False
    drifted, detail = _drift_of(conn)
    if not drifted:
        return False
    conn["history"].append({"t": _now(), "status": "unresolved",
                            "why": "geometry drift → verdict auto-demoted: %s" % detail.get("why")})
    vd = conn.get("verdict") or {}
    vd["demoted"] = {"t": _now(), "reason": detail}
    conn["verdict"] = vd
    conn["status"] = "unresolved"
    _log("demote", {"id": cid, "detail": detail})
    return True


# ---------------------------------------------------------------- evidence

def c_evidence(label, view=None, note="", objects=None, scope=None):
    K = _kernel()
    api = getattr(K, "dsh_view_api", None)
    if api is None:
        return _j({"ok": False, "error": "view.py required: preload/inject K.dsh_view_api first (ensureView in the engine)"})
    import hashlib, os
    spec = dict(view or {})
    path = spec.get("path")
    if not path:
        return _j({"ok": False, "error": "view.path is required (the engine supplies the default working directory)"})
    info = json.loads(api["capture"](json.dumps(spec)))
    if not info.get("ok"):
        return _j({"ok": False, "error": info})
    h = hashlib.md5(open(path, "rb").read()).hexdigest()
    # v0.9.0: evidence binds the geometry fingerprint — once the source changes, the ledger marks this evidence stale
    fp = _fingerprint(objects, scope)
    fp_objs = ([str(x) for x in (objects if isinstance(objects, (list, tuple)) else [objects])]
               if objects else None)
    rec = {"label": str(label), "path": path, "md5": h, "bytes": os.path.getsize(path),
           "width": info.get("width"), "height": info.get("height"),
           "view": {k: spec.get(k) for k in ("from", "look_at", "lens", "ortho", "ortho_scale", "shading")},
           "fp": fp, "fp_objects": fp_objs, "note": str(note), "t": _now()}
    _store()["evidence"].append(rec)
    _log("evidence", {"label": label, "md5": h, "fp": fp.get("digest")})
    return _j({"ok": True, "evidence": rec, "total": len(_store()["evidence"])})


def c_ledger(with_stale=True):
    """Evidence ledger. With with_stale=True (the default), each entry is compared against the current geometry fingerprint: evidence whose source changed is marked stale=true."""
    st = _store()
    out = {"ok": True, "evidence": [], "stale_evidence": 0, "stale_labels": [],
           "demoted_connections": [], "checked": bool(with_stale)}
    cache = {}

    def _cur_global():
        if "scene" not in cache:
            cache["scene"] = _fingerprint(None, None)
        return cache["scene"]
    for e in st["evidence"]:
        rec = dict(e)
        if with_stale and e.get("fp"):
            names = e.get("fp_objects")
            key = "scene" if not names else ",".join(names)
            if key not in cache:
                cache[key] = _cur_global() if not names else _fingerprint(names, None)
            rec["stale"] = (cache[key].get("digest") != e["fp"].get("digest"))
            rec["fp_now"] = cache[key].get("digest")
            if rec["stale"]:
                out["stale_evidence"] += 1
                out["stale_labels"].append(e.get("label"))
        out["evidence"].append(rec)
    for cid, conn in st["connections"].items():
        if _demote_if_drifted(conn, cid):
            out["demoted_connections"].append(cid)
    return _j(out)


def c_status():
    st = _store()
    demoted = []
    for k, v in st["connections"].items():
        if _demote_if_drifted(v, k):
            demoted.append(k)
    conns = {k: {"a": v["a"], "b": v["b"], "status": v["status"], "candidates": v["candidates"],
                 "forbidden": v["forbidden"], "verdict": v["verdict"],
                 "history_len": len(v["history"])} for k, v in st["connections"].items()}
    unresolved = [k for k, v in st["connections"].items() if v["status"] != "supported"]
    return _j({"ok": True, "components": len(st["components"]), "connections": len(st["connections"]),
               "envelopes": len(st["envelopes"]), "evidence": len(st["evidence"]),
               "unresolved_connections": unresolved, "detail": conns,
               "demoted_now": demoted,
               "note": "demoted_now = connections auto-demoted during this read because of geometry drift (center > 10% of diagonal or size > 20%)"})


# ----------------------------------------------------------------: three-state verdict and flip

def c_verify(conn_id, err=None, tolerance=None, identifiable=None, probe_err=None,
             probe_tolerance=None, evidence_labels=None, note=""):
    """Three-state verdict (cookbook §5):
         err <= tol and key parameters identifiable → supported
         err >  tol                                  → refuted
         err <= tol but key params unidentifiable / multiple hypotheses → unresolved (and lists the probes needed)
       When probe_err is given: probe_err <= probe_tolerance → support; otherwise overturn the external conclusion.
    """
    st = _store()
    conn = st["connections"].get(str(conn_id))
    if not conn:
        return _j({"ok": False, "error": "connection not registered: %s" % conn_id})
    ident = list(identifiable or [])
    missing = [p for p in (conn.get("params") or {}) if p not in ident]
    verdict = None; why = []
    if err is not None and tolerance is not None:
        if float(err) > float(tolerance):
            verdict = "refuted"; why.append("external error %s > tolerance %s" % (err, tolerance))
        elif missing:
            verdict = "unresolved"
            why.append("external error %s <= %s but parameters unidentifiable: %s (probe needed)" % (err, tolerance, ", ".join(missing)))
        else:
            verdict = "supported"; why.append("external error %s <= %s and parameters identifiable" % (err, tolerance))
    if probe_err is not None and probe_tolerance is not None:
        if float(probe_err) <= float(probe_tolerance):
            verdict = "supported"; why.append("probe error %s <= %s → support" % (probe_err, probe_tolerance))
        else:
            verdict = "refuted"; why.append("probe error %s > %s → overturn" % (probe_err, probe_tolerance))
    if verdict is None:
        return _j({"ok": False, "error": "give at least err+tolerance or probe_err+probe_tolerance"})
    ev = [{"label": e["label"], "md5": e["md5"], "path": e["path"]} for e in st["evidence"]
          if not evidence_labels or e["label"] in evidence_labels]
    # v0.9.0: the verdict binds a bbox snapshot → later geometry drift (center > 10% of diagonal / size > 20%) auto-demotes it to unresolved
    drifted, drift_detail = _drift_of(conn)
    if drifted:
        why.append("note: the geometry of the previous verdict has drifted (%s) → this is a re-judgement" % drift_detail.get("why"))
    objs = _conn_objects(conn)
    snap = _snapshot_of(objs)
    conn["status"] = verdict
    conn["verdict"] = {"verdict": verdict, "why": why, "err": err, "tolerance": tolerance,
                       "identifiable": ident, "unidentifiable": missing,
                       "probe_err": probe_err, "probe_tolerance": probe_tolerance,
                       "evidence": ev, "bbox_snapshot": snap,
                       "objects": [o.name for o in objs], "drift_of_previous": drift_detail if drifted else None,
                       "note": str(note), "t": _now()}
    conn["history"].append({"t": _now(), "status": verdict, "why": why})
    _log("verify", {"id": conn_id, "verdict": verdict})
    return _j({"ok": True, "connection": conn_id, "verdict": verdict, "why": why,
               "unidentifiable_params": missing, "evidence_used": len(ev),
               "bbox_snapshot": snap,
               "drift_guard": {"center_fraction": DRIFT_CENTER_FRACTION, "size_fraction": DRIFT_SIZE_FRACTION,
                               "note": "if the geometry later drifts past the limits, status is auto-demoted to unresolved on status/ledger reads, "
                                       "with the reason kept in verdict.demoted (objects with animation data skip demotion)"}})


def c_flip(conn_id, to, why=""):
    """Hypothesis flip: switch the connection to another candidate type, keeping history (old verdicts are not deleted)."""
    st = _store()
    conn = st["connections"].get(str(conn_id))
    if not conn:
        return _j({"ok": False, "error": "connection not registered: %s" % conn_id})
    if conn["candidates"] and to not in conn["candidates"]:
        return _j({"ok": False, "error": "not among candidates: %s" % to, "candidates": conn["candidates"]})
    conn["history"].append({"t": _now(), "flip_from": conn.get("flipped_to"), "status": conn.get("status"),
                            "why": "flip -> %s: %s" % (to, why)})
    conn["flipped_to"] = str(to)
    conn["status"] = "testing"
    conn["verdict"] = None
    _log("flip", {"id": conn_id, "to": to, "why": why})
    return _j({"ok": True, "connection": conn_id, "now": to, "status": "testing", "history_len": len(conn["history"])})


def c_advance(conn_id, status, why=""):
    st = _store()
    conn = st["connections"].get(str(conn_id))
    if not conn:
        return _j({"ok": False, "error": "connection not registered: %s" % conn_id})
    if status not in ("proposed", "testing", "supported", "refuted"):
        return _j({"ok": False, "error": "invalid status", "allowed": ["proposed", "testing", "supported", "refuted"]})
    conn["status"] = status
    conn["history"].append({"t": _now(), "status": status, "why": why})
    _log("advance", {"id": conn_id, "status": status})
    return _j({"ok": True, "connection": conn_id, "status": status})


def c_report(path=None):
    """Generate a Markdown report: hypothesis/range/verdict/evidence/repro command (provenance table)."""
    st = _store()
    L = ["# Contract and hypothesis report (auto-generated)", "", "> Generated at: %s" % _now(), "",
         "## Components (%d)" % len(st["components"]), "", "| Component | Objects | Tags | Missing objects |", "|---|---|---|---|"]
    for k, v in st["components"].items():
        L.append("| %s | %s | %s | %s |" % (k, ", ".join(v["objects"]) or "-", ", ".join(v["tags"]) or "-",
                                            ", ".join(v["missing_objects"]) or "-"))
    L += ["", "## Connections and verdicts (%d)" % len(st["connections"]), "",
          "| Connection | a → b | Candidates | Forbidden | Status | Verdict basis |", "|---|---|---|---|---|---|"]
    for k, v in st["connections"].items():
        vd = v.get("verdict") or {}
        why = "; ".join(vd.get("why") or []) or "-"
        extra = ""
        if vd.get("unidentifiable"):
            extra = " (unidentifiable: %s)" % ", ".join(vd["unidentifiable"])
        L.append("| %s | %s → %s | %s | %s | **%s** | %s%s |" % (
            k, v["a"], v["b"], ", ".join(v["candidates"]) or "-", ", ".join(v["forbidden"]) or "-",
            v["status"], why, extra))
    if st["envelopes"]:
        L += ["", "## Envelopes", "", "| Envelope | min | max | Scope |", "|---|---|---|---|"]
        for k, v in st["envelopes"].items():
            L.append("| %s | %s | %s | %s |" % (k, v["min"], v["max"], ", ".join(v["scope"]) or "(all)"))
    L += ["", "## Evidence ledger (%d)" % len(st["evidence"]), "",
          "| Label | File | md5 | Size |", "|---|---|---|---|"]
    for e in st["evidence"]:
        L.append("| %s | %s | %s | %sx%s |" % (e["label"], e["path"], e["md5"], e.get("width"), e.get("height")))
    L += ["", "## History", ""]
    for r in st["log"][-30:]:
        L.append("- %s %s %s" % (r["t"], r["action"], json.dumps(r["detail"], ensure_ascii=False)[:200]))
    L += ["", "## Reproduce", "", "    this report is generated by the contract layer: blender_rt_plan(op=\"report\")",
          "    assumption/range/probe workflow: see docs/assumption-driven-modeling-cookbook.md", ""]
    text = "\n".join(L) + "\n"
    if path:
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            return _j({"ok": True, "path": path, "bytes": len(text.encode("utf-8")), "preview": text[:600]})
        except Exception as e:
            return _j({"ok": False, "error": str(e), "preview": text[:600]})
    return _j({"ok": True, "path": None, "text": text})


# ============================================================================
# v0.9.0: assembly-level criteria (used with the gate / assembly feature library / interference report)
# ----------------------------------------------------------------------------
# Source: SpatiaOS/Procedura (MIT)
#   * src/motion/geometry.ts —— analyzeContactRegion / analyzeMateRegistration / computeMeshVolume
#   * OpenSCAD lib/assembly.scad —— 9 mate features + asm_fit four tiers + asm_lead + ISO 273 clearance holes
#
# Why check_interface was upgraded from bbox level to mesh level (the whole motive for this change):
#   bbox only looks at bounding boxes. For a fit like "pin into hole", the bboxes at both ends necessarily
#   overlap → the bbox reading always reads "overlap, 0 gap", which neither distinguishes a 0.15 mm
#   location fit nor reveals that the pin has pressed 3 mm into the parent material. So it changed to:
#     A side sampled by **area weighting** → nearest point on B's **surface** → measure the gap from the
#     distance field, ray parity decides inside/outside.
#
# Three invariants kept in step with upstream (read the reasoning here before changing anything):
#   * contact distance contact_max = 1.5% × diagonal of the **combined** bbox of both parts (not the sum of the individual diagonals)
#   * hard sampling cap 4000 points; contact points < 8 → insufficient evidence → unresolved
#   * contact area ratio is computed in both directions and the **larger** one is taken (when a small part
#     sits on a large one, only the small part's reading means anything: the large part's surface area is
#     big, so its "contact ratio" is naturally tiny; taking the maximum effectively normalizes by the
#     small part — the upstream comment's own words)
