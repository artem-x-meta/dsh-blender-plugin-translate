# -*- coding: utf-8 -*-
"""Split from vehicle.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403

def _apply_insets(pts, insets):
    """Feature lines (geometry layer): pull ring points that fall inside a given height band and x interval **inward** by inset_mm ⇒ facets/grooves.

    inset spec: {"z_mm": 900, "band_mm": 60, "inset_mm": 12, "x_mm": [400, 3900], "weight": 1.0}
                {"frac": 0.55, ...} also works (located by that station's height fraction)
    """
    if not insets:
        return pts, 0
    out = []
    hit = 0
    for (x, y, z) in pts:
        ny = y
        for sp in insets:
            band = float(sp.get("band_mm") or 60.0) / 1000.0
            ins = float(sp.get("inset_mm") or 0.0) / 1000.0
            if ins <= 0:
                continue
            w = float(sp.get("weight") or 1.0)
            zt = sp.get("z_mm")
            if zt is None and sp.get("frac") is not None:
                zt = None      # frac needs that station's top/bottom bounds and the caller converts it; only z_mm is honoured here
            if zt is None:
                continue
            zt = float(zt) / 1000.0
            xr = sp.get("x_mm")
            if xr and not (float(xr[0]) / 1000.0 <= x <= float(xr[1]) / 1000.0):
                continue
            if abs(z - zt) <= band:
                k = 1.0 - (abs(z - zt) / band) ** 2      # strongest at the band centre, smooth at the edges
                ny = ny - (1.0 if y >= 0 else -1.0) * ins * k * w
                hit += 1
        out.append((x, ny, z))
    return out, hit


def _mark_creases_idx(me, ring_co, lines, edge_of=None, attr_name="crease_edge", default_w=0.7):
    """Mark creases by **ring index** (reliable): a longitudinal line = the edges joining each ring's "point nearest the target"; a transverse line = one ring's full loop of edges.

    Why not match by z band: that requires both endpoints of an edge to fall inside the band, while the vertices around a ring are discrete,
    so at the target height there is often **no edge at all** (measured in practice: frac=0.55 crease gave 0 edges).
    spec: {"frac":0.55} (by each ring's own height fraction) · {"z_mm":560} (absolute height) · {"x_mm":1500} (transverse seam) · {"at":0.5} (ring param)
    """
    if not lines or not ring_co or not ring_co[0]:
        return []
    n = len(ring_co[0])
    K = len(ring_co)
    if edge_of is None:
        edge_of = {}
        for e in me.edges:
            a, b = e.vertices[0], e.vertices[1]
            edge_of[(min(a, b), max(a, b))] = e.index
    attr = me.attributes.get(attr_name)
    if attr is None:
        attr = me.attributes.new(attr_name, "FLOAT", "EDGE")
    out = []
    for sp in lines:
        w = float(sp.get("weight") or default_w)
        marked = 0
        xv = sp.get("x_mm")
        if isinstance(xv, (int, float)) and not isinstance(xv, bool):
            xt = float(xv) / 1000.0
            k = min(range(K), key=lambda q: abs(ring_co[q][0][0] - xt))
            for i in range(n):
                a = k * n + i
                b = k * n + ((i + 1) % n)
                key = (min(a, b), max(a, b))
                if key in edge_of:
                    attr.data[edge_of[key]].value = w
                    marked += 1
        else:
            xr = sp.get("x_mm") if isinstance(sp.get("x_mm"), (list, tuple)) else None
            idxs = []
            for k in range(K):
                if xr and not (float(xr[0]) / 1000.0 - 1e-6 <= ring_co[k][0][0] <= float(xr[1]) / 1000.0 + 1e-6):
                    idxs.append(None)
                    continue
                zs = [q[2] for q in ring_co[k]]
                zb, zt = min(zs), max(zs)
                if sp.get("at") is not None:
                    idxs.append(min(n - 1, max(0, int(round(float(sp["at"]) * (n - 1))))))
                    continue
                if sp.get("frac") is not None:
                    tgt = zb + float(sp["frac"]) * (zt - zb)
                else:
                    tgt = float(sp.get("z_mm") or 0.0) / 1000.0
                idxs.append(min(range(n), key=lambda i: abs(ring_co[k][i][2] - tgt)))
            for k in range(K - 1):
                if idxs[k] is None or idxs[k + 1] is None:
                    continue
                a = k * n + idxs[k]
                b = (k + 1) * n + idxs[k + 1]
                key = (min(a, b), max(a, b))
                if key in edge_of:
                    attr.data[edge_of[key]].value = w
                    marked += 1
        row = {"spec": {q: sp[q] for q in sp if q in ("z_mm", "frac", "at", "x_mm", "weight", "radius_mm", "segments")}, "edges": marked}
        if marked == 0:
            row["hint"] = "no edges marked: a transverse line (numeric x_mm) inserts a station automatically; for a longitudinal line check that frac/z_mm lies inside the geometry range"
        out.append(row)
    return out


def _mark_creases(me, lines, zmin, zmax, xmin, xmax):
    """Feature lines (crease layer): apply SubD crease weights to ring edges at a given height/position (the source of the faceted look).

    spec: {"z_mm": 900, "tol_mm": 40, "x_mm": [400, 3900], "weight": 0.8}   ← longitudinal beltline/door line
          {"frac": 0.55, "tol_frac": 0.06, "weight": 0.7}                    ← by height fraction (old crease_shoulder)
          {"x_mm": 1500, "tol_mm": 60, "weight": 1.0}                        ← transverse (A-pillar/seam)
    Returns [{spec summary, edges}]. Blender 4+ creases go through the crease_edge attribute (e.crease_weight no longer exists).
    """
    if not lines:
        return []
    attr = me.attributes.get("crease_edge")
    if attr is None:
        attr = me.attributes.new("crease_edge", "FLOAT", "EDGE")
    zr = max(1e-6, zmax - zmin)
    xr = max(1e-6, xmax - xmin)
    res = []
    for sp in lines:
        w = float(sp.get("weight") or 0.7)
        zt = sp.get("z_mm")
        if zt is None and sp.get("frac") is not None:
            zt = zmin + float(sp["frac"]) * zr
        xt = sp.get("x_mm") if not isinstance(sp.get("x_mm"), (list, tuple)) else None
        ztol = float(sp.get("tol_mm") or 40.0) / 1000.0 if sp.get("z_mm") is not None else zr * float(sp.get("tol_frac") or 0.06)
        xtol = float(sp.get("tol_mm") or 60.0) / 1000.0
        zrange = sp.get("z_range_mm") if isinstance(sp.get("z_range_mm"), (list, tuple)) else None
        xrange = sp.get("x_mm") if isinstance(sp.get("x_mm"), (list, tuple)) else None
        n = 0
        for e in me.edges:
            a = me.vertices[e.vertices[0]].co
            b = me.vertices[e.vertices[1]].co
            hit = True
            if zt is not None:
                zt_m = float(zt) / 1000.0
                if not (abs(a.z - zt_m) <= ztol and abs(b.z - zt_m) <= ztol):
                    hit = False
            if hit and xt is not None:
                xt_m = float(xt) / 1000.0
                if not (abs(a.x - xt_m) <= xtol and abs(b.x - xt_m) <= xtol):
                    hit = False
            if hit and xrange and not (float(xrange[0]) / 1000.0 - 1e-6 <= a.x <= float(xrange[1]) / 1000.0 + 1e-6):
                hit = False
            if hit and zrange and not (float(zrange[0]) / 1000.0 - 1e-6 <= a.z <= float(zrange[1]) / 1000.0 + 1e-6):
                hit = False
            if hit:
                attr.data[e.index].value = w
                n += 1
        row = {"spec": {k: sp[k] for k in sp if k in ("z_mm", "frac", "x_mm", "tol_mm", "tol_frac", "weight")}, "edges": n}
        if n == 0:
            row["hint"] = ("no ring edge hit: for a longitudinal line check z_mm/tol_mm and z_range; when a transverse line falls between two stations "
                           "vehicle_loft inserts a station automatically (just give a numeric x_mm), or widen tol_mm")
        res.append(row)
    return res


def _ring_from_outline(st, outline, flare=0.0):
    """**Custom section outline** (may be asymmetric: aerofoil/cambered/irregular): outline = [[y_mm, z_mm], …] closed outline.

    Difference from _ring_from_shape: shape is "per-row width from the front view" then mirrored (necessarily left-right symmetric),
    whereas outline uses the given outline directly — left and right may differ (aerofoils have camber, side-mounted parts are asymmetric).
    Scaled per station: y normalised by that station's half-width, z by that station's height.
    """
    x = st["x_mm"] / 1000.0
    zt, zb = st.get("z_top_mm"), st.get("z_bottom_mm")
    if zt is None or zb is None:
        return None
    zt, zb = zt / 1000.0, zb / 1000.0
    pts = [(float(q[0]) / 1000.0, float(q[1]) / 1000.0) for q in (outline or [])]
    if len(pts) < 3:
        return None
    ymax = max(abs(q[0]) for q in pts) or 1e-6
    zmin = min(q[1] for q in pts)
    zmax = max(q[1] for q in pts)
    hw = (st.get("half_w_mm") or 0.0) / 1000.0 + flare / 1000.0
    if hw <= 0:
        hw = 0.35 * max(1e-4, zt - zb)
    sy = hw / ymax
    sz = (zt - zb) / max(1e-6, zmax - zmin)
    return [(x, q[0] * sy, zb + (q[1] - zmin) * sz) for q in pts]


def _ring_from_shape(st, shape, flare=0.0):
    """Build a ring from the **section profile measured in the front view** (metres): z_frac → half-width ratio × this station's half-width."""
    x = st["x_mm"] / 1000.0
    zt, zb = st.get("z_top_mm"), st.get("z_bottom_mm")
    if zt is None or zb is None:
        return None
    zt, zb = zt / 1000.0, zb / 1000.0
    hw = (st.get("half_w_mm") or 0.0) / 1000.0 + flare / 1000.0
    if hw <= 0:
        hw = 0.35 * max(1e-4, zt - zb)
    right = []
    for q in shape:
        z = zb + float(q["z_frac"]) * (zt - zb)
        y = hw * float(q["hw_frac"])
        right.append((x, y, z))
    left = [(x, -y, z) for (x, y, z) in reversed(right)]
    return right + left


def _ring_from_station(st, n=24, n_top=4.0, n_bot=4.0, tumblehome=0.0, beltline_frac=0.55,
                       shoulder_inset=0.0, sill_tuck=0.0, flare=0.0):
    """Generate one station ring from the section parameters (metres): separate superellipse exponents for the upper/lower half, including tumblehome/beltline step/sill tuck."""
    x = st["x_mm"] / 1000.0
    zt = st.get("z_top_mm")
    zb = st.get("z_bottom_mm")
    hw = (st.get("half_w_mm") or 0.0) / 1000.0
    if zt is None or zb is None:
        return None
    zt, zb = zt / 1000.0, zb / 1000.0
    if hw <= 0:
        hw = 0.5 * max(0.35, 1.0 - 0.5 * abs(0.5 - (x / max(1e-9, x + 1.0)))) * (zt - zb)
    hw = hw + flare / 1000.0
    zc = 0.5 * (zt + zb)
    hh = max(1e-4, 0.5 * (zt - zb))
    belt_z = zb + (zt - zb) * float(beltline_frac)
    pts = []
    for i in range(int(n)):
        th = 2.0 * math.pi * i / float(n)
        ct, stn = math.cos(th), math.sin(th)
        up = stn >= 0.0
        exp = 2.0 / (float(n_top) if up else float(n_bot))
        yy = hw * math.copysign(abs(ct) ** exp, ct)
        zz = zc + hh * math.copysign(abs(stn) ** exp, stn)
        # tumblehome: linear taper by height above the beltline (in mm, meaning "how much it tapers from beltline to roof")
        if zz > belt_z and tumblehome > 0:
            k = (zz - belt_z) / max(1e-9, (zt - belt_z))
            yy *= max(0.2, 1.0 - (tumblehome / 1000.0) / max(1e-6, hw) * k)
        # beltline step: inset slightly near the beltline to form a facet
        if shoulder_inset > 0 and abs(zz - belt_z) < 0.12 * (zt - zb):
            yy *= max(0.2, 1.0 - (shoulder_inset / 1000.0) / max(1e-6, hw))
        # sill tuck
        if sill_tuck > 0 and zz < zb + 0.18 * (zt - zb):
            yy *= max(0.2, 1.0 - (sill_tuck / 1000.0) / max(1e-6, hw))
        pts.append((x, yy, zz))
    return pts


def _vehicle_loft_p1(st):
    crease_lines, flare_mm, flare_x_mm, inset_lines, name = (st.get("crease_lines"), st.get("flare_mm"), st.get("flare_x_mm"), st.get("inset_lines"), st.get("name"))
    shoulder_inset_mm, side, spec, stations = (st.get("shoulder_inset_mm"), st.get("side"), st.get("spec"), st.get("stations"))
    try:
        import bmesh as _bm
        if not stations:
            if not (isinstance(spec, dict) and spec.get("length_mm")) and side is None:
                return _j({"ok": False, "error": "give either stations (the output of vehicle_sections) or spec/side"})
            sp = vehicle_spec(**({k: v for k, v in (spec or {}).items() if k in DEFAULTS}), **kw) if spec else vehicle_spec(**kw)
            sp["_profile"] = _profile_points(sp)
            L = sp["length_mm"] / 1000.0
            n_st = 24
            stations = []
            for i in range(n_st):
                x = L * i / float(n_st - 1)
                lo, hi = _bottom_top_at(sp, x, sp["_profile"])
                lo = _arch_bottom(sp, x, lo)
                stations.append({"x_mm": x * 1000.0, "z_top_mm": hi * 1000.0, "z_bottom_mm": lo * 1000.0,
                                 "half_w_mm": 0.5 * sp["width_mm"] * (1.0 - 0.5 * max(0.0, (abs(x / max(1e-9, L) - 0.5) - 0.28) / 0.22) ** 1.4)})
        sts = [s for s in stations if s.get("z_top_mm") is not None and s.get("z_bottom_mm") is not None]
        if len(sts) < 3:
            return _j({"ok": False, "error": "fewer than 3 valid stations (the station table may not have measured a profile)"})
        if flare_mm and not flare_x_mm:
            # a wheel arch = a station whose bottom edge is **raised** (largest z_bottom), not the lowest point (that is the lowest lip/sill)
            highs = sorted(sts, key=lambda s: -s["z_bottom_mm"])[:2]
            flare_x_mm = [s["x_mm"] for s in highs]
        fl_set = set()
        if flare_mm and flare_x_mm:
            for s in sts:
                if any(abs(s["x_mm"] - fx) <= 0.12 * (sts[-1]["x_mm"] - sts[0]["x_mm"] + 1.0) for fx in flare_x_mm):
                    fl_set.add(round(s["x_mm"], 3))
        nm = str(name or "Shell")
        o0 = bpy.data.objects.get(nm)
        if o0 is not None:
            me0 = o0.data
            bpy.data.objects.remove(o0, do_unlink=True)
            if me0 is not None and me0.users == 0:
                bpy.data.meshes.remove(me0, do_unlink=True)
        me = bpy.data.meshes.new(nm)
        bm = _bm.new()
        rings = []
        ring_co = []
        # a transverse feature line ({"x_mm": 1500}) needs a **station** to land on the geometry: insert one if absent (otherwise 0 edges)
        inserted = 0
        for cl in (crease_lines or []):
            xv = cl.get("x_mm")
            if isinstance(xv, bool) or not isinstance(xv, (int, float)):
                continue
            xv = float(xv) / 1000.0
            xs_ = [s["x_mm"] / 1000.0 for s in sts]
            if any(abs(q - xv) <= 1e-4 for q in xs_):
                continue
            left = max([i for i in range(len(xs_)) if xs_[i] <= xv], default=None)
            right = min([i for i in range(len(xs_)) if xs_[i] >= xv], default=None)
            if left is None or right is None or left == right:
                continue
            t = (xv - xs_[left]) / max(1e-9, xs_[right] - xs_[left])
            ns = {"x_mm": xv * 1000.0, "_inserted": True}
            for k in ("z_top_mm", "z_bottom_mm", "half_w_mm"):
                a, b = sts[left].get(k), sts[right].get(k)
                ns[k] = None if (a is None or b is None) else a + t * (b - a)
            sts = sorted(sts + [ns], key=lambda s: s["x_mm"])
            inserted += 1
        inset_hits = 0
        insets_eff = list(inset_lines or [])
        if not insets_eff and shoulder_inset_mm:
            insets_eff = []      # the old parameter goes through _ring_from_station internals, so do not process it twice
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")


def _vehicle_loft_p2(st):
    bm, fl_set, inset_hits, insets_eff, me = st.get("bm"), st.get("fl_set"), st.get("inset_hits"), st.get("insets_eff"), st.get("me")
    nm, ring_co, rings, sts = st.get("nm"), st.get("ring_co"), st.get("rings"), st.get("sts")
    beltline_frac, close_ends, crease_lines, crease_shoulder, flare_mm = (st.get("beltline_frac"), st.get("close_ends"), st.get("crease_lines"), st.get("crease_shoulder"), st.get("flare_mm"))
    n_bot, n_top, section_outline, section_pts, section_shape = (st.get("n_bot"), st.get("n_top"), st.get("section_outline"), st.get("section_pts"), st.get("section_shape"))
    shoulder_inset_mm, sill_tuck_mm, tumblehome_mm = (st.get("shoulder_inset_mm"), st.get("sill_tuck_mm"), st.get("tumblehome_mm"))
    try:
        for s in sts:
            _fl = flare_mm if round(s["x_mm"], 3) in fl_set else 0.0
            if section_outline:
                ring = _ring_from_outline(s, section_outline, flare=_fl)
            elif section_shape:
                ring = _ring_from_shape(s, section_shape, flare=_fl)
            else:
                ring = _ring_from_station(s, n=int(section_pts), n_top=n_top, n_bot=n_bot,
                                          tumblehome=tumblehome_mm, beltline_frac=beltline_frac,
                                          shoulder_inset=shoulder_inset_mm, sill_tuck=sill_tuck_mm,
                                          flare=_fl)
            if ring is None:
                continue
            # feature lines (geometry layer): inset by height band/interval ⇒ facets, grooves
            if insets_eff:
                _z0 = min(q[2] for q in ring)
                _z1 = max(q[2] for q in ring)
                eff = []
                for sp in insets_eff:
                    q = dict(sp)
                    if q.get("z_mm") is None and q.get("frac") is not None:
                        q["z_mm"] = (_z0 + float(q["frac"]) * (_z1 - _z0)) * 1000.0
                    eff.append(q)
                ring, h = _apply_insets(ring, eff)
                inset_hits += h
            ring_co.append(list(ring))
            rings.append([bm.verts.new(p) for p in ring])
        for a, b in zip(rings, rings[1:]):
            for i in range(len(a)):
                j = (i + 1) % len(a)
                try:
                    bm.faces.new((a[i], a[j], b[j], b[i]))
                except Exception:
                    pass
        if close_ends:
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
        # feature lines (crease layer): mark them whether or not subsurf is on (without subsurf the crease has no effect but is on record)
        _zmin = min(x.co.z for x in me.vertices)
        _zmax = max(x.co.z for x in me.vertices)
        _xmin = min(x.co.x for x in me.vertices)
        _xmax = max(x.co.x for x in me.vertices)
        lines_eff = list(crease_lines or [])
        if crease_shoulder and 0.0 < beltline_frac < 1.0:
            lines_eff = lines_eff + [{"frac": float(beltline_frac), "weight": float(crease_shoulder)}]
        # feature lines split two ways: crease (SubD crease = hard crease line) / bevel (**rounded**: real radius, real arc transition)
        radius_lines = [q for q in lines_eff if float(q.get("radius_mm") or 0.0) > 0]
        hard_lines = [q for q in lines_eff if float(q.get("radius_mm") or 0.0) <= 0]
        crease_report = _mark_creases_idx(me, ring_co, hard_lines) if hard_lines else []
        bevel_report = (_mark_creases_idx(me, ring_co, radius_lines, attr_name="bevel_weight_edge",
                                         default_w=1.0) if radius_lines else [])
        creases = sum(int(r.get("edges") or 0) for r in crease_report)   # legacy field: total creased ring edges
        bevel_info = None
        if bevel_report:
            bmax = max(float(q.get("radius_mm") or 0.0) for q in radius_lines)
            segs = int(max([int(q.get("segments") or 3) for q in radius_lines] or [3]))
            bv = ob.modifiers.new("feature_bevel", "BEVEL")
            try:
                bv.affect = "EDGES"
                bv.limit_method = "WEIGHT"
                bv.offset_type = "OFFSET"
            except Exception:
                pass
            bv.width = bmax / 1000.0            # metres (the model is in metres)
            bv.segments = max(1, min(8, segs))
            bv.profile = min(0.95, max(0.05, float(radius_lines[0].get("profile") or 0.5)))
            # 0.5 = perfect circle; >0.5 squarer (closer to a smooth G2 transition), <0.5 more concave
            bevel_info = {"radius_mm": bmax, "segments": bv.segments, "profile": round(float(bv.profile), 3), "edges": sum(int(q.get("edges") or 0) for q in bevel_report)}
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")


def _vehicle_loft_p3(st):
    bevel_info, bevel_report, crease_report, creases, fl_set = st.get("bevel_info"), st.get("bevel_report"), st.get("crease_report"), st.get("creases"), st.get("fl_set")
    inserted, inset_hits, ob, rings = st.get("inserted"), st.get("inset_hits"), st.get("ob"), st.get("rings")
    beltline_frac, flare_mm, n_bot, n_top, section_outline = (st.get("beltline_frac"), st.get("flare_mm"), st.get("n_bot"), st.get("n_top"), st.get("section_outline"))
    section_shape, shoulder_inset_mm, sill_tuck_mm, subsurf, tumblehome_mm = (st.get("section_shape"), st.get("shoulder_inset_mm"), st.get("sill_tuck_mm"), st.get("subsurf"), st.get("tumblehome_mm"))
    try:
        if int(subsurf or 0) > 0:
            ss = ob.modifiers.new("subsurf", "SUBSURF")
            ss.levels = int(subsurf)
            ss.render_levels = int(subsurf)
            for o in bpy.context.selected_objects:
                o.select_set(False)
            ob.select_set(True)
            bpy.context.view_layer.objects.active = ob
            for m in list(ob.modifiers):
                try:
                    bpy.ops.object.modifier_apply(modifier=m.name)
                except Exception:
                    pass
        elif bevel_report:
            # apply the bevel even without subsurf (otherwise the bevel only sits on the stack and the geometry never changes)
            for o in bpy.context.selected_objects:
                o.select_set(False)
            ob.select_set(True)
            bpy.context.view_layer.objects.active = ob
            for m in list(ob.modifiers):
                try:
                    bpy.ops.object.modifier_apply(modifier=m.name)
                except Exception:
                    pass
        d = [round(float(x) * 1000.0, 1) for x in ob.dimensions]
        return _j({"ok": True, "object": ob.name, "stations_used": len(rings),
                   "size_mm": {"len": d[0], "w": d[1], "h": d[2]},
                   "vertices": len(ob.data.vertices), "polygons": len(ob.data.polygons),
                   "section_source": ("custom_outline" if section_outline else ("front_view_shape" if section_shape else "superellipse")),
                   "section_params": {"n_top": n_top, "n_bot": n_bot, "tumblehome_mm": tumblehome_mm,
                                      "beltline_frac": beltline_frac, "shoulder_inset_mm": shoulder_inset_mm,
                                      "sill_tuck_mm": sill_tuck_mm},
                   "flare": {"mm": flare_mm, "at_x_mm": sorted(fl_set) if fl_set else []},
                   "crease_lines": crease_report, "crease_radius": bevel_report, "bevel": bevel_info,
                   "inset_hits": inset_hits, "stations_inserted": inserted,
                   "crease_edges": creases,
                   "note": "the station table sets the outline, the section parameters set the character (flatness/tumblehome/beltline/sill), flare sets wheel-arch width; "
                           "next: orthographic render + img_diff IoU against the source image, then adjust parameters and rerun"})
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")


def vehicle_loft(stations=None, name="Shell", section_pts=24, n_top=4.0, n_bot=4.0,
                 tumblehome_mm=0.0, beltline_frac=0.55, shoulder_inset_mm=0.0, sill_tuck_mm=0.0,
                 flare_mm=0.0, flare_x_mm=None, subsurf=1, crease_shoulder=0.0, close_ends=True,
                 section_shape=None, section_outline=None, crease_lines=None, inset_lines=None,
                 spec=None, side=None, **kw):
    """Station table → loft into a shell (step 3 of outer-surface reconstruction).

    stations: the station table from vehicle_sections (per station x_mm / z_top_mm / z_bottom_mm / half_w_mm).
    Section parameters: n_top (roof flatness) / n_bot (bottom squareness) / tumblehome_mm (lean-in) / beltline_frac (beltline position) /
              shoulder_inset_mm (beltline step) / sill_tuck_mm (sill tuck).
    flare_mm + flare_x_mm: wheel-arch **flaring** (most typical on sports-car rear arches); flare_x_mm defaults to the two lowest z_bottom positions in the station table.
    crease_shoulder>0: adds a SubD crease to the beltline ring edges (the source of the faceted look).
    You may also pass spec only: build a station table from the vehicle_spec profile first (simplified sports car), then loft.
    """
    st = dict(locals())
    try:
        for _fn_ in (_vehicle_loft_p1, _vehicle_loft_p2, _vehicle_loft_p3):
            _r = _fn_(st)
            if _r is not None:
                return _r
    except Exception as e:
        return _j({"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:220])})
