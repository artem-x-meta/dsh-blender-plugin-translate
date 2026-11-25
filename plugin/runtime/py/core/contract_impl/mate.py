# -*- coding: utf-8 -*-
"""Split from contract.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403
from .fingerprint import _r4

# ============================================================================

def _r6(x):
    try:
        return round(float(x), 6)
    except Exception:
        return x


def _units():
    """Scene unit conversion → (metres/unit, millimetres/unit). Every mm-based threshold goes through it; never hard-code (project rule)."""
    m = 1.0
    try:
        m = float(bpy.context.scene.unit_settings.scale_length) or 1.0
    except Exception:
        m = 1.0
    return m, m * 1000.0


def _units_block(m_per_unit, mm_per_unit):
    try:
        sys_name = str(bpy.context.scene.unit_settings.system)
    except Exception:
        sys_name = "?"
    return {"m_per_unit": _r6(m_per_unit), "mm_per_unit": _r4(mm_per_unit),
            "scale_length": _r6(m_per_unit), "unit_system": sys_name,
            "note": "Rule: every *_mm field = the Blender unit value × mm_per_unit; every length in this reply carries a unit suffix"}


def _mesh_data(objs):
    """**Evaluated** meshes of a set of objects → world-space triangles (numpy) + closure + volume.

    Why the evaluated mesh (evaluated_get) rather than ob.data: for a parent whose Boolean modifier is not applied,
    ob.data has **no hole at all** — using ob.data reads "the pin already cuts through" as "the pin floats in mid-air". The evaluated mesh is the final shape.
    Volume comes from the divergence theorem (the same formula as the upstream computeMeshVolume): |Σ a·(b×c)/6|, which is the volume for a closed mesh and junk for an open one
    → so closure and volume are returned together, and callers must never take an open mesh's volume at face value.
    """
    import numpy as np
    dg = bpy.context.evaluated_depsgraph_get()
    tris_all, idx_all, base = [], [], 0
    per_object, skipped = {}, []
    for ob in objs:
        if ob.type != "MESH":
            skipped.append({"object": ob.name, "why": "Not a MESH object (type=%s)" % ob.type})
            continue
        obe = None
        try:
            obe = ob.evaluated_get(dg)
            me = obe.to_mesh()
            if me is None:
                skipped.append({"object": ob.name, "why": "No evaluated mesh"})
                continue
            me.calc_loop_triangles()
            n = len(me.loop_triangles)
            if n == 0:
                skipped.append({"object": ob.name, "why": "0 triangles"})
                continue
            v = np.empty(len(me.vertices) * 3, dtype=np.float64)
            me.vertices.foreach_get("co", v)
            v = v.reshape(-1, 3)
            idx = np.empty(n * 3, dtype=np.int64)
            me.loop_triangles.foreach_get("vertices", idx)
            idx = idx.reshape(-1, 3)
            mw = np.array(obe.matrix_world, dtype=np.float64)
            t = (v[idx.reshape(-1)] @ mw[:3, :3].T + mw[:3, 3]).reshape(-1, 3, 3)
            tris_all.append(t)
            idx_all.append(idx + base)      # per-object vertex ranges do not overlap → the closure test never stitches across objects
            base += len(v)
            per_object[ob.name] = n
        except Exception as e:
            skipped.append({"object": ob.name, "why": "Evaluation failed: %s" % e})
        finally:
            try:
                if obe is not None:
                    obe.to_mesh_clear()
            except Exception:
                pass
    if not tris_all:
        return None
    tris = np.concatenate(tris_all, axis=0)
    idx = np.concatenate(idx_all, axis=0)
    edges = np.concatenate([idx[:, [0, 1]], idx[:, [1, 2]], idx[:, [2, 0]]], axis=0)
    _u, cnt = np.unique(np.sort(edges, axis=1), axis=0, return_counts=True)
    boundary = int((cnt == 1).sum())
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    vol = float(abs(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0))
    return {"tris": tris, "tris_n": int(len(tris)), "per_object": per_object,
            "objects": [o.name for o in objs if o.type == "MESH"], "skipped": skipped,
            "boundary_edges": boundary, "closed": boundary == 0, "volume_m3": vol}


def _tris_diagonal(tris):
    import numpy as np
    lo = tris.min(axis=(0, 1))
    hi = tris.max(axis=(0, 1))
    d = hi - lo
    return float(np.sqrt(float((d * d).sum()))), lo, hi


def _sample_surface(tris, n):
    """Area-weighted sampling of n points on the triangles (world coordinates) — deterministic, no random numbers.

    Why area weighting: the upstream sampleContactPoints picks "vertices + centroids by stride", so the sampling density follows **vertex density**
    — a large plane (2 triangles) and a thin pin (hundreds of triangles) get disproportionate point counts, and the "contact-point share" then
    drifts with the degree of tessellation. Here the j-th sample falls inside the cumulative-area interval (j+0.5)/n → each sample stands for an equal amount of area,
    so the share is an **area** share (independent of scale and tessellation).
    The position inside a triangle comes from an R2 low-discrepancy sequence (not random numbers): deterministic → repeatable self-tests and identical numbers on two runs of the same model.
    """
    import numpy as np
    if tris is None or len(tris) == 0 or n <= 0:
        return None
    v0, v1, v2 = tris[:, 0], tris[:, 1], tris[:, 2]
    area = 0.5 * np.linalg.norm(np.cross(v1 - v0, v2 - v0), axis=1)
    tot = float(area.sum())
    if tot <= 0:
        return None
    cum = np.cumsum(area) / tot
    j = np.arange(int(n), dtype=np.float64)
    u = (j + 0.5) / float(n)
    pick = np.clip(np.searchsorted(cum, u, side="left"), 0, len(tris) - 1)
    r1 = np.mod((j + 0.5) * 0.7548776662466927, 1.0)     # the two coefficients of the R2 sequence
    r2 = np.mod((j + 0.5) * 0.5698402909980532, 1.0)
    s = np.sqrt(r1)
    w0, w1, w2 = 1.0 - s, s * (1.0 - r2), s * r2
    return v0[pick] * w0[:, None] + v1[pick] * w1[:, None] + v2[pick] * w2[:, None]


def _bvh(tris):
    """Triangles → BVHTree (mathutils, no new dependency). Vertices are not deduplicated: each triangle gets its own three, which is enough and fastest."""
    from mathutils.bvhtree import BVHTree
    import numpy as np
    if tris is None or len(tris) == 0:
        return None
    verts = tris.reshape(-1, 3).tolist()
    polys = np.arange(len(verts), dtype=np.int64).reshape(-1, 3).tolist()
    return BVHTree.FromPolygons(verts, polys)


def _nearest(tree, P):
    """Per-point nearest lookup → (Q hit point, N normal, D distance). Points that cannot be resolved get D=inf (never silently filled with 0)."""
    import numpy as np
    n = len(P)
    Q = np.full((n, 3), np.nan)
    N = np.full((n, 3), np.nan)
    D = np.full(n, np.inf)
    if tree is None or n == 0:
        return Q, N, D
    for i, p in enumerate(P.tolist()):
        loc, nor, _ix, dist = tree.find_nearest(p)
        if loc is None:
            continue
        Q[i] = (loc[0], loc[1], loc[2])
        if nor is not None:
            N[i] = (nor[0], nor[1], nor[2])
        D[i] = dist
    return Q, N, D


def _inside_mask(P, tris):
    """Point inside a closed mesh: ray parity along a fixed slightly-oblique direction (Möller–Trumbore, chunked and vectorised).

    Why not "nearest-point normal dot product" for inside/outside: that is a **near-surface** local test, and it gives the wrong sign for points in cavities or buried deep
    (a pin passing through the bottom of a hole lands exactly in such regions); ray parity is globally exact for a **closed** mesh.
    Why not +X: an axis-aligned ray can pass exactly through a shared edge or vertex and flip the parity — a fixed slightly-oblique direction avoids that
    (deterministic, no random numbers, repeatable self-tests).
    Chunking: (chunk × M) point-triangle pairs are computed at a time, with chunk derived from 1e6 elements, so a large mesh cannot blow up memory.
    """
    import numpy as np
    n = len(P)
    if tris is None or len(tris) == 0 or n == 0:
        return np.zeros(n, dtype=bool)
    d = np.array([1.0, 0.00031, 0.00057])
    d = d / np.linalg.norm(d)
    v0 = tris[:, 0]
    e1 = tris[:, 1] - v0
    e2 = tris[:, 2] - v0
    h = np.cross(d, e2)
    a = np.einsum("ij,ij->i", e1, h)
    ok = np.abs(a) > 1e-14
    f = np.zeros_like(a)
    f[ok] = 1.0 / a[ok]
    M = len(tris)
    chunk = max(1, min(n, int(1000000 / max(1, M))))
    hits = np.zeros(n, dtype=np.int64)
    for i0 in range(0, n, chunk):
        s = P[i0:i0 + chunk][:, None, :] - v0[None, :, :]
        u = np.einsum("nmj,mj->nm", s, h) * f[None, :]
        q = np.cross(s, e1[None, :, :])
        v = np.einsum("nmj,j->nm", q, d) * f[None, :]
        t = np.einsum("nmj,mj->nm", q, e2) * f[None, :]
        hit = ok[None, :] & (u >= -1e-12) & (v >= -1e-12) & ((u + v) <= 1.0 + 1e-12) & (t > 1e-12)
        hits[i0:i0 + chunk] = hit.sum(axis=1)
    return (hits % 2) == 1


def _pt_tri_dist(P, tris):
    """Point-to-triangle nearest distance (pure numpy, no BVH) — the use_bvh=false fallback plus an independent cross-check of the BVH result.

    Algorithm: closest-point-on-triangle from Ericson, Real-Time Collision Detection §5.1.5.
    The seven vertex/edge/face regions are mutually exclusive, so cascading masks can cover them one by one (later writes overwrite earlier ones).
    Why keep this path: the BVH is the workhorse, and nobody notices when the workhorse computes nonsense — an independently implemented algorithm cross-checks it,
    and use_bvh=false still yields real numbers (this repo's anti-Goodhart discipline: verify through a second computational path).
    """
    import numpy as np
    n = len(P)
    dmin = np.full(n, np.inf)
    if tris is None or len(tris) == 0 or n == 0:
        return dmin
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    ab, ac, bc = b - a, c - a, c - b
    M = len(tris)
    chunk = max(1, min(n, int(1000000 / max(1, M))))

    def _safe(x):
        return np.where(np.abs(x) > 1e-18, x, 1.0)

    for i0 in range(0, n, chunk):
        Pp = P[i0:i0 + chunk][:, None, :]
        ap, bp, cp = Pp - a[None], Pp - b[None], Pp - c[None]
        d1 = np.einsum("nmj,mj->nm", ap, ab); d2 = np.einsum("nmj,mj->nm", ap, ac)
        d3 = np.einsum("nmj,mj->nm", bp, ab); d4 = np.einsum("nmj,mj->nm", bp, ac)
        d5 = np.einsum("nmj,mj->nm", cp, ab); d6 = np.einsum("nmj,mj->nm", cp, ac)
        m_a = (d1 <= 0) & (d2 <= 0)
        m_b = (~m_a) & (d3 >= 0) & (d4 <= d3)
        m_c = (~m_a) & (~m_b) & (d6 >= 0) & (d5 <= d6)
        pre = m_a | m_b | m_c
        vc = d1 * d4 - d3 * d2
        m_ab = (~pre) & (vc <= 0) & (d1 >= 0) & (d3 <= 0)
        pre = pre | m_ab
        vb = d5 * d2 - d1 * d6
        m_ac = (~pre) & (vb <= 0) & (d2 >= 0) & (d6 <= 0)
        pre = pre | m_ac
        va = d3 * d6 - d5 * d4
        m_bc = (~pre) & (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
        denom = va + vb + vc
        inv = 1.0 / _safe(denom)
        Q = a[None] + ab[None] * (vb * inv)[..., None] + ac[None] * (vc * inv)[..., None]
        Q = np.where(m_ab[..., None], a[None] + ab[None] * (d1 / _safe(d1 - d3))[..., None], Q)
        Q = np.where(m_ac[..., None], a[None] + ac[None] * (d2 / _safe(d2 - d6))[..., None], Q)
        Q = np.where(m_bc[..., None], b[None] + bc[None] * ((d4 - d3) / _safe((d4 - d3) + (d5 - d6)))[..., None], Q)
        Q = np.where(m_c[..., None], c[None], Q)
        Q = np.where(m_b[..., None], b[None], Q)
        Q = np.where(m_a[..., None], a[None], Q)
        dmin[i0:i0 + chunk] = np.linalg.norm(Pp - Q, axis=2).min(axis=1)
    return dmin


def _overlap_estimate(trisA, trisB, volA, volB, closedA, closedB, samples=VOL_SAMPLES):
    """Overlapping-volume estimate: low-discrepancy sampling inside the A/B world-AABB **intersection box** + a double inside test.

    Upstream recompiles with OpenSCAD's intersection() to get an exact overlap volume (a second CSG pass); this repo has no CSG compiler,
    so it uses Monte Carlo: take samples low-discrepancy points in the intersection box → the ray-parity share that is "inside A and inside B at the same time" × box volume
    = an **unbiased estimate** of the overlap volume. The binomial standard error is reported alongside — this is an estimate, not an exact value, so do not use it as one.
    The fraction's denominator is min(volA, volB) ("how much of the smaller part" is what carries engineering meaning); when the denominator is unreliable you get None plus a reason.
    """
    import numpy as np
    out = {"samples": int(samples), "box_volume_mm3": None, "overlap_volume_mm3": None,
           "frac_of_box": None, "frac_of_smaller": None, "stderr_frac": None,
           "reliable": False, "why": []}
    if trisA is None or trisB is None or len(trisA) == 0 or len(trisB) == 0:
        out["why"].append("One side has no triangles")
        return out
    loA, hiA = trisA.min(axis=(0, 1)), trisA.max(axis=(0, 1))
    loB, hiB = trisB.min(axis=(0, 1)), trisB.max(axis=(0, 1))
    lo = np.maximum(loA, loB); hi = np.minimum(hiA, hiB)
    if np.any(hi <= lo):
        out["box_volume_mm3"] = 0.0
        out["overlap_volume_mm3"] = 0.0
        out["frac_of_box"] = 0.0
        out["frac_of_smaller"] = 0.0
        out["reliable"] = True
        out["why"].append("The two AABBs do not intersect → the overlap volume must be 0 (exact, no sampling needed)")
        return out
    n = int(max(32, samples))
    j = np.arange(1, n + 1, dtype=np.float64)

    def vdc(base):
        x = j.copy(); o = np.zeros(n); f = 1.0 / base
        while x.max() > 0:
            o += f * np.mod(x, base); x = np.floor(x / base); f /= base
        return o
    frac = np.stack([vdc(2), vdc(3), vdc(5)], axis=1)
    P = lo[None, :] + (hi - lo)[None, :] * frac
    inA = _inside_mask(P, trisA)
    inB = _inside_mask(P, trisB)
    both = int((inA & inB).sum())
    f = both / float(n)
    box_vol = float(np.prod(hi - lo))
    ov = box_vol * f
    _m_per_unit, mm_per_unit = _units()
    mm3 = mm_per_unit ** 3   # volume is length **cubed**: mm_per_unit³ is required here.
    # A pitfall we actually hit: using mm_per_unit (1000 instead of 1e9) reported a 400 mm³ overlap as 0.0004 mm³,
    # while the fractions were right (they are dimensionless) → the number looked "plausible" yet was off by 1e6; a dedicated self-test assertion now pins it down.
    out["box_volume_mm3"] = _r4(box_vol * mm3)
    out["overlap_volume_mm3"] = _r4(ov * mm3)
    out["frac_of_box"] = _r4(f)
    out["stderr_frac"] = _r6(math.sqrt(max(f * (1.0 - f), 0.0) / n))
    small = min(float(volA or 0.0), float(volB or 0.0))
    if small > 0:
        out["frac_of_smaller"] = _r4(ov / small)
    else:
        out["why"].append("The smaller part's volume is 0 → no fraction (no fake numbers)")
    out["reliable"] = bool(closedA and closedB and small > 0)
    if not (closedA and closedB):
        out["why"].append("One mesh is not closed (it has boundary edges) → ray parity and volume are only rough estimates")
    if f == 0.0:
        out["why"].append("Not one of the %d samples in the intersection box lands inside both parts at once → overlap < 1/%d of the box volume" % (n, n))
    return out


def _mate_measure(mdA, mdB, mm_per_unit, PA, PB, contact_max_m):
    """Shared measurement of two parts on their **real meshes**: contact points / gap distribution (mm) / penetration (mm) / overlap-volume estimate.

    Why it is factored out: c_mate_check (the three-state verdict) and c_check_interface (which adds a mesh-grade view to the old bbox one)
    measure the same thing, and two copies would inevitably drift — one implementation, two call sites, so changing a criterion changes only this file.
    Returns {"used_a","used_b","contact","gap","penetration","overlap","min_a_mm","contact_max_m"}.
    """
    import numpy as np
    QA, _NA, DA = _nearest(_bvh(mdB["tris"]), PA)
    QB, _NB, DB = _nearest(_bvh(mdA["tris"]), PB)
    iA = np.where(DA <= contact_max_m)[0]
    iB = np.where(DB <= contact_max_m)[0]
    fracA = float(len(iA)) / float(len(PA))
    fracB = float(len(iB)) / float(len(PB))
    min_a_mm = (float(np.nanmin(DA)) * mm_per_unit) if np.isfinite(DA).any() else None
    cA = PA[iA] if len(iA) else None
    cB = PB[iB] if len(iB) else None
    if cA is not None:
        anchor, anchor_src = cA.mean(axis=0), "mean of the A-side contact points"
    elif cB is not None:
        anchor, anchor_src = cB.mean(axis=0), "mean of the B-side contact points (no contact points on the A side)"
    else:
        anchor, anchor_src = None, "no contact points"
    normal = None
    if cA is not None and cB is not None:
        dv = cA.mean(axis=0) - cB.mean(axis=0)
        nv = float(np.linalg.norm(dv))
        normal = (dv / nv) if nv > 1e-9 else None
    gap_units = np.concatenate([DA[iA], DB[iB]]) if (len(iA) or len(iB)) else np.zeros(0)
    gap_mm = gap_units * mm_per_unit
    if len(gap_mm):
        p10, p50, p90 = np.percentile(gap_mm, [10, 50, 90])
        gap = {"n": int(len(gap_mm)), "median_mm": _r4(p50), "mean_mm": _r4(gap_mm.mean()),
               "min_mm": _r4(gap_mm.min()), "max_mm": _r4(gap_mm.max()),
               "p10_mm": _r4(p10), "p90_mm": _r4(p90),
               "median_a_mm": _r4(np.median(DA[iA] * mm_per_unit)) if len(iA) else None,
               "median_b_mm": _r4(np.median(DB[iB] * mm_per_unit)) if len(iB) else None,
               "source": "A+B distances from both directions merged"}
    else:
        gap = {"n": 0, "median_mm": None, "mean_mm": None, "min_mm": None, "max_mm": None,
               "p10_mm": None, "p90_mm": None, "median_a_mm": None, "median_b_mm": None,
               "source": "no contact points → no gap to report"}
    pen = {"status": "skipped", "tested": False, "points": 0, "depth_max_mm": None,
           "depth_mean_mm": None, "surface_inside_frac": None, "direction": "A→B + B→A",
           "rule": "inside/outside = ray parity (globally exact for closed meshes); depth = nearest-point distance (SDF approximation)"}
    if INSIDE_MAX_TRIS > 0 and (mdA["tris_n"] > INSIDE_MAX_TRIS or mdB["tris_n"] > INSIDE_MAX_TRIS):
        pen["status"] = "skipped_too_big"
        pen["why"] = "mesh faces %d/%d > inside-test cap %d → no intrusion test performed" % (mdA["tris_n"], mdB["tris_n"], INSIDE_MAX_TRIS)
    elif not (mdA["closed"] and mdB["closed"]):
        pen["status"] = "unreliable_mesh"
        pen["why"] = "mesh not closed (boundary edges A=%d / B=%d) → ray parity is unreliable, so no intrusion conclusion holds" % (
            mdA["boundary_edges"], mdB["boundary_edges"])
    else:
        inB = _inside_mask(PA, mdB["tris"])
        inA = _inside_mask(PB, mdA["tris"])
        pa = np.where(inB & np.isfinite(DA))[0]
        pb = np.where(inA & np.isfinite(DB))[0]
        dep = np.concatenate([DA[pa], DB[pb]]) if (len(pa) or len(pb)) else np.zeros(0)
        pen["status"] = "ok"
        pen["tested"] = True
        pen["points"] = int(len(dep))
        pen["points_a_in_b"] = int(len(pa))
        pen["points_b_in_a"] = int(len(pb))
        pen["surface_inside_frac"] = _r6(float(len(dep)) / float(len(PA) + len(PB)))
        pen["depth_max_mm"] = _r4(dep.max() * mm_per_unit) if len(dep) else 0.0
        pen["depth_mean_mm"] = _r4(dep.mean() * mm_per_unit) if len(dep) else 0.0
        pen["mesh_closed"] = {"a": mdA["closed"], "b": mdB["closed"]}
    contact = {"close_a": int(len(iA)), "close_b": int(len(iB)),
               "area_fraction_a": _r6(fracA), "area_fraction_b": _r6(fracB),
               "contact_area_fraction": _r6(max(fracA, fracB)),
               "rule": "computed once per direction, the larger wins (upstream: normalise by the smaller part so the larger part's surface area cannot dilute it)",
               "anchor_world": ([_r6(x) for x in anchor] if anchor is not None else None),
               "anchor_source": anchor_src,
               "contact_normal": ([_r6(x) for x in normal] if normal is not None else None),
               "contact_normal_rule": "normalised difference between the A/B contact-point cluster means (degenerates when the clusters coincide; then null)"}
    ov = None
    if VOL_MAX_TRIS <= 0 or (mdA["tris_n"] + mdB["tris_n"]) <= VOL_MAX_TRIS:
        ov = _overlap_estimate(mdA["tris"], mdB["tris"], mdA["volume_m3"], mdB["volume_m3"],
                               mdA["closed"], mdB["closed"])
    return {"used_a": int(len(PA)), "used_b": int(len(PB)), "contact": contact, "gap": gap,
            "penetration": pen, "overlap": ov, "min_a_mm": min_a_mm, "contact_max_m": contact_max_m}


def _fit_value(cls):
    """asm_fit(cls) four classes (values lifted verbatim from assembly_features.json); an unknown class falls back to location as upstream does."""
    c = str(cls) if cls is not None else None
    if c in FIT_TABLE:
        return FIT_TABLE[c], (None if c == FIT_DEFAULT_CLS else "class=%s" % c)
    return FIT_TABLE[FIT_DEFAULT_CLS], "Unknown fit class '%s' → falls back to location(0.15 mm) like upstream asm_fit" % cls


def _aabb_pairs(objs):
    """AABB sweep-and-prune along x → candidate index pairs. The same coarse filter as check_interference (the old op is unchanged)."""
    import numpy as np
    n = len(objs)
    if n < 2:
        return []
    mn = np.empty((n, 3)); mx = np.empty((n, 3))
    for i, ob in enumerate(objs):
        (a, b) = _bbox(ob)
        mn[i] = a; mx[i] = b
    order = np.argsort(mn[:, 0])
    out = []
    for ii in range(n):
        i = int(order[ii]); jj = ii + 1
        while jj < n:
            j = int(order[jj])
            if mn[j][0] > mx[i][0]:
                break
            if (mn[i][1] <= mx[j][1] and mx[i][1] >= mn[j][1]
                    and mn[i][2] <= mx[j][2] and mx[i][2] >= mn[j][2]):
                out.append((i, j))
            jj += 1
    return out


def _iface_hint(contact, gap, pen):
    """One-line reading hint for check_interface (draws no conclusion, only turns numbers into words — the verdict belongs to mate_check)."""
    if gap.get("n") == 0:
        return "Not mated: 0 sample points inside the contact band (the two parts never come close on the mesh)"
    dep = pen.get("depth_max_mm")
    if pen.get("tested") and dep is not None and dep > MATE_DEPTH_EPS_MM:
        return "Intrusion: max penetration %.3f mm > %.2f mm threshold (the pin is pressed into the parent material; not a fit)" % (dep, MATE_DEPTH_EPS_MM)
    return "In contact: per-side median gap %.4f mm, contact area share %.3f, max penetration %s mm" % (
        gap.get("median_mm") or 0.0, contact.get("contact_area_fraction") or 0.0,
        pen.get("depth_max_mm") if pen.get("tested") else "not tested")


def _c_mate_check_p1(_state):
    conn_id, contact_max_mm, depth_eps_mm, fit, nominal = (
        _state["conn_id"], _state["contact_max_mm"], _state["depth_eps_mm"], _state["fit"], _state["nominal"])
    samples, tol_mm = _state["samples"], _state["tol_mm"]
    expected_mm = (_state.get("expected_mm"))
    try:
        import numpy as np
        st = _store()
        conn = st["connections"].get(str(conn_id))
        if not conn:
            return _j({"ok": False, "verdict": "unresolved", "connection": conn_id, "measured": False,
                       "error": "Connection not registered: %s" % conn_id,
                       "why": ["Connection not registered → no two ends to measure (empty output, so no verdict)"],
                       "free_params": [{"param": "conn_id", "why": "Run register_component + register_connection first to build the contract"}]})
        allA, allB = _component_objects(conn["a"]), _component_objects(conn["b"])
        A = [o for o in allA if o.type == "MESH"]
        B = [o for o in allB if o.type == "MESH"]
        m_per_unit, mm_per_unit = _units()
        ub = _units_block(m_per_unit, mm_per_unit)
        if not A or not B:
            return _j({"ok": False, "verdict": "unresolved", "connection": conn_id, "measured": False,
                       "error": "The component has no measurable mesh objects (empty output → no verdict)", "units": ub,
                       "a": {"id": conn["a"], "registered": len(allA), "mesh": len(A)},
                       "b": {"id": conn["b"], "registered": len(allB), "mesh": len(B)},
                       "why": ["a=%s has %d mesh objects / b=%s has %d mesh objects → nothing to measure, and no forced either/or is allowed"
                               % (conn["a"], len(A), conn["b"], len(B))],
                       "free_params": [{"param": "component objects", "why": "Put the object names actually taking part in the fit into register_component"}]})
        mdA, mdB = _mesh_data(A), _mesh_data(B)
        if mdA is None or mdB is None or mdA["tris_n"] == 0 or mdB["tris_n"] == 0:
            return _j({"ok": False, "verdict": "unresolved", "connection": conn_id, "measured": False,
                       "error": "One of the two ends has no triangles (empty after evaluation)",
                       "a_tris": (mdA or {}).get("tris_n"), "b_tris": (mdB or {}).get("tris_n"),
                       "skipped": (mdA or {}).get("skipped"), "units": ub})
        if MATE_MAX_TRIS > 0 and (mdA["tris_n"] > MATE_MAX_TRIS or mdB["tris_n"] > MATE_MAX_TRIS):
            return _j({"ok": False, "verdict": "unresolved", "connection": conn_id, "measured": False,
                       "error": "Mesh too large, not judged (large meshes are always analyzed=false; never a silent downgrade)",
                       "a_tris": mdA["tris_n"], "b_tris": mdB["tris_n"], "limit": MATE_MAX_TRIS, "units": ub})
        diag_m, _lo, _hi = _tris_diagonal(np.concatenate([mdA["tris"], mdB["tris"]], axis=0))
        contact_max_m = (float(contact_max_mm) / mm_per_unit) if contact_max_mm is not None \
            else DEFAULT_CONTACT_DISTANCE_FRAC * diag_m
        if not (contact_max_m > 0):
            return _j({"ok": False, "verdict": "unresolved", "connection": conn_id, "measured": False,
                       "error": "contact_max ≤ 0 (the merged bbox diagonal is 0, or the argument is invalid)", "units": ub})
        used_req = int(samples) if samples else 0
        n = int(max(1, min(used_req, CONTACT_SAMPLE_CAP)))
        PA = _sample_surface(mdA["tris"], n)
        PB = _sample_surface(mdB["tris"], n)
        if PA is None or PB is None:
            return _j({"ok": False, "verdict": "unresolved", "connection": conn_id, "measured": False,
                       "error": "Sampling failed (zero-area mesh?)", "units": ub})
        meas = _mate_measure(mdA, mdB, mm_per_unit, PA, PB, contact_max_m)
        contact, gap, pen, ov = meas["contact"], meas["gap"], meas["penetration"], meas["overlap"]
        fracA, fracB = contact["area_fraction_a"], contact["area_fraction_b"]
        used_min = min(meas["used_a"], meas["used_b"])
        free = []
        if n < CONTACT_SAMPLE_CAP:
            free.append({"param": "samples", "now": n, "max": CONTACT_SAMPLE_CAP,
                         "why": "Fewer samples means more variance in the contact share and the median gap"})
        if fit is None and nominal is None:
            free.append({"param": "nominal/fit", "why": "Give a fit class (clearance|location|press|snap) or the expected per-side gap nominal(mm) directly"})
        if tol_mm is None:
            free.append({"param": "tol_mm", "now": FIT_DEFAULT_TOL_MM,
                         "why": "The default is a measurement+process band; resolving fit classes needs something smaller (e.g. 0.03), but mesh noise may get there first"})
        if contact_max_mm is None:
            free.append({"param": "contact_max_mm", "now": _r4(contact_max_m * mm_per_unit),
                         "why": "Default is 1.5%× the merged diagonal; lower it to check small features (thin walls/small holes) more tightly"})
        if pen["status"] != "ok":
            free.append({"param": "mesh (closed / reduced faces)", "why": pen.get("why", "no intrusion test performed")})
        # ---- three-state verdict ----
        why, verdict = [], None
        if nominal is not None:
            expected_mm, fit_note = float(nominal), "expected per-side gap supplied directly by the caller"
        elif fit is not None:
            expected_mm, fit_note = _fit_value(fit)
        else:
            expected_mm, fit_note = None, None
        tol_used = float(tol_mm) if tol_mm is not None else FIT_DEFAULT_TOL_MM
        tol_src = "caller" if tol_mm is not None else "default"
        eps_mm = float(depth_eps_mm) if depth_eps_mm is not None else MATE_DEPTH_EPS_MM
        allowed_mm = eps_mm if (expected_mm is None or expected_mm >= 0) else max(eps_mm, abs(expected_mm) + tol_used)
    finally:
        _state.update((k, v) for k, v in locals().items() if k != "_state")

def _c_mate_check_p2(_state):
    PA, PB, allowed_mm, conn, conn_id = (
        _state.get("PA"), _state.get("PB"), _state.get("allowed_mm"), _state.get("conn"), _state["conn_id"])
    contact, contact_max_m, contact_max_mm, diag_m, eps_mm = (
        _state.get("contact"), _state.get("contact_max_m"), _state["contact_max_mm"], _state.get("diag_m"), _state.get("eps_mm"))
    expected_mm, fit, fit_note, fracA, fracB = (
        _state.get("expected_mm"), _state["fit"], _state.get("fit_note"), _state.get("fracA"), _state.get("fracB"))
    free, gap, mdA, mdB, meas = (
        _state.get("free"), _state.get("gap"), _state.get("mdA"), _state.get("mdB"), _state.get("meas"))
    mm_per_unit, nominal, ov, pen, tol_src = (
        _state.get("mm_per_unit"), _state["nominal"], _state.get("ov"), _state.get("pen"), _state.get("tol_src"))
    tol_used, ub, used_min, used_req, why = (
        _state.get("tol_used"), _state.get("ub"), _state.get("used_min"), _state.get("used_req"), _state.get("why"))
    hi_mm, lo_mm, med, verdict = (_state.get("hi_mm"), _state.get("lo_mm"), _state.get("med"), _state.get("verdict"))
    try:
        if used_min < CONTACT_MIN_POINTS:
            verdict = "unresolved"
            why.append("fewer than %d samples (measured A=%d / B=%d points) → insufficient evidence, no forced either/or (upstream CONTACT_MIN_POINTS)"
                       % (CONTACT_MIN_POINTS, len(PA), len(PB)))
        elif expected_mm is None:
            verdict = "unresolved"
            why.append("Neither fit nor nominal was given → there is no expected per-side gap to compare against, and no forced either/or is allowed")
        elif gap["n"] == 0:
            verdict = "refuted"
            why.append("**Not mated at all**: not a single sample point in either direction falls inside the %.3f mm contact band (0/%d contact points, nearest on the A side %s mm)"
                       % (contact_max_m * mm_per_unit, used_min,
                          ("%.3f" % meas["min_a_mm"]) if meas.get("min_a_mm") is not None else "∞"))
        elif pen["tested"] and pen["depth_max_mm"] is not None and pen["depth_max_mm"] > allowed_mm:
            verdict = "refuted"
            why.append("Intrusion too deep: max penetration %.3f mm > allowed %.3f mm (%s) → the pin is pressed into the parent material; this is not a fit"
                       % (pen["depth_max_mm"], allowed_mm,
                          "relaxed by the fit press class" if allowed_mm > eps_mm else "depth_eps default 0.2 mm"))
        else:
            lo_mm, hi_mm = expected_mm - tol_used, expected_mm + tol_used
            med = gap["median_mm"]
            if pen["status"] != "ok":
                verdict = "unresolved"
                why.append("Measured per-side median gap %.4f mm is inside [%.4f, %.4f] (expected %.4f ± %.4f), but %s → "
                           "only the gap was judged, not interpenetration, so it cannot be read as supported"
                           % (med, lo_mm, hi_mm, expected_mm, tol_used, pen.get("why", "no intrusion test performed")))
            elif lo_mm <= med <= hi_mm:
                verdict = "supported"
                why.append("Measured per-side median gap %.4f mm (mean %.4f, n=%d) is inside the expected %.4f ± %.4f mm → supported; "
                           "contact area share %.3f, max penetration %.3f mm ≤ allowed %.3f mm"
                           % (med, gap["mean_mm"], gap["n"], expected_mm, tol_used, max(fracA, fracB),
                              pen["depth_max_mm"], allowed_mm))
            else:
                verdict = "refuted"
                why.append("Measured per-side median gap %.4f mm (mean %.4f, n=%d) falls outside [%.4f, %.4f] (expected %.4f ± %.4f) → refuted"
                           % (med, gap["mean_mm"], gap["n"], lo_mm, hi_mm, expected_mm, tol_used))
        if fit_note:
            why.append(fit_note)
        if nominal is None and fit is not None:
            why.append("nominal derived from the fit table (assembly_features.json: fits.%s.per_side_mm = %.2f mm, per side)"
                       % (fit if str(fit) in FIT_TABLE else FIT_DEFAULT_CLS, expected_mm))
        srule = "Shared-nominal discipline: the female and male must derive from one and the same nominal (female = nominal + 2×asm_fit(cls), male = nominal)" \
                ", and writing a literal in two places is forbidden — the per-side median gap this op measures is that discipline's checkup metric."
        ev = {"units": ub,
              "contact_max_m": _r6(contact_max_m), "contact_max_mm": _r4(contact_max_m * mm_per_unit),
              "contact_max_rule": "1.5%% × the merged bbox diagonal of the two parts (currently %.3f mm)%s"
                                  % (diag_m * mm_per_unit, ", overridden by the caller" if contact_max_mm is not None else ""),
              "merged_diagonal_mm": _r4(diag_m * mm_per_unit),
              "samples": {"requested": used_req, "cap": CONTACT_SAMPLE_CAP, "used_a": int(len(PA)),
                          "used_b": int(len(PB)), "samples_used": int(used_min),
                          "rule": "area-weighted + R2 low-discrepancy sequence (deterministic); hard cap of %d points (same convention as upstream)" % CONTACT_SAMPLE_CAP},
              "contact": contact,
              "gap_mm": gap, "penetration": pen,
              "overlap_volume": (ov or {"skipped": True, "why": "triangles > %d, Monte-Carlo volume estimate skipped" % VOL_MAX_TRIS}),
              "fit": {"class": (str(fit) if fit is not None else None),
                      "table_per_side_mm": dict(FIT_TABLE),
                      "expected_gap_mm": expected_mm, "expected_source": fit_note or "caller/none",
                      "tol_mm": tol_used, "tol_source": tol_src,
                      "band_mm": ([_r4(expected_mm - tol_used), _r4(expected_mm + tol_used)] if expected_mm is not None else None),
                      "allowed_penetration_mm": _r4(allowed_mm)},
              "shared_nominal_rule": srule,
              "verdict_inputs": {"samples_used": int(used_min), "contact_points": gap["n"],
                                 "median_gap_mm": gap["median_mm"], "depth_max_mm": pen.get("depth_max_mm")},
              "objects": {"a": mdA["objects"], "b": mdB["objects"], "a_tris": mdA["tris_n"], "b_tris": mdB["tris_n"],
                          "closed": {"a": mdA["closed"], "b": mdB["closed"]},
                          "volume_mm3": {"a": _r4(mdA["volume_m3"] * (mm_per_unit ** 3)),
                                         "b": _r4(mdB["volume_m3"] * (mm_per_unit ** 3))}}}
        res = {"ok": True, "measured": True, "connection": conn_id, "a": conn["a"], "b": conn["b"],
               "verdict": verdict, "why": why, "confidence": ("full" if pen["status"] == "ok" else "reduced"),
               "evidence": ev, "free_params": free, "shared_nominal_rule": srule,
               "readonly": "This op does not change connection state (use verify/advance to record state); it only logs",
               "drift_guard": "Re-run after geometry changes: this op measures the current evaluated mesh every time and caches no old numbers"}
        _log("mate_check", {"id": conn_id, "verdict": verdict, "samples": int(used_min),
                            "median_gap_mm": gap["median_mm"], "depth_max_mm": pen.get("depth_max_mm")})
        return _j(res)
    finally:
        _state.update((k, v) for k, v in locals().items() if k != "_state")

def c_mate_check(conn_id, fit=None, nominal=None, tol_mm=None, samples=4000,
                 contact_max_mm=None, depth_eps_mm=None):
    """Fit gate (mesh level): measures contact / gap / intrusion on the **actual meshes** and returns a three-state verdict per fit class.

    How it measures (the rationale lives here; change this block first when changing the algorithm):
      1. Sampling: the A side is sampled with **area weighting** at ≤4000 points (_sample_surface, a deterministic low-discrepancy sequence)
         — each sample stands for an equal amount of area, so the "contact-point share" is an area share.
      2. Nearest point: mathutils BVHTree.FromPolygons builds a **surface** BVH for B → find_nearest per point
         → distances ≤ contact_max (default 1.5% × the merged bbox diagonal of the two parts) count as contact points.
      3. Inside/outside: ray parity (_inside_mask, vectorised Möller–Trumbore) — a global test that never flips even deep inside a cavity;
         the depth magnitude comes from the nearest-point distance (an SDF approximation). Only both together give "how deep the intrusion is".
      4. Per-side gap: mean/median of the contact-point distances (in mm, converted by the scene scale_length, returned with a units block).

    Criterion order (the reason for each step is written here; relaxing a criterion requires editing this comment first and giving measured evidence):
      0) connection not registered / empty component / mesh over the cap / contact_max≤0 → ok:false + verdict=unresolved (empty output never succeeds silently)
      1) fewer than 8 samples → unresolved (upstream CONTACT_MIN_POINTS; two points also produce a number, but it is noise)
      2) neither fit nor nominal given → unresolved (without an expected value there is no way to judge "right", and no forced either/or is allowed)
      3) 0 contact points → **refuted**, naming "not mated". This comes before the gap test: with no contact at all the median is meaningless
      4) penetration depth > allowed depth → **refuted** (a pin pressed into the parent material is not a fit)
         allowed depth = depth_eps_mm (default 0.2 mm); for fit=press (interference) it relaxes to max(eps, |nominal|+tol)
      5) per-side median gap ∈ [nominal-tol, nominal+tol] → supported; otherwise refuted (with the measured numbers attached)
      Honesty clause: when the intrusion test could not run (mesh over INSIDE_MAX_TRIS / mesh not closed), an in-band gap can still only give
         unresolved ("interpenetration not checked" must never be read as "pass" — the same discipline as audit.py's "not analysed can never read as connected").

    Why tol_mm defaults to 0.15 mm: the smallest spacing between the four fit classes is only 0.05 mm (location 0.15 ↔ snap 0.20),
      while the noise floor of mesh measurement (triangulation chord error + sparse sampling) sits at that same magnitude — so the default tolerance is **not** for resolving classes,
      it is a "measurement + process" band: FDM dimensional accuracy is typically ±0.1~0.2 mm, so the midpoint 0.15 was chosen; it also happens to equal location's nominal value,
      making the supported band [0.00, 0.30] mm, which reads as "touching without being crushed". To resolve classes, pass a smaller tol_mm explicitly
      (e.g. 0.03) and accept the premise that "mesh noise may misjudge the class first".

    **Shared-nominal discipline** (the first written rule in assembly_features.json): the female and male must derive from one and the same nominal
      (female = nominal + 2×asm_fit(cls), male = nominal), and writing a literal in two places is forbidden.
      The "per-side median gap" this op measures is that discipline's checkup metric — deviating from nominal ± tol means it has been broken.
      The reply's verdict carries the shared_nominal_rule text verbatim so callers can relay it to a human unchanged.

    Read-only: does not change connection state (use verify/advance to record state); it logs one entry.
    """
    _state = dict(locals())
    for _fn_ in (_c_mate_check_p1, _c_mate_check_p2):
        _r = _fn_(_state)
        if _r is not None:
            return _r
