# -*- coding: utf-8 -*-
"""Second half of qc_render_views: site setup / per-view rendering / post-batch checking / site restore / receipt assembly.

State travels through st(dict): a helper unpacks from st on entry and writes its locals back to st on exit (on success and on error alike).
So on an exception path finally still sees the "half-modified site", matching the semantics before the split.
"""
from .common import *  # noqa: F401,F403
from .lock import _lock_release
from .geom import _apply_step, _corners, _db_counts, _focus_box, _md5, _montage_api, _project_px, _safe, _solve_view
from .rig import _add_rig, _aim_rig, _alpha_stats, _device_info, _device_line, _device_live, _device_slim, _engine_label
from .parts import _legend_line_count, _parts_override, _parts_restore, _write_parts_legend


def _qv_scene(st):
    a, css, hidden_lights, lights_cfg, lights_mode = (
        st["a"], st["css"], st["hidden_lights"], st["lights_cfg"], st["lights_mode"])
    parts_assign, parts_enabled, parts_flat, parts_group_by, pc_objs = (
        st["parts_assign"], st["parts_enabled"], st["parts_flat"], st["parts_group_by"], st["pc_objs"])
    rs, sc, sensor_def, vt_mode, vt_target = (
        st["rs"], st["sc"], st["sensor_def"], st["vt_mode"], st["vt_target"])
    pc_err = (st.get("pc_err"))
    try:
        # ---- v0.8.11 (A): per-part colouring —— overrides material slots (placed before the three-point light: if the override fails, no lights exist yet)
        if parts_enabled:
            pc_state, pc_mats, pc_err = _parts_override(pc_objs, parts_assign,
                                                        lambda ob: (sorted([str(c.name) for c in ob.users_collection])
                                                                    or ["(no collection)"])[0]
                                                        if parts_group_by == "collection" else str(ob.name),
                                                        parts_flat)
        if pc_err:
            raise RuntimeError(pc_err)
        # three-point light (created temporarily inside this process only)
        if lights_cfg and lights_mode != "off":
            if lights_mode == "only":
                for ob in list(sc.objects):
                    if ob.type == "LIGHT" and not ob.hide_render:
                        ob.hide_render = True
                        hidden_lights.append(ob)
            rig = _add_rig(0.0, lights_cfg)
        # temporary camera
        cam_data = bpy.data.cameras.new("DSH_QC_CAM")
        made_cam = bpy.data.objects.new("DSH_QC_CAM", cam_data)
        sc.collection.objects.link(made_cam)
        made_cam.rotation_mode = "QUATERNION"
        cam_data.clip_start = 0.001
        cam_data.clip_end = 100000.0
        cam_data.sensor_width = sensor_def
        cam_data.sensor_fit = "AUTO"

        # render settings (all restored after rendering)
        rs.image_settings.file_format = "PNG"
        rs.image_settings.color_mode = "RGBA"
        rs.film_transparent = bool(a.get("film_transparent", True))
        rs.resolution_percentage = 100
        rs.use_file_extension = False
        sc.camera = made_cam
        # ---- v0.9.1 (A2): actually write the view transform + **read it back** (cannot write / name missing locally → must not render while broken)
        vt_apply_err = None
        if vt_mode != "scene":
            if css is None:
                vt_apply_err = "the scene has no view_settings, so the view transform cannot be guaranteed"
            else:
                try:
                    css.view_transform = str(vt_target)
                except Exception as e:
                    vt_apply_err = "%s: %s" % (type(e).__name__, str(e)[:160])
                vt_now = str(getattr(css, "view_transform", None))
                if vt_apply_err is None and vt_now != str(vt_target):
                    vt_apply_err = "read back %r after writing (requested %r)" % (vt_now, str(vt_target))
                if vt_apply_err is None:
                    vt_used = vt_now
        if vt_apply_err is not None:
            raise RuntimeError("view_transform=%r did not take effect: %s (available names: %s;"
                               "to keep the scene setting pass \"scene\")"
                               % (str(vt_target), vt_apply_err, ", ".join(_vt_options()) or "list unreadable"))

        lines = []
        # ---- v0.8.10 (C2): warm-up frame (not timed / not in the budget / not in jsonl) + quality-ladder state
        do_warmup = bool(a.get("warmup", True))
        warmup_info = None
        ladder = a.get("ladder")
        if isinstance(ladder, dict):
            ladder = [ladder]
        elif isinstance(ladder, str):
            try:
                ladder = json.loads(ladder)
            except Exception:
                ladder = None
        if not isinstance(ladder, list):
            ladder = None
        ladder_idx = 0
        try:
            per_view_budget_ms = int(round(float(a.get("per_view_budget_s")) * 1000)) if a.get("per_view_budget_s") \
                else int(a.get("per_view_budget_ms") or 0)
        except Exception:
            per_view_budget_ms = 0
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def _qv_capture_a(st):
    a, base_res, cam_data, center, corners = (
        st["a"], st["base_res"], st["cam_data"], st["center"], st["corners"])
    lens_def, made_cam, margin, mn, mx = st["lens_def"], st["made_cam"], st["margin"], st["mn"], st["mx"]
    outdir, rig, rs, sensor_def, tag = st["outdir"], st["rig"], st["rs"], st["sensor_def"], st["tag"]
    v = st["v"]
    try:
        rv = v.get("res") or base_res
        if isinstance(rv, (int, float)):
            rv = [int(rv), int(rv)]
        w, h = max(16, int(rv[0])), max(16, int(rv[1]))
        lens = float(v.get("lens", lens_def))
        ortho = bool(v.get("ortho", False))
        vmargin = float(v.get("margin", margin))
        nm = _safe(v.get("name"))
        path = _win(v.get("path") or os.path.join(outdir, "%s_%s.png" % (tag, nm)))
        corners_used = corners
        frm = v.get("from") or v.get("loc")
        look = v.get("look_at") or v.get("target")
        if frm and look:
            loc = Vector([float(x) for x in frm[:3]])
            d = (Vector([float(x) for x in look[:3]]) - loc)
            d = d.normalized() if d.length > 1e-9 else Vector((0.0, -1.0, 0.0))
            az = math.degrees(math.atan2(-d[1], -d[0]))
            el = math.degrees(math.asin(max(-1.0, min(1.0, -d[2]))))
            stats = {"explicit": True}
            oscale = float(v.get("ortho_scale")) if (ortho and v.get("ortho_scale")) else (float(v.get("ortho_scale")) if v.get("ortho_scale") else None)
        else:
            az = float(v.get("az", NAMED_VIEWS["iso"][0]))
            el = float(v.get("el", NAMED_VIEWS["iso"][1]))
            # v0.8.10 (C5): world-space framing —— aabb=[...] / focus="x,y,z,r" (per view first, then the top level)
            _frame = _focus_box(v.get("aabb")) or _focus_box(v.get("focus")) or _focus_box(a.get("aabb")) or _focus_box(a.get("focus"))
            if _frame:
                corners_used = _corners(_frame[0], _frame[1])
                _fc = (_frame[0] + _frame[1]) * 0.5
                loc, d, oscale, stats = _solve_view(_fc, corners_used, az, el, w, h, lens, sensor_def, vmargin,
                                                    ortho=ortho, ortho_scale=v.get("ortho_scale"))
                stats["framed_by"] = "aabb/focus"
            else:
                loc, d, oscale, stats = _solve_view(center, corners, az, el, w, h, lens, sensor_def, vmargin,
                                                    ortho=ortho, ortho_scale=v.get("ortho_scale"))
        made_cam.location = loc
        made_cam.rotation_quaternion = d.to_track_quat("-Z", "Y")
        cam_data.lens = lens
        cam_data.type = "ORTHO" if ortho else "PERSP"
        if ortho:
            cam_data.ortho_scale = float(oscale or a.get("ortho_scale") or 10.0)
        # camera and light angles: hug the view frustum + do not poke into the near clip plane
        radius = max((mx - mn).length * 0.5, 1e-3)
        cam_data.clip_start = max(0.001, radius * 0.01)
        cam_data.clip_end = max(radius * 100.0, cam_data.clip_start * 1000.0)
        if rig:
            _aim_rig(rig, az)
        rs.resolution_x = w
        rs.resolution_y = h
        rs.filepath = path
        try:
            bpy.context.view_layer.update()
        except Exception:
            pass
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def _qv_capture_b(st):
    az, cam_data, corners_used, d, dev_batch = (
        st["az"], st["cam_data"], st["corners_used"], st["d"], st["dev_batch"])
    do_warmup, el, h, idx, ladder = st["do_warmup"], st["el"], st["h"], st["idx"], st["ladder"]
    ladder_idx, lens, loc, made_cam, ortho = (
        st["ladder_idx"], st["lens"], st["loc"], st["made_cam"], st["ortho"])
    outdir, path, per_view_budget_ms, rs, samples = (
        st["outdir"], st["path"], st["per_view_budget_ms"], st["rs"], st["samples"])
    spent_ms, stats, v, w, warmup_info = st["spent_ms"], st["stats"], st["v"], st["w"], st["warmup_info"]
    try:
        # ---- v0.8.10 (C2) warm-up frame: the first-frame EEVEE shader compile is not timed, not in the budget, not in jsonl
        if do_warmup and idx == 0 and warmup_info is None:
            try:
                rs.filepath = _win(os.path.join(outdir, "_warmup.png"))
                tw = time.perf_counter()
                bpy.ops.render.render(write_still=True)
                warmup_info = {"ms": int(round((time.perf_counter() - tw) * 1000.0)),
                               "path": _win(os.path.join(outdir, "_warmup.png")), "counted": False}
            except Exception as e:
                warmup_info = {"error": str(e)[:120], "counted": False}
            rs.filepath = path
        # ---- rendering (quality ladder: over per_view_budget_s and a coarser step remains → drop one step and re-render, leaving a trace per step)
        step_i = ladder_idx
        ms_hist = []
        while True:
            w_eff, h_eff, step_used = _apply_step(rs, ladder, step_i, w, h)
            t1 = time.perf_counter()
            bpy.ops.render.render(write_still=True)
            ms = int(round((time.perf_counter() - t1) * 1000.0))
            ms_hist.append(ms)
            if per_view_budget_ms and ms > per_view_budget_ms and ladder and step_i + 1 < len(ladder):
                step_i += 1
                continue
            break
        if ladder and step_i != ladder_idx:
            ladder_idx = step_i      # later views reuse the coarser step (per-step trace in ladder_trace)
        ladder_used = (ladder[step_i] if ladder else None)
        spent_ms += ms
        # projection comparison uses the **actual** render resolution (the ladder step changes it)
        pred, pm_src, pm_err = _project_px(made_cam, corners_used, w_eff, h_eff)
        got = os.path.isfile(path)
        nbytes = int(os.path.getsize(path)) if got else 0
        if not got:
            raise RuntimeError("the render produced no file: %s" % path)
        _dev_live = _device_live(dev_batch)      # read back right after rendering (EEVEE can supply the real renderer string at this point)
        entry = {"view": str(v.get("name")), "ms": ms, "bytes": nbytes, "hash": _md5(path),
                 "path": path, "res": [w_eff, h_eff], "engine": _engine_label(), "samples": samples,
                 "warmup": bool(do_warmup and idx == 0), "step": (step_i if ladder else 0),
                 "step_cfg": ladder_used, "ms_history": ms_hist,
                 # v0.8.11 (B): the "render device actually used" for this image (read back right after rendering; null + device_source when unavailable)
                 "device": _device_slim(_dev_live), "device_source": _dev_live.get("source"),
                 "camera": {"az": round(az, 3), "el": round(el, 3), "lens": lens, "ortho": ortho,
                            "loc": [round(float(x), 4) for x in loc],
                            "look_at": [round(float(x), 4) for x in (loc + d)],
                            "ortho_scale": (round(float(cam_data.ortho_scale), 4) if ortho else None)},
                 "frame": {"pred_bbox_px": pred, "proj_source": pm_src, "proj_err_px": pm_err,
                           "solve": {k: (round(float(vv), 4) if isinstance(vv, float) else vv) for k, vv in stats.items()}},
                 "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def _qv_emit(st):
    a, catalog_ortho, entries, entry, jsonl = (
        st["a"], st["catalog_ortho"], st["entries"], st["entry"], st["jsonl"])
    legend_txt, lines, lock_line, parts_enabled, parts_flat = (
        st["legend_txt"], st["lines"], st["lock_line"], st["parts_enabled"], st["parts_flat"])
    parts_rows, path, v, vt_used = st["parts_rows"], st["path"], st["v"], st["vt_used"]
    try:
        # v0.8.11: view provenance (alias normalisation / az=el recorded as given) and the parts_color legend path
        if v.get("_requested") and str(v.get("_requested")) != str(v.get("name")):
            entry["view_requested"] = str(v.get("_requested"))
        if v.get("_source"):
            entry["view_source"] = str(v.get("_source"))
        if catalog_ortho and v.get("_ortho_src"):
            entry["ortho_source"] = str(v.get("_ortho_src"))
        if parts_enabled:
            entry["mode"] = "parts_color"
            entry["legend_path"] = legend_txt
            entry["parts"] = len(parts_rows)
            entry["parts_flat"] = bool(parts_flat)
        # ---- v0.9.1 (A2/E1): every jsonl line records "the view transform actually used for this image" and "this batch's lock convention"
        # (A2: the caller's analysis script can adapt from it; E1: waited_ms/holder make the timing auditable)
        entry["view_transform"] = vt_used
        entry["lock"] = dict(lock_line)
        try:
            entry["frame"].update(_alpha_stats(path))
        except Exception as e:
            entry["frame"]["alpha_err"] = str(e)[:120]
        # ---- optional: reference comparison (via compare in qc.py)
        ref_path = v.get("ref_path") or a.get("ref_path")
        if ref_path:
            K = _kernel()
            qapi = getattr(K, "dsh_qc_api", None) if K is not None else None
            if qapi is None:
                entry["ref"] = {"ok": False, "error": "qc.py must be injected first (include qc in the headless preload, or let the engine inject it)"}
            else:
                rb = v.get("ref_box", None)
                if rb is None:
                    rball = a.get("ref_box")
                    rb = rball.get(str(v.get("name")), None) if isinstance(rball, dict) else rball
                try:
                    rr = json.loads(qapi["compare"](_win(ref_path), rb, path, str(v.get("name")),
                                                    None, None, bool(a.get("ref_search", False))))
                    met = rr.get("metrics", {}) or {}
                    entry["ref"] = {"ok": True, "iou": rr.get("iou"), "iou_fixed": met.get("iou_fixed"),
                                    "iou_search": met.get("iou_search"), "dice": met.get("dice"),
                                    "missing_px": met.get("missing_px"), "extra_px": met.get("extra_px"),
                                    "boundary_mean_px": (met.get("boundary") or {}).get("mean_px"),
                                    "profile_mean_diff_px": ((rr.get("profile") or {}).get("diff") or {}).get("mean_diff_px"),
                                    "sheet": rr.get("sheet"), "overlay": rr.get("overlay"),
                                    "ms": rr.get("ms"), "search": bool(a.get("ref_search", False))}
                except Exception as e:
                    entry["ref"] = {"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:160])}
        entries.append(entry)
        lines.append(entry)
        # append image by image (the first one truncates and rewrites): stopping mid-budget still leaves the completed lines
        with open(jsonl, ("w" if len(lines) == 1 else "a"), encoding="utf-8") as f:
            f.write(_j(entry) + chr(10))
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def _qv_post(st):
    a, dev_batch, eng_after, eng_mode, entries = (
        st["a"], st["dev_batch"], st["eng_after"], st["eng_mode"], st["entries"])
    err, legend_txt, outdir, parts_enabled, parts_flat = (
        st["err"], st["legend_txt"], st["outdir"], st["parts_enabled"], st["parts_flat"])
    parts_group_by, parts_info, parts_palette, parts_rows, samples = (
        st["parts_group_by"], st["parts_info"], st["parts_palette"], st["parts_rows"], st["samples"])
    scope_warnings, tag, vt_used = st["scope_warnings"], st["tag"], st["vt_used"]
    try:
        # ---- v0.8.11 (B): in-batch device re-check + the measured read-back before the engine read-back check
        dev_after = _device_info()
        _d0 = _device_slim(dev_batch)
        _d1 = _device_slim(dev_after)
        _d_used = dict(dev_after or dev_batch or {})
        _d_used["measured"] = "after_render (measured read-back at the end of the batch)"
        device_used = _d_used
        device_check = {"same_device": (_d0.get("device") == _d1.get("device") and _d0.get("engine") == _d1.get("engine")),
                        "identical_reading": (_d0 == _d1),
                        "before_render": _d0, "after_render": _d1,
                        "note": "EEVEE's renderer string only becomes available **after the first render** in a background process (gpu.platform needs a GL context),"
                                "so before/after may differ only in the gpu field —— as long as device/engine match it counts as the same device"}
        if not device_check["same_device"]:
            scope_warnings.append("device read-back differs before/after rendering (before=%r / after=%r) —— the device may have changed mid-batch,"
                                  " so this batch's ms are not comparable" % (_d0.get("device"), _d1.get("device")))
        elif _d1.get("device") is None:
            scope_warnings.append("device unknown (device=null): %s" % (_d1.get("source") or "no criterion available"))

        # ---- v0.8.11 (A): write the legend to disk (only after a successful render —— a legend without an image is fabricated evidence)
        if parts_enabled and entries:
            try:
                pc_legend_json = _write_parts_legend(
                    legend_txt, parts_rows,
                    {"version": QC_RENDER_VERSION, "kind": "parts_color_legend",
                     "scene_file": bpy.data.filepath, "outdir": outdir, "tag": tag,
                     "group_by": parts_group_by, "flat": bool(parts_flat),
                     "view_transform": vt_used,
                     "palette_size": len(parts_palette),
                     "palette_srgb": [[int(c[0]), int(c[1]), int(c[2])] for c in parts_palette],
                     "color_space_note": "R,G,B are sRGB 0-255 (legend colours); what is written into the material is the linear value of the same colour"
                                         "(srgb_to_linear), and Principled also stacks lighting and the view transform",
                     "color_reused_by_hash": [r["name"] for r in parts_rows if r.get("color_source") == "hash"],
                     "views": [str(e.get("view")) for e in entries],
                     "ts": time.strftime("%Y-%m-%dT%H:%M:%S")})
                parts_info["legend_path"] = legend_txt
                parts_info["legend_json"] = pc_legend_json
                parts_info["legend_lines"] = _legend_line_count(legend_txt)
                if parts_info["legend_lines"] != len(parts_rows):
                    scope_warnings.append("legend row count %d != part count %d (was the legend file changed externally?)"
                                          % (parts_info["legend_lines"], len(parts_rows)))
            except Exception as e:
                if err is None:
                    err = {"error": "failed to write the legend: %s: %s" % (type(e).__name__, str(e)[:200])}

        # ---- v0.8.10 (C2) engine read-back check: the criterion must carry "what engine it was at the time"
        _eng_now = _engine_label()
        engine_check = {"requested": eng_mode, "configured_at_start": eng_after, "actual": _eng_now,
                        "rt": bool("+RT" in _eng_now), "samples": samples, "ok": True, "warnings": []}
        if str(eng_mode).lower() in ("eevee", "eevee_rt", "e") and "+RT" not in _eng_now:
            engine_check["ok"] = False
            engine_check["warnings"].append("EEVEE+raytracing requested but the read-back has no RT —— glass/refractive materials will not be correct")
        elif "+RT" not in _eng_now:
            engine_check["warnings"].append("this run's engine has raytracing off (%s): not directly comparable with historical EEVEE+RT scores" % _eng_now)

        # ---- v0.8.10 (C5) N-cell contact sheet (montage + per-cell metrics)
        sheet_path, sheet_metrics = None, None
        if int(a.get("sheet") or 0) > 1 and entries:
            try:
                mapi = _montage_api()
                if mapi is None:
                    scope_warnings.append("the sheet needs the montage module (runtime/py/render/montage.py) —— not found, montage skipped")
                else:
                    _sp = _win(os.path.join(outdir, "%s_sheet.png" % tag))
                    _r = mapi["montage"]([e["path"] for e in entries], int(a.get("sheet_cols") or 0) or None,
                                         int(a.get("sheet_tile") or 420), _sp, [e["view"] for e in entries],
                                         a.get("sheet_grid"), a.get("sheet_scale_m"))
                    if isinstance(_r, dict):
                        sheet_path = _r.get("path") or _sp
                        sheet_metrics = _r.get("tiles")
                    else:
                        sheet_path = _r or _sp
            except Exception as e:
                scope_warnings.append("montage failed: %s" % str(e)[:140])
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def _qv_restore(st):
    css, err, hidden_lights, lock_holder, lock_path = (
        st["css"], st["err"], st["hidden_lights"], st["lock_holder"], st["lock_path"])
    lock_res, made_cam, pc_mats, pc_state, rig = (
        st["lock_res"], st["made_cam"], st["pc_mats"], st["pc_state"], st["rig"])
    samp_before, saved, sc, scope_warnings, vt_before = (
        st["samp_before"], st["saved"], st["sc"], st["scope_warnings"], st["vt_before"])
    vt_mode, vt_target = st["vt_mode"], st["vt_target"]
    try:
        # ---- v0.8.11 (A): the parts_color site restore **comes first** —— if material slots are not restored before deleting lights/cameras,
        # one throw in the middle and there is no way back (render settings are restored below, same order: first what "changed content", then "settings").
        if pc_state:
            try:
                pc_restore = _parts_restore(pc_state, pc_mats)
            except Exception as e:
                pc_restore = {"ok": False, "mismatches": ["parts_color restore raised %s: %s"
                                                          % (type(e).__name__, str(e)[:200])],
                              "temp_materials_left": [], "objects": len(pc_state)}
        # ---- restore the site (delete temporary objects, roll settings back)
        try:
            for ob in rig:
                try:
                    _ld = ob.data if ob.type == "LIGHT" else None
                    bpy.data.objects.remove(ob, do_unlink=True)
                    if _ld is not None:
                        # v0.8.10 (D1): the light datablock must be deleted too —— the old version deleted only the object and accumulated dozens of orphan lights per round
                        try:
                            bpy.data.lights.remove(_ld, do_unlink=True)
                        except Exception:
                            pass
                except Exception:
                    pass
            if made_cam is not None:
                try:
                    cd = made_cam.data
                    bpy.data.objects.remove(made_cam, do_unlink=True)
                    bpy.data.cameras.remove(cd, do_unlink=True)
                except Exception:
                    pass
            for ob in hidden_lights:
                try:
                    ob.hide_render = False
                except Exception:
                    pass
            sc.camera = saved["camera"]
            rs = sc.render
            rs.resolution_x = saved["res_x"]
            rs.resolution_y = saved["res_y"]
            rs.resolution_percentage = saved["res_pct"]
            rs.filepath = saved["filepath"]
            rs.use_file_extension = saved["use_ext"]
            rs.image_settings.file_format = saved["fmt"]
            rs.image_settings.color_mode = saved["color_mode"]
            rs.film_transparent = saved["film_transparent"]
            try:
                sc.render.engine = saved["engine"]
            except Exception:
                pass
            ee = getattr(sc, "eevee", None)
            if ee is not None and "eevee.taa_render_samples" in samp_before:
                try:
                    ee.taa_render_samples = samp_before["eevee.taa_render_samples"]
                except Exception:
                    pass
            if "cycles.samples" in samp_before:
                try:
                    sc.cycles.samples = samp_before["cycles.samples"]
                except Exception:
                    pass
            # ---- v0.9.1 (A2): restore the view transform + **compare item by item** (a change left un-restored = a polluted scene, worse than one missing image)
            if vt_mode != "scene" and css is not None and vt_before is not None:
                vt_restore_err = None
                try:
                    css.view_transform = vt_before
                except Exception as e:
                    vt_restore_err = "%s: %s" % (type(e).__name__, str(e)[:160])
                vt_after_back = str(getattr(css, "view_transform", None))
                vt_restore = {"mode": vt_mode, "assigned": (str(vt_target) if vt_target is not None else None),
                              "scene_before": str(vt_before), "scene_after": vt_after_back,
                              "ok": (vt_after_back == str(vt_before) and vt_restore_err is None)}
                if vt_restore_err:
                    vt_restore["error"] = vt_restore_err
                if not vt_restore["ok"]:
                    scope_warnings.append("view_transform restore **failed the check**: before=%r after=%r%s"
                                          % (str(vt_before), vt_after_back,
                                             (" (%s)" % vt_restore_err) if vt_restore_err else ""))
            db_after = _db_counts()
            # ---- v0.9.1 (E1): release the lock (the exception path also reaches here; delete only when the holder matches, never someone else's lock)
            if lock_res and lock_res.get("acquired"):
                try:
                    _rel = _lock_release(lock_path, lock_holder)
                    lock_res["release"] = _rel
                    lock_res["released"] = bool(_rel.get("released"))
                    if _rel.get("held_ms") is not None:
                        lock_res["held_ms"] = _rel.get("held_ms")
                    if not _rel.get("ok"):
                        scope_warnings.append("render lock release failed: %s" % _rel.get("error"))
                    elif not _rel.get("released"):
                        scope_warnings.append("render lock release: %s" % _rel.get("reason"))
                except Exception as e:
                    lock_res["released"] = False
                    scope_warnings.append("render lock release raised: %s: %s (once TTL=%ss expires the next process will break it)"
                                          % (type(e).__name__, str(e)[:160], LOCK_DEFAULT_TTL_S))
        except Exception as e2:
            if err is None:
                err = {"error": "site restore failed: %s" % str(e2)[:200]}
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def _qv_finish_checks(st):
    budget_ms, db_after, db_before, err, lock_line = (
        st["budget_ms"], st["db_after"], st["db_before"], st["err"], st["lock_line"])
    lock_res, parts_enabled, parts_info, pc_restore, scope_warnings = (
        st["lock_res"], st["parts_enabled"], st["parts_info"], st["pc_restore"], st["scope_warnings"])
    stopped_early, t0, vt_restore = st["stopped_early"], st["t0"], st["vt_restore"]
    try:
        # ---- v0.8.10 (D1): temporary resource leak self-check
        db_delta = {}
        try:
            if db_before and db_after:
                for k, v0 in db_before.items():
                    v1 = db_after.get(k)
                    if isinstance(v0, int) and isinstance(v1, int) and v1 != v0:
                        db_delta[k] = v1 - v0
            if db_delta:
                scope_warnings.append("temporary resource counts did not return to baseline: %s (leaked lights/cameras slow down later renders)" % db_delta)
        except Exception:
            pass
        # ---- v0.8.11 (A): a failed parts_color restore check = polluted scene → do not succeed silently
        if parts_enabled and pc_restore is not None:
            if not pc_restore.get("ok"):
                scope_warnings.append("parts_color site restore **failed the check**: %s"
                                      % (_j(pc_restore.get("mismatches"))[:400]))
                if err is None:
                    err = {"error": "parts_color restore check failed (material slots may differ from before rendering; be sure to inspect before rendering more)",
                           "restore": pc_restore}
            parts_info["restore"] = pc_restore
        # ---- v0.9.1 (A2): a view transform not restored = polluted scene → likewise do not succeed silently
        if vt_restore is not None and not vt_restore.get("ok"):
            if err is None:
                err = {"error": "view_transform restore check failed (the scene view transform differs from before rendering; inspect before rendering more)",
                       "view_transform_restore": vt_restore}
        total_ms = int(round((time.perf_counter() - t0) * 1000.0))
        within = (not stopped_early) if budget_ms else True
        # v0.9.1 (E1): the lock in the return body carries the "release result" (jsonl lines were written when the lock was taken and contain no released/held_ms)
        if lock_res is not None and lock_res.get("acquired"):
            lock_line = dict(lock_line, released=bool(lock_res.get("released")),
                             held_ms=lock_res.get("held_ms"), release=lock_res.get("release"))
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def _qv_finish_out(st):
    alias_applied, base_res, budget_ms, catalog_ortho, center = (
        st["alias_applied"], st["base_res"], st["budget_ms"], st["catalog_ortho"], st["center"])
    db_after, db_before, db_delta, deduped_views, dev_after = (
        st["db_after"], st["db_before"], st["db_delta"], st["deduped_views"], st["dev_after"])
    dev_batch, device_check, device_used, eng_mode, engine_check = (
        st["dev_batch"], st["device_check"], st["device_used"], st["eng_mode"], st["engine_check"])
    entries, err, fallback_used, jsonl, ladder = (
        st["entries"], st["err"], st["fallback_used"], st["jsonl"], st["ladder"])
    ladder_idx, lights_cfg, lights_mode, lock_line, lock_path = (
        st["ladder_idx"], st["lights_cfg"], st["lights_mode"], st["lock_line"], st["lock_path"])
    margin, mn, mode, mx, no_guess_views = st["margin"], st["mn"], st["mode"], st["mx"], st["no_guess_views"]
    nobj, opened, outdir, parts_info, per_view_budget_ms = (
        st["nobj"], st["opened"], st["outdir"], st["parts_info"], st["per_view_budget_ms"])
    requested_count, samples, scope_warnings, sheet_metrics, sheet_path = (
        st["requested_count"], st["samples"], st["scope_warnings"], st["sheet_metrics"], st["sheet_path"])
    size, skipped, skipped_views, spent_ms, stopped_early = (
        st["size"], st["skipped"], st["skipped_views"], st["spent_ms"], st["stopped_early"])
    targets_resolved, total_ms, unknown_views, view_order, views = (
        st["targets_resolved"], st["total_ms"], st["unknown_views"], st["view_order"], st["views"])
    views_from, vlist, vt_before, vt_mode, vt_raw = (
        st["views_from"], st["vlist"], st["vt_before"], st["vt_mode"], st["vt_raw"])
    vt_restore, vt_target, vt_used, warmup_info, within = (
        st["vt_restore"], st["vt_target"], st["vt_used"], st["warmup_info"], st["within"])
    try:
        out = {"ok": err is None and len(entries) > 0,
               "version": QC_RENDER_VERSION,
               "file": bpy.data.filepath, "opened_file": opened,
               "mode": mode,
               "outdir": outdir, "jsonl": jsonl, "jsonl_lines": len(entries),
               "views": entries, "count": len(entries),
               "total_ms": total_ms, "render_ms": spent_ms,
               "budget_ms": budget_ms, "within_budget": within, "stopped_early": stopped_early,
               "skipped_views": skipped_views,
               "engine": _engine_label(), "engine_mode": eng_mode, "samples": samples,
               # ---- v0.8.11 (B): the render device actually used in this batch (the top summary = the measured read-back **after rendering**, closest to "what was used")
               "device": device_used,
               "device_before_render": dev_batch,
               "device_line": _device_line(dev_after if dev_after is not None else dev_batch),
               "device_check": device_check,
               # ---- v0.8.11 (C): view catalogue/aliases/unknown names
               "view_order": view_order, "catalog_ortho": catalog_ortho,
               "views_requested": ([str(x) for x in views] if views_from == "request" else None),
               "views_from": views_from, "render_order": [str(v.get("name")) for v in vlist],
               "unknown_views": unknown_views, "view_aliases_applied": alias_applied,
               "deduped_views": deduped_views, "default_views_fallback": (list(DEFAULT_VIEWS_FALLBACK) if fallback_used else None),
               # ---- v0.9.1 (A1): three counts ("12 names but only 8 images" must be visible at a glance)
               "requested_count": requested_count, "rendered_count": len(entries),
               "unknown_count": len(unknown_views), "no_guess_views": no_guess_views,
               "available_views": list(VIEW_ORDER),
               # ---- v0.9.1 (A2): view transform (effective value + requested value + three-state + restore check)
               "view_transform": vt_used, "view_transform_mode": vt_mode,
               "view_transform_requested": (str(vt_raw) if vt_raw is not None else None),
               "view_transform_assigned": (str(vt_target) if vt_target is not None else None),
               "view_transform_scene": (str(vt_before) if vt_before is not None else None),
               "view_transform_restore": vt_restore,
               # ---- v0.9.1 (E1): render lock (holder/waited_ms/acquired/stale_broken/path —— the timing is auditable)
               "lock": lock_line, "lock_dir": os.path.dirname(os.path.dirname(lock_path)),
               "view_group_of": dict((str(v.get("name")), VIEW_GROUP_OF.get(str(v.get("name")))) for v in vlist
                                     if str(v.get("name")) in VIEW_GROUP_OF),
               "parts_color": parts_info,
               "res": base_res, "objects": nobj, "aabb": {"min": [round(float(x), 4) for x in mn],
                                                          "max": [round(float(x), 4) for x in mx],
                                                          "size": [round(float(x), 4) for x in size],
                                                          "center": [round(float(x), 4) for x in center]},
               "skipped_objects": skipped, "lights": {"mode": lights_mode, "config": lights_cfg,
                                                      "angles_deg": LIGHT_ANGLES, "relative_to": "camera azimuth"},
               "margin": margin,
               "warmup": warmup_info, "per_view_budget_ms": per_view_budget_ms,
               "ladder": ladder, "ladder_final_step": (ladder_idx if ladder else None),
               "engine_check": engine_check,
               "scope_warnings": scope_warnings, "targets_resolved": targets_resolved,
               "datablocks": {"before": db_before, "after": db_after, "delta": db_delta},
               "sheet": sheet_path, "sheet_tiles": sheet_metrics,
               "note": "each jsonl line = one image; ms is the single-image render time (the first one includes the EEVEE shader compile);"
                       "device is the **measured** render device (null = no criterion available, see device_source; guessing is never allowed);"
                       "within_budget=false means it stopped after exceeding the cumulative budget (images already produced are kept)"}
        if err is not None:
            out["error"] = err
        return _j(out)
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def _qv_loop(st):
    for idx, v in enumerate(st["vlist"]):
        if st["budget_ms"] and st["spent_ms"] >= st["budget_ms"]:
            st["stopped_early"] = True
            st["skipped_views"] = [str(x.get("name")) for x in st["vlist"][idx:]]
            break
        st["idx"] = idx
        st["v"] = v
        _qv_capture_a(st)
        _qv_capture_b(st)
        _qv_emit(st)
        if st["budget_ms"] and st["spent_ms"] > st["budget_ms"]:
            st["stopped_early"] = True
            st["skipped_views"] = [str(x.get("name")) for x in st["vlist"][idx + 1:]]
            break
