# -*- coding: utf-8 -*-
"""Split from qc_render.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403
from .lock import _lock_path, render_lock
from .geom import _collect_objs, _corners, _db_counts, _project_px, _solve_view
from .parts import _legend_line_count
from .main import qc_render_views

def _selftest_projection():
    """Old self-test content (kept verbatim from v0.8.8): the solved camera is re-checked with Blender's own world_to_camera_view.
    For each named view it gives: solved distance / pixel bbox after projecting the 8 corners / whether everything is inside the frame /
    per-point pixel difference between our own matrix and Blender's ground truth (proj_err_px)."""
    box_mn = Vector((-1.0, -0.5, 0.0))
    box_mx = Vector((1.0, 0.5, 2.0))
    center = (box_mn + box_mx) * 0.5
    corners = _corners(box_mn, box_mx)
    w = h = 512
    lens, sensor = 50.0, 36.0
    margin = 1.12
    sc = bpy.context.scene
    rx, ry = int(sc.render.resolution_x), int(sc.render.resolution_y)
    sc.render.resolution_x, sc.render.resolution_y = w, h
    cd = bpy.data.cameras.new("DSH_QC_SELFTEST_CAM")
    cd.lens = lens
    cd.sensor_width = sensor
    cd.sensor_fit = "AUTO"
    ob = bpy.data.objects.new("DSH_QC_SELFTEST_CAM", cd)
    sc.collection.objects.link(ob)
    ob.rotation_mode = "QUATERNION"
    rows = []
    srcs = {}
    errs = []
    try:
        for name, (az, el) in sorted(NAMED_VIEWS.items()):
            loc, d, osc, st = _solve_view(center, corners, az, el, w, h, lens, sensor, margin)
            ob.location = loc
            ob.rotation_quaternion = d.to_track_quat("-Z", "Y")
            try:
                bpy.context.view_layer.update()
            except Exception:
                pass
            bbox, src, err = _project_px(ob, corners, w, h)
            srcs[src] = srcs.get(src, 0) + 1
            if err is not None:
                errs.append(err)
            rows.append({"view": name, "dist": round(st["dist"], 4),
                         "bbox_px": bbox,
                         "inside_frame": bool(bbox[0] >= -0.5 and bbox[1] >= -0.5 and bbox[2] <= w + 0.5 and bbox[3] <= h + 0.5),
                         "fill": round(max((bbox[2] - bbox[0]) / float(w), (bbox[3] - bbox[1]) / float(h)), 4),
                         "proj_err_px": err})
    finally:
        try:
            bpy.data.objects.remove(ob, do_unlink=True)
            bpy.data.cameras.remove(cd)
        except Exception:
            pass
        sc.render.resolution_x, sc.render.resolution_y = rx, ry
    return {"res": [w, h], "margin": margin, "views": rows, "proj_sources": srcs,
            "proj_err_px_max": (round(max(errs), 6) if errs else None),
            "all_inside": all(r["inside_frame"] for r in rows),
            "expect": "all_inside=true; fill ≈ %.3f (=1/margin); proj_err_px ≈ 0 (own matrix vs Blender ground truth)"
                      % (1.0 / margin)}


# ---------------------------------------------------------------- scene snapshot (for the self-test)

def _scene_snapshot():
    """Scene snapshot: object count + per-object material slots (link/material name)/visibility/mesh and user counts + render settings + datablock counts.

    Why record material slots per object: parts_color works by **changing material slots**, so missing one object on restore
    means polluting the user's finished file; link must be recorded too (DATA/OBJECT slots have different write paths), and
    the mesh name together with users (linked copies swap the mesh temporarily).
    """
    sc = bpy.context.scene
    rs = sc.render
    objs = {}
    for ob in sc.objects:
        try:
            slots = [[str(s.link), (str(s.material.name) if s.material else None)] for s in ob.material_slots]
        except Exception:
            slots = None
        objs[str(ob.name)] = {"type": str(ob.type), "slots": slots,
                              "hide_render": bool(ob.hide_render),
                              "mesh": (str(ob.data.name) if ob.data is not None else None),
                              "mesh_users": (int(getattr(ob.data, "users", 0) or 0) if str(ob.type) == "MESH" else None)}
    ee = getattr(sc, "eevee", None)
    counts = _db_counts()
    try:
        # The renderer's own resident images ("Render Result" / "Viewer Node") only appear **on the first render**, so they are not a live change —
        # drop them from the snapshot, otherwise a fresh -b process misreads its own first render as "not restored" (measured: +2 images on the first render).
        counts["images"] = len([i for i in bpy.data.images
                                if str(i.name) not in ("Render Result", "Viewer Node")])
        counts["images_note"] = "excluded the renderer's resident Render Result / Viewer Node (not a live change)"
    except Exception:
        pass
    return {"objects": objs, "n_objects": len(sc.objects),
            "render": {"engine": str(rs.engine), "res": [int(rs.resolution_x), int(rs.resolution_y)],
                       "pct": int(rs.resolution_percentage), "film_transparent": bool(rs.film_transparent),
                       "filepath": str(rs.filepath), "format": str(rs.image_settings.file_format),
                       "color_mode": str(rs.image_settings.color_mode), "frame": int(sc.frame_current)},
            "camera": (str(sc.camera.name) if sc.camera else None),
            "view_transform": str(getattr(getattr(sc, "view_settings", None), "view_transform", None)),
            "samples": {"eevee_taa": (int(getattr(ee, "taa_render_samples", -1)) if ee is not None else None),
                        "cycles": (int(sc.cycles.samples) if hasattr(sc, "cycles") else None)},
            "counts": counts}


def _snap_diff(a, b, path=""):
    """Compare two snapshots item by item → list of difference strings (empty = all equal). The self-test uses it to assert "scene after rendering = scene before rendering"."""
    diffs = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(list(a.keys()) + list(b.keys()))):
            p = ("%s.%s" % (path, k)) if path else str(k)
            if k not in a:
                diffs.append("%s: absent before render, appeared after (%r)" % (p, b[k]))
            elif k not in b:
                diffs.append("%s: present before render, lost after (was %r)" % (p, a[k]))
            else:
                diffs.extend(_snap_diff(a[k], b[k], p))
        return diffs
    if a != b:
        diffs.append("%s: %r != %r" % (path or "(root)", a, b))
    return diffs


def _png_palette_hits(path, rgbs, tol=16):
    """Read the PNG and, for every legend color, count how many pixels in the image match it (±tol/255 per channel).

    Why judge this way: the value of a color-coded image is entirely "does the legend match the image" — under flat(Emission)+Standard
    the pixels of a part's solid area are the legend color; a mismatch means one of material/color transform/legend is wrong.
    """
    img = bpy.data.images.load(path, check_existing=False)
    try:
        w, h = int(img.size[0]), int(img.size[1])
        buf = np.empty(w * h * 4, dtype=np.float32)
        img.pixels.foreach_get(buf)
    finally:
        bpy.data.images.remove(img)
    px = np.clip(buf.reshape(h, w, 4)[:, :, :3], 0.0, 1.0) * 255.0
    hits = []
    for rgb in rgbs:
        d = np.abs(px - np.array([float(rgb[0]), float(rgb[1]), float(rgb[2])], dtype=np.float32))
        hits.append(int(np.count_nonzero(np.all(d <= float(tol), axis=2))))
    return hits


def _st_box_mesh(name, size=1.0, loc=(0.0, 0.0, 0.0)):
    """Box mesh for the self-test (built by hand with from_pydata: no bpy.ops context needed, runs headless and in the GUI)."""
    s = float(size) * 0.5
    verts = [(-s, -s, -s), (s, -s, -s), (s, s, -s), (-s, s, -s),
             (-s, -s, s), (s, -s, s), (s, s, s), (-s, s, s)]
    faces = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    me = bpy.data.meshes.new(name + "_mesh")
    me.from_pydata([(v[0] + loc[0], v[1] + loc[1], v[2] + loc[2]) for v in verts], [], faces)
    me.update()
    return me

def _read_jsonl(p):
    rows = []
    if p and os.path.isfile(p):
        with open(p, encoding="utf-8") as f:
            for ln in f:
                if ln.strip():
                    rows.append(json.loads(ln))
    return rows

def _st_build_parts(sc):
    made_objs, made_meshes, made_mats = [], [], []
    # ---- temporary parts: 4 (including 1 pair of **linked copies sharing one mesh** + 1 object with 0 slots) ——
    # laid out in a row along X (none missing in top view), both landing exactly on parts_color's most error-prone points.
    # Note: the two linked-copy objects **must sit at different positions** (they used to overlap → one was fully occluded,
    # its legend color could not be found in the image → A4 could not tell "wrong color" from "occluded").
    base_me = _st_box_mesh("DSH_QC_ST_B", 1.0)
    for m in (bpy.data.materials.new("DSH_QC_ST_M0"), bpy.data.materials.new("DSH_QC_ST_M1")):
        base_me.materials.append(m)
        made_mats.append(m)
    ob_a = bpy.data.objects.new("DSH_QC_ST_A", _st_box_mesh("DSH_QC_ST_A", 1.0))
    made_meshes.append(ob_a.data)
    mt = bpy.data.materials.new("DSH_QC_ST_MA")
    ob_a.data.materials.append(mt)
    made_mats.append(mt)
    ob_b = bpy.data.objects.new("DSH_QC_ST_B", base_me)          # shares its mesh with ob_c (linked copy)
    ob_c = bpy.data.objects.new("DSH_QC_ST_C", base_me)
    made_meshes.append(base_me)
    ob_d_me = _st_box_mesh("DSH_QC_ST_D", 1.0)                   # 0 material slots
    ob_d = bpy.data.objects.new("DSH_QC_ST_D", ob_d_me)
    made_meshes.append(ob_d_me)
    for ob, loc in ((ob_a, (3.2, 0.0, 0.5)), (ob_b, (4.8, 0.0, 0.5)),
                    (ob_c, (6.4, 0.0, 0.5)), (ob_d, (8.0, 0.0, 0.5))):
        ob.location = loc
        sc.collection.objects.link(ob)
        made_objs.append(ob)
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    parts_n = len(_collect_objs(None)[0])          # part count = all visible meshes (including the default scene's own)
    snap1 = _scene_snapshot()
    return made_objs, made_meshes, made_mats, parts_n, snap1

def _st_batch_parts_color(a, res, samples, outdir, lock_dir, parts_n, snap1, _chk):
    outdir_msgs = []
    # ---- batch 1: parts_color (flat; the top view keeps all 5 parts visible — A4 relies on it to judge "legend matches image")
    b1_views = a.get("views_batch1") or ["iso", "front", "top", "totally_bogus_view_xyz"]
    r1 = json.loads(qc_render_views({
        "mode": "parts_color", "parts_flat": True, "views": b1_views, "res": res, "samples": samples,
        "outdir": outdir, "tag": "selftest_pc", "warmup": True, "budget_s": 240,
        "jsonl": os.path.join(outdir, "selftest_pc.jsonl"), "lights_mode": "only",
        "lock_dir": lock_dir}))
    snap2 = _scene_snapshot()
    restore_diffs = _snap_diff(snap1, snap2)
    files = [e.get("path") for e in (r1.get("views") or [])]
    sizes = [int(e.get("bytes") or 0) for e in (r1.get("views") or [])]
    _chk("A1 parts_color renders", bool(r1.get("ok")) and len(files) >= 1 and all(s > 0 for s in sizes),
         "ok=%s count=%s bytes=%s" % (r1.get("ok"), len(files), sizes))
    _chk("A2 scene restored item by item after rendering (objects/material slots/engine/resolution/samples/color transform)", not restore_diffs,
         ("all equal" if not restore_diffs else "diffs: %s" % restore_diffs[:6]) + "; restore check=%s"
         % _j((r1.get("parts_color") or {}).get("restore", {}).get("ok")))
    legend = (r1.get("parts_color") or {}).get("legend_path")
    legend_lines = (_legend_line_count(legend) if (legend and os.path.isfile(legend)) else None)
    _chk("A3 legend exists and its row count == part count", bool(legend and os.path.isfile(legend))
         and legend_lines == parts_n == (r1.get("parts_color") or {}).get("parts"),
         "legend=%s rows=%s; independently counted visible meshes=%s; part count reported in the result=%s"
         % (legend, legend_lines, parts_n, (r1.get("parts_color") or {}).get("parts")))
    # A4: the palette colors must be findable on the flat image (use the top view one)
    used = []
    for row in ((r1.get("parts_color") or {}).get("assignments") or {}).values():
        if row.get("rgb"):
            used.append(row["rgb"])
    top_entry = None
    for e in (r1.get("views") or []):
        if str(e.get("view")) == "top":
            top_entry = e
    if top_entry is None and (r1.get("views") or []):
        top_entry = r1["views"][0]
    if top_entry and used:
        try:
            hits = _png_palette_hits(top_entry["path"], used)
        except Exception as e:
            hits = None
            outdir_msgs.append("failed to read the image: %s" % str(e)[:120])
        _chk("A4 legend colors are findable on the flat image (the color coding can be cross-checked)", bool(hits) and all(h > 0 for h in hits),
             "view=%s pixel hits per color=%s (tol=16/255; 0 = that part is fully occluded or the material/color transform is wrong)"
             % (top_entry.get("view"), hits))
    # B1/B2: every jsonl line has a device key; device is measured (null still reports its source)
    jl = r1.get("jsonl")
    lines = []
    if jl and os.path.isfile(jl):
        with open(jl, encoding="utf-8") as f:
            for ln in f:
                if ln.strip():
                    lines.append(json.loads(ln))
    has_dev = [("device" in ln) for ln in lines]
    dev_ok = [bool(ln.get("device")) and ln["device"].get("engine") for ln in lines]
    _chk("B1 every jsonl line has a device key", bool(lines) and all(has_dev),
         "jsonl=%s rows=%d all have the device key=%s; device=%s"
         % (jl, len(lines), all(has_dev), _j([ln.get("device") for ln in lines[:2]])))
    _chk("B2 device is measured (device_source given when null)", bool(lines) and all(
        (d and d.get("device") and d.get("source")) or ((not d or not d.get("device")) and ln.get("device_source"))
        for d, ln in zip([ln.get("device") for ln in lines], lines)),
        "this batch device=%s / source=%s" % (_j((r1.get("device") or {}).get("device")),
                                        (r1.get("device") or {}).get("source")))
    # C1: unknown names go to unknown_views, known views still render as usual
    known = [str(e.get("view")) for e in (r1.get("views") or [])]
    _chk("C1 unknown names go to unknown_views and known views still render",
         (r1.get("unknown_views") == ["totally_bogus_view_xyz"]) and len(known) == 3
         and set(known) == set(["iso", "front", "top"]) and known == ["front", "top", "iso"],
         "unknown_views=%s render_order=%s (catalog order) count=%s"
         % (_j(r1.get("unknown_views")), known, r1.get("count")))
    # C2/C3/C4: pure-function criteria (no rendering, fast)
    # v0.9.1: isoright was **corrected** from "→ iso" to "→ iso_br" (the catalog desc says iso-BR-top = rear upper right),
    # so this old assertion now uses isofrontright to keep guarding the old "isometric spelling → iso" contract.
    rr = resolve_view_names(["iso-FR-top", "isometric", "isofrontright", "front-left", "ISO_L"])
    _chk("C2 alias normalization (iso-FR-top/isometric/isofrontright → iso; front-left/ISO_L hit the catalog directly)",
         rr["names"] == ["iso", "iso_l", "front_left"] and not rr["unknown"]
         and len(rr["aliases"]) == 3 and [x["resolved"] for x in rr["aliases"]] == ["iso"] * 3,
         "names=%s aliases=%s unknown=%s" % (_j(rr["names"]), _j(rr["aliases"]), _j(rr["unknown"])))
    bad = [k for k, v in LEGACY_NAMED_VIEWS.items() if NAMED_VIEWS.get(k) != v]
    _chk("C3 legacy named-view angles unchanged item by item", not bad and len(VIEW_CATALOG) >= len(LEGACY_NAMED_VIEWS),
         "all %d legacy names equal (diffs %s); the catalog has %d names" % (len(LEGACY_NAMED_VIEWS), bad or "none", len(VIEW_CATALOG)))
    rr2 = resolve_view_names(["top", "front", "front", "iso"])
    _chk("C4 catalog order + dedup (catalog criteria)",
         rr2["names"] == ["front", "top", "iso"] and rr2["deduped"] == ["front"],
         "names=%s deduped=%s (order comes from the catalog, not the request order)" % (_j(rr2["names"]), _j(rr2["deduped"])))
    # E1: the material override really reached the render (same view, same color transform, only materials differ → the hash must differ)
    r2 = json.loads(qc_render_views({
        "views": ["iso"], "res": res, "samples": samples, "outdir": outdir, "tag": "selftest_plain",
        "warmup": False, "view_transform": "Standard",
        "jsonl": os.path.join(outdir, "selftest_plain.jsonl"), "lights_mode": "only",
        "lock_dir": lock_dir}))
    h_pc = None
    for e in (r1.get("views") or []):
        if str(e.get("view")) == "iso":
            h_pc = e.get("hash")
    h_plain = ((r2.get("views") or [{}])[0]).get("hash")
    _chk("E1 material override really reached the render (plain vs parts_color hash differs for the same view)",
         bool(h_pc) and bool(h_plain) and h_pc != h_plain,
         "parts_color.iso=%s plain.iso=%s" % (h_pc, h_plain))
    snap3 = _scene_snapshot()
    d3 = _snap_diff(snap1, snap3)
    _chk("E1b the second batch on the same setup is restored too (plain batch)", not d3, ("all equal" if not d3 else "diffs: %s" % d3[:6]))
    return {"batch1": r1, "batch2": r2, "hits": hits, "legend_lines": legend_lines}

def _st_phase_v091a(a, res, samples, outdir, lock_dir, sc, _chk):
    # ---- F1 (A1): all views unknown → ok:false and **nothing rendered** (also checks that the output directory holds no fallback PNG / jsonl)
    # Note: these must be **truly unknown names** (no spelling an alias could hit) — "side_left/side_right" went into the
    # alias table in v0.9.1 (A1-4); using them as "all unknown" would resolve through the alias → that is F1b's "partially unknown" case.
    a1_dir = os.path.join(outdir, "selftest_a1_unknown", time.strftime("%Y%m%d-%H%M%S"))
    r3 = json.loads(qc_render_views({
        "views": ["muzzle_end", "breech_end", "flux_capacitor", "side"],
        "res": res, "samples": samples, "outdir": a1_dir, "tag": "selftest_a1",
        "jsonl": os.path.join(a1_dir, "selftest_a1.jsonl"), "lock_dir": lock_dir}))
    a1_files = sorted(os.listdir(a1_dir)) if os.path.isdir(a1_dir) else []
    a1_pngs = [n for n in a1_files if n.lower().endswith(".png")]
    a1_jsonls = [n for n in a1_files if n.lower().endswith(".jsonl")]
    _chk("F1 A1 all names unknown → ok:false and nothing rendered (no fallback image / no jsonl / no PNG)",
         (r3.get("ok") is False) and r3.get("rendered_count") == 0 and r3.get("count") == 0
         and r3.get("unknown_count") == 4
         and r3.get("unknown_views") == ["muzzle_end", "breech_end", "flux_capacitor", "side"]
         and r3.get("no_guess_views") == ["muzzle_end", "breech_end"]
         and bool(r3.get("available_views")) and len(r3.get("available_views") or []) == len(VIEW_CATALOG)
         and bool(r3.get("hint")) and bool(r3.get("view_menu")) and not a1_pngs and not a1_jsonls,
         "ok=%s rendered_count=%s unknown_count=%s no_guess=%s outdir=%s files=%s available_views=%d hint=%s"
         % (r3.get("ok"), r3.get("rendered_count"), r3.get("unknown_count"), _j(r3.get("no_guess_views")),
            a1_dir, _j(a1_files), len(r3.get("available_views") or []), str(r3.get("hint"))[:80]))

    # ---- F1b (A1): the **original repro list** from the 93 feedback (side_left/side_right/muzzle_end/breech_end) ——
    # after A1-4 added spelling aliases, the former resolve to left/right while the latter are still not guessed → "partially unknown":
    # 2 rendered, counts 2/4/2 obvious at a glance; **the key criterion is that the artifacts contain no iso/top/front fallback images**
    # (v0.8.11 silently rendered those 4).
    a1b_dir = os.path.join(outdir, "selftest_a1_repro", time.strftime("%Y%m%d-%H%M%S"))
    r3b = json.loads(qc_render_views({
        "views": ["side_left", "side_right", "muzzle_end", "breech_end"], "warmup": False,
        "res": res, "samples": samples, "outdir": a1b_dir, "tag": "selftest_a1b",
        "jsonl": os.path.join(a1b_dir, "selftest_a1b.jsonl"), "lights_mode": "only", "lock_dir": lock_dir}))
    a1b_pngs = sorted([n for n in os.listdir(a1b_dir)
                       if n.lower().endswith(".png")]) if os.path.isdir(a1b_dir) else []
    _chk("F1b A1 original list from the 93 feedback → 2 aliased + 2 unknown (counts 2/4/2), and **no iso/front/top fallback images**",
         bool(r3b.get("ok")) and r3b.get("requested_count") == 4 and r3b.get("rendered_count") == 2
         and r3b.get("unknown_count") == 2 and r3b.get("count") == 2
         and set(a1b_pngs) == set(["selftest_a1b_left.png", "selftest_a1b_right.png"])
         and not [n for n in a1b_pngs if n.endswith(("_iso.png", "_top.png", "_front.png"))],
         "requested/rendered/unknown=%s/%s/%s artifacts=%s (should be the two left/right images, no fallback)"
         % (r3b.get("requested_count"), r3b.get("rendered_count"), r3b.get("unknown_count"), _j(a1b_pngs)))

    # ---- F2/F6 (A1 default / A2 default Standard): views omitted → the 3 default views (v0.8.11 criteria); every jsonl line has view_transform
    vt_scene_before = str(getattr(getattr(sc, "view_settings", None), "view_transform", None))
    r4 = json.loads(qc_render_views({
        "res": res, "samples": samples, "outdir": outdir, "tag": "selftest_default4",
        "warmup": False, "jsonl": os.path.join(outdir, "selftest_default4.jsonl"),
        "lights_mode": "only", "lock_dir": lock_dir}))
    d4_names = [str(e.get("view")) for e in (r4.get("views") or [])]
    vt_scene_after = str(getattr(getattr(sc, "view_settings", None), "view_transform", None))
    _chk("F2 A1 views omitted → the 3 default views (iso/front/right, matching v0.8.11) + counts consistent",
         bool(r4.get("ok")) and d4_names == ["front", "right", "iso"] and r4.get("count") == 3
         and r4.get("requested_count") == 3 and r4.get("rendered_count") == 3
         and r4.get("views_from") == "default_legacy" and r4.get("unknown_count") == 0,
         "render_order=%s requested_count=%s rendered_count=%s views_from=%s"
         % (_j(d4_names), r4.get("requested_count"), r4.get("rendered_count"), r4.get("views_from")))
    lines4 = _read_jsonl(r4.get("jsonl"))
    vt_lines4 = [ln.get("view_transform") for ln in lines4]
    vtr = r4.get("view_transform_restore") or {}
    _chk("F6 A2 defaulted view_transform measured as Standard + present on every jsonl line + scene restored item by item after rendering",
         r4.get("view_transform") == "Standard" and r4.get("view_transform_mode") == "default_standard"
         and bool(lines4) and all(v == "Standard" for v in vt_lines4)
         and bool(vtr.get("ok")) and vtr.get("scene_before") == vt_scene_before
         and vtr.get("scene_after") == vt_scene_before and vt_scene_after == vt_scene_before,
         "view_transform=%s mode=%s jsonl rows=%d per-row values=%s; scene before=%r after(restored)=%r snapshot=%s"
         % (r4.get("view_transform"), r4.get("view_transform_mode"), len(lines4), _j(set(vt_lines4)),
            vt_scene_before, vt_scene_after, _j(vtr)))
    return {"r3": r3, "a1_dir": a1_dir, "a1_pngs": a1_pngs, "a1_jsonls": a1_jsonls, "r3b": r3b, "a1b_dir": a1b_dir, "a1b_pngs": a1b_pngs, "r4": r4, "d4_names": d4_names, "lines4": lines4, "vt_scene_before": vt_scene_before}

def _st_phase_v091b(a, res, samples, outdir, lock_dir, _chk):
    # ---- F3/F4 (A1 partially unknown / aliases): requested/rendered/unknown counts + aliases take effect + *_end is not guessed
    r5 = json.loads(qc_render_views({
        "views": ["side_left", "iso_right", "muzzle_end"], "res": res, "samples": samples,
        "outdir": outdir, "tag": "selftest_alias", "warmup": False,
        "jsonl": os.path.join(outdir, "selftest_alias.jsonl"), "lights_mode": "only", "lock_dir": lock_dir}))
    n5 = [str(e.get("view")) for e in (r5.get("views") or [])]
    _chk("F3 A1 partially unknown → the three counts are correct (rendered_count < requested_count)",
         bool(r5.get("ok")) and r5.get("requested_count") == 3 and r5.get("rendered_count") == 2
         and r5.get("unknown_count") == 1 and r5.get("count") == 2
         and r5.get("unknown_views") == ["muzzle_end"],
         "requested_count=%s rendered_count=%s unknown_count=%s unknown_views=%s"
         % (r5.get("requested_count"), r5.get("rendered_count"), r5.get("unknown_count"),
            _j(r5.get("unknown_views"))))
    _chk("F4 A1 spelling aliases side_left→left / iso_right→iso_br take effect; muzzle_end still goes to unknown (not guessed)",
         n5 == ["left", "iso_br"]
         and sorted([(x.get("requested"), x.get("resolved")) for x in (r5.get("view_aliases_applied") or [])])
             == [("iso_right", "iso_br"), ("side_left", "left")]
         and r5.get("no_guess_views") == ["muzzle_end"] and r5.get("unknown_views") == ["muzzle_end"],
         "render_order=%s aliases=%s no_guess=%s" % (_j(n5), _j(r5.get("view_aliases_applied")),
                                                     _j(r5.get("no_guess_views"))))

    # ---- F5 (A1 old form still works): an explicit 3-view request still renders 3 images
    r5b = json.loads(qc_render_views({
        "views": ["iso", "front", "right"], "res": res, "samples": samples, "outdir": outdir,
        "tag": "selftest_explicit3", "warmup": False,
        "jsonl": os.path.join(outdir, "selftest_explicit3.jsonl"), "lights_mode": "only",
        "lock_dir": lock_dir}))
    _chk("F5 A1 an explicit 3-view request still renders 3 images (the old parameters form has not broken)",
         bool(r5b.get("ok")) and r5b.get("count") == 3
         and [str(e.get("view")) for e in (r5b.get("views") or [])] == ["front", "right", "iso"]
         and r5b.get("requested_count") == 3 and r5b.get("rendered_count") == 3,
         "render_order=%s count=%s requested_count=%s"
         % (_j([str(e.get("view")) for e in (r5b.get("views") or [])]), r5b.get("count"),
            r5b.get("requested_count")))
    return {"r5": r5, "n5": n5, "r5b": r5b}

def _st_phase_v091c(a, res, samples, outdir, lock_dir, r4, sc, assertions, _chk):
    # ---- F7 (A2 "scene" three-state): keep the scene value (non-Standard → warning), and the hash differs from the Standard one
    vt_orig = str(getattr(getattr(sc, "view_settings", None), "view_transform", None))
    vt_nonstd = None
    for _cand in ("AgX", "Filmic", "Khronos PBR Neutral", "Filmic Log", "Raw"):
        try:
            sc.view_settings.view_transform = _cand
            if str(sc.view_settings.view_transform) == _cand:
                vt_nonstd = _cand
                break
        except Exception:
            pass
    r6 = None
    if vt_nonstd is None:
        # this machine's OCIO has no non-Standard option → **explicitly marked untested** (no pretending this branch was measured)
        assertions.append({"name": "F7 A2 view_transform=\"scene\" keeps the scene value (warning when not Standard)",
                           "pass": False, "untested": True,
                           "detail": "this machine only offers Standard for view_transform, so the 'non-Standard + warning' branch cannot be measured"})
    else:
        r6 = json.loads(qc_render_views({
            "views": ["front"], "res": res, "samples": samples, "outdir": outdir, "tag": "selftest_scene",
            "warmup": False, "view_transform": "scene",
            "jsonl": os.path.join(outdir, "selftest_scene.jsonl"), "lights_mode": "only",
            "lock_dir": lock_dir}))
        sc_after6 = str(getattr(getattr(sc, "view_settings", None), "view_transform", None))
        lines6 = _read_jsonl(r6.get("jsonl"))
        warn6 = " ".join([str(w) for w in (r6.get("scope_warnings") or [])])
        h_std = [e.get("hash") for e in (r4.get("views") or []) if str(e.get("view")) == "front"]
        h_scn = [e.get("hash") for e in (r6.get("views") or []) if str(e.get("view")) == "front"]
        _chk("F7 A2 view_transform=\"scene\" keeps the scene value %s (warning when not Standard; hash differs from Standard)" % vt_nonstd,
             bool(r6.get("ok")) and r6.get("view_transform") == vt_nonstd
             and r6.get("view_transform_mode") == "scene" and r6.get("view_transform_assigned") is None
             and ("manual correction" in warn6) and sc_after6 == vt_nonstd
             and bool(lines6) and all(ln.get("view_transform") == vt_nonstd for ln in lines6)
             and bool(h_std) and bool(h_scn) and h_std[0] != h_scn[0],
             "view_transform=%s jsonl=%s warning=%s scene before/after=%s/%s; "
             "Standard.front=%s scene.front=%s (they must differ)"
             % (r6.get("view_transform"), _j([ln.get("view_transform") for ln in lines6]),
                ("present" if "manual correction" in warn6 else "absent"), vt_nonstd, sc_after6,
                (h_std or [None])[0], (h_scn or [None])[0]))
    try:
        sc.view_settings.view_transform = vt_orig          # restore the scene setting the self-test changed itself (E2 double-checks once more)
    except Exception:
        pass

    # ---- F8 (B1/B2): callable API
    _Kapi = getattr(_kernel(), "dsh_qc_render_api", None) if _kernel() is not None else None
    api_res = api_res2 = api_str = api_help = None
    api_err = None
    if _Kapi is None:
        api_err = "K.dsh_qc_render_api does not exist (kernel not injected?)"
    else:
        try:
            _unk = {"views": ["not_a_real_view_name"], "res": res, "outdir": outdir, "lock_dir": lock_dir}
            api_res = _Kapi("render_views", _unk)      # positional-argument form
            api_res2 = _Kapi(_unk)                     # dict only (equivalent to render_views)
            api_str = _Kapi["dispatch"]("render_catalog", "{}")   # old contract: still a str
            api_help = _Kapi("help")
        except Exception as e:
            api_err = "%s: %s" % (type(e).__name__, str(e)[:160])
    _chk("F8 B1/B2 api(...) returns a dict, api({...}) is equivalent, api[\"dispatch\"] still returns a str, api(\"help\") works",
         (api_err is None) and callable(_Kapi) and isinstance(api_res, dict) and isinstance(api_res2, dict)
         and isinstance(api_str, str) and isinstance(api_help, dict)
         and api_res.get("ok") is False and api_res.get("rendered_count") == 0
         and api_res2.get("unknown_views") == ["not_a_real_view_name"]
         and api_help.get("version") == QC_RENDER_VERSION,
         "callable=%s api(...)=%s api({...})=%s dispatch=%s help=%s err=%s"
         % (callable(_Kapi), type(api_res).__name__, type(api_res2).__name__, type(api_str).__name__,
            type(api_help).__name__, api_err))
    return {"r6": r6, "api_err": api_err, "api_res": api_res, "api_res2": api_res2, "api_str": api_str, "_Kapi": _Kapi}

def _st_phase_lock(lock_dir, lines4, r4, a, res, samples, outdir, sc, _Kapi, _chk):
    # ---- G1/G2/G3 (E1): lock primitives (self-test-only directory)
    def _lk(**kw):
        return json.loads(render_lock(dict({"dir": lock_dir}, **kw)))

    g1a = _lk(action="acquire", holder="selftest-A", ttl_s=600)
    g1b = _lk(action="acquire", holder="selftest-B", wait_s=1)
    _chk("G1 E1 A holds → B with wait_s=1 times out and is refused (reports holder + waited_ms ≥ 900)",
         bool(g1a.get("ok")) and bool(g1a.get("acquired")) and (g1b.get("ok") is False)
         and g1b.get("current_holder") == "selftest-A" and int(g1b.get("waited_ms") or 0) >= 900
         and os.path.isfile(_lock_path(lock_dir)) and bool(g1b.get("hint")),
         "A=%s; B ok=%s holder=%s waited_ms=%s path=%s"
         % (_j({k: g1a.get(k) for k in ("ok", "acquired", "holder", "waited_ms", "stale_broken")}),
            g1b.get("ok"), g1b.get("current_holder"), g1b.get("waited_ms"), _lock_path(lock_dir)))
    g2a = _lk(action="release", holder="selftest-B")        # holder mismatch → must be refused
    g2b = _lk(action="release", holder="selftest-A")        # the real holder → release
    g2c = _lk(action="acquire", holder="selftest-B", wait_s=0)
    g2s = _lk(action="status")
    _chk("G2 E1 a release with a mismatched holder is refused; after A releases, B can acquire (status reports B)",
         (g2a.get("ok") is False) and g2a.get("current_holder") == "selftest-A"
         and bool(g2b.get("ok")) and bool(g2b.get("released"))
         and bool(g2c.get("ok")) and bool(g2c.get("acquired")) and g2s.get("holder") == "selftest-B",
         "B release refused=%s (current %s); A release=%s; B re-acquire=%s; status holder=%s remaining_s=%s"
         % (g2a.get("ok"), g2a.get("current_holder"), g2b.get("released"), g2c.get("acquired"),
            g2s.get("holder"), g2s.get("remaining_s")))
    g2d = _lk(action="release", holder="selftest-B")
    # G3: forge a "stale lock" (acquired_at is a timestamp far in the past) → acquire must judge it stale by timestamp and break it
    _lp = _lock_path(lock_dir)
    os.makedirs(os.path.dirname(_lp), exist_ok=True)
    with open(_lp, "w", encoding="utf-8") as f:
        f.write(_j({"holder": "selftest-stale", "pid": 0, "acquired_at": time.time() - 9999.0,
                    "ttl_s": 600.0, "note": "stale lock forged by the self-test"}))
    g3 = _lk(action="acquire", holder="selftest-C", ttl_s=600, wait_s=0)
    g3r = _lk(action="release", holder="selftest-C")
    _chk("G3 E1 forged stale lock → broken with stale_broken=true, the new holder acquires it",
         bool(g3.get("ok")) and bool(g3.get("acquired")) and bool(g3.get("stale_broken"))
         and g3.get("holder") == "selftest-C" and bool(g3r.get("ok"))
         and bool(g3.get("stale_note")),
         "stale_broken=%s holder=%s waited_ms=%s note=%s" % (g3.get("stale_broken"), g3.get("holder"),
                                                             g3.get("waited_ms"), g3.get("stale_note")))
    # G4: the automatic lock is recorded in the artifacts (the lock field of every jsonl line)
    lock_paths4 = [((ln.get("lock") or {}).get("path")) for ln in lines4]
    lock_ok4 = all(isinstance(ln.get("lock"), dict) and (ln["lock"].get("acquired") is True)
                   and bool(ln["lock"].get("holder")) and ("waited_ms" in ln["lock"])
                   and ("stale_broken" in ln["lock"]) and bool(ln["lock"].get("path")) for ln in lines4)
    _chk("G4 E1 every jsonl line has lock{holder, waited_ms, acquired, stale_broken, path} (automatic lock)",
         bool(lines4) and lock_ok4 and all(p == _lock_path(lock_dir) for p in lock_paths4)
         and (r4.get("lock") or {}).get("released") is True,
         "rows=%d lock[0]=%s all paths equal=%s response lock.released=%s"
         % (len(lines4), _j(lines4[0].get("lock")) if lines4 else None,
            all(p == _lock_path(lock_dir) for p in lock_paths4), (r4.get("lock") or {}).get("released")))

    # ---- G5 (E1/B2): both of the engine's **route spellings** actually land (the ops the plan channel really sends)
    # engine.mjs: op="render_lock" → dispatch("lock") (the render_* branch slices by 7);
    #             op="render_status" → dispatch("status"); op="qc_render_lock" → dispatch("render_lock").
    g5, g5_err = {}, None
    if _Kapi is not None:
        try:
            for _op in ("lock", "render_lock", "status", "render_status"):
                _s = _Kapi["dispatch"](_op, _j({"action": "status", "dir": lock_dir}))
                g5[_op] = [isinstance(_s, str), bool(json.loads(_s).get("ok"))]
        except Exception as e:
            g5_err = "%s: %s" % (type(e).__name__, str(e)[:160])
    _chk("G5 E1 engine route spellings (lock / render_lock / status / render_status) all dispatch and still return a str",
         bool(g5) and g5_err is None and all(v[0] and v[1] for v in g5.values()),
         "per spelling=[returns str, ok]=%s err=%s" % (_j(g5), g5_err))

    # ---- G6 (E1 regression): cannot get the lock → **empty output ok:false**, and engine/samples must already be rolled back (early return does not pollute the scene)
    # Why it exists: this was hit once in practice — the lock-timeout early-return path skipped finally and left eevee.taa_render_samples
    # at 16 instead of 64 (caught by the E2 snapshot comparison). This assertion guards that regression specifically.
    _hold = _lk(action="acquire", holder="selftest-HOLD", ttl_s=600)
    _eng0 = str(sc.render.engine)
    _ee0 = int(getattr(getattr(sc, "eevee", None), "taa_render_samples", -1))
    _cy0 = int(sc.cycles.samples) if hasattr(sc, "cycles") else -1
    r7 = json.loads(qc_render_views({
        "views": ["front"], "res": res, "samples": 8, "outdir": outdir, "tag": "selftest_lockfail",
        "warmup": False, "lock_wait_s": 0, "lock_dir": lock_dir, "lights_mode": "only"}))
    _eng1 = str(sc.render.engine)
    _ee1 = int(getattr(getattr(sc, "eevee", None), "taa_render_samples", -1))
    _cy1 = int(sc.cycles.samples) if hasattr(sc, "cycles") else -1
    _pre = r7.get("prelock_restore") or {}
    _chk("G6 E1 cannot get the lock → empty output ok:false, and engine/samples rolled back (early return does not pollute the scene)",
         bool(_hold.get("ok")) and (r7.get("ok") is False) and r7.get("count") == 0
         and r7.get("rendered_count") == 0
         and (r7.get("lock") or {}).get("acquired") is False
         and r7.get("current_holder") == "selftest-HOLD"
         and r7.get("holder_ttl_remaining_s") is not None
         and bool(_pre.get("ok")) and _eng1 == _eng0 and _ee1 == _ee0 and _cy1 == _cy0,
         "ok=%s holder=%s remaining_s=%s; engine %s→%s · eevee %s→%s · cycles %s→%s · prelock=%s"
         % (r7.get("ok"), r7.get("current_holder"), r7.get("holder_ttl_remaining_s"),
            _eng0, _eng1, _ee0, _ee1, _cy0, _cy1, _j(_pre)))
    _lk(action="release", holder="selftest-HOLD")
    return {"g1b": g1b, "g3": g3}

def _st_cleanup(made_objs, made_meshes, made_mats, outdir, snap0):
    for ob in made_objs:
        try:
            bpy.data.objects.remove(ob, do_unlink=True)
        except Exception:
            pass
    for me in made_meshes:
        try:
            if me.users == 0:
                bpy.data.meshes.remove(me)
        except Exception:
            pass
    for m in made_mats:
        try:
            bpy.data.materials.remove(m, do_unlink=True)
        except Exception:
            pass
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    # v0.9.1: also remove the lock file (self-test-only directory; real users' locks live under K.workdir/locks and are never touched)
    try:
        _lp_clean = _lock_path(os.path.join(outdir, "selftest_lock"))
        if os.path.isfile(_lp_clean):
            os.remove(_lp_clean)
    except Exception:
        pass
    return _snap_diff(snap0, _scene_snapshot())

def _st_report(a, outdir, res, samples, parts_n, hits, legend_lines, batch1, batch2, assertions,
               r3, a1_dir, a1_pngs, a1_jsonls, r3b, a1b_dir, a1b_pngs, r4, d4_names,
               r5, n5, r5b, r6, api_err, api_res, api_res2, api_str, g1b, g3, lock_dir,
               cleanup_diffs, _chk):
    # ---- D1: projection cross-check (old self-test content)
    try:
        proj = _selftest_projection()
    except Exception as e:
        proj = {"error": "%s: %s" % (type(e).__name__, str(e)[:200])}
    _chk("D1 projection cross-check proj_err_px ≈ 0 (own matrix vs Blender ground truth)",
         bool(proj) and proj.get("all_inside") and (proj.get("proj_err_px_max") is None
                                                    or proj["proj_err_px_max"] < 0.05),
         "all_inside=%s proj_err_px_max=%s view count=%s" % (proj.get("all_inside"), proj.get("proj_err_px_max"),
                                                       len(proj.get("views") or [])))
    _chk("E2 self-test objects/materials/meshes cleaned up (back to the snapshot taken before entering the self-test)", not cleanup_diffs,
         ("all equal" if not cleanup_diffs else "diffs: %s" % cleanup_diffs[:8]))

    failed = [x["name"] for x in assertions if not x["pass"]]
    out = {"ok": not failed, "version": QC_RENDER_VERSION, "kind": "qc_render_selftest",
           "blender": str(bpy.app.version_string), "background": bool(bpy.app.background),
           "file": bpy.data.filepath, "outdir": outdir, "res": res, "samples": samples,
           "assertions": assertions, "failed": failed,
           "parts_color_batch": ({"ok": batch1.get("ok"), "count": batch1.get("count"),
                                  "mode": batch1.get("mode"), "jsonl": batch1.get("jsonl"),
                                  "legend": (batch1.get("parts_color") or {}).get("legend_path"),
                                  "legend_lines": legend_lines,
                                  "parts": (batch1.get("parts_color") or {}).get("parts"),
                                  "restore": (batch1.get("parts_color") or {}).get("restore"),
                                  "view_transform_defaulted":
                                      (batch1.get("parts_color") or {}).get("view_transform_defaulted"),
                                  "palette_hits": hits} if batch1 else None),
           "plain_batch": ({"ok": batch2.get("ok"), "count": batch2.get("count"),
                            "jsonl": batch2.get("jsonl")} if batch2 else None),
           "device": (batch1.get("device") if batch1 else None),
           "device_line": (batch1.get("device_line") if batch1 else None),
           "views": ({"unknown_views": batch1.get("unknown_views"), "render_order": batch1.get("render_order"),
                      "aliases": batch1.get("view_aliases_applied"), "menu": view_menu_text()} if batch1 else None),
           # ---- v0.9.1 (93 feedback): measured snapshots of A1/A2/E1/B (the self-test report must be reviewable by a human, not just the first few lines)
           "v091": {"a1_unknown": ({"ok": r3.get("ok"), "rendered_count": r3.get("rendered_count"),
                                    "unknown_views": r3.get("unknown_views"),
                                    "no_guess_views": r3.get("no_guess_views"), "outdir": a1_dir,
                                    "png_in_outdir": a1_pngs, "jsonl_in_outdir": a1_jsonls} if r3 else None),
                    "a1_repro_93": ({"ok": r3b.get("ok"), "requested_count": r3b.get("requested_count"),
                                     "rendered_count": r3b.get("rendered_count"),
                                     "unknown_count": r3b.get("unknown_count"),
                                     "png": a1b_pngs, "outdir": a1b_dir} if r3b else None),
                    "default4": ({"ok": r4.get("ok"), "render_order": d4_names,
                                  "requested_count": r4.get("requested_count"),
                                  "rendered_count": r4.get("rendered_count"), "views_from": r4.get("views_from"),
                                  "view_transform": r4.get("view_transform"),
                                  "view_transform_restore": r4.get("view_transform_restore"),
                                  "lock": r4.get("lock")} if r4 else None),
                    "partial_unknown": ({"ok": r5.get("ok"), "requested_count": r5.get("requested_count"),
                                         "rendered_count": r5.get("rendered_count"),
                                         "unknown_count": r5.get("unknown_count"),
                                         "render_order": n5,
                                         "aliases": r5.get("view_aliases_applied")} if r5 else None),
                    "explicit3": ({"ok": r5b.get("ok"), "count": r5b.get("count"),
                                   "render_order": [str(e.get("view")) for e in (r5b.get("views") or [])]}
                                  if r5b else None),
                    "scene_transform": ({"ok": r6.get("ok"), "view_transform": r6.get("view_transform"),
                                         "mode": r6.get("view_transform_mode"),
                                         "warnings": r6.get("scope_warnings")} if r6 else {"tested": False,
                                                                                            "reason": "this machine has no non-Standard option"}),
                    "api": {"callable": bool(api_err is None), "call_returns": type(api_res).__name__,
                            "dict_arg_returns": type(api_res2).__name__,
                            "dispatch_returns": type(api_str).__name__, "error": api_err},
                    "lock": {"g1_waited_ms": g1b.get("waited_ms"), "g1_holder": g1b.get("current_holder"),
                             "g3_stale_broken": g3.get("stale_broken"), "path": _lock_path(lock_dir),
                             "dir": lock_dir}},
           "projection": proj,
           "expect": "ok=true means A1-A4/B1-B2/C1-C4/D1/E1-E2 plus v0.9.1's F1-F8/G1-G6 all pass; "
                     "any failure → ok=false with the names listed in failed"}
    # Write the self-test report to disk: evidence must be reviewable by people and other sessions (tool return values get truncated by logs; the file on disk does not)
    try:
        rp = _win(a.get("report") or os.path.join(outdir, "qc_render_selftest.json"))
        with open(rp, "w", encoding="utf-8") as f:
            f.write(_j(out))
        out["report_path"] = rp
    except Exception as e:
        out["report_error"] = "%s: %s" % (type(e).__name__, str(e)[:160])
    return _j(out)

def qc_render_selftest(args=None):
    """Render harness self-test (v0.9.1 extension): projection cross-check (old content) + Procedura fusion (v0.8.11) + 93 feedback A1/A2/E1/B1-B2.

    **Must run in an isolated headless process** (it creates temporary objects, overrides material slots and renders; everything is restored,
    but the scene you are looking at should not be touched):
        blender_rt_headless(preload="qc,qc_render", engine="eevee", factory_startup=True, timeout_ms=300000,
                            script="import json;print('HEADLESS ' + K.dsh_qc_render_api['selftest']())")
    Refused by default in the GUI; to really run it pass {"allow_gui": true} (the objects it builds are deleted, but your scene gets rendered a few times).

    args: {"outdir": artifact directory (default K.out_dir), "res": default [192,192], "samples": default 16,
           "allow_gui": bool, "views_batch1": [...], "keep_files": bool}

    Assertions (ok = all pass; every one reports pass + detail in assertions, nothing silent):
      A1 parts_color renders (>=1 image, bytes > 0)          A2 the scene is **restored item by item** after rendering (object count/material slots/engine/resolution/samples/color transform)
      A3 the legend exists and its row count == part count   A4 every part's legend color is findable on the flat image (the color coding is not wrong)
      B1 every jsonl line has a device key (value may be null)  B2 device is measured: reports engine/device, or null + source
      C1 unknown names go to unknown_views, known views render as usual  C2 alias normalization (iso-FR-top/isometric/isofrontright → iso)
      C3 legacy named-view angles unchanged item by item (LEGACY_NAMED_VIEWS)  C4 catalog order + dedup take effect (catalog criteria)
      D1 projection cross-check proj_err_px ≈ 0 (old self-test content)
      E1 the material override really reached the render (plain vs parts_color hash differs for the same view)
      E2 self-test objects cleaned up (the scene returns to the snapshot taken before the self-test)
      —— v0.9.1 (93 feedback) additions ——
      F1 A1: all views unknown → ok:false and **nothing rendered** (no PNG at all in outdir, no fallback image)
      F2 A1: views omitted → the same 3 default views as v0.8.11 (iso/front/right); requested_count == rendered_count == 3
      F3 A1: partially unknown → rendered_count < requested_count and each of the three counts correct
      F4 A1: spelling aliases take effect (side_left→left, iso_right→iso_br), muzzle_end still goes to unknown (the no-guess discipline holds)
      F5 A1: an explicit 3-view request still renders 3 images (the old argument form has not broken)
      F6 A2: defaulted view_transform measured == "Standard", present on every jsonl line; the scene transform is restored item by item after rendering
      F7 A2: view_transform="scene" → keeps the scene value (warning when not Standard), and the hash differs from the Standard one
      F8 B: api("render_views", {...}) returns a dict, api({...}) is equivalent, api["dispatch"] still returns a str, api("help") works
      G1 E1: A holds → B with wait_s=1 times out and is refused (reports holder + waited_ms ≥ 900)
      G2 E1: a release with a mismatched holder is refused; after A releases, B can acquire
      G3 E1: a forged stale lock → broken with stale_broken=true, the new holder acquires it
      G4 E1: every jsonl line has lock{holder, waited_ms, acquired, stale_broken, path} (the automatic lock is recorded in the artifacts)
      G5 E1: engine route spellings (lock / render_lock / status / render_status) all dispatch and still return a str
      G6 E1 regression: cannot get the lock → empty output ok:false, and engine/samples rolled back (the early-return path does not pollute the scene)
    """
    a = _unpack_args(args)
    assertions = []

    def _chk(name, ok, detail):
        assertions.append({"name": name, "pass": bool(ok), "detail": detail})
        return bool(ok)

    if not bool(getattr(bpy.app, "background", False)) and not a.get("allow_gui"):
        return _j({"ok": False, "version": QC_RENDER_VERSION, "kind": "qc_render_selftest",
                   "error": "the self-test does not run in a GUI process by default (it temporarily changes the current scene's material slots and renders a few images)",
                   "hint": "run it headless in isolation: blender_rt_headless(preload=\"qc,qc_render\", engine=\"eevee\", "
                           "factory_startup=True, timeout_ms=300000, "
                           "script=\"import json;print('HEADLESS ' + K.dsh_qc_render_api['selftest']())\"); "
                           "if you really want it in the GUI, pass {\"allow_gui\": true}"})
    outdir = _win(a.get("outdir") or _out_dir())
    rv = a.get("res") or [192, 192]
    if isinstance(rv, (int, float)):
        rv = [int(rv), int(rv)]
    res = [max(64, int(rv[0])), max(64, int(rv[1]))]
    samples = int(a.get("samples") or 16)
    try:
        os.makedirs(outdir, exist_ok=True)
    except Exception as e:
        return _j({"ok": False, "error": "cannot create outdir: %s (%s)" % (outdir, e)})
    sc = bpy.context.scene
    snap0 = _scene_snapshot()
    # v0.9.1 (E1): the self-test **uses an isolated lock directory throughout** (<outdir>/selftest_lock) and never fights live renders for the real lock
    # — measured: the first two self-test batches did not pass lock_dir, hit the real lock, waited the full 120 s and failed, turning 9 legacy assertions red.
    lock_dir = os.path.join(outdir, "selftest_lock")
    made_objs, made_meshes, made_mats = [], [], []
    batch1 = batch2 = proj = None
    parts_n = legend_lines = None
    hits = None
    cleanup_diffs = None
    try:
        made_objs, made_meshes, made_mats, parts_n, snap1 = _st_build_parts(sc)
        _pm = _st_batch_parts_color(a, res, samples, outdir, lock_dir, parts_n, snap1, _chk)
        batch1, batch2 = _pm["batch1"], _pm["batch2"]
        hits, legend_lines = _pm["hits"], _pm["legend_lines"]
        _va = _st_phase_v091a(a, res, samples, outdir, lock_dir, sc, _chk)
        r3, a1_dir, a1_pngs, a1_jsonls = _va["r3"], _va["a1_dir"], _va["a1_pngs"], _va["a1_jsonls"]
        r3b, a1b_dir, a1b_pngs = _va["r3b"], _va["a1b_dir"], _va["a1b_pngs"]
        r4, d4_names, lines4 = _va["r4"], _va["d4_names"], _va["lines4"]
        _vb = _st_phase_v091b(a, res, samples, outdir, lock_dir, _chk)
        r5, n5, r5b = _vb["r5"], _vb["n5"], _vb["r5b"]
        _vc = _st_phase_v091c(a, res, samples, outdir, lock_dir, r4, sc, assertions, _chk)
        r6, api_err, api_res, api_res2, api_str = _vc["r6"], _vc["api_err"], _vc["api_res"], _vc["api_res2"], _vc["api_str"]
        _lk = _st_phase_lock(lock_dir, lines4, r4, a, res, samples, outdir, sc, _vc["_Kapi"], _chk)
        g1b, g3 = _lk["g1b"], _lk["g3"]
    finally:
        cleanup_diffs = _st_cleanup(made_objs, made_meshes, made_mats, outdir, snap0)
    return _st_report(a, outdir, res, samples, parts_n, hits, legend_lines, batch1, batch2, assertions,
                       r3, a1_dir, a1_pngs, a1_jsonls, r3b, a1b_dir, a1b_pngs, r4, d4_names,
                       r5, n5, r5b, r6, api_err, api_res, api_res2, api_str, g1b, g3, lock_dir,
                       cleanup_diffs, _chk)
