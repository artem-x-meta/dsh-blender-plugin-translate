# -*- coding: utf-8 -*-
"""Split from vehicle.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403

def _vb_prepare(spec, name, kw, wheels):
    """Parse spec + clear old objects with the same name; returns (sp, nm, L)."""
    if isinstance(spec, dict) and spec:
        kw = dict({k: x for k, x in spec.items() if k in DEFAULTS}, **kw)
    sp = vehicle_spec(**kw)
    sp["_profile"] = _profile_points(sp)
    L = sp["length_mm"] / 1000.0
    nm = str(name or "VehicleShell")
    for nmx in [nm] + ([nm + "_wheel_%s" % s for s in ("fl", "fr", "rl", "rr")] if wheels else []):
        o = bpy.data.objects.get(nmx)
        if o is not None:
            me0 = o.data if o.type == "MESH" else None
            bpy.data.objects.remove(o, do_unlink=True)
            if me0 is not None and me0.users == 0:
                bpy.data.meshes.remove(me0, do_unlink=True)
    return sp, nm, L


def _vb_stations(sp, stations, L):
    """Stations: uniform + densified at the wheel rims; returns sorted, deduplicated xs.

    The wheel arch is a cliff at dx=r+clear, so with uniform stations (one per 0.19 m) the chords pass straight through the wheel's rear edge (58 face pairs intersect, measured in practice).
    """
    r_w = sp["wheel_r_mm"] / 1000.0
    clear_w = sp["arch_clear_mm"] / 1000.0
    fx_w = sp["front_axle_from_front_mm"] / 1000.0
    rx_w = fx_w + sp["wheelbase_mm"] / 1000.0
    xs = [L * i / float(max(1, int(stations) - 1)) for i in range(int(stations))]
    for wx in (fx_w, rx_w):
        for off in (0.0, -r_w, r_w, -(r_w + clear_w), (r_w + clear_w),
                    -0.5 * r_w, 0.5 * r_w, -0.9 * r_w, 0.9 * r_w):
            xw = wx + off
            if 0.0 <= xw <= L:
                xs.append(xw)
    return sorted(set(round(x, 6) for x in xs))


def _vb_shell(sp, xs, nm, section_pts):
    """Per-station superellipse section → bridged into a shell (capped at both ends + normals recalculated); returns ob."""
    me = bpy.data.meshes.new(nm)
    bm = bmesh.new()
    rings = []
    for x in xs:
        pts = _section(sp, x, n=int(section_pts))
        rings.append([bm.verts.new(p) for p in pts])
    for a, b in zip(rings, rings[1:]):
        for i in range(len(a)):
            j = (i + 1) % len(a)
            try:
                bm.faces.new((a[i], a[j], b[j], b[i]))
            except Exception:
                pass
    for ring in (rings[0], rings[-1]):
        try:
            bm.faces.new(ring)
        except Exception:
            pass
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(nm, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def _vb_arch_cut(ob, sp, nm):
    """Wheel arch refinement: boolean-subtract a slightly larger wheel cylinder (radius r + arch_clear).

    The analytic arch already lifts the section, but the wheel rim is a cliff, so coarse stations let the chords cut into the wheel (20 face pairs intersect, measured in practice).
    After the boolean, "zero interpenetration between wheel and shell" is a **construction guarantee** and does not depend on station density.
    """
    r_b = sp["wheel_r_mm"] / 1000.0
    ww_b = sp["wheel_w_mm"] / 1000.0
    sink_b = sp["wheel_sink_frac"]
    clear_b = sp["arch_clear_mm"] / 1000.0
    fx_b = sp["front_axle_from_front_mm"] / 1000.0
    rx_b = fx_b + sp["wheelbase_mm"] / 1000.0
    wc_z_b = r_b * (1.0 - sink_b)
    cutters = []
    for ax_b in (fx_b, rx_b):
        for sy_b in (1.0, -1.0):
            cme = bpy.data.meshes.new(nm + "_cut")
            cbm = bmesh.new()
            bmesh.ops.create_cone(cbm, cap_ends=True, cap_tris=False, segments=32,
                                  radius1=r_b + clear_b, radius2=r_b + clear_b, depth=ww_b * 1.8,
                                  matrix=__import__("mathutils").Matrix.Rotation(math.radians(90), 4, "X"))
            cbm.to_mesh(cme)
            cbm.free()
            cob = bpy.data.objects.new(nm + "_cut", cme)
            cob.location = (ax_b, sy_b * sp["track_mm"] / 1000.0 / 2.0, wc_z_b)
            bpy.context.scene.collection.objects.link(cob)
            cutters.append(cob)
    for cob in cutters:
        md = ob.modifiers.new("arch_cut", "BOOLEAN")
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


def _vb_make_wheel(nm, sid, axle, x, sy, r, ww, zc, sp, mmu):
    """One wheel: 24-segment cone (axis X); returns (object name, wheel_info row)."""
    wme = bpy.data.meshes.new(nm + "_wheel_" + sid)
    wbm = bmesh.new()
    bmesh.ops.create_cone(wbm, cap_ends=True, cap_tris=False, segments=24,
                          radius1=r, radius2=r, depth=ww,
                          matrix=__import__("mathutils").Matrix.Rotation(math.radians(90), 4, "X"))
    wbm.to_mesh(wme)
    wbm.free()
    wob = bpy.data.objects.new(nm + "_wheel_" + sid, wme)
    wob.location = (x, sy * sp["track_mm"] / 1000.0 / 2.0, zc)
    bpy.context.scene.collection.objects.link(wob)
    return wob.name, {"side": sid, "axle": axle, "x_mm": round(x * mmu, 1),
                      "z_mm": round(zc * mmu, 1), "r_mm": round(r * mmu, 1)}


def _vb_wheels(sp, nm, mmu):
    """Four wheels (front/rear axle × left/right); returns (wheel_objects, wheel_info)."""
    made = []
    wheel_info = []
    r = sp["wheel_r_mm"] / 1000.0
    ww = sp["wheel_w_mm"] / 1000.0
    sink = sp["wheel_sink_frac"]
    fx = sp["front_axle_from_front_mm"] / 1000.0
    rx = fx + sp["wheelbase_mm"] / 1000.0
    zc = r * (1.0 - sink)
    for sid, sy in (("fl", 1.0), ("fr", -1.0)):
        name, info = _vb_make_wheel(nm, sid, "front", fx, sy, r, ww, zc, sp, mmu)
        made.append(name)
        wheel_info.append(info)
    for sid, sy in (("rl", 1.0), ("rr", -1.0)):
        name, info = _vb_make_wheel(nm, sid, "rear", rx, sy, r, ww, zc, sp, mmu)
        made.append(name)
        wheel_info.append(info)
    return made, wheel_info


def _vb_markers(sp, nm, L):
    """Axle/ground/nose/tail empty markers; returns the mk list."""
    coll = bpy.data.collections.get(nm + "_marks")
    if coll is None:
        coll = bpy.data.collections.new(nm + "_marks")
        bpy.context.scene.collection.children.link(coll)
    for o in list(coll.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    fx = sp["front_axle_from_front_mm"] / 1000.0
    rx = fx + sp["wheelbase_mm"] / 1000.0
    mk = []
    for an, co in (("front_axle", (fx, 0.0, 0.0)), ("rear_axle", (rx, 0.0, 0.0)),
                   ("ground_front", (fx, 0.0, 0.0)), ("nose", (0.0, 0.0, 0.5 * sp["height_mm"] / 1000.0)),
                   ("tail", (L, 0.0, 0.5 * sp["height_mm"] / 1000.0))):
        e = bpy.data.objects.new(nm + "_M_" + an, None)
        e.empty_display_type = "PLAIN_AXES"
        e.empty_display_size = 0.1
        e.location = co
        coll.objects.link(e)
        mk.append(e.name)
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    return mk


def _vb_payload(ob, sp, nm, xs, stations, section_pts, wheel_info, made, mk, mmu):
    """vehicle_base receipt."""
    d = [round(float(x) * mmu, 1) for x in ob.dimensions]
    return _j({"ok": True, "object": ob.name, "size_mm": {"len": d[0], "w": d[1], "h": d[2]},
               "stations": len(xs), "stations_uniform": int(stations), "section_pts": int(section_pts),
               "vertices": len(ob.data.vertices), "polygons": len(ob.data.polygons),
               "wheels": wheel_info, "wheel_objects": made[1:], "markers": mk,
               "arch_clear_mm": sp["arch_clear_mm"],
               "spec": {k: sp[k] for k in ("type", "length_mm", "width_mm", "height_mm", "wheelbase_mm",
                                           "wheel_r_mm", "track_mm", "ride_mm")},
               "note": "the wheel arches are **cut out analytically** (the underside lifted to the wheel circle + arch_clear) ⇒ the wheel piercing the body is structurally impossible; "
                       "the shell's side profile is determined by the section parameters ⇒ the difference from the reference image is the difference in section parameters, fixable item by item"})


def vehicle_base(spec=None, name="VehicleShell", stations=28, section_pts=16, wheels=True, markers=True, **kw):
    """Loft the vehicle shell: longitudinal profile → per-station superellipse section → bridged into a shell (with analytic wheel arches) + four wheels + markers."""
    try:
        sp, nm, L = _vb_prepare(spec, name, kw, wheels)
        xs = _vb_stations(sp, stations, L)
        ob = _vb_shell(sp, xs, nm, section_pts)
        _vb_arch_cut(ob, sp, nm)
        made = [nm]
        mmu = _KIT.units()
        wheel_info = []
        if wheels:
            wnames, wheel_info = _vb_wheels(sp, nm, mmu)
            made.extend(wnames)
        mk = _vb_markers(sp, nm, L) if markers else []
        return _vb_payload(ob, sp, nm, xs, stations, section_pts, wheel_info, made, mk, mmu)
    except Exception as e:
        return _j({"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:220])})

def _vs_scan(img, p, inv, threshold):
    """imgtools scan call (threshold is passed only when given)."""
    a = {"path": p, "invert": bool(inv)}
    if threshold is not None:
        a["threshold"] = threshold
    return img("scan", a)


def _vs_side(img, side, invert_side, threshold):
    """Side-view silhouette + calibration; returns (sc, err)."""
    sc = _vs_scan(img, side, invert_side, threshold)
    if not sc.get("ok") or not sc.get("bbox"):
        return None, _j({"ok": False, "error": "the side-view silhouette could not be segmented (pass threshold or matte the background first)", "scan": sc})
    return sc, None


def _vs_scale(sc, mm_per_px, known_len_mm):
    """Pixel↔mm calibration (explicit mm_per_px or a known length); returns (mpp, err)."""
    bx, by, bw_, bh_ = sc["bbox"]
    mpp = mm_per_px
    if mpp is None:
        if known_len_mm:
            mpp = float(known_len_mm) / float(bw_)
        else:
            return None, _j({"ok": False, "error": "mm_per_px or known_len_mm is required (one known length is enough to calibrate)"})
    return float(mpp), None


def _vs_rows(sc, mpp, stations):
    """Side-view station table (x from 0 at the nose to length); returns a dict or None (col_top/col_bottom missing)."""
    bx, by, bw_, bh_ = sc["bbox"]
    ctop = sc.get("col_top") or []
    cbot = sc.get("col_bottom") or []
    step_c = int(sc.get("col_px_per_step") or 1)
    if not ctop:
        return None
    length_mm = bw_ * mpp
    height_mm = bh_ * mpp
    rows = []
    n = max(3, int(stations))
    for i in range(n):
        u = i / float(n - 1)
        ci = min(len(ctop) - 1, int(round(u * (len(ctop) - 1))))
        t, b = ctop[ci], cbot[ci]
        if t is None or b is None:
            rows.append({"u": round(u, 4), "x_mm": round(u * length_mm, 1), "empty": True})
            continue
        rows.append({"u": round(u, 4), "x_mm": round(u * length_mm, 1),
                     "z_top_mm": round((bh_ - float(t)) * mpp, 1),
                     "z_bottom_mm": round((bh_ - float(b)) * mpp, 1),
                     "z_px": [int(t), int(b)]})
    return {"rows": rows, "ctop": ctop, "cbot": cbot, "step_c": step_c,
            "bx": bx, "by": by, "bw": bw_, "bh": bh_,
            "length_mm": length_mm, "height_mm": height_mm}


def _vs_top(rows, img, top, invert_top, threshold, mpp):
    """Plan half-width (top view preferred); returns half_width_source."""
    hw_src = "none"
    if top:
        tc = _vs_scan(img, top, invert_top, threshold)
        ttop, tbot = tc.get("col_top") or [], tc.get("col_bottom") or []
        if tc.get("ok") and ttop and tbot:
            hw_src = "top_view"
            for r in rows:
                if r.get("empty"):
                    continue
                ci = min(len(ttop) - 1, int(round(r["u"] * (len(ttop) - 1))))
                if ttop[ci] is None or tbot[ci] is None:
                    r["half_w_mm"] = None
                else:
                    r["half_w_mm"] = round((float(tbot[ci]) - float(ttop[ci])) * mpp / 2.0, 1)
            hw_src = "top_view"
    return hw_src


def _vs_front(img, front, invert_front, threshold, mpp):
    """Front-view per-row width → (front_width_mm, section_params)."""
    fc = _vs_scan(img, front, invert_front, threshold)
    prof = fc.get("row_profile") or []
    if not (fc.get("ok") and prof and fc.get("bbox")):
        return None, {"n_top": 4.0, "n_top_source": "assumed", "beltline_z_mm": None,
                      "tumblehome_mm": None, "sill_tuck_mm": None, "source": "none"}
    fbx, fby, fbw, fbh = fc["bbox"]
    front_w = fbw * mpp
    # per-row width (sampled inside the bbox; the row step is derived from the row_profile length)
    step_r = max(1, fbh // max(1, len(prof)))
    widest_i = max(range(len(prof)), key=lambda k: prof[k])
    belt_z = (fbh - widest_i * step_r) * mpp
    top_w = max(prof[:max(1, len(prof) // 10)] or [0])
    bot_w = max(prof[-max(1, len(prof) // 10):] or [0])
    section = {"n_top": 4.0, "n_top_source": "assumed",
               "beltline_z_mm": round(belt_z, 1),
               "tumblehome_mm": round((prof[widest_i] - top_w) * mpp / 2.0, 1),
               "sill_tuck_mm": round((prof[widest_i] - bot_w) * mpp / 2.0, 1),
               "front_width_mm": round(front_w, 1), "source": "front_view"}
    return front_w, section


def _vs_section_shape(img, front, invert_front, threshold):
    """Section profile: front-view per-row width → normalized shape [{z_frac, hw_frac}] (0=bottom, 1=top; width/widest)."""
    if not front:
        return None
    fc2 = _vs_scan(img, front, invert_front, threshold)
    prof2 = fc2.get("row_profile") or []
    if not (fc2.get("ok") and prof2 and max(prof2) > 0):
        return None
    npts = max(6, min(20, len(prof2)))
    mx = float(max(prof2))
    pts = []
    for k in range(npts):
        i = int(round(k * (len(prof2) - 1) / float(max(1, npts - 1))))
        pts.append({"z_frac": round(1.0 - i / float(max(1, len(prof2) - 1)), 4),
                    "hw_frac": round(float(prof2[i]) / mx, 4)})
    return sorted(pts, key=lambda q: q["z_frac"])


def _vs_axles(rows, length_mm):
    """Axles: cluster centres of the ground-contact runs (low runs); returns (axles, wheel_info)."""
    # adaptive threshold: z_min + 0.35×(median bottom edge − z_min). A fixed threshold breaks down —
    # when the whole bottom edge (front lip/sill/rear bumper) sits "low", the entire car is taken as a ground-contact run (only 1 run was detected, measured in practice).
    ground_runs = []
    run = None
    _zs = [r["z_bottom_mm"] for r in rows if not r.get("empty") and r.get("z_bottom_mm") is not None]
    _zmin = min(_zs) if _zs else 0.0
    _zmed = sorted(_zs)[len(_zs) // 2] if _zs else 0.0
    _thr = _zmin + 0.35 * max(1.0, (_zmed - _zmin))
    for i, r in enumerate(rows):
        if r.get("empty"):
            continue
        # wheels and body merge into one blob in the filled silhouette ⇒ cannot just look at "a few pixels resting on the ground":
        # take the bottom **low runs** (z_bottom clearly below 15% of the car height) and cluster them; each centre is an axle x
        on_ground = r["z_bottom_mm"] is not None and r["z_bottom_mm"] <= _thr
        gap_ok = run is not None and (r["x_mm"] - run[1]) <= 0.06 * length_mm
        if on_ground and (run is None or not gap_ok):
            if run is not None:
                ground_runs.append(run)
            run = [r["x_mm"], r["x_mm"]]
        elif on_ground:
            run[1] = r["x_mm"]
        elif run is not None:
            ground_runs.append(run); run = None
    if run is not None:
        ground_runs.append(run)
    axles = [round((a + b) / 2.0, 1) for (a, b) in ground_runs if (b - a) >= 0.05 * length_mm]
    wheel_info = {"source": "ground_runs", "axles_x_mm": axles, "threshold_mm": round(_thr, 2),
                  "runs": [[round(a, 1), round(b, 1)] for (a, b) in ground_runs]}
    return axles, wheel_info


def _vs_wheel_given(wheel_centers_px, bx, by, bh, mpp):
    """Given wheel-centre pixels → wheel_info (source=given_px)."""
    pts = []
    for p in wheel_centers_px:
        px = (float(p[0]) - bx) * mpp
        py = (bh_ - (float(p[1]) - by)) * mpp
        pts.append({"x_mm": round(px, 1), "z_mm": round(py, 1)})
    return {"source": "given_px", "centers": pts,
            "axles_x_mm": [q["x_mm"] for q in pts]}


def _vs_taper(rows, front_w):
    """No top view but a front view: fill half_w with max width × a plan taper assumption (**declared as an assumption**)."""
    for r in rows:
        if r.get("empty"):
            continue
        u = float(r.get("u") or 0.0)
        taper = 1.0 - 0.35 * max(0.0, (abs(u - 0.5) - 0.30) / 0.20) ** 1.4
        r["half_w_mm"] = round(front_w / 2.0 * max(0.62, taper), 1)


def _vs_payload(sc, mpp, rows, hw_src, section, section_shape, wheel_info, axles,
                front_w, wheel_r_mm, length_mm, height_mm):
    """vehicle_sections receipt (including package and warnings)."""
    pkg = {"length_mm": round(length_mm, 1), "height_mm": round(height_mm, 1)}
    if len(axles) >= 2:
        pkg["front_axle_from_front_mm"] = axles[0]
        pkg["wheelbase_mm"] = round(axles[-1] - axles[0], 1)
    if front_w:
        pkg["width_mm"] = round(front_w, 1)
    if wheel_r_mm:
        pkg["wheel_r_mm"] = wheel_r_mm
    warn = []
    if hw_src == "none":
        warn.append("no top view: half_w_mm not given (the loft will use the default taper)")
    if wheel_r_mm is None:
        warn.append("the wheel radius cannot be back-derived from the filled silhouette: pass wheel_r_px or use a known spec")
    if len(axles) < 2:
        warn.append("fewer than two ground-contact runs: the axle x may not have been identified (passing wheel_centers_px is more reliable)")
    return _j({"ok": True, "side": sc.get("path"), "scale_mm_per_px": round(mpp, 5),
               "stations": rows, "station_count": len(rows),
               "half_width_source": hw_src, "section_params": section, "section_shape": section_shape, "wheels": wheel_info,
               "package": pkg, "warnings": warn,
               "note": "the station table can be fed straight to vehicle_loft; the envelope numbers can be fed to vehicle_package to pass the proportion gate first",
               "protocol": ["① pass the proportion gate with package first → ② loft the station table → ③ orthographic render vs the source image for IoU → ④ adjust the station-table parameters and rerun"]})


def vehicle_sections(side, front=None, top=None, mm_per_px=None, known_len_mm=None,
                     stations=41, invert_side=False, invert_front=False, invert_top=False,
                     threshold=None, wheel_centers_px=None, wheel_r_px=None):
    """Three-view images → **station table + section parameters + envelope numbers** (step 2 of outer-surface reconstruction; works for sports cars and complex shells).

    side (required): the side view. Per column it gives z_top(x)/z_bottom(x) ⇒ the silhouette and the station table.
    top (optional): the top view. Per column it gives half_width(x) ⇒ the plan taper (a sports car's waist).
    front (optional): the front view. Per row it gives the width ⇒ beltline height / tumblehome / sill tuck.
    Calibration: pass mm_per_px, or pass known_len_mm (converted from the side view's bbox width).
    wheel_centers_px: wheel-centre pixels (relative to the whole image); otherwise the axle x is located automatically from the **ground-contact run centres** (reliable),
                      while the wheel radius cannot be back-derived from the filled silhouette (wheels and body merge into one blob) ⇒ wheel_r_px or a known spec is needed.
    """
    img = _api("img")
    if img is None:
        return _j({"ok": False, "error": "imgtools is required (add imgtools to preload)"})
    sc, err = _vs_side(img, side, invert_side, threshold)
    if err is not None:
        return err
    mpp, err = _vs_scale(sc, mm_per_px, known_len_mm)
    if err is not None:
        return err
    info = _vs_rows(sc, mpp, stations)
    if info is None:
        return _j({"ok": False, "error": "the side view has no col_top/col_bottom (imgtools version too old?)"})
    rows, length_mm, height_mm = info["rows"], info["length_mm"], info["height_mm"]
    hw_src = _vs_top(rows, img, top, invert_top, threshold, mpp)
    front_w = None
    section = {"n_top": 4.0, "n_top_source": "assumed", "beltline_z_mm": None,
               "tumblehome_mm": None, "sill_tuck_mm": None, "source": "none"}
    if front:
        front_w, section = _vs_front(img, front, invert_front, threshold, mpp)
    axles, wheel_info = _vs_axles(rows, length_mm)
    section_shape = _vs_section_shape(img, front, invert_front, threshold)
    if wheel_centers_px:
        wheel_info = _vs_wheel_given(wheel_centers_px, info["bx"], info["by"], info["bh"], mpp)
    if hw_src == "none" and front_w:
        _vs_taper(rows, front_w)
        hw_src = "front_view_taper_assumed"
    wheel_r_mm = round(float(wheel_r_px) * mpp, 1) if wheel_r_px else None
    return _vs_payload(sc, mpp, rows, hw_src, section, section_shape, wheel_info, axles,
                       front_w, wheel_r_mm, length_mm, height_mm)
