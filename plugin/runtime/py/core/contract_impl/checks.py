# -*- coding: utf-8 -*-
"""Split from contract.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403
from .fingerprint import _r4
from .mate import _iface_hint, _mate_measure, _mesh_data, _sample_surface, _tris_diagonal, _units, _units_block



def c_register_component(cid, objects=None, tags=None, note=""):
    st = _store()
    miss = [n for n in (objects or []) if bpy.data.objects.get(n) is None]
    st["components"][str(cid)] = {"objects": list(objects or []), "tags": list(tags or []),
                                  "note": str(note), "missing_objects": miss, "registered": _now()}
    _log("register_component", {"id": cid, "objects": objects, "missing": miss})
    return _j({"ok": True, "id": cid, "objects": objects, "missing_objects": miss})


def c_register_connection(cid, a, b, candidates=None, params=None, forbidden=None,
                          confidence="", evidence_required=None, status="proposed", note=""):
    st = _store()
    for side, name in (("a", a), ("b", b)):
        if name not in st["components"]:
            return _j({"ok": False, "error": "Component not registered: %s" % name, "side": side})
    st["connections"][str(cid)] = {
        "a": str(a), "b": str(b),
        "candidates": list(candidates or []),
        "params": params or {},
        "forbidden": list(forbidden or []),
        "confidence": str(confidence),
        "evidence_required": list(evidence_required or []),
        "status": str(status),
        "note": str(note),
        "verdict": None, "history": [], "registered": _now(),
    }
    _log("register_connection", {"id": cid, "a": a, "b": b, "candidates": candidates, "status": status})
    return _j({"ok": True, "id": cid, "status": status, "forbidden": list(forbidden or [])})


def c_register_envelope(eid, mn, mx, scope=None, note=""):
    st = _store()
    st["envelopes"][str(eid)] = {"min": list(mn), "max": list(mx), "scope": list(scope or []),
                                 "note": str(note), "registered": _now()}
    _log("register_envelope", {"id": eid, "min": mn, "max": mx, "scope": scope})
    return _j({"ok": True, "id": eid})




def c_check_envelope(eid=None):
    st = _store()
    ids = [eid] if eid else list(st["envelopes"])
    out = []
    for i in ids:
        env = st["envelopes"].get(str(i))
        if not env:
            out.append({"id": i, "error": "not registered"})
            continue
        bad = []
        for ob in _scope_objects(env["scope"] or None):
            (mnx, mny, mnz), (mxx, mxy, mxz) = _bbox(ob)
            over = []
            for k, (lo, hi) in enumerate(zip(env["min"], env["max"])):
                v_lo, v_hi = (mnx, mny, mnz)[k], (mxx, mxy, mxz)[k]
                if v_lo < lo - 1e-9:
                    over.append(["%s_min" % "xyz"[k], round(v_lo - lo, 4)])
                if v_hi > hi + 1e-9:
                    over.append(["%s_max" % "xyz"[k], round(v_hi - hi, 4)])
            if over:
                bad.append({"name": ob.name, "out_of_envelope": over})
        out.append({"id": i, "scope": env["scope"], "violations": len(bad), "objects": bad[:50]})
    return _j({"ok": True, "envelopes": out})


def c_check_interference(scope=None, use_bvh=True, limit=400, include_hidden=False):
    """AABB swept along x with pruning → optional BVH fine check. Returns candidate pairs, fine-check hits and timings (read-only)."""
    import numpy as np
    t0 = time.perf_counter()
    objs = _scope_objects(scope, include_hidden)
    n = len(objs)
    if n == 0:
        return _j({"ok": True, "objects": 0, "pairs": 0, "ms": 0})
    mn = np.empty((n, 3)); mx = np.empty((n, 3))
    for i, ob in enumerate(objs):
        (a, b) = _bbox(ob)
        mn[i] = a; mx[i] = b
    t_box = time.perf_counter() - t0
    order = np.argsort(mn[:, 0])
    t1 = time.perf_counter()
    cand = []
    for ii in range(n):
        i = int(order[ii]); jj = ii + 1
        while jj < n:
            j = int(order[jj])
            if mn[j][0] > mx[i][0]:
                break
            if (mn[i][1] <= mx[j][1] and mx[i][1] >= mn[j][1] and mn[i][2] <= mx[j][2] and mx[i][2] >= mn[j][2]):
                cand.append((i, j))
            jj += 1
    t_sweep = time.perf_counter() - t1
    refined = None
    t2 = time.perf_counter()
    if use_bvh and cand:
        from mathutils.bvhtree import BVHTree
        dg = bpy.context.evaluated_depsgraph_get()
        trees = {}
        used = sorted({x for p in cand[:limit] for x in p})
        for i in used:
            try:
                trees[i] = BVHTree.FromObject(objs[i], dg)
            except Exception:
                trees[i] = None
        hit = []
        for (i, j) in cand[:limit]:
            if trees.get(i) and trees.get(j) and trees[i].overlap(trees[j]):
                hit.append([objs[i].name, objs[j].name])
        refined = hit
    t_bvh = time.perf_counter() - t2
    return _j({"ok": True, "objects": n, "pairs_aabb": len(cand),
               "pairs_bvh": (len(refined) if refined is not None else None),
               "bvh_tested": min(len(cand), limit),
               "bbox_ms": round(t_box * 1000, 1), "sweep_ms": round(t_sweep * 1000, 1),
               "bvh_ms": round(t_bvh * 1000, 1),
               "pairs": (refined if refined is not None else [[objs[i].name, objs[j].name] for i, j in cand[:limit]])})




def c_check_interface(conn_id, mesh=True, samples=1500):
    """Gap between two components. **The legacy field semantics are unchanged byte for byte** (backward compatible): gap_axis_m / gap_m / overlap_bbox
    are still bbox-level (>0 means a gap, <0 means a bbox overlap).

    The new mesh block (on by default, mesh=False turns it off): the same pair measured on the **real mesh**.
    Why this block is mandatory: the bbox basis **always** reads a fit like "pin into hole" as "overlapping, 0 gap" —
    it can neither tell a 0.15 mm location fit apart nor see that the pin has already been pressed 3 mm into the base material (measured: with 3 mm
    of interpenetration the bbox basis reports gap_m=0.0, the mesh basis reports depth_max=3.000 mm and a median per-side gap of 0.1498 mm).
    Measurement and mate_check share one implementation (_mate_measure), no second copy — having the two bases drift apart once was enough.
    When it cannot measure (empty component / no triangles / mesh too large) it returns mesh.skipped + the reason, never a silent omission.
    """
    st = _store()
    conn = st["connections"].get(str(conn_id))
    if not conn:
        return _j({"ok": False, "error": "Connection not registered: %s" % conn_id})
    A = _component_objects(conn["a"]); B = _component_objects(conn["b"])
    if not A or not B:
        return _j({"ok": False, "error": "Component has no objects", "a": len(A), "b": len(B)})
    def union(obs):
        bs = [_bbox(o) for o in obs]
        return ([min(b[0][k] for b in bs) for k in range(3)], [max(b[1][k] for b in bs) for k in range(3)])
    (amn, amx) = union(A); (bmn, bmx) = union(B)
    gaps = {}
    for k, ax in enumerate("xyz"):
        if amx[k] < bmn[k]:
            gaps[ax] = round(bmn[k] - amx[k], 5)
        elif bmx[k] < amn[k]:
            gaps[ax] = round(amn[k] - bmx[k], 5)
        else:
            gaps[ax] = 0.0
    sep = math.sqrt(sum(g * g for g in gaps.values()))
    out = {"ok": True, "connection": conn_id, "gap_axis_m": gaps, "gap_m": round(sep, 5),
           "overlap_bbox": all(g == 0.0 for g in gaps.values()),
           "a_objects": [o.name for o in A], "b_objects": [o.name for o in B]}
    # --- new: mesh-level measurement (legacy fields untouched; this block is additive only) ---
    if not mesh:
        out["mesh"] = {"skipped": True, "why": "mesh=False (bbox-basis coarse filter only)"}
        return _j(out)
    AM = [o for o in A if o.type == "MESH"]
    BM = [o for o in B if o.type == "MESH"]
    if not AM or not BM:
        out["mesh"] = {"skipped": True, "why": "one side has no MESH object → cannot measure (no made-up numbers)"}
        return _j(out)
    mdA, mdB = _mesh_data(AM), _mesh_data(BM)
    if mdA is None or mdB is None or mdA["tris_n"] == 0 or mdB["tris_n"] == 0:
        out["mesh"] = {"skipped": True, "why": "no triangles after evaluation → cannot measure"}
        return _j(out)
    if MATE_MAX_TRIS > 0 and (mdA["tris_n"] > MATE_MAX_TRIS or mdB["tris_n"] > MATE_MAX_TRIS):
        out["mesh"] = {"skipped": True, "why": "mesh too large (%d/%d faces > %d) → not judged, never read as passed"
                       % (mdA["tris_n"], mdB["tris_n"], MATE_MAX_TRIS)}
        return _j(out)
    import numpy as np
    _m_per_unit, mm_per_unit = _units()
    diag_m, _lo, _hi = _tris_diagonal(np.concatenate([mdA["tris"], mdB["tris"]], axis=0))
    contact_max_m = DEFAULT_CONTACT_DISTANCE_FRAC * diag_m
    n = int(max(1, min(int(samples or 0), CONTACT_SAMPLE_CAP)))
    PA = _sample_surface(mdA["tris"], n)
    PB = _sample_surface(mdB["tris"], n)
    if PA is None or PB is None:
        out["mesh"] = {"skipped": True, "why": "zero-area mesh, sampling failed"}
        return _j(out)
    meas = _mate_measure(mdA, mdB, mm_per_unit, PA, PB, contact_max_m)
    out["units"] = _units_block(_m_per_unit, mm_per_unit)
    out["mesh"] = {"skipped": False, "units_rule": "every *_mm = Blender units × mm_per_unit",
                   "samples_used": min(meas["used_a"], meas["used_b"]), "cap": CONTACT_SAMPLE_CAP,
                   "contact_max_mm": _r4(contact_max_m * mm_per_unit),
                   "contact_area_fraction": meas["contact"]["contact_area_fraction"],
                   "gap_median_mm": meas["gap"]["median_mm"], "gap_mean_mm": meas["gap"]["mean_mm"],
                   "gap_min_mm": meas["gap"]["min_mm"], "gap_max_mm": meas["gap"]["max_mm"],
                   "contact_points": meas["gap"]["n"],
                   "depth_max_mm": meas["penetration"].get("depth_max_mm"),
                   "penetration_status": meas["penetration"].get("status"),
                   "closed": {"a": mdA["closed"], "b": mdB["closed"]},
                   "contact_anchor_world": meas["contact"]["anchor_world"],
                   "verdict_hint": _iface_hint(meas["contact"], meas["gap"], meas["penetration"]),
                   "next": "For a three-state verdict (supported/refuted/unresolved) use mate_check(conn_id, fit=...); "
                           "this block only reports the measured numbers"}
    return _j(out)


# ---------------------------------------------------------------- gating

def c_destructive_guard(op, targets=None, conn_ids=None):
    """Destructive operation gating: block as soon as a target object belongs to a connection that is "not yet resolved (status != supported)", or the connection lists this op as forbidden."""
    st = _store()
    op = str(op)
    if op not in DESTRUCTIVE_OPS:
        return _j({"ok": True, "allowed": True, "op": op, "reason": "non-destructive operation, not blocked"})
    targets = list(targets or [])
    ids = [str(x) for x in (conn_ids or list(st["connections"]))]
    hits = []
    for cid in ids:
        conn = st["connections"].get(cid)
        if not conn:
            continue
        objs = {o.name for o in _component_objects(conn["a"])} | {o.name for o in _component_objects(conn["b"])}
        touched = [t for t in targets if t in objs] if targets else []
        forbidden = (op in conn.get("forbidden", [])) or (op == "boolean_union" and "boolean_union" in conn.get("forbidden", []))
        unresolved = conn.get("status") != "supported"
        if forbidden or (unresolved and (not targets or touched)):
            hits.append({"connection": cid, "a": conn["a"], "b": conn["b"], "status": conn.get("status"),
                         "forbidden_listed": bool(forbidden), "touched": touched})
    if hits:
        return _j({"ok": False, "allowed": False, "op": op,
                   "code": "Unsupported Destructive Merge" if op in ("boolean_union", "weld", "merge", "join") else "Forbidden Destructive Op",
                   "reason": "The target involves an unresolved connection, or that connection explicitly forbids this operation; resolve it first per the cookbook (probe/explain), then proceed",
                   "blocked_by": hits})
    return _j({"ok": True, "allowed": True, "op": op, "reason": "no unresolved connection involves this operation"})

