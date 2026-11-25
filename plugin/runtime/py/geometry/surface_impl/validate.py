# -*- coding: utf-8 -*-
"""Split from surface_orig.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403
from .build import surface_mesh_data
from .objects import _SpecError, _bbox_mm, _faces_to_tris, _object_eval_mesh

def _resolve_source(src):
    """spec(dict) or a mesh object name → analysis context {verts_mm, tris, faces, spec, source}; bad input raises."""
    mmu = max(_mmu(), 1e-12)
    if isinstance(src, dict) and "kind" not in src and src.get("object"):
        src = str(src.get("object"))
    if isinstance(src, dict):
        norm, errs = surface_spec_normalize(src)
        if errs:
            raise _SpecError(errs)
        md = surface_mesh_data(norm)
        return {"verts_mm": np.asarray(md["verts_mm"], dtype=np.float64),
                "faces": md["faces"], "tris": _faces_to_tris(md["faces"]),
                "spec": norm, "source": {"kind": "spec", "spec_kind": norm["kind"],
                                         "spec_hash": norm["spec_hash"]}}
    if isinstance(src, str):
        ob = bpy.data.objects.get(str(src))
        if ob is None:
            raise ValueError("object does not exist: %r" % src)
        if ob.type != "MESH":
            raise ValueError("object is not a mesh (type=%s): %r" % (ob.type, src))
        baked = _object_eval_mesh(ob)
        if len(baked["tris"]) == 0:
            raise ValueError("object evaluates to 0 triangles: %r" % src)
        return {"verts_mm": baked["verts"] * mmu, "faces": None, "tris": baked["tris"],
                "spec": None, "source": {"kind": "object", "object": str(ob.name)}}
    raise ValueError("spec_or_object must be a SurfaceSpec object or a mesh object name")


def _vertex_normals(verts, tris):
    V = np.asarray(verts, dtype=np.float64)
    T = np.asarray(tris, dtype=np.int64)
    n = np.zeros_like(V)
    if len(T) == 0:
        return n
    a, b, c = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    fn = np.cross(b - a, c - a)
    for k in range(3):
        np.add.at(n, T[:, k], fn)
    ln = np.linalg.norm(n, axis=1)
    ok = ln > 1e-12
    n[ok] = n[ok] / ln[ok, None]
    n[~ok] = np.array([0.0, 0.0, 1.0])
    return n


def _mesh_topo(verts, tris):
    """Topology/quality stats: boundary edges, non-manifold edges, degenerate faces, aspect ratio, edge lengths, flipped normals."""
    V = np.asarray(verts, dtype=np.float64)
    T = np.asarray(tris, dtype=np.int64)
    if len(T) == 0:
        return {"tris": 0, "verts": len(V), "boundary_edges": 0, "nonmanifold_edges": 0,
                "watertight": False, "degenerate_faces": 0, "flipped_normals": 0,
                "aspect_max": None, "aspect_mean": None, "edge_min_mm": None, "edge_max_mm": None}
    edges = np.concatenate([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]], axis=0)
    uniq, cnt = np.unique(np.sort(edges, axis=1), axis=0, return_counts=True)
    boundary = int((cnt == 1).sum())
    nonmanifold = int((cnt > 2).sum())
    a, b, c = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    cross = np.cross(b - a, c - a)
    area = 0.5 * np.linalg.norm(cross, axis=1)
    degenerate = int((area < 1e-12).sum())
    e = np.stack([np.linalg.norm(b - a, axis=1), np.linalg.norm(c - b, axis=1),
                  np.linalg.norm(a - c, axis=1)], axis=1)
    emax = e.max(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        aspect = np.where(area > 1e-12, (emax ** 2) / (2.0 * np.maximum(area, 1e-30)), np.inf)
    finite = aspect[np.isfinite(aspect)]
    # flipped normals: the angle between the two face normals on a manifold edge is > 90°
    fn = cross / np.maximum(np.linalg.norm(cross, axis=1), 1e-30)[:, None]
    edges_n = np.sort(np.concatenate([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]], axis=0), axis=1)
    order = np.lexsort((edges_n[:, 1], edges_n[:, 0]))
    edges_s = edges_n[order]
    tri_of_edge = np.concatenate([np.arange(len(T))] * 3)[order]
    flipped = 0
    i = 0
    while i + 1 < len(edges_s):
        if edges_s[i][0] == edges_s[i + 1][0] and edges_s[i][1] == edges_s[i + 1][1]:
            t1, t2 = int(tri_of_edge[i]), int(tri_of_edge[i + 1])
            if t1 != t2 and float(np.dot(fn[t1], fn[t2])) < -0.1:
                flipped += 1
            i += 2
        else:
            i += 1
    return {"tris": int(len(T)), "verts": int(len(V)),
            "boundary_edges": boundary, "nonmanifold_edges": nonmanifold,
            "watertight": bool(boundary == 0 and nonmanifold == 0),
            "degenerate_faces": degenerate, "flipped_normals": int(flipped),
            "aspect_max": (_r(float(finite.max()), 4) if len(finite) else None),
            "aspect_mean": (_r(float(finite.mean()), 4) if len(finite) else None),
            "edge_min_mm": _r(float(e.min()), 4), "edge_max_mm": _r(float(e.max()), 4)}


def _curvature_metrics(verts, tris, vnormals):
    """Discrete curvature approximation: per edge k = angle between the two vertex normals / edge length (mm); per vertex, the mean over incident edges."""
    V = np.asarray(verts, dtype=np.float64)
    T = np.asarray(tris, dtype=np.int64)
    nv = len(V)
    if len(T) == 0 or nv == 0:
        return {"max_1_per_mm": None, "mean_1_per_mm": None, "hotspots": 0,
                "p95_1_per_mm": None, "n_edges": 0}
    edges = np.sort(np.concatenate([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]], axis=0), axis=1)
    edges = np.unique(edges, axis=0)
    i, j = edges[:, 0], edges[:, 1]
    lens = np.linalg.norm(V[j] - V[i], axis=1)
    ok = lens > 1e-9
    cosang = np.clip(np.einsum("ij,ij->i", vnormals[i], vnormals[j]), -1.0, 1.0)
    ang = np.arccos(cosang)
    k_edge = np.where(ok, ang / np.maximum(lens, 1e-12), 0.0)
    acc = np.zeros(nv, dtype=np.float64)
    cnt = np.zeros(nv, dtype=np.float64)
    np.add.at(acc, i, k_edge)
    np.add.at(acc, j, k_edge)
    np.add.at(cnt, i, 1.0)
    np.add.at(cnt, j, 1.0)
    k_v = np.where(cnt > 0, acc / np.maximum(cnt, 1e-12), 0.0)
    mean = float(k_v.mean())
    hotspot_thr = max(2.0 * mean, 0.5)          # 1/mm ⇒ a sharp bend with radius ≤2mm
    return {"max_1_per_mm": _r(float(k_v.max()), 6), "mean_1_per_mm": _r(mean, 6),
            "hotspots": int((k_v > hotspot_thr).sum()), "hotspot_threshold_1_per_mm": _r(hotspot_thr, 6),
            "p95_1_per_mm": _r(float(np.percentile(k_v, 95)), 6),
            "n_edges": int(len(edges))}


def _self_intersection(verts, tris, max_tris):
    """BVH self-intersection: tri-tri overlap (excluding topologically adjacent pairs sharing a vertex). Over the triangle cap → degraded."""
    from mathutils.bvhtree import BVHTree
    T = np.asarray(tris, dtype=np.int64)
    if len(T) == 0:
        return {"state": "pass", "pairs": 0, "analyzed": True, "limit": int(max_tris)}
    if int(max_tris) > 0 and len(T) > int(max_tris):
        return {"state": "degraded", "pairs": None, "analyzed": False, "limit": int(max_tris),
                "reason": "triangle count %d > max_tris %d; self-intersection check skipped (not treated as pass)" % (len(T), int(max_tris))}
    V = np.asarray(verts, dtype=np.float64)
    try:
        tree = BVHTree.FromPolygons([tuple(v) for v in V.tolist()],
                                    [tuple(int(i) for i in t) for t in T.tolist()],
                                    all_triangles=True)
        raw = tree.overlap(tree) or []
    except Exception as e:
        return {"state": "degraded", "pairs": None, "analyzed": False, "limit": int(max_tris),
                "reason": "BVH build/self-overlap failed: %s: %s" % (type(e).__name__, str(e)[:160])}
    seen = set()
    for a, b in raw:
        if a >= b:
            continue
        if len(set(T[a].tolist()) & set(T[b].tolist())) > 0:
            continue
        seen.add((int(a), int(b)))
        if len(seen) >= 5000:
            break
    sample = []
    for (a, b) in list(seen)[:5]:
        cen = 0.5 * (V[T[a]].mean(axis=0) + V[T[b]].mean(axis=0))
        sample.append({"tri_a": int(a), "tri_b": int(b), "at_mm": [_r(x, 4) for x in cen]})
    return {"state": "fail" if seen else "pass", "pairs": int(len(seen)),
            "analyzed": True, "limit": int(max_tris), "sample": sample}


def _thickness(verts, tris, vnormals, watertight, max_samples=1500):
    """Normal-ray approximate thickness (mm): from a closed shell, shoot rays inward from the vertices and take the distance to the first hit."""
    if not watertight:
        return {"state": "n/a", "reason": "an open surface has no thickness (an inward ray passes straight out); only closed shells are measured",
                "min_mm": None, "median_mm": None, "sampled": 0}
    from mathutils.bvhtree import BVHTree
    V = np.asarray(verts, dtype=np.float64)
    T = np.asarray(tris, dtype=np.int64)
    try:
        tree = BVHTree.FromPolygons([tuple(v) for v in V.tolist()],
                                    [tuple(int(i) for i in t) for t in T.tolist()],
                                    all_triangles=True)
    except Exception as e:
        return {"state": "degraded", "reason": "thickness BVH build failed: %s: %s" % (type(e).__name__, str(e)[:160]),
                "min_mm": None, "median_mm": None, "sampled": 0}
    from mathutils import Vector
    nv = len(V)
    idx = np.unique(np.linspace(0, nv - 1, min(int(max_samples), nv)).astype(np.int64))
    diag = float(np.linalg.norm(V.max(axis=0) - V.min(axis=0)))
    eps = max(1e-6, diag * 1e-4)
    vals = []
    for vi in idx.tolist():
        p = Vector(V[vi].tolist())
        d = Vector([-float(x) for x in vnormals[vi]])
        origin = p + d * eps
        hit = tree.ray_cast(origin, d)
        if hit is None or hit[0] is None:
            continue
        dist = float(hit[3]) + eps
        if dist > eps * 2.0 and math.isfinite(dist):
            vals.append(dist)
    if not vals:
        return {"state": "degraded", "reason": "on the closed shell every ray missed the opposite side (normals/topology suspect)",
                "min_mm": None, "median_mm": None, "sampled": 0}
    arr = np.asarray(vals, dtype=np.float64)
    return {"state": "pass", "min_mm": _r(float(arr.min()), 4), "median_mm": _r(float(np.median(arr)), 4),
            "p05_mm": _r(float(np.percentile(arr, 5)), 4), "sampled": int(len(arr))}


def _continuity_spec(ctx, g1_tol_deg, g2_tol_ratio):
    """Seam continuity in spec mode: loft looks at section seams (normal/curvature jumps); sweep looks at the closed-profile seam; patch = n/a."""
    spec = ctx.get("spec") or {}
    kind = str(spec.get("kind"))
    V = ctx["verts_mm"]
    T = ctx["tris"]
    vn = _vertex_normals(V, T)
    tess = spec.get("tessellation") or {}
    u = int(tess.get("u") or 0)
    v = int(tess.get("v") or 0)
    target = str(spec.get("continuity") or "G1")
    out = {"target": target, "method": None, "g0": True, "g1_deg": None, "g2_ratio": None,
           "state": "n/a", "note": ""}

    def _angle(a, b):
        c = float(np.clip(np.dot(a, b), -1.0, 1.0))
        return math.degrees(math.acos(c))

    if kind == "loft" and u > 0 and v > 1:
        secs = spec.get("sections") or []
        zs = np.array([s["z_mm"] for s in secs], dtype=np.float64)
        t = (zs - zs[0]) / max(zs[-1] - zs[0], 1e-12)
        rows = []
        for tt in t.tolist():
            rows.append(int(np.clip(round(tt * (v - 1)), 0, v - 1)))
        max_ang, max_jump = 0.0, 0.0
        # measure only at interior section seams (skip both ends of v)
        for k in range(1, len(rows) - 1):
            r = rows[k]
            if r <= 0 or r >= v - 1:
                continue
            for c in range(u):
                n_prev = vn[(r - 1) * u + c]
                n_mid = vn[r * u + c]
                n_next = vn[(r + 1) * u + c]
                a1 = _angle(n_prev, n_mid)
                a2 = _angle(n_mid, n_next)
                max_ang = max(max_ang, a1, a2)
                k1 = a1 / max(1e-9, float(np.linalg.norm(V[r * u + c] - V[(r - 1) * u + c])))
                k2 = a2 / max(1e-9, float(np.linalg.norm(V[(r + 1) * u + c] - V[r * u + c])))
                jump = abs(k2 - k1) / max(k1, k2, 1e-12)
                max_jump = max(max_jump, jump)
        out.update({"method": "loft section seam (normal angle / curvature jump between adjacent spans)",
                    "g1_deg": _r(max_ang, 4), "g2_ratio": _r(max_jump, 4),
                    "seams": max(0, len(rows) - 2)})
    elif kind == "sweep" and u > 2 and v > 1:
        if not spec.get("closed"):
            out["note"] = "an open profile has no seam; sweep continuity has no interior seam to inspect"
            return out
        max_ang = 0.0
        for r in range(v):
            n0 = vn[r * u + (u - 1)]
            n1 = vn[r * u + 0]
            max_ang = max(max_ang, _angle(n0, n1))
        out.update({"method": "sweep closed-profile seam (normal angle)", "g1_deg": _r(max_ang, 4),
                    "g2_ratio": 0.0, "seams": v})
    else:
        out["note"] = "%s is a single patch with no interior boundary seam (G0/G1/G2 follow from the construction)" % kind
        out["state"] = "n/a"
        return out
    if target == "G0":
        out["state"] = "pass"
        return out
    ok = (out["g1_deg"] is not None and out["g1_deg"] <= float(g1_tol_deg))
    if target == "G2":
        ok = ok and (out["g2_ratio"] is not None and out["g2_ratio"] <= float(g2_tol_ratio))
    out["state"] = "pass" if ok else "fail"
    out["reason"] = ("%s continuous: max normal angle %.3f° ≤ %.3f°%s"
                     % (target, out["g1_deg"] or 0.0, float(g1_tol_deg),
                        "" if target != "G2" else ", curvature jump %.3f ≤ %.3f"
                        % (out["g2_ratio"] or 0.0, float(g2_tol_ratio)))) if ok else \
                    ("%s discontinuous: max normal angle %.3f° (> %.3f°)%s"
                     % (target, out["g1_deg"] or 0.0, float(g1_tol_deg),
                        "" if target != "G2" else " / curvature jump %.3f (> %.3f)"
                        % (out["g2_ratio"] or 0.0, float(g2_tol_ratio))))
    return out


def _continuity_mesh(verts, tris, g1_tol_deg):
    """Object mode: mesh smoothness (max dihedral angle); informational only, never judged fail against a spec target."""
    V = np.asarray(verts, dtype=np.float64)
    T = np.asarray(tris, dtype=np.int64)
    if len(T) == 0:
        return {"state": "n/a", "method": "mesh dihedral", "max_dihedral_deg": None}
    face_n = np.cross(V[T[:, 1]] - V[T[:, 0]], V[T[:, 2]] - V[T[:, 0]])
    face_n = face_n / np.maximum(np.linalg.norm(face_n, axis=1), 1e-30)[:, None]
    edges = np.sort(np.concatenate([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]], axis=0), axis=1)
    order = np.lexsort((edges[:, 1], edges[:, 0]))
    es = edges[order]
    te = np.concatenate([np.arange(len(T))] * 3)[order]
    max_d = 0.0
    i = 0
    while i + 1 < len(es):
        if es[i][0] == es[i + 1][0] and es[i][1] == es[i + 1][1]:
            t1, t2 = int(te[i]), int(te[i + 1])
            if t1 != t2:
                c = float(np.clip(np.dot(face_n[t1], face_n[t2]), -1.0, 1.0))
                max_d = max(max_d, math.degrees(math.acos(c)))
            i += 2
        else:
            i += 1
    return {"state": "n/a", "method": "mesh dihedral (the object declares no continuity target, so numbers only)",
            "max_dihedral_deg": _r(max_d, 4), "tolerance_reference_deg": float(g1_tol_deg)}
# ────────────────────────────── M2 public op: surface_validate ──────────────────────────────
def _surface_validate_p1(_state):
    curvature, draft, g1_tol_deg, g2_tol_ratio, max_curvature = (
        _state["curvature"], _state["draft"], _state["g1_tol_deg"], _state["g2_tol_ratio"], _state["max_curvature"])
    max_tris, min_thickness_mm, self_intersection, spec_or_object = (
        _state["max_tris"], _state["min_thickness_mm"], _state["self_intersection"], _state["spec_or_object"])
    ctx, lim, st = (_state.get("ctx"), _state.get("lim"), _state.get("st"))
    try:
        t0 = time.perf_counter()
        try:
            ctx = _resolve_source(spec_or_object)
        except _SpecError as e:
            return _err("SurfaceSpec validation failed (bad parameters)", errors=e.errors[:12], stage="M0")
        except Exception as e:
            return _err("cannot resolve spec_or_object: %s: %s" % (type(e).__name__, str(e)[:240]), stage="M0")
        spec = ctx.get("spec")
        cons = dict((spec or {}).get("constraints") or {})
        gi_tol = _num(g1_tol_deg) or _num(cons.get("g1_tol_deg")) or 12.0
        g2_tol = _num(g2_tol_ratio) or _num(cons.get("g2_tol_ratio")) or 0.6
        thin_min = _num(min_thickness_mm) or _num(cons.get("min_thickness_mm")) or 0.8
        curv_max = _num(max_curvature) if max_curvature is not None else _num(cons.get("max_curvature_1_per_mm"))
        V = ctx["verts_mm"]
        T = ctx["tris"]
        vn = _vertex_normals(V, T)
        topo = _mesh_topo(V, T)
        checks, defects, skipped, nexts = {}, [], [], []

        # ---- mesh quality ----
        q_state = "pass"
        if topo["degenerate_faces"]:
            q_state = "fail"
            defects.append({"check": "mesh_quality", "severity": "fail",
                            "msg": "%d degenerate faces (area≈0) — fix the sections/resample first" % topo["degenerate_faces"]})
        if topo["flipped_normals"]:
            q_state = "fail"
            defects.append({"check": "mesh_quality", "severity": "fail",
                            "msg": "%d flipped-normal edges (angle between adjacent face normals >90°)" % topo["flipped_normals"]})
        if topo["nonmanifold_edges"]:
            q_state = "fail"
            defects.append({"check": "mesh_quality", "severity": "fail",
                            "msg": "%d non-manifold edges (>2 faces share an edge)" % topo["nonmanifold_edges"]})
        checks["mesh_quality"] = dict({"state": q_state}, **topo)
        if not topo["watertight"]:
            nexts.append("%d open boundary edges (normal for a surface patch; cap it or use a closed solid if you need thickness/watertightness)" % topo["boundary_edges"])

        # ---- curvature ----
        cur = None
        if curvature:
            cur = _curvature_metrics(V, T, vn)
            st = "pass"
            if curv_max is not None and cur["max_1_per_mm"] is not None and cur["max_1_per_mm"] > float(curv_max):
                st = "fail"
                defects.append({"check": "curvature", "severity": "fail",
                                "msg": "max curvature %.6g /mm > constraint %.6g /mm (sharp bend/noise)"
                                       % (cur["max_1_per_mm"], float(curv_max))})
            elif cur["hotspots"]:
                nexts.append("%d curvature hotspots (>%.3g /mm) — check for abrupt section-radius changes or mesh noise"
                             % (cur["hotspots"], cur["hotspot_threshold_1_per_mm"] or 0.0))
            checks["curvature"] = dict({"state": st}, **cur)
        else:
            skipped.append({"check": "curvature", "why": "continuity/curvature=False (explicitly skipped by the caller)"})

        # ---- self-intersection ----
        si = None
        if self_intersection:
            lim = int(min(int(max_tris), 20000)) if draft else int(max_tris)
            si = _self_intersection(V, T, lim)
            checks["self_intersection"] = si
            if si.get("state") == "fail":
                defects.append({"check": "self_intersection", "severity": "fail",
                                "msg": "%d self-intersecting triangle pairs (truncated at 5000 pairs before the cap)" % int(si.get("pairs") or 0),
                                "sample": si.get("sample")})
            elif si.get("state") == "degraded":
                skipped.append({"check": "self_intersection", "why": si.get("reason")})
        else:
            skipped.append({"check": "self_intersection", "why": "self_intersection=False"})

        # ---- thickness ----
        th = None
    finally:
        _state.update((k, v) for k, v in locals().items() if k != "_state")

def _surface_validate_p2(_state):
    T, V, checks, continuity, ctx = (
        _state.get("T"), _state.get("V"), _state.get("checks"), _state["continuity"], _state.get("ctx"))
    cur, curv_max, defects, draft, g2_tol = (
        _state.get("cur"), _state.get("curv_max"), _state.get("defects"), _state["draft"], _state.get("g2_tol"))
    gi_tol, max_tris, nexts, si, skipped = (
        _state.get("gi_tol"), _state["max_tris"], _state.get("nexts"), _state.get("si"), _state.get("skipped"))
    spec, t0, thickness, thin_min, topo = (
        _state.get("spec"), _state.get("t0"), _state["thickness"], _state.get("thin_min"), _state.get("topo"))
    vn = _state.get("vn")
    th, verdict = (_state.get("th"), _state.get("verdict"))
    try:
        if thickness:
            if draft:
                th = {"state": "n/a", "reason": "draft=True skips thickness (high cost)",
                      "min_mm": None, "median_mm": None, "sampled": 0}
                skipped.append({"check": "thickness", "why": th["reason"]})
            else:
                th = _thickness(V, T, vn, bool(topo["watertight"]))
                if th.get("state") == "pass" and th.get("min_mm") is not None:
                    if th["min_mm"] < float(thin_min):
                        th["state"] = "fail"
                        defects.append({"check": "thickness", "severity": "fail",
                                        "msg": "approximate minimum thickness %.4g mm < target %.4g mm" % (th["min_mm"], float(thin_min))})
                elif th.get("state") == "n/a":
                    skipped.append({"check": "thickness", "why": th.get("reason")})
                elif th.get("state") == "degraded":
                    skipped.append({"check": "thickness", "why": th.get("reason")})
                checks["thickness"] = th
        else:
            skipped.append({"check": "thickness", "why": "thickness=False"})

        # ---- continuity ----
        cont = None
        if continuity:
            if spec is not None:
                cont = _continuity_spec(ctx, gi_tol, g2_tol)
                if cont.get("state") == "fail":
                    defects.append({"check": "continuity", "severity": "fail",
                                    "msg": cont.get("reason") or "boundary continuity below target",
                                    "g1_deg": cont.get("g1_deg"), "g2_ratio": cont.get("g2_ratio")})
                elif cont.get("state") == "n/a":
                    skipped.append({"check": "continuity", "why": cont.get("note")})
            else:
                cont = _continuity_mesh(V, T, gi_tol)
                if cont.get("max_dihedral_deg") is not None and cont["max_dihedral_deg"] > 90.0:
                    nexts.append("the object has a %0.1f° dihedral angle (informational; no continuity target is declared, so it is not judged fail)"
                                 % cont["max_dihedral_deg"])
            checks["continuity"] = cont
        else:
            skipped.append({"check": "continuity", "why": "continuity=False"})

        if any(d.get("severity") == "fail" for d in defects):
            verdict = "fail"
        elif any((c or {}).get("state") == "degraded" for c in checks.values()):
            verdict = "degraded"
        else:
            verdict = "pass"
        if verdict == "fail":
            nexts.insert(0, "fix the defects one by one first (change the sections/parameters or use a larger tessellation), then rerun validate; a fail must not be treated as pass")
        elif verdict == "degraded":
            nexts.insert(0, "some checks did not run (%s) — raise max_tris or supply a closed shell, then rerun; degraded ≠ pass"
                         % (skipped[-1].get("check") if skipped else "over the cap"))
        bbox = _bbox_mm(V)
        body = {
            "ok": True, "version": SURFACE_VERSION, "verdict": verdict,
            "source": ctx.get("source"), "spec_hash": (spec or {}).get("spec_hash"),
            "metrics": {"verts": int(len(V)), "tris": int(len(T)), "bbox_mm": bbox,
                        "watertight": bool(topo["watertight"]),
                        "boundary_edges": int(topo["boundary_edges"]),
                        "nonmanifold_edges": int(topo["nonmanifold_edges"]),
                        "degenerate_faces": int(topo["degenerate_faces"]),
                        "flipped_normals": int(topo["flipped_normals"]),
                        "aspect_max": topo["aspect_max"],
                        "curvature": ({"max_1_per_mm": cur["max_1_per_mm"], "mean_1_per_mm": cur["mean_1_per_mm"],
                                       "hotspots": cur["hotspots"]} if cur else None),
                        "thickness": ({"min_mm": th.get("min_mm"), "median_mm": th.get("median_mm"),
                                       "state": th.get("state")} if th else None),
                        "self_intersection": ({"pairs": si.get("pairs"), "state": si.get("state"),
                                               "analyzed": si.get("analyzed")} if si else None),
                        "continuity": ({"state": cont.get("state"), "g1_deg": cont.get("g1_deg"),
                                        "g2_ratio": cont.get("g2_ratio"),
                                        "max_dihedral_deg": cont.get("max_dihedral_deg")} if cont else None)},
            "checks": checks, "defects": defects, "skipped": skipped, "next": nexts[:8],
            "targets": {"min_thickness_mm": _r(thin_min, 4), "max_curvature_1_per_mm": curv_max,
                        "g1_tol_deg": _r(gi_tol, 4), "g2_tol_ratio": _r(g2_tol, 4),
                        "max_tris": int(max_tris), "draft": bool(draft)},
            "note": "fail never silently becomes pass; degraded = not fully checked (degraded ≠ pass); an open surface with no thickness is n/a",
            "honest_limits": [
                "curvature is a discrete approximation (vertex-normal angle / edge length) and is sensitive to triangulation density; it is only used to find sharp-bend hotspots, not as analytic curvature",
                "thickness is an inward-ray approximation (a vertex subset ≤1500); on non-convex/cavity parts it may read a local diameter instead of the wall thickness",
                "self-intersection uses BVH tri-tri (excluding adjacent pairs sharing a vertex); a triangle count over max_tris ⇒ degraded, not treated as no self-intersection",
                "object mode has no declared G1/G2 target: continuity only reports the dihedral reference, and only spec mode judges fail against continuity",
            ],
        }
        return _j(_receipt(body, t0))
    finally:
        _state.update((k, v) for k, v in locals().items() if k != "_state")

def surface_validate(spec_or_object=None, continuity=True, curvature=True, self_intersection=True,
                     thickness=True, draft=False, min_thickness_mm=None, max_curvature=None,
                     max_tris=120000, g1_tol_deg=None, g2_tol_ratio=None):
    """Surface/object health check: continuity, curvature, self-intersection, thickness, mesh quality → ok/verdict/metrics/defects/next.

    Criteria (a fail must never silently become pass):
      * confirmed defect ⇒ fail: self-intersections >0, closed-shell minimum thickness < target, flipped normals, degenerate faces, non-manifold edges, curvature constraint exceeded;
      * insufficient resources / unmeasurable ⇒ degraded: triangle count over max_tris so no self-intersection test ran, every thickness ray on a closed shell missed;
      * "no thickness" on an open surface is n/a (a surface patch has no volume by definition) and counts as neither fail nor degraded;
      * an object with no declared continuity target → continuity only reports mesh dihedral numbers (informational) and is not judged fail against a spec.
    """
    _state = dict(locals())
    for _fn_ in (_surface_validate_p1, _surface_validate_p2):
        _r = _fn_(_state)
        if _r is not None:
            return _r
# ────────────────────────────── M4: selftest / help / registration ──────────────────────────────
def _cleanup_objects(names):
    removed = []
    for nm in list(names or []):
        ob = bpy.data.objects.get(str(nm))
        if ob is None:
            continue
        me = ob.data if ob.type == "MESH" else None
        try:
            bpy.data.objects.remove(ob, do_unlink=True)
            removed.append(str(nm))
        except Exception:
            continue
        if me is not None and me.users == 0:
            try:
                bpy.data.meshes.remove(me, do_unlink=True)
            except Exception:
                pass
    return removed


def _circle_pts(n, rx, ry=None, cx=0.0, cy=0.0):
    ry = rx if ry is None else ry
    return [[cx + rx * math.cos(2.0 * math.pi * k / float(n)),
             cy + ry * math.sin(2.0 * math.pi * k / float(n))] for k in range(int(n))]


def _meshes_equal(ob_a, ob_b, n=64):
    if not ob_a or not ob_b:
        return False, {"error": "object_missing", "a": ob_a, "b": ob_b}
    a, b = bpy.data.objects.get(str(ob_a)), bpy.data.objects.get(str(ob_b))
    if a is None or b is None or a.type != "MESH" or b.type != "MESH":
        return False, "object missing"
    va = [tuple(round(float(x), 9) for x in v.co) for v in a.data.vertices[:n]]
    vb = [tuple(round(float(x), 9) for x in v.co) for v in b.data.vertices[:n]]
    return (len(a.data.vertices) == len(b.data.vertices) and va == vb), {"verts": len(a.data.vertices)}