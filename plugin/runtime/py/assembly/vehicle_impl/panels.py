# -*- coding: utf-8 -*-
"""Split from vehicle.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403
from .base import vehicle_sections
from .loft import vehicle_loft

def vehicle_panels(object_name=None, cuts_mm=None, gap_mm=3.0, separate=True, names=None):
    """Split a part along seams (exterior surface reconstruction, step 4): **subtract a thin slab** at each given x (seam width gap_mm) ⇒ a real seam; optionally separate into multiple parts."""
    try:
        import bmesh as _bm
        ob = bpy.data.objects.get(str(object_name)) if object_name else bpy.context.view_layer.objects.active
        if ob is None or ob.type != "MESH":
            return _j({"ok": False, "error": "Supply object_name (or select a mesh)"})
        if not cuts_mm:
            return _j({"ok": False, "error": "cuts_mm is required: [x positions…] (millimetres, along the vehicle length)"})
        mmu = _KIT.units()
        cutters = []
        for i, x in enumerate(list(cuts_mm)):
            cme = bpy.data.meshes.new(ob.name + "_cut%d" % i)
            cbm = _bm.new()
            import mathutils as _mu
            size = max(float(ob.dimensions.x), float(ob.dimensions.y), float(ob.dimensions.z)) * 2.0
            _bm.ops.create_cube(cbm, size=1.0, matrix=_mu.Matrix.Diagonal(
                (float(gap_mm) / mmu, size, size, 1.0)))
            cbm.to_mesh(cme)
            cbm.free()
            cob = bpy.data.objects.new(ob.name + "_cut%d" % i, cme)
            cob.location = (float(x) / mmu, float(ob.dimensions.y) * 0.0, float(ob.dimensions.z) * 0.0)
            bpy.context.scene.collection.objects.link(cob)
            cutters.append(cob)
        for cob in cutters:
            md = ob.modifiers.new("panel_cut", "BOOLEAN")
            md.operation = "DIFFERENCE"
            md.object = cob
        for o in bpy.context.selected_objects:
            o.select_set(False)
        ob.select_set(True)
        bpy.context.view_layer.objects.active = ob
        for md in list(ob.modifiers):
            try:
                bpy.ops.object.modifier_apply(modifier=md.name)
            except Exception:
                pass
        for cob in cutters:
            cme = cob.data
            bpy.data.objects.remove(cob, do_unlink=True)
            if cme is not None and cme.users == 0:
                try:
                    bpy.data.meshes.remove(cme, do_unlink=True)
                except Exception:
                    pass
        made = []
        if separate:
            try:
                bpy.ops.mesh.separate(type="LOOSE")
                for o in bpy.context.selected_objects:
                    made.append(o.name)
            except Exception:
                made = [ob.name]
        else:
            made = [ob.name]
        return _j({"ok": True, "source": ob.name, "cuts_mm": list(cuts_mm), "gap_mm": gap_mm,
                   "parts": made, "part_count": len(made),
                   "note": "The seams are real geometry: measure each seam width with clear_check (min_mm around half the gap); left-right symmetry can be measured too"})
    except Exception as e:
        return _j({"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:220])})



def vehicle_regions(stations=None, regions=None, side=None, mm_per_px=None, known_len_mm=None,
                    name="Region", loft_kw=None, invert_side=False, wheel_r_px=None):
    """Multi-region assembly (part 2): cut the reference image into x intervals and **loft each one into its own volume**.

    Use it for **multi-volume** vehicles such as trucks (cab + bed), armour (hull + turret), sci-fi (body + pods);
    each region gets its own name, so detail/material/assembly acceptance can be handled per region.
    regions=[{name:"cab", x0_mm:0, x1_mm:2200}, {name:"bed", x0_mm:2250, x1_mm:6000}]
    """
    try:
        if not regions:
            return _j({"ok": False, "error": "regions is required: [{name, x0_mm, x1_mm}]"})
        sts = stations
        if not sts:
            if not side:
                return _j({"ok": False, "error": "Supply stations or side (with side, vehicle_sections runs internally first)"})
            sec = json.loads(vehicle_sections(side=side, mm_per_px=mm_per_px, known_len_mm=known_len_mm,
                                              invert_side=invert_side, wheel_r_px=wheel_r_px))
            if not sec.get("ok"):
                return _j({"ok": False, "error": "Station table extraction failed", "sections": sec})
            sts = sec.get("stations") or []
        lk = dict(loft_kw or {})
        made = []
        for rg in regions:
            r = dict(rg or {})
            rn = str(r.get("name") or "part")
            x0 = float(r.get("x0_mm") or 0.0)
            x1 = float(r.get("x1_mm") or 0.0)
            sub = [s for s in sts if s.get("z_top_mm") is not None
                   and x0 - 1e-6 <= float(s.get("x_mm") or -1e9) <= x1 + 1e-6]
            if len(sub) < 3:
                made.append({"name": rn, "ok": False, "error": "Fewer than 3 valid stations in this interval (%d)" % len(sub)})
                continue
            out = json.loads(vehicle_loft(stations=sub, name="%s_%s" % (name, rn), **lk))
            made.append({"name": rn, "ok": bool(out.get("ok")), "object": out.get("object"),
                         "size_mm": out.get("size_mm"), "stations_used": out.get("stations_used"),
                         "error": out.get("error")})
        ok = all(m.get("ok") for m in made)
        return _j({"ok": ok, "regions": made, "count": len(made),
                   "note": "Each region is an independent volume: assembly/detail/material are handled separately; leave seams between intervals with vehicle_panels or just leave a gap between adjacent intervals"})
    except Exception as e:
        return _j({"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:220])})


def _silhouette_iou(xs, top_a, bot_a, top_b, bot_b):
    """**Region IoU** enclosed by two top/bottom contours (pure 2D, trapezoid integration). Returns (iou, area_a, area_b, inter)."""
    inter = 0.0
    area_a = 0.0
    area_b = 0.0
    for i in range(len(xs) - 1):
        dx = xs[i + 1] - xs[i]
        if dx <= 0:
            continue
        a_lo, a_hi = bot_a[i], top_a[i]
        b_lo, b_hi = bot_b[i], top_b[i]
        area_a += 0.5 * dx * ((a_hi - a_lo) + (top_a[i + 1] - bot_a[i + 1]))
        area_b += 0.5 * dx * ((b_hi - b_lo) + (top_b[i + 1] - bot_b[i + 1]))
        lo = max(a_lo, b_lo)
        hi = min(a_hi, b_hi)
        lo2 = max(bot_a[i + 1], bot_b[i + 1])
        hi2 = min(top_a[i + 1], top_b[i + 1])
        inter += 0.5 * dx * (max(0.0, hi - lo) + max(0.0, hi2 - lo2))
    union = area_a + area_b - inter
    return ((inter / union) if union > 1e-9 else 0.0), area_a, area_b, inter


def _params_from_stations(sts):
    """**Analytically back out** profile parameters from the station table (seeds for the fit): the roof plateau plus slope breaks locate windshield/rear window/trunk."""
    xs = [float(s["x_mm"]) for s in sts]
    zs = [float(s["z_top_mm"]) for s in sts]
    n = len(xs)
    L = max(1e-6, xs[-1])
    H = max(zs)
    z0 = zs[0]
    out = {"length_mm": L, "height_mm": max(1.0, H)}
    top_idx = [i for i, z in enumerate(zs) if z >= H - 0.03 * max(1.0, H)]
    if not top_idx:
        return out
    i0, i1 = top_idx[0], top_idx[-1]
    j = max(0, i0 - 1)
    out["grille_h_mm"] = max(1.0, zs[0])
    out["hood_len_mm"] = max(50.0, xs[j])
    out["hood_angle_deg"] = max(0.0, min(60.0, math.degrees(math.atan2(zs[j] - z0, max(1e-6, xs[j])))))
    dz = H - zs[j]
    dx = max(1e-6, xs[i0] - xs[j])
    out["windshield_angle_deg"] = max(5.0, min(80.0, math.degrees(math.atan2(dz, dx))))
    out["roof_len_mm"] = max(50.0, xs[i1] - xs[i0])
    k = min(n - 1, i1 + 1)
    while k < n - 1 and zs[k] > zs[-1] + 0.05 * max(1.0, H - zs[-1]):
        k += 1
    out["rear_window_h_mm"] = max(1.0, zs[k])
    d2 = H - zs[k]
    x2 = max(1e-6, xs[k] - xs[i1])
    out["rear_window_angle_deg"] = max(5.0, min(80.0, math.degrees(math.atan2(d2, x2))))
    out["trunk_angle_deg"] = max(0.0, min(45.0, math.degrees(math.atan2(max(0.0, zs[k] - zs[-1]),
                                                                        max(1e-6, L - xs[k])))))
    zb = [float(s.get("z_bottom_mm") or 0.0) for s in sts]
    out["ride_mm"] = max(20.0, min(zb))
    try:
        lows = sorted(rgs for rgs in [(abs(b - (min(zb) + 0.25 * (max(zb) - min(zb) + 1.0))), xs[i])
                                      for i, b in enumerate(zb)])
    except Exception:
        pass
    return out
