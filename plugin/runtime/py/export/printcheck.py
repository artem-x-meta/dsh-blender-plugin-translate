# -*- coding: utf-8 -*-
"""DSH manufacturing check (v0.9.6 · upstream integration) — wall thickness and overhang on a 3D print/machining basis.

The old runtime had 0 hits for the thin wall / overhang keywords; audit_* only covers interference/connectivity/envelope, not "can it actually be manufactured".
This module does not depend on Blender's 3D Print Toolbox add-on (that is what upstream blend-ai does): it measures wall thickness itself with BVH rays and
overhang with a normal cone — the results are recomputable and can go into an acceptance receipt.

ops:
    blender_rt_plan(op="print_walls",    args={objects:["Body"], min_mm:1.2, max_samples:4000})   # read-only
    blender_rt_plan(op="print_overhang", args={objects:["Body"], max_angle_deg:45})               # read-only
    blender_rt_plan(op="print_report",   args={objects:["Body"], min_mm:1.2, max_angle_deg:45})   # read-only
    blender_rt_plan(op="print_selftest")

Basis: 1 Blender unit = 1 m (default scene), mm = unit * scale_length * 1000; mm_per_unit overrides it.

v1.0.5 (issue #14): overhang **excludes the bed-contact face** by default — flat-bottomed parts are no longer always judged overhang_ok=false.
        The bed-contact area is listed separately as bed_area_mm2; the old basis (bed face included) is kept in overhang_area_incl_bed_mm2,
        and exclude_bed=False rolls everything back. Criteria: see the print_overhang docstring and bed_caliber in print_help.
"""
import json
import math

import bpy
import mathutils
from mathutils import Vector
from mathutils.bvhtree import BVHTree

PRINT_VERSION = 2   # v2: overhang excludes the bed-contact face by default (issue #14; field basis in print_overhang)


import sys as _sys_kit
_KIT = getattr(_sys_kit.modules.get("dsh_rt_kernel"), "dsh_kit", None)
if _KIT is None:
    raise RuntimeError("printcheck requires the shared kernel K.dsh_kit (injected by KERNEL_BOOTSTRAP)")


_j = _KIT.j  # shared kernel (the original local implementation has been removed)
def _num(v, name, lo=None, hi=None, default=None):
    if v is None:
        if default is None:
            raise ValueError("%s is required" % name)
        return float(default)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError("%s needs a number, got %r" % (name, v))
    f = float(v)
    if not math.isfinite(f):
        raise ValueError("%s must be a finite number (NaN/Inf corrupts the .blend)" % name)
    if lo is not None and f < lo:
        raise ValueError("%s=%g is below the lower bound %g" % (name, f, lo))
    if hi is not None and f > hi:
        raise ValueError("%s=%g is above the upper bound %g" % (name, f, hi))
    return f


def _objs(objects=None, scope="ACTIVE"):
    if objects:
        names = [objects] if isinstance(objects, str) else list(objects)
        out = []
        for n in names:
            ob = bpy.data.objects.get(str(n))
            if ob is None:
                raise ValueError("Object does not exist: %s" % n)
            if ob.type != "MESH":
                raise ValueError("%s is not a mesh (type=%s)" % (n, ob.type))
            out.append(ob)
        if not out:
            raise ValueError("objects is empty")
        return out
    sc = str(scope or "ACTIVE").upper()
    if sc == "ACTIVE":
        ob = bpy.context.view_layer.objects.active
        if ob is None or ob.type != "MESH":
            raise ValueError("no active mesh object")
        return [ob]
    if sc == "SELECTED":
        sel = [o for o in bpy.context.selected_objects if o.type == "MESH"]
        if not sel:
            raise ValueError("no selected mesh")
        return sel
    if sc == "VISIBLE":
        vis = [o for o in bpy.context.view_layer.objects if o.type == "MESH" and o.visible_get()]
        if not vis:
            raise ValueError("no visible mesh")
        return vis
    if sc == "ALL":
        allm = [o for o in bpy.data.objects if o.type == "MESH"]
        if not allm:
            raise ValueError("the scene has no mesh")
        return allm
    raise ValueError("unknown scope: %s" % scope)


def _mm_per_unit(mm_per_unit=None):
    if mm_per_unit is not None:
        return _num(mm_per_unit, "mm_per_unit", 1e-9, 1e9)
    try:
        return _KIT.units()
    except Exception:
        return 1000.0


def _scale_avg(ob):
    s = ob.matrix_world.to_scale()
    return (abs(s[0]) + abs(s[1]) + abs(s[2])) / 3.0 or 1.0


def _bvh(me):
    verts = [v.co.copy() for v in me.vertices]
    polys = [tuple(p.vertices) for p in me.polygons]
    return BVHTree.FromPolygons(verts, polys, all_triangles=False, epsilon=0.0)


def print_walls(objects=None, scope="ACTIVE", min_mm=1.0, max_samples=4000, mm_per_unit=None,
                samples=None):
    """Wall thickness: cast a ray from each sampled face centre along -normal; the hit distance is the local thickness (measured in local space, then converted through the scale)."""
    thr_mm = _num(min_mm, "min_mm", 1e-6, 1e6)
    cap = int(_num(max_samples if samples is None else samples, "max_samples", 16, 200000))
    mmu = _mm_per_unit(mm_per_unit)
    obs = _objs(objects, scope)
    out = []
    for ob in obs:
        me = ob.data
        nf = len(me.polygons)
        if nf == 0:
            out.append({"name": ob.name, "ok": False, "error": "0 faces"})
            continue
        bvh = _bvh(me)
        sc = _scale_avg(ob)
        # The resolution ceiling of a thin-wall measurement = the local face size: faces rebuilt from voxels are ~60mm and a non-planar quad's
        # normal disagrees with its triangulated normal, so a ray offset 1e-5 from the face centre hits the same facet at once and
        # reads a 2m sphere as a 0.02mm thin wall (measured: 26% of samples misjudged). Therefore:
        #   1) offset the origin 0.25 * local face size along -normal;
        #   2) treat any hit distance <= 0.5 * local face size as "the same surface facet" and skip it;
        #   3) report resolution_mm — a min_mm conclusion below the resolution is untrustworthy and must say so.
        diag = max(float(ob.dimensions.length), 1e-9)
        fsize0 = max((math.sqrt(max(float(pp.area), 0.0)) for pp in me.polygons), default=0.0)
        stride = max(1, nf // cap)
        vals = []
        worst = []
        self_hits = 0
        sizes = []
        for i in range(0, nf, stride):
            p = me.polygons[i]
            n = p.normal.copy()
            if n.length < 1e-12:
                continue
            n.normalize()
            fsize = math.sqrt(max(float(p.area), 0.0))
            sizes.append(fsize)
            # v0.9.6 (caught by calibration): the old off = 0.25*face size (off≈8.7mm for a 40x30 face) was **larger than the plate thickness**
            # ⇒ the ray origin ended up outside the part and a thin plate got no sample at all (40x30x0.3mm measured as 30mm, thin=0).
            # Changed to: the origin only steps off its own facet (tiny offset), and the **hit face normal** separates "the same surface facet" from "the opposite wall":
            #   same direction (n·hn > 0) ⇒ still the same facet, keep searching forward; opposite (n·hn < -0.5) ⇒ opposite wall found, take that distance.
            _eps = max(1e-6, fsize * 1e-3)
            off = _eps
            origin = p.center - n * off
            hit = bvh.ray_cast(origin, -n, 1e9)
            _tries = 0
            while hit is not None and hit[3] is not None and _tries < 8:
                _tries += 1
                hn = hit[1]
                if hn is not None and float(n.dot(hn)) < -0.5:
                    break                              # opposite wall ✓
                self_hits += 1
                origin = hit[0] - n * _eps
                hit = bvh.ray_cast(origin, -n, 1e9)
            if hit is None or hit[3] is None:
                continue
            # v0.9.6 (caught by calibration · second real bug): anisotropic scale must not use the average scale —
            # with the base plate z scaled 0.1 (3mm→0.3mm) sc≈0.7, so 0.3mm became 2.1mm ⇒ thin walls missed.
            # Correct approach: transform both the hit point and the face centre by the **world matrix** and then measure the distance (valid for any affine transform).
            _mw = ob.matrix_world
            thick_mm = (_mw @ mathutils.Vector(hit[0]) - _mw @ p.center).length * mmu
            vals.append(thick_mm)
            if thick_mm < thr_mm:
                worst.append({"face": int(i), "mm": round(thick_mm, 4)})
        if not vals:
            out.append({"name": ob.name, "ok": False, "skipped_self_hits": self_hits,
                        "error": "the ray hit no back face (open shell / inward normals?)",
                        "hint": "an open thin shell cannot be measured for thickness: run audit_mesh first to check boundary/normals"})
            continue
        vals.sort()
        n = len(vals)

        def q(f):
            return vals[min(n - 1, max(0, int(f * (n - 1))))]
        thin = [v for v in vals if v < thr_mm]
        rec = {"name": ob.name, "ok": len(thin) == 0, "threshold_mm": thr_mm, "samples": n,
               "sampled_faces": n, "stride": stride, "mm_per_unit": mmu,
               "min_mm": round(vals[0], 4), "p05_mm": round(q(0.05), 4), "median_mm": round(q(0.5), 4),
               "max_mm": round(vals[-1], 4), "thin_samples": len(thin),
               "thin_ratio": round(len(thin) / float(n), 4),
               "skipped_self_hits": self_hits,
               "resolution_mm": round((sorted(sizes)[len(sizes)//2] if sizes else fsize0) * sc * mmu, 4),
               # how fine the ray method itself can resolve (v0.9.6 new logic: the origin only steps off its own facet) — kept separate from the **geometric** resolution above
               "ray_precision_mm": round(max(1e-6, (sorted(sizes)[len(sizes)//2] if sizes else fsize0) * 1e-3) * sc * mmu, 6),
               "worst": sorted(worst, key=lambda r: r["mm"])[:10]}
        res_mm = rec["resolution_mm"]
        hint = ("%d spots below %.3f mm: thin walls will not print / crumble when touched" % (len(thin), thr_mm)) if thin else "no thin walls"
        if thr_mm < res_mm:
            rec["warning"] = ("min_mm=%.3f is below this mesh's measurement resolution %.3f mm: the geometry cannot resolve a wall that thin, so the conclusion is untrustworthy (refine the mesh / lower voxel_size first)" % (thr_mm, res_mm))
        if self_hits:
            hint += "; %d hits within the resolution were skipped as the same surface" % self_hits
        rec["hint"] = hint
        out.append(rec)
    return _j({"ok": all(r.get("ok") for r in out), "objects": out,
               "note": "thickness = nearest hit inward along the face normal; concave corners/thin shells can read optimistic, judge by p05 and thin_ratio"})


def _bed_level_flat(level_areas, tol_mm):
    """Cluster the "horizontal downward" faces by level (within tol_mm they count as one layer) and return the level of the largest-area cluster.

    issue #14: the bed-contact face must not be defined by the "global lowest point" — chamfers/slivers at the bottom edge of a base plate sit below the flat bottom face
    (the reporter measured a lowest point of -0.6905 mm while the flat bottom face sits at z = 0), so the flat bottom face was judged as overhang instead.
    Use "the level of the largest-area horizontal downward layer" as the platform face: the flat bottom face usually has far more area than the slivers.
    """
    clusters = []
    for lvl, area in sorted(level_areas, key=lambda t: t[0]):
        if clusters and abs(lvl - clusters[-1]["ref"]) <= tol_mm:
            c = clusters[-1]
            c["area"] += area
            c["wsum"] += lvl * area
            if c["area"] > 0:
                c["ref"] = c["wsum"] / c["area"]
        else:
            clusters.append({"ref": lvl, "area": area, "wsum": lvl * area})
    if not clusters:
        return None, []
    best = max(clusters, key=lambda c: c["area"])
    return best["ref"], clusters


def _oh_parse(objects, scope, max_angle_deg, up, mm_per_unit, min_area_mm2, exclude_bed, max_list,
              bed_tol_mm, bed_mode, bed_horiz_deg, bed_band_mm):
    """Parameter parsing + selection set; returns (cfg, err)."""
    ang = _num(max_angle_deg, "max_angle_deg", 0.0, 90.0)
    # tol must be > 0: tol=0 makes slivers of "the same flat bottom face split by float noise" judge each other as not touching the bed (measured on the same geometry:
    # 90000mm²@0 + 10000mm²@+1e-9mm, tol=0 ⇒ net overhang 10000, tol=0.2 ⇒ 0, the answer flips with no warning).
    tol = _num(bed_tol_mm, "bed_tol_mm", 1e-9, 1e9)
    horiz = _num(bed_horiz_deg, "bed_horiz_deg", 0.0, 90.0)
    mode = str(bed_mode or "flat").strip().lower()
    if mode not in ("flat", "min"):
        return None, _j({"ok": False, "error": "bed_mode only supports flat|min, got %r" % bed_mode})
    upv = str(up or "Z").upper()
    axis = {"X": Vector((1, 0, 0)), "Y": Vector((0, 1, 0)), "Z": Vector((0, 0, 1))}.get(upv)
    if axis is None:
        return None, _j({"ok": False, "error": "up only supports X/Y/Z, got %r" % up})
    mmu = _mm_per_unit(mm_per_unit)
    min_area = _num(min_area_mm2, "min_area_mm2", 0.0, 1e12, 0.0)
    obs = _objs(objects, scope)
    return {"ang": ang, "tol": tol, "horiz": horiz, "mode": mode, "upv": upv, "axis": axis,
            "down": -axis, "mmu": mmu, "min_area": min_area, "obs": obs,
            "cos_lim": math.cos(math.radians(ang)), "cos_horiz": math.cos(math.radians(horiz)),
            "exclude_bed": exclude_bed, "max_list": max_list,
            "band": _num(bed_band_mm, "bed_band_mm", 0.0, 1e9)}, None


def _oh_faces(obs, cfg):
    """First pass: (level / area / downward-ness) of every face + the set's lowest point; returns (faces, lowest)."""
    # the level uses the face centre (for a horizontal face the face-centre level is the layer level); the lowest point uses real vertices (min mode wants the physical platform).
    # v1.0.5 fixes two old debts around anisotropic scaling (re-verified by measurement, present since v1.0.4):
    #   ① normals must use the **inverse transpose** ((M⁻¹)ᵀ @ n) — the old M.to_3x3() @ n turned a face whose true angle is 16° into 49° under scale(2,1,1)
    #      ⇒ the whole face was dropped from the overhang set (missed); under rotation/uniform scale the two agree.
    #   ② area is computed from the **world-space triangle fan** — the old p.area × (_scale_avg × mmu)² was off by -11.1% under scale(2,1,1)
    #      (1.777e6 vs the true 2e6 mm²).
    axis, mmu, down = cfg["axis"], cfg["mmu"], cfg["down"]
    faces = []      # (ob_index, face_index, level_mm, area_mm2, cos_down)
    lowest = None
    for oi, ob in enumerate(obs):
        me = ob.data
        if len(me.polygons) == 0:
            continue
        mw = ob.matrix_world
        rot = mw.inverted_safe().transposed().to_3x3()
        vco = [v.co.copy() for v in me.vertices]
        for v in me.vertices:
            lv = (mw @ v.co).dot(axis) * mmu
            if lowest is None or lv < lowest:
                lowest = lv
        for i, p in enumerate(me.polygons):
            nrm = (rot @ p.normal)
            if nrm.length < 1e-12:
                continue
            nrm.normalize()
            vs = [mw @ vco[vi] for vi in p.vertices]
            a_world = 0.0
            for k in range(1, len(vs) - 1):
                a_world += (vs[k] - vs[0]).cross(vs[k + 1] - vs[0]).length * 0.5
            faces.append((oi, i, (mw @ p.center).dot(axis) * mmu,
                          a_world * mmu * mmu, nrm.dot(down)))
    return faces, lowest


def _oh_bed(faces, cfg, lowest):
    """Platform face level (flat candidates + bed_band_mm guard + min fallback); returns (bed, used, fallback_why)."""
    # bed_band_mm is the guard for "platform face candidates": if the largest-area horizontal downward face sits further than this from the set's lowest point,
    # it is most likely **not** the platform face but an eave/roof in mid-air (mushroom parts) — treating it as the platform would exclude the entire real overhang
    # and make ok falsely green (measured: 200×200 cap + steep cone stalk ⇒ 40000mm² swallowed, ok=true).
    # In that case always fall back to "lowest point as the platform face" and write the reason into bed_warning.
    tol = cfg["tol"]
    band = cfg["band"]
    cand = None
    if cfg["mode"] == "flat":
        cand, _clusters = _bed_level_flat([(f[2], f[3]) for f in faces if f[4] >= cfg["cos_horiz"]], tol)
    fallback_why = None
    if cfg["mode"] != "flat":
        bed, used = lowest, "min"
    elif cand is None:                      # no horizontal downward face (sphere/revolution?) → fall back to the lowest point
        bed, used = lowest, "min-fallback"
        fallback_why = "no horizontal downward face (sphere/revolution?)"
    elif lowest is not None and (cand - lowest) > band:
        bed, used = lowest, "min-fallback"
        fallback_why = ("the largest-area horizontal downward face sits at %.4f mm, %.4f mm above the set's lowest point (> bed_band_mm=%.4f) "
                        "⇒ it does not look like a platform face (an eave/roof in mid-air, or the whole part floating)" % (cand, cand - lowest, band))
    else:
        bed, used = cand, "flat"
    if bed is None:
        bed = 0.0
    return bed, used, fallback_why


def _oh_accumulate(obs, faces, cfg, bed):
    """Second pass: separate the "bed-contact face" from the "real overhang" by platform face; returns (out, acc)."""
    out = [None] * len(obs)
    acc = {}
    for oi, ob in enumerate(obs):
        if len(ob.data.polygons) == 0:
            out[oi] = {"name": ob.name, "ok": False, "error": "0 faces"}
        else:
            acc[oi] = {"tot": 0.0, "bad_area": 0.0, "bed_area": 0.0, "incl_area": 0.0,
                       "bad": [], "bed": []}
    for (oi, i, lvl, a_mm2, c) in faces:
        a = acc[oi]
        a["tot"] += a_mm2
        if c < cfg["cos_lim"]:
            continue
        a["incl_area"] += a_mm2          # old basis: every downward face counts as overhang
        is_bed = bool(cfg["exclude_bed"]) and (c >= cfg["cos_horiz"]) and (abs(lvl - bed) <= cfg["tol"])
        row = {"face": int(i), "level_mm": round(lvl, 4),
               "angle_deg": round(math.degrees(math.acos(max(-1.0, min(1.0, c)))), 2),
               "area_mm2": round(a_mm2, 4)}
        if is_bed:
            a["bed_area"] += a_mm2
            if len(a["bed"]) < int(cfg["max_list"]):
                a["bed"].append(row)
        else:
            a["bad_area"] += a_mm2
            if len(a["bad"]) < int(cfg["max_list"]):
                a["bad"].append(row)
    return out, acc


def _oh_bed_warning(fallback_why, used, lowest, bed, tol):
    """Bed-contact-face basis warning (fallback reason / level deviation)."""
    if fallback_why:
        return ("%s; the lowest point %.4f mm is used as the platform face instead. ⚠ Do not casually raise bed_band_mm just to 'make it flat' — "
                "that treats a large mid-air plane as the platform face and swallows the entire real overhang (better to over-report conservatively). "
                "To roll back to the v1.0.4 old basis (bed-contact face counted as overhang): exclude_bed=false"
                % (fallback_why, (lowest if lowest is not None else 0.0)))
    if used == "flat" and lowest is not None and (bed - lowest) > tol:
        return ("the bed-contact face level %.4f against the set's lowest point %.4f deviates by %.4f mm (chamfer/slivers below the flat bottom face?)"
                " — if the lowest spot is the real contact face, lower bed_band_mm or use bed_mode=min" % (bed, lowest, bed - lowest))
    return None


def _oh_row(ob, a, cfg, bed, used, lowest, bed_warning):
    """Per-object overhang receipt (net overhang / bed-contact face / old basis / samples)."""
    bad_area, bed_area, incl_area, tot = a["bad_area"], a["bed_area"], a["incl_area"], a["tot"]
    min_area = cfg["min_area"]
    over_min = bad_area > min_area
    hint = ("net overhang area %.2f mm² exceeds the budget %.2f mm²: support is needed or reorient the part" % (bad_area, min_area)) if over_min \
        else "no overhang over budget"
    if bed_area > 0:
        hint += "; excluded the bed-contact face %.2f mm² (%.1f%% of the total surface)" % (
            bed_area, (100.0 * bed_area / tot) if tot > 0 else 0.0)
    rec = {"name": ob.name, "ok": not over_min, "up": cfg["upv"], "max_angle_deg": cfg["ang"],
           "faces": len(ob.data.polygons), "total_area_mm2": round(tot, 4),
           # primary basis (since v1.0.5): net overhang excluding the bed-contact face
           "overhang_area_mm2": round(bad_area, 4),
           "overhang_ratio": round(bad_area / tot, 4) if tot > 0 else None,
           # bed-contact face listed separately (issue #14 suggestion 3)
           "bed_area_mm2": round(bed_area, 4),
           "bed_ratio": round(bed_area / tot, 4) if tot > 0 else None,
           # old basis (<= v1.0.4: bed-contact face counted as overhang), kept for comparison and rollback
           "overhang_area_incl_bed_mm2": round(incl_area, 4),
           "exclude_bed": bool(cfg["exclude_bed"]), "bed_mode": used, "bed_tol_mm": cfg["tol"],
           "bed_horiz_deg": cfg["horiz"], "bed_band_mm": cfg["band"], "bed_level_mm": round(bed, 4),
           "lowest_mm": (round(lowest, 4) if lowest is not None else None),
           "overhang_faces_listed": len(a["bad"]), "samples": a["bad"],
           "bed_faces_listed": len(a["bed"]), "bed_samples": a["bed"],
           "hint": hint}
    if bed_warning:
        rec["bed_warning"] = bed_warning
    return rec


def _oh_payload(out, bed, used):
    """Aggregate receipt."""
    return _j({"ok": all(r.get("ok") for r in out), "objects": out,
               "bed_level_mm": round(bed, 4), "bed_mode": used,
               "note": ("Basis: a face whose normal is within max_angle_deg of straight down (default 45°) needs support; "
                        "among those, a face that is horizontal-downward and within the platform face ±bed_tol_mm is judged as bed contact and excluded from overhang_area_mm2 "
                        "(the platform face follows bed_mode=%s; exclude_bed=False rolls back to the old basis); "
                        "the platform face is **shared by the whole selection set** as a single level (bed_level_mm), not inferred per object — "
                        "so the same part measured alone vs together with others can differ (for per-part judgement: one call per part); "
                        "min_area_mm2 is the net overhang area budget" % used)})


def print_overhang(objects=None, scope="ACTIVE", max_angle_deg=45.0, up="Z", min_area_mm2=0.0,
                   mm_per_unit=None, max_list=20, exclude_bed=True, bed_tol_mm=0.2,
                   bed_mode="flat", bed_horiz_deg=1.0, bed_band_mm=1.0):
    """Overhang: a face normal within max_angle_deg of "straight down" needs support (0° = pointing straight down).

    v1.0.5 (issue #14): **the bed-contact face no longer counts toward the overhang area by default** — flat-bottomed parts are no longer always judged overhang_ok=false.
        A bed-contact face must satisfy both: ① horizontal downward (normal within bed_horiz_deg of straight down, default 1°);
        ② its level within the platform face ±bed_tol_mm. The platform face level is decided by bed_mode:
            flat (default) = the level of the largest-area "horizontal downward" layer (robust against voxel slivers/chamfers dragging the level down);
            min            = the lowest point of the selected set along the up axis (the physical print platform, sensitive to slivers).
        flat has a guard, bed_band_mm (default 1.0): if the largest-area horizontal downward face sits higher than the set's lowest point by
        more than this distance, it is judged "not a platform face" (an eave/roof in mid-air, or the whole part floating), and it **falls back to the lowest-point basis**
        with the reason in bed_warning — otherwise a mushroom part would exclude the entire real overhang and make ok falsely green (measured: 200×200 cap
        + steep cone stalk: 40000mm² swallowed, ok=true).
        min_area_mm2 is the **net overhang area budget** (exceeding it fails), no longer a means of "excluding the bed-contact face".
        Rollback: exclude_bed=False restores the v1.0.4-and-earlier old basis (bed-contact face counted as overhang);
        overhang_area_incl_bed_mm2 always reports the old basis numbers including the bed-contact face, for comparison.
    """
    cfg, perr = _oh_parse(objects, scope, max_angle_deg, up, mm_per_unit, min_area_mm2, exclude_bed,
                          max_list, bed_tol_mm, bed_mode, bed_horiz_deg, bed_band_mm)
    if perr is not None:
        return perr
    faces, lowest = _oh_faces(cfg["obs"], cfg)
    bed, used, fallback_why = _oh_bed(faces, cfg, lowest)
    out, acc = _oh_accumulate(cfg["obs"], faces, cfg, bed)
    bed_warning = _oh_bed_warning(fallback_why, used, lowest, bed, cfg["tol"])
    for oi, ob in enumerate(cfg["obs"]):
        a = acc.get(oi)
        if a is None:
            continue
        out[oi] = _oh_row(ob, a, cfg, bed, used, lowest, bed_warning)
    return _oh_payload(out, bed, used)


def print_report(objects=None, scope="ACTIVE", min_mm=1.0, max_angle_deg=45.0, up="Z",
                 min_area_mm2=0.0, mm_per_unit=None, max_samples=4000,
                 exclude_bed=True, bed_tol_mm=0.2, bed_mode="flat", bed_horiz_deg=1.0, bed_band_mm=1.0):
    """Aggregate receipt: wall thickness + overhang + mesh manufacturability, one overall verdict (for the delivery gate).

    v1.0.5 (issue #14): the overhang pass excludes the bed-contact face by default (basis in the print_overhang docstring);
    the bed area is listed separately in objects[].bed_area_mm2, the old basis in objects[].overhang_area_incl_bed_mm2.
    """
    w = json.loads(print_walls(objects=objects, scope=scope, min_mm=min_mm, max_samples=max_samples,
                               mm_per_unit=mm_per_unit))
    o = json.loads(print_overhang(objects=objects, scope=scope, max_angle_deg=max_angle_deg, up=up,
                                  min_area_mm2=min_area_mm2, mm_per_unit=mm_per_unit,
                                  exclude_bed=exclude_bed, bed_tol_mm=bed_tol_mm,
                                  bed_mode=bed_mode, bed_horiz_deg=bed_horiz_deg,
                                  bed_band_mm=bed_band_mm))
    if not w.get("ok") and any(r.get("error") for r in w.get("objects", [])):
        return _j({"ok": False, "stage": "walls", "walls": w, "overhang": o})
    rows = []
    for a, b in zip(w.get("objects", []), o.get("objects", [])):
        rows.append({"name": a.get("name"), "ok": bool(a.get("ok") and b.get("ok")),
                     "min_mm": a.get("min_mm"), "thin_samples": a.get("thin_samples"),
                     "overhang_area_mm2": b.get("overhang_area_mm2"), "overhang_ratio": b.get("overhang_ratio"),
                     # v1.0.5 (issue #14): bed area listed separately + old basis for comparison, so the gate criterion can use net overhang only
                     "bed_area_mm2": b.get("bed_area_mm2"), "bed_level_mm": b.get("bed_level_mm"),
                     "overhang_area_incl_bed_mm2": b.get("overhang_area_incl_bed_mm2"),
                     # the platform-face criterion's self-attesting warning must reach the aggregate level — keeping it only in detail makes it invisible to the gate
                     "bed_warning": b.get("bed_warning")})
    _thin_total = sum(int(a.get("thin_samples") or 0) for a in w.get("objects", []))
    _mins = [a.get("min_mm") for a in w.get("objects", []) if a.get("min_mm") is not None]
    # v1.0.5: the overhang side's self-attesting warning (the platform-face criterion may judge wrongly) must be visible at top level — gates/delivery scripts read top level and rows
    _owarn = sorted(set(str(b["bed_warning"]) for b in o.get("objects", []) if b.get("bed_warning")))
    return _j({"ok": all(r["ok"] for r in rows), "objects": rows,
               # v0.9.6 (integration plan): gate-friendly summary — criteria use top-level fields, don't make the gate spec dig through objects[]
               "walls_ok": all(bool(a.get("ok")) for a in w.get("objects", [])),
               "overhang_ok": all(bool(b.get("ok")) for b in o.get("objects", [])),
               "thin_samples_total": _thin_total,
               "worst_min_mm": (min(_mins) if _mins else None),
               # gate criteria should prefer p05: measured voxel spheres carry 0.05% near-zero outlier samples, so judging min falsely reports thin walls
               "worst_p05_mm": (min([a.get("p05_mm") for a in w.get("objects", []) if a.get("p05_mm") is not None] or [None])),
               "warnings": _owarn,
               "params": {"min_mm": min_mm, "max_angle_deg": max_angle_deg, "up": str(up).upper(),
                           "min_area_mm2": min_area_mm2, "exclude_bed": bool(exclude_bed),
                           "bed_tol_mm": bed_tol_mm, "bed_mode": o.get("bed_mode"),
                           "bed_horiz_deg": bed_horiz_deg, "bed_band_mm": bed_band_mm,
                           "bed_level_mm": o.get("bed_level_mm")},
               "detail": {"walls": w, "overhang": o},
               "note": ("ok=true only means the wall-thickness/overhang gates passed; connectivity and interference have their own audit_connectivity / audit_interference; "
                        "a non-empty warnings means the overhang platform-face criterion may have judged wrongly (see bed_caliber in print_overhang)")})


def _print_selftest_p1(st):
    try:
        import bmesh
        P = "__dsh_print_selftest_"
        made = []
        ev = {}

        def box(name, size, loc=(0.0, 0.0, 0.0)):
            """size = full extent; loc is baked straight into the vertices (not via the object transform, avoiding the unrefreshed matrix_world trap)."""
            m = bpy.data.meshes.new(name)
            o = bpy.data.objects.new(name, m)
            bpy.context.scene.collection.objects.link(o)
            bm = bmesh.new()
            bmesh.ops.create_cube(bm, size=1.0)
            bmesh.ops.scale(bm, vec=Vector(size), verts=list(bm.verts))
            bmesh.ops.translate(bm, verts=list(bm.verts), vec=Vector(loc))
            bm.to_mesh(m)
            bm.free()
            made.append((o, m))
            return o

        def two_box(name, size_a, loc_a, size_b, loc_b):
            """Both boxes stuffed into **one mesh** (one part carrying both a bed-contact face and a real overhang ⇒ used to lock the denominator of overhang_ratio)."""
            m = bpy.data.meshes.new(name)
            o = bpy.data.objects.new(name, m)
            bpy.context.scene.collection.objects.link(o)
            bm = bmesh.new()
            bmesh.ops.create_cube(bm, size=1.0)
            bmesh.ops.scale(bm, vec=Vector(size_a), verts=list(bm.verts))
            bmesh.ops.translate(bm, verts=list(bm.verts), vec=Vector(loc_a))
            r = bmesh.ops.create_cube(bm, size=1.0)
            vs = list(r["verts"])
            bmesh.ops.scale(bm, vec=Vector(size_b), verts=vs)
            bmesh.ops.translate(bm, verts=vs, vec=Vector(loc_b))
            bm.to_mesh(m)
            bm.free()
            made.append((o, m))
            return o

        def tilt_face(name, size, loc, tilt_deg):
            """Tilt a thin plate by tilt_deg around **its own bottom face centre** ⇒ the face centre stays at the original level but the normal no longer points straight down.

            Purpose: lock bed_horiz_deg — if the implementation forgets "it must be horizontal to count as a bed-contact face", this face gets wrongly excluded as one.
            """
            m = bpy.data.meshes.new(name)
            o = bpy.data.objects.new(name, m)
            bpy.context.scene.collection.objects.link(o)
            bm = bmesh.new()
            bmesh.ops.create_cube(bm, size=1.0)
            bmesh.ops.scale(bm, vec=Vector(size), verts=list(bm.verts))
            cent = Vector((0.0, 0.0, -size[2] / 2.0))          # bottom face centre (after scaling)
            bmesh.ops.rotate(bm, cent=cent, verts=list(bm.verts),
                             matrix=mathutils.Matrix.Rotation(math.radians(tilt_deg), 3, "Y"))
            bmesh.ops.translate(bm, verts=list(bm.verts),
                                vec=Vector((loc[0], loc[1], loc[2] + size[2] / 2.0)))
            bm.to_mesh(m)
            bm.free()
            made.append((o, m))
            return o

        def near(a, b, eps=4.0):
            return a is not None and abs(float(a) - float(b)) <= eps

        def ov(names, **kw):
            return json.loads(print_overhang(objects=names, max_angle_deg=45.0, **kw))

    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def _print_selftest_p2a(st):
    P, box, ev, near, ov = st["P"], st["box"], st["ev"], st["near"], st["ov"]
    try:
        fails = []
        # ── 1) flat-bottomed cube: the bed-contact face must not count as overhang (the core of issue #14) ──
        cube = box(P + "cube", (1.0, 1.0, 1.0))
        w = json.loads(print_walls(objects=[cube.name], min_mm=1.0))
        r1 = ov([cube.name])["objects"][0]
        ev["walls"] = {k: w["objects"][0][k] for k in ("min_mm", "thin_samples")}
        ev["cube"] = {k: r1[k] for k in ("faces", "bed_area_mm2", "overhang_area_mm2",
                                         "overhang_area_incl_bed_mm2", "overhang_ratio", "ok")}
        if not near(ev["walls"]["min_mm"], 1000.0, 5.0):
            fails.append("wall thickness min_mm=%.3f should be ≈1000mm" % float(ev["walls"]["min_mm"]))
        if not (near(r1["bed_area_mm2"], 1e6) and near(r1["overhang_area_mm2"], 0.0)
                and near(r1["overhang_area_incl_bed_mm2"], 1e6) and near(r1["overhang_ratio"], 0.0, 1e-6)):
            fails.append("flat-bottomed cube: net overhang should be 0, bed-contact face 1e6 mm², old basis 1e6 mm² (got %s)"
                         % json.dumps(ev["cube"]))
        if r1["ok"] is not True:
            fails.append("a flat-bottomed cube should be judged ok=true (issue #14: flat-bottomed parts are no longer always judged unacceptable)")
        r1b = ov([cube.name], exclude_bed=False)["objects"][0]
        ev["cube_legacy"] = {k: r1b[k] for k in ("overhang_area_mm2", "overhang_ratio", "ok")}
        if not (near(r1b["overhang_area_mm2"], 1e6) and near(r1b["overhang_ratio"], 0.1667, 1e-3)
                and r1b["ok"] is False):
            fails.append("exclude_bed=False should reproduce the v1.0.4 old basis 1e6 / 0.1667 / ok=false (got %s)"
                         % json.dumps(ev["cube_legacy"]))

        # ── 2) base plate + cantilever: the real overhang must not be swallowed by the platform face ──
        base = box(P + "base", (2.0, 2.0, 0.5), (0.0, 0.0, 0.0))     # bottom face 4 m² @ z=-0.25
        arm = box(P + "arm", (1.0, 1.0, 0.5), (1.0, 0.0, 0.5))       # bottom face 1 m² @ z=+0.25 (500mm off the table)
        o2 = ov([base.name, arm.name])
        rb, ra = o2["objects"][0], o2["objects"][1]
        ev["cantilever"] = {"bed_level_mm": o2["bed_level_mm"],
                            "base": {k: rb[k] for k in ("bed_area_mm2", "overhang_area_mm2")},
                            "arm": {k: ra[k] for k in ("bed_area_mm2", "overhang_area_mm2")}}
        if not (near(rb["bed_area_mm2"], 4e6) and near(rb["overhang_area_mm2"], 0.0)):
            fails.append("base plate: bed-contact face should be 4e6, net overhang 0 (got %s)" % json.dumps(ev["cantilever"]["base"]))
        if not (near(ra["overhang_area_mm2"], 1e6) and near(ra["bed_area_mm2"], 0.0, 1e-6)):
            fails.append("the cantilever's bottom face (500mm off the table) must count as overhang=1e6, bed-contact face=0 (got %s)"
                         % json.dumps(ev["cantilever"]["arm"]))
        if o2["ok"] is not False:
            fails.append("with a real overhang ok must be false")

        # ── 3) a sliver 0.5mm under the flat bottom face (within bed_band_mm): flat still treats the flat bottom face as the platform ──
        base2 = box(P + "base2", (2.0, 2.0, 0.5), (0.0, 0.0, 0.25))    # bottom face 4 m² @ z=0
        chip = box(P + "chip", (0.2, 0.2, 0.001), (0.5, 0.5, 0.0))     # bottom face 0.04 m² @ z=-0.5mm
        fl = ov([base2.name, chip.name])
        fb, fc = fl["objects"][0], fl["objects"][1]
        mn = ov([base2.name, chip.name], bed_mode="min")
        mb = mn["objects"][0]
        ev["sliver"] = {
            "flat": {"bed_level_mm": fl["bed_level_mm"], "bed_mode": fl["bed_mode"],
                     "base_bed_mm2": fb["bed_area_mm2"],
                     "base_over_mm2": fb["overhang_area_mm2"], "chip_over_mm2": fc["overhang_area_mm2"],
                     "bed_warning": bool(fb.get("bed_warning"))},
            "min": {"bed_level_mm": mn["bed_level_mm"], "base_over_mm2": mb["overhang_area_mm2"]}}
        if not (near(fl["bed_level_mm"], 0.0, 1e-6) and fl["bed_mode"] == "flat"
                and near(fb["bed_area_mm2"], 4e6)
                and near(fb["overhang_area_mm2"], 0.0) and near(fc["overhang_area_mm2"], 4e4)
                and bool(fb.get("bed_warning"))):
            fails.append("flat mode should treat the flat bottom face as the platform (4e6 excluded), count the sliver + give a bed_warning (got %s)"
                         % json.dumps(ev["sliver"]["flat"]))
        if not (near(mn["bed_level_mm"], -0.5, 1e-3) and near(mb["overhang_area_mm2"], 4e6)):
            fails.append("min mode should reproduce issue #14's failing shape (the platform pushed down to the sliver layer ⇒ the flat bottom face counts as overhang 4e6, got %s)"
                         % json.dumps(ev["sliver"]["min"]))

        # ── 4) mushroom part (thin stalk + wide cap): the cap underside 40000mm² is a large overhang and **not** a platform face ──
        # without the bed_band_mm guard, flat would treat the cap underside as the platform face ⇒ the whole real overhang swallowed, ok falsely green (measured).
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def _print_selftest_p2b(st):
    P, box, ev, fails, near = st["P"], st["box"], st["ev"], st["fails"], st["near"]
    ov, tilt_face, two_box = st["ov"], st["tilt_face"], st["two_box"]
    try:
        stalk = box(P + "stalk", (0.02, 0.02, 0.02), (0.0, 0.0, 0.01))   # 20mm stalk, z ∈ [0, 20]mm
        cap = box(P + "cap", (0.2, 0.2, 0.02), (0.0, 0.0, 0.03))         # 200mm cap, z ∈ [20, 40]mm
        mush = ov([stalk.name, cap.name])
        mcap = mush["objects"][1]
        ev["mushroom"] = {"ok": mush["ok"], "bed_mode": mush["bed_mode"], "bed_level_mm": mush["bed_level_mm"],
                          "cap_over_mm2": mcap["overhang_area_mm2"], "cap_bed_mm2": mcap["bed_area_mm2"],
                          "warning": bool(mcap.get("bed_warning"))}
        if not (mush["bed_mode"] == "min-fallback" and near(mush["bed_level_mm"], 0.0, 1e-6)
                and near(mcap["overhang_area_mm2"], 4e4) and near(mcap["bed_area_mm2"], 0.0, 1e-6)
                and mush["ok"] is False and bool(mcap.get("bed_warning"))):
            fails.append("mushroom part: the cap underside 40000mm² must still count as overhang (flat taking it as the platform face is exactly the false green) — "
                         "expected bed_mode=min-fallback / ok=false / bed_warning (got %s)"
                         % json.dumps(ev["mushroom"]))

        # ── 5) an **inclined face** at the platform level: it must not be taken as a bed-contact face (locks bed_horiz_deg) ──
        # the plate is tilted 30° around its own bottom face centre ⇒ the face centre still sits 0.1mm above the platform face (within bed_tol_mm),
        # but the normal is 30° off straight down. If the implementation forgets "it must be horizontal to count as bed contact", this face gets wrongly excluded ⇒ net overhang becomes 0.
        plate5 = box(P + "plate5", (2.0, 2.0, 0.5), (0.0, 0.0, 0.25))      # bottom face 4 m² @ z=0 (the platform face)
        facet = tilt_face(P + "facet", (0.0004, 0.0004, 0.0001), (1.5, 1.5, 0.0001), 30.0)
        #          0.4×0.4mm plate, bottom face centre at z=+0.1mm (within tol=0.2), lowest corner exactly back at z=0
        tl = ov([plate5.name, facet.name], bed_mode="min")
        tp, tf = tl["objects"][0], tl["objects"][1]
        ev["tilted"] = {"bed_level_mm": tl["bed_level_mm"], "bed_mode": tl["bed_mode"],
                        "plate_bed_mm2": tp["bed_area_mm2"], "plate_over_mm2": tp["overhang_area_mm2"],
                        "facet_over_mm2": tf["overhang_area_mm2"], "facet_bed_mm2": tf["bed_area_mm2"]}
        if not (near(tp["bed_area_mm2"], 4e6) and near(tf["overhang_area_mm2"], 0.16, 0.05)
                and near(tf["bed_area_mm2"], 0.0, 1e-6)):
            fails.append("an inclined face (30°, face centre 0.1mm above the platform face) must still count as overhang 0.16mm², not be taken as a bed-contact face (got %s)"
                         % json.dumps(ev["tilted"]))

        # ── 6) one part with both a bed-contact face and a real overhang: locks that overhang_ratio's denominator is the whole surface ──
        tee = two_box(P + "tee", (2.0, 2.0, 0.5), (0.0, 0.0, 0.0), (1.0, 1.0, 0.5), (1.0, 0.0, 0.5))
        tt = ov([tee.name])["objects"][0]
        _tot, _bad = float(tt["total_area_mm2"]), float(tt["overhang_area_mm2"])
        ev["tee"] = {"total_area_mm2": _tot, "bed_area_mm2": tt["bed_area_mm2"],
                     "overhang_area_mm2": _bad, "overhang_ratio": tt["overhang_ratio"],
                     "bad_over_total": round(_bad / _tot, 4) if _tot > 0 else None}
        if not (near(tt["bed_area_mm2"], 4e6) and near(_bad, 1e6) and near(tt["overhang_ratio"], 0.0625, 1e-3)
                and abs(float(tt["overhang_ratio"]) - _bad / _tot) <= 1e-3):
            fails.append("single T-shaped part: bed 4e6 / overhang 1e6 / ratio = 1e6÷16e6 = 0.0625 (the denominator is the whole surface, got %s)"
                         % json.dumps(ev["tee"]))

        # ── 7) non-uniform scale: areas must be computed in world space (the old `_scale_avg` basis was off by -11%) ──
        cube7 = box(P + "cube7", (1.0, 1.0, 1.0))
        cube7.scale = (2.0, 1.0, 1.0)
        bpy.context.view_layer.update()          # make matrix_world reflect the scale
        r7 = ov([cube7.name])["objects"][0]
        ev["aniso_area"] = {"bed_area_mm2": r7["bed_area_mm2"], "total_area_mm2": r7["total_area_mm2"]}
        # true bottom face = 2m × 1m = 2 m² = 2e6 mm²; total surface = 2×(2×1)+2×(2×1)+2×(1×1) = 10 m² = 1e7 mm²
        # the old basis ((_scale_avg=1.333)²) gave 1.777e6 / 8.888e6
        if not (near(r7["bed_area_mm2"], 2e6, 10.0) and near(r7["total_area_mm2"], 1e7, 50.0)):
            fails.append("a 1m cube with non-uniform scale (2,1,1): bottom face should be 2e6, total surface 1e7 mm² (got %s)"
                         % json.dumps(ev["aniso_area"]))

        # ── 8) the **normal** under non-uniform scale: must use the inverse transpose (the old basis turned a 16° face into 49° ⇒ the whole face missed) ──
        plate8 = box(P + "plate8", (2.0, 2.0, 0.5), (0.0, 0.0, 0.25))          # bottom face 4 m² @ z=0
        facet8 = tilt_face(P + "facet8", (0.0004, 0.0004, 0.0001), (1.5, 1.5, 0.0001), 30.0)
        facet8.scale = (2.0, 1.0, 1.0)
        bpy.context.view_layer.update()
        t8 = ov([plate8.name, facet8.name], bed_mode="min")
        f8 = t8["objects"][1]
        ev["aniso_normal"] = {"facet_over_mm2": f8["overhang_area_mm2"], "facet_bed_mm2": f8["bed_area_mm2"]}
        if not (f8["overhang_area_mm2"] > 0.1 and near(f8["bed_area_mm2"], 0.0, 1e-6)):
            fails.append("inclined face missed under non-uniform scale: the true normal is ≈16° off straight down (it must count as overhang), "
                         "`M @ n` turns it into 49° and drops the whole face (got %s)" % json.dumps(ev["aniso_normal"]))

        return _j({"ok": not fails, "fails": fails, "evidence": ev,
                   "expect": {"walls_min_mm": 1000.0, "cube_net_overhang_mm2": 0.0,
                              "cube_bed_mm2": 1e6, "cube_legacy_overhang_mm2": 1e6,
                              "arm_overhang_mm2": 1e6, "base_bed_mm2": 4e6,
                              "cap_overhang_mm2": 4e4, "facet_overhang_mm2": 0.16,
                              "tee_overhang_ratio": 0.0625, "aniso_bed_mm2": 2e6,
                              "tolerance_mm2": 4.0}})
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def print_selftest():
    """Self-test: four shapes verifying "the bed-contact face is excluded, real overhangs are still counted" (issue #14's regression lock).

    1) a 1-unit cube: wall thickness ≈1000mm; the bed-contact bottom face 1e6 mm² must be excluded → net overhang = 0, ok = true.
          The old basis (exclude_bed=False) must reproduce the v1.0.4 numbers (1e6 / 0.1667 / ok=false) — that is issue #14.
    2) base plate + cantilever: bed-contact face 4e6, the cantilever's bottom face (500mm off the table) must still count as overhang 1e6.
    3) a sliver 0.5mm under the flat bottom face (the reporter's shape, within bed_band_mm): flat treats the flat bottom face as the platform (the sliver counted and a
          bed_warning given); min pushes the platform down to the sliver layer → the flat bottom face is judged overhang instead (reproducing the old basis's failing shape).
    4) mushroom part (thin stalk + 200mm wide cap): the cap underside 40000mm² is a **large overhang, not a platform face** — if flat treats it as the platform face it would
          swallow the entire real overhang and make ok falsely green; bed_band_mm must force the fallback to the min basis (bed_mode=min-fallback).
    """
    st = dict(locals())
    _print_selftest_p1(st)
    try:
        for _fn_ in (_print_selftest_p2a, _print_selftest_p2b):
            _r = _fn_(st)
            if _r is not None:
                return _r
    except Exception as e:
        return _j({"ok": False, "evidence": st.get("ev"),
                   "error": "%s: %s" % (type(e).__name__, str(e)[:200])})
    finally:
        for o, m in (st.get("made") or []):
            try:
                bpy.data.objects.remove(o, do_unlink=True)
            except Exception:
                pass
            try:
                bpy.data.meshes.remove(m, do_unlink=True)
            except Exception:
                pass



def print_help():
    return _j({
        "module": "printcheck.py", "version": PRINT_VERSION,
        "ops": {
            "print_walls": "read-only: min_mm threshold + max_samples (default 4000); the receipt gives min/p05/median/max, thin_samples, worst 10",
            "print_overhang": ("read-only: max_angle_deg (default 45, the angle between the normal and straight down), up=X|Y|Z, "
                               "min_area_mm2 (net overhang area budget), exclude_bed (default true), bed_tol_mm (0.2), "
                               "bed_mode=flat|min, bed_horiz_deg (1.0), bed_band_mm (1.0, flat's guard); "
                               "the bed-contact face is listed separately in bed_area_mm2, the old basis in overhang_area_incl_bed_mm2"),
            "print_report": "read-only: both gates summarised (used by the delivery gate); the overhang pass excludes the bed-contact face by default; top-level warnings[] carries the platform-face criterion's self-attesting warnings",
            "print_selftest": "self-test: 8 shapes — flat-bottomed cube net overhang=0 / cantilever still counted / flat-bottom sliver / mushroom cap must not go falsely green / inclined face must not pass as bed contact / single-part T ratio / non-uniform scale area truth and normals not missed",
            "print_help": "this table",
        },
        "units": "1 unit = scale_length metres; mm = unit * scale_length * 1000 (mm_per_unit overrides it)",
        "bed_caliber": ("bed-contact face = horizontal downward (<= bed_horiz_deg) and within the platform face ±bed_tol_mm; "
                        "the platform face is flat (default): the level of the largest-area horizontal downward layer, or min: the set's lowest point; "
                        "flat additionally requires that layer to be no more than bed_band_mm from the lowest point (default 1.0, i.e. a 'bottom-edge sliver/bridge tolerance'), "
                        "otherwise it falls back to the min basis and gives a bed_warning. **Differences within bed_band_mm cannot be judged apart**: "
                        "a wide face <=1mm off the bed and a 'bottom-edge sliver' are the same shape, and flat always counts it as bed contact (FDM can bridge it); "
                        "this kind of uncertainty must be exposed through bed_warning / print_report's top-level warnings, "
                        "and the gate's print preset already counts a non-empty warnings as degraded (no false green). "
                        "flat/min both derive from the geometry and are position-independent: when the whole part floats, the lowest point is itself — for absolute-platform judgement, place it on the bed first, "
                        "or use the conservative exclude_bed=False basis (= the v1.0.4 old basis, bed-contact face counted as overhang)"),
        "why_not_3d_print_toolbox": "upstream blend-ai wraps the 3D Print Toolbox add-on (not enabled by default); this module computes with BVH itself: one dependency fewer, results recomputable",
        "limits": ("an open thin shell cannot be measured for thickness (the ray leaves the part); concave corners read optimistic — judge by p05 and thin_ratio, not by a single minimum; "
                   "the bed-contact criterion is **position-independent** (the platform face is derived from the geometry): when the whole part floats or is not on the bed, flat still takes its largest-area "
                   "horizontal downward face as the platform face (to have the lowest face of a floating part count as overhang too, use the conservative exclude_bed=False basis, "
                   "or drop the part to z=0 first; bed_band_mm only rescues when 'that face is really too far from the lowest point'); "
                   "bed_mode=min is sensitive to chamfers/slivers (it lowers the platform ⇒ the flat bottom face is judged overhang instead)"),
    })


def print_dispatch(op, args_json):
    args = {}
    if isinstance(args_json, str) and args_json.strip():
        try:
            args = json.loads(args_json)
        except Exception as e:
            return _j({"ok": False, "error": "args is not valid JSON: %s" % str(e)[:120]})
    if not isinstance(args, dict):
        return _j({"ok": False, "error": "args must be an object"})
    kw = {}
    for k, v in args.items():
        if k == "args" and isinstance(v, dict):
            kw.update(v)
        else:
            kw[k] = v
    ops = {"walls": print_walls, "overhang": print_overhang, "report": print_report,
           "selftest": print_selftest, "help": print_help}
    fn = ops.get(str(op))
    if fn is None:
        return _j({"ok": False, "error": "unknown print op", "op": op, "ops": sorted(ops)})
    import inspect
    try:
        allowed = set(inspect.signature(fn).parameters)
        unknown = sorted(set(kw) - allowed)
        if unknown:
            return _j({"ok": False, "error": "unrecognized parameter %s" % unknown, "op": op, "allowed": sorted(allowed)})
    except (TypeError, ValueError):
        pass
    try:
        return fn(**kw)
    except TypeError as e:
        return _j({"ok": False, "error": "parameter mismatch: %s" % str(e)[:200], "op": op, "help": print_help()})
    except Exception as e:
        return _j({"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:220]), "op": op})


_DshApi = _KIT.Api  # shared kernel (the trailing registration lines need no change)
import sys as _sys
_K = _sys.modules.get("dsh_rt_kernel")
if _K is not None:
    _K.dsh_print_api = _DshApi({"version": PRINT_VERSION, "dispatch": print_dispatch,
                                "walls": print_walls, "overhang": print_overhang,
                                "report": print_report, "selftest": print_selftest, "help": print_help})
