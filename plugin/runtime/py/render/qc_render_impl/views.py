# -*- coding: utf-8 -*-
"""First half of qc_render_views: params/targets/views/parts/render settings/render lock (no render loop).

State is passed via st (dict): a helper unpacks from st on entry and writes its locals back into st on exit
(on both success and exception). So even on the exception path finally still sees the "half-modified
state", matching the semantics from before the split.
"""
from .common import *  # noqa: F401,F403
from .lock import _lock_acquire, _lock_holder_default, _lock_line, _lock_path
from .geom import _aabb, _collect_objs, _corners, _db_counts, _safe
from .rig import _apply_samples, _device_info, _restore_engine_samples, _set_engine
from .parts import PARTS_PALETTE, _parts_assign, _parts_groups, _parts_legend_rows


def _qv_prepare(st):
    a = st["a"]
    try:
        # ---- v0.8.10 (B1): strict parameter-scope validation -- top-level-only keys appearing in a sub-dict must be reported (root cause of the 234 pieces of false evidence in this project)
        TOP_KEYS = set(["file", "views", "res", "samples", "budget_s", "thr", "outdir", "jsonl", "ref_path", "ref_box",
                        "ref_search", "lights", "lights_mode", "margin", "engine", "view_transform", "tag", "targets",
                        "allow_open_file", "film_transparent", "lens", "sensor_width", "warmup", "ladder",
                        "per_view_budget_s", "aabb", "focus", "sheet", "sheet_cols", "sheet_tile", "chunk",
                        "sheet_grid", "sheet_scale_m", "args",
                        # v0.8.11 (Procedura merge: parts_color / view catalog / device)
                        "mode", "parts_color", "parts_group_by", "parts_flat", "parts_palette", "parts_legend",
                        "catalog_ortho", "view_order", "strict_views",
                        # v0.9.1 (93 feedback E1: render lock)
                        "lock", "lock_wait_s", "lock_dir", "lock_holder"])
        VIEW_KEYS = set(["name", "az", "el", "from", "loc", "location", "look_at", "target", "to", "lens", "sensor",
                         "sensor_fit", "ortho", "ortho_scale", "res", "margin", "path", "ref_path", "ref_box",
                         "aabb", "focus", "samples"])
        scope_warnings = []
        for k in sorted(a.keys()):
            if k not in TOP_KEYS:
                scope_warnings.append("unrecognized top-level parameter %s (ignored; see qc_render_help for available parameters)" % k)
        _views_raw = a.get("views")
        if isinstance(_views_raw, list):
            for _i, _v in enumerate(_views_raw):
                if not isinstance(_v, dict):
                    continue
                for _k in _v.keys():
                    if _k in TOP_KEYS and _k not in VIEW_KEYS:
                        scope_warnings.append("views[%d]: %s **only takes effect at top level, ignored**; effective value = %r (move it to top-level args)"
                                              % (_i, _k, a.get(_k)))
                    elif _k not in VIEW_KEYS:
                        scope_warnings.append("views[%d] unrecognized key %s (ignored)" % (_i, _k))

        # ---- output directory and jsonl
        outdir = _win(a.get("outdir") or _out_dir())
        try:
            os.makedirs(outdir, exist_ok=True)
        except Exception as e:
            return _j({"ok": False, "error": "cannot create outdir: %s (%s)" % (outdir, e)})
        tag = _safe(a.get("tag") or "views")
        jsonl = a.get("jsonl") or os.path.join(outdir, "render_views.jsonl")
        jsonl = _win(jsonl)
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def _qv_open_file(st):
    a = st["a"]
    try:
        want_file = a.get("file")
        opened = False
        if want_file:
            target = _win(want_file)
            cur = bpy.data.filepath or ""
            same = False
            try:
                same = bool(cur) and os.path.normcase(os.path.abspath(cur)) == os.path.normcase(os.path.abspath(target))
            except Exception:
                same = (cur == target)
            if not same:
                if bool(getattr(bpy.app, "background", False)) or a.get("allow_open_file"):
                    bpy.ops.wm.open_mainfile(filepath=target)
                    opened = True
                else:
                    return _j({"ok": False, "error": "refusing to open another .blend in the GUI process (it would replace your current scene)",
                               "file": target, "current": cur,
                               "hint": "for long jobs use blender_rt_headless(file=..., preload=\"qc,qc_render\", as_job=true); "
                                       "to really switch files in the GUI pass allow_open_file=true"})
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def _qv_aim(st):
    a, scope_warnings = st["a"], st["scope_warnings"]
    try:
        sc = bpy.context.scene
        eng_mode = str(a.get("engine") or "keep")
        samples = int(a.get("samples") or 64)

        # ---- targets and AABB (+ v0.8.10 B1: echo the "actually effective filter set")
        _t_req = a.get("targets")
        objs, skipped = _collect_objs(_t_req)
        try:
            bpy.context.view_layer.update()
        except Exception:
            pass
        mn, mx, nobj = _aabb(objs)
        if nobj == 0 or mn is None:
            return _j({"ok": False, "error": "framing failed: no visible mesh (pass targets=[name] to specify)",
                       "file": bpy.data.filepath, "skipped": skipped})
        targets_resolved = {"requested": ([str(x) for x in _t_req] if isinstance(_t_req, (list, tuple)) else None),
                            "resolved": [ob.name for ob in objs], "count": len(objs),
                            "missing": list(skipped.get("missing") or []), "skipped_hidden": int(skipped.get("hidden") or 0)}
        if targets_resolved["missing"]:
            scope_warnings.append("these names in targets do not exist (ignored): %s" % ", ".join(targets_resolved["missing"]))
        if targets_resolved["requested"] and len(objs) < len(targets_resolved["requested"]):
            scope_warnings.append("targets requested %d, actually framed %d (see targets_resolved.missing for the difference)"
                                  % (len(targets_resolved["requested"]), len(objs)))
        center = (mn + mx) * 0.5
        size = mx - mn
        corners = _corners(mn, mx)
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def _qv_views(st):
    a = st["a"]
    try:
        # ---- view normalization (v0.8.11: via catalog + aliases; unknown names echoed back verbatim, never silently replaced)
        # v0.9.1 (A1): **fail when unrecognized** -- non-empty views with zero resolved -> ok:false and nothing rendered;
        # only "omitted/empty" falls back to defaults (default = 4-view fallback; v0.8.11 and earlier used 3, see DEFAULT_VIEWS_LEGACY).
        views = a.get("views")
        views_from = "default_legacy"
        if not views:                                   # None / "" / [] -> v0.8.11 old default (3 images; the patch release keeps the default output set)
            views = list(DEFAULT_VIEWS_LEGACY)
        else:
            views_from = "request"
        if isinstance(views, str):
            views = [v.strip() for v in views.split(",") if v.strip()]
        requested_count = len([v for v in views
                               if (isinstance(v, str) and v.strip()) or isinstance(v, dict)])
        base_res = a.get("res") or DEFAULT_RES
        if isinstance(base_res, (int, float)):
            base_res = [int(base_res), int(base_res)]
        base_res = [int(base_res[0]), int(base_res[1])]
        view_order = str(a.get("view_order") or "catalog").lower()
        strict_views = bool(a.get("strict_views"))
        catalog_ortho = bool(a.get("catalog_ortho"))
        named_req = [v for v in views if isinstance(v, str) and not _is_azel_spec(v)]
        rv = resolve_view_names(named_req)
        canon_order, unknown_views, alias_applied, deduped_views = rv["names"], rv["unknown"], rv["aliases"], rv["deduped"]
        no_guess_views = rv.get("no_guess") or []
        explicit_specs, spec_err = [], None
        # explicit views (dict / az=el string) keep request order and are **not** affected by catalog sorting or dedup (key to keeping old params working as-is)
        for i, v in enumerate(views):
            if isinstance(v, dict):
                explicit_specs.append(dict(v))
            elif isinstance(v, str) and _is_azel_spec(v):
                s = {"name": v, "_source": "azel"}
                try:
                    kv = {}
                    for part in v.strip().lower().replace(" ", "").split(","):
                        if "=" in part:
                            kk, vv = part.split("=", 1)
                            kv[kk] = vv
                    if "az" in kv:
                        s["az"] = float(kv["az"])
                    if "el" in kv:
                        s["el"] = float(kv["el"])
                except Exception as e:
                    spec_err = "views[%d] az/el syntax failed to parse: %r (%s)" % (i, v, str(e)[:100])
                    break
                s.setdefault("az", NAMED_VIEWS["iso"][0])
                s.setdefault("el", NAMED_VIEWS["iso"][1])
                explicit_specs.append(s)
            elif not isinstance(v, str):
                return _j({"ok": False, "error": "views[%d] unsupported type: %r" % (i, v)})
        if spec_err:
            return _j({"ok": False, "error": spec_err, "views": [str(x) for x in views]})
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def _qv_vlist(st):
    base_res, canon_order, catalog_ortho, deduped_views, explicit_specs = (
        st["base_res"], st["canon_order"], st["catalog_ortho"], st["deduped_views"], st["explicit_specs"])
    named_req, no_guess_views, outdir, requested_count, scope_warnings = (
        st["named_req"], st["no_guess_views"], st["outdir"], st["requested_count"], st["scope_warnings"])
    strict_views, unknown_views, view_order, views, views_from = (
        st["strict_views"], st["unknown_views"], st["view_order"], st["views"], st["views_from"])
    try:
        fallback_used = (views_from in ("default_legacy", "default_fallback"))
        if views_from == "default_legacy":
            scope_warnings.append("views omitted/empty -> default %s (matches v0.8.11; for the Procedura 4-view set pass %s explicitly)"
                                  % (",".join(DEFAULT_VIEWS_LEGACY), ",".join(DEFAULT_VIEWS_FALLBACK)))
        if not canon_order and not explicit_specs:
            # v0.9.1 (A1) **hard failure**: views non-empty and none resolved -- this used to silently fall back to 4 views
            # (93 feedback: right output filenames, wrong angles, ok:true, the caller could not tell). Now **nothing is rendered**,
            # and the list of valid names is returned directly.
            _requested_raw = [str(x) for x in views]
            scope_warnings.append("none of the %d names in views is recognized -> nothing rendered (unknown names are never guessed or substituted)"
                                  % requested_count)
            return _j({"ok": False,
                       "version": QC_RENDER_VERSION,
                       "error": "no recognizable view name in views: %s (A1 policy hard failure: nothing rendered, "
                                "no silent substitution with iso/front/right/top)" % ", ".join(_requested_raw),
                       "unknown_views": unknown_views, "unknown_count": len(unknown_views),
                       "no_guess_views": no_guess_views,
                       "requested_count": requested_count, "rendered_count": 0, "count": 0,
                       "views_requested": _requested_raw, "views_from": views_from,
                       "available_views": list(VIEW_ORDER),
                       "view_menu": view_menu_full_text(),
                       "view_aliases": dict(VIEW_ALIASES),
                       "hint": "unknown names are not guessed; use a catalog name (available_views / view_menu) or an alias; "
                               "for weapon contexts map muzzle_end→front yourself (*_end is never guessed, the caller maps it explicitly per this project's catalog)",
                       "file": bpy.data.filepath, "outdir": outdir,
                       "scope_warnings": scope_warnings,
                       "note": "this is an **empty output**: rendered_count=0, no PNG at all (not even fallback images); "
                               "rename from unknown_views and rerun"})
        if unknown_views:
            scope_warnings.append("unknown view names %s skipped (%d/%d renderable; returned verbatim in unknown_views; "
                                  "name table in qc_render_help.view_menu)"
                                  % (", ".join(unknown_views), len(canon_order) + len(explicit_specs), requested_count))
            if no_guess_views:
                scope_warnings.append("%s hit the **no-guess** policy (%s)" % (", ".join(no_guess_views), VIEW_NO_GUESS_NOTE))
        if deduped_views:
            scope_warnings.append("duplicate views %s deduplicated (each canonical name renders once; to render twice use a dict view with an explicit path)"
                                  % ", ".join(deduped_views))
        if strict_views and unknown_views:
            return _j({"ok": False, "version": QC_RENDER_VERSION,
                       "error": "views contains unrecognized names; strict_views=true forbids delivering a flawed result",
                       "unknown_views": unknown_views, "unknown_count": len(unknown_views),
                       "no_guess_views": no_guess_views,
                       "requested_count": requested_count, "rendered_count": 0, "count": 0,
                       "known_views": canon_order,
                       "available_views": list(VIEW_ORDER), "view_menu": view_menu_full_text(),
                       "hint": "remove the unknown names or use catalog names (available_views); strict_views=false renders known names and reports unknown ones in unknown_views",
                       "file": bpy.data.filepath, "outdir": outdir, "views_from": views_from,
                       "scope_warnings": scope_warnings})
        named_specs = {}
        req_spelling = {}
        for raw in named_req:                       # on alias/case tolerance, record the user's original spelling (traceable in the result)
            c = _canon_view(raw)
            if c and _norm_view_name(raw) != _norm_view_name(c):
                req_spelling.setdefault(c, str(raw))
        for nm in canon_order:
            s = {"name": nm, "az": NAMED_VIEWS[nm][0], "el": NAMED_VIEWS[nm][1], "_source": "catalog"}
            if nm in req_spelling:
                s["_requested"] = req_spelling[nm]
            if catalog_ortho:
                s["ortho"] = VIEW_ORTHO[nm]
                s["_ortho_src"] = "catalog"
            named_specs[nm] = s
        if view_order == "request":
            # legacy escape hatch: strictly request order (strings inserted back at first appearance, dict/az=el stay in place)
            vlist, _emitted = [], set()
            for v in views:
                if isinstance(v, dict) or (isinstance(v, str) and _is_azel_spec(v)):
                    vlist.append(explicit_specs.pop(0))
                else:
                    nm = _canon_view(v)
                    if nm and nm in named_specs and nm not in _emitted:
                        _emitted.add(nm)
                        vlist.append(named_specs[nm])
        else:
            vlist = [named_specs[n] for n in canon_order] + explicit_specs
        for i, s in enumerate(vlist):
            if str(s.get("_source")) == "azel":
                s["_requested"] = str(s.get("name"))     # az=el kept verbatim (the name is the original string)
            s.setdefault("name", "v%d" % (i + 1))
            s.setdefault("res", base_res)
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def _qv_parts(st):
    a, outdir, scope_warnings = st["a"], st["outdir"], st["scope_warnings"]
    pc_objs, pc_skipped = (st.get("pc_objs"), st.get("pc_skipped"))
    try:
        # ---- v0.8.11 (A): per-part coloring (parts_color) -- settle "what to override and with what" before touching material slots
        mode = str(a.get("mode") or ("parts_color" if a.get("parts_color") else "views")).lower()
        if mode in ("parts", "parts_color", "parts_color_views", "parts-color"):
            mode = "parts_color"
        parts_enabled = (mode == "parts_color")
        parts_group_by = str(a.get("parts_group_by") or "object").lower()
        if parts_group_by not in ("object", "collection"):
            scope_warnings.append("parts_group_by=%r not recognized (only object/collection) -> using object" % parts_group_by)
            parts_group_by = "object"
        parts_flat = bool(a.get("parts_flat"))
        parts_palette = PARTS_PALETTE
        if a.get("parts_palette"):
            try:
                pp = [tuple(int(x) for x in c[:3]) for c in a["parts_palette"]]
                pp = [c for c in pp if len(c) == 3]
                if pp:
                    parts_palette = pp
                else:
                    scope_warnings.append("no valid [R,G,B] in parts_palette -> using the default 12 colors")
            except Exception as e:
                scope_warnings.append("parts_palette failed to parse (%s) -> using the default 12 colors" % str(e)[:100])
        parts_groups, parts_assign, parts_rows, parts_info = [], {}, [], None
        if parts_enabled:
            pc_objs, pc_skipped = _collect_objs(None)        # **all visible meshes** taking part in rendering (independent of targets framing)
            if not pc_objs:
                return _j({"ok": False, "error": "parts_color: no visible mesh in the scene, nothing to color",
                           "skipped": pc_skipped})
            parts_groups = _parts_groups(pc_objs, parts_group_by)
            parts_assign = _parts_assign(parts_groups, parts_palette)
            parts_rows = _parts_legend_rows(parts_groups, parts_assign)
            _reused = [r["name"] for r in parts_rows if r.get("color_source") == "hash"]
            if len(parts_rows) > len(parts_palette):
                scope_warnings.append("parts %d > palette %d colors: %d parts reuse colors by name hash "
                                      "(color_source=hash in the legend; same name keeps the same color across runs, no error)"
                                      % (len(parts_rows), len(parts_palette), len(_reused)))
            if a.get("ref_path"):
                scope_warnings.append("ref comparison is of limited use in parts_color mode (materials are overridden with flat colors, so IoU/profile difference is no longer a geometric criterion)")
            parts_info = {"enabled": True, "mode": mode, "group_by": parts_group_by, "flat": parts_flat,
                          "parts": len(parts_rows), "palette_size": len(parts_palette),
                          "palette": [[int(c[0]), int(c[1]), int(c[2])] for c in parts_palette],
                          "palette_space": "sRGB 0-255 (legend colors); written to materials as srgb→linear at render time, "
                                           "and Principled adds lighting/color transform, so on-image colors will not equal the legend per pixel "
                                           "(for a per-pixel match use parts_flat=true + view_transform=\"Standard\")",
                          "assignments": dict((k, v) for k, v in parts_assign.items()),
                          "color_reused_by_hash": _reused,
                          "scope": "all visible meshes (%d objects / %d parts); independent of targets framing"
                                   % (len(pc_objs), len(parts_rows)),
                          "skipped": pc_skipped,
                          "touched": "only object material slots (+ temporary mesh copy for linked duplicates); visibility/world/lights/camera untouched"}
        else:
            parts_info = {"enabled": False, "mode": mode,
                          "hint": "for per-part colored renders: pass mode=\"parts_color\" (or parts_color=true)"}
        if a.get("parts_legend"):
            legend_txt = _win(a["parts_legend"])
        else:
            legend_txt = _win(os.path.join(outdir, "parts_color_meta.txt"))
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def _qv_setup(st):
    a, eng_mode, parts_enabled, parts_flat, parts_info = (
        st["a"], st["eng_mode"], st["parts_enabled"], st["parts_flat"], st["parts_info"])
    samples, sc, scope_warnings, vlist = st["samples"], st["sc"], st["scope_warnings"], st["vlist"]
    try:
        eng_before, eng_after = _set_engine(eng_mode)
        samp_before = _apply_samples(samples)
        # v0.8.11 (B): device **must be probed after the engine switch** -- probing before the batch records
        # the "previous batch's / previous run's engine" into this batch
        # (seen in practice: a batch with engine="cycles" reported EEVEE GPU semantics for device, i.e. the criterion hung on the wrong object)
        dev_batch = _device_info()

        # ---- v0.8.10 (C7 chunking): chunk=[i,n] -> render only the i-th slice (1-based); large jobs can be split for parallel/resumable runs
        _chunk = a.get("chunk")
        if isinstance(_chunk, (list, tuple)) and len(_chunk) == 2:
            try:
                _ci, _cn = int(_chunk[0]), max(1, int(_chunk[1]))
                _sel = [v for _idx, v in enumerate(vlist) if (_idx % _cn) == (_ci - 1)]
                if _sel:
                    vlist = _sel
                    scope_warnings.append("chunk mode: chunk=[%d,%d] -> rendering only %d/%d images this run" % (_ci, _cn, len(vlist), _cn))
            except Exception as e:
                scope_warnings.append("chunk parameter not recognized (expected [i,n]): %s" % str(e)[:80])

        budget_s = a.get("budget_s", a.get("thr"))
        try:
            budget_ms = int(round(float(budget_s) * 1000.0)) if budget_s not in (None, "", 0, "0") else 0
            # v0.8.11: a positive budget < 0.5ms rounds to 0, and 0 downstream means "no budget" -- silently ignoring the
            # budget is the opposite of the "stop immediately when over budget" contract; raise it to 1ms and say so
            # (None/""/0/"0" unchanged = no budget).
            if budget_ms == 0 and budget_s not in (None, "", 0, "0"):
                try:
                    if float(budget_s) > 0:
                        budget_ms = 1
                        scope_warnings.append("budget_s=%r too small (rounds to <1ms), treating as 1ms (not degraded to 'no budget')"
                                              % (budget_s,))
                except Exception:
                    pass
        except Exception:
            budget_ms = 0

        lights_cfg = a.get("lights", DEFAULT_LIGHTS)
        if lights_cfg is False or lights_cfg is None:
            lights_cfg = {}
        elif lights_cfg is True:
            lights_cfg = dict(DEFAULT_LIGHTS)
        elif isinstance(lights_cfg, dict):
            lights_cfg = dict(DEFAULT_LIGHTS, **{k: v for k, v in lights_cfg.items() if k in ("key", "fill", "rim")})
        else:
            lights_cfg = dict(DEFAULT_LIGHTS)
        lights_mode = str(a.get("lights_mode") or "add").lower()
        margin = float(a.get("margin", 1.12))
        lens_def = float(a.get("lens", 50.0))
        sensor_def = float(a.get("sensor_width", 36.0))
        # ---- v0.9.1 (A2): three-state view transform (**default = "Standard"**)
        # 93 feedback verbatim: under headless EEVEE, AgX compresses a pure white background to ≈0.85, so every analysis
        # that "crops the reference / computes the silhouette by luminance threshold" fails for the whole round.
        # Three states:
        #   omitted/empty/concrete name like "Standard" -> use that (default = Standard: the QC criterion)
        #   "scene"                                     -> keep scene settings (v0.8.11 old behavior, for beauty renders); warn when the scene is not Standard
        vt_raw = a.get("view_transform")
        vt_arg = None if vt_raw is None else str(vt_raw).strip()
        if not vt_arg:
            vt_mode, vt_target = "default_standard", "Standard"
        elif vt_arg.lower() == "scene":
            vt_mode, vt_target = "scene", None
        else:
            vt_mode, vt_target = "explicit", vt_arg
        view_transform = vt_target                 # keep the old variable name: value = the name to write into css (None when scene)
        if parts_enabled and parts_flat and vt_mode == "default_standard":
            # v0.8.11 old key kept (parts_color+flat view transform is also Standard; now a side effect of the default criterion)
            parts_info["view_transform_defaulted"] = "Standard"
            scope_warnings.append("parts_color+parts_flat: view_transform not given, defaulted to Standard "
                                  "(AgX/Filmic wash out legend colors; original settings restored after rendering)")
        if vt_mode == "scene":
            scope_warnings.append("view_transform=\"scene\": keeping scene settings (old behavior); if the scene is not Standard, "
                                  "threshold readings need manual correction")

        # ---- capture current state
        css = getattr(sc, "view_settings", None)
        vt_before = getattr(css, "view_transform", None) if css is not None else None
        if vt_mode == "scene" and vt_before is not None and str(vt_before) != "Standard":
            scope_warnings.append("current scene view transform is %s (not Standard): this run keeps scene settings, "
                                  "so luminance-threshold cropping/silhouette analysis needs manual correction "
                                  "(for the QC criterion pass view_transform=\"Standard\")"
                                  % str(vt_before))
        vt_used = str(vt_target) if vt_target is not None else (str(vt_before) if vt_before is not None else None)
        rs = sc.render
        saved = {
            "camera": sc.camera, "engine": eng_before,
            "res_x": int(rs.resolution_x), "res_y": int(rs.resolution_y), "res_pct": int(rs.resolution_percentage),
            "filepath": str(rs.filepath), "use_ext": bool(rs.use_file_extension),
            "fmt": str(rs.image_settings.file_format), "color_mode": str(rs.image_settings.color_mode),
            "film_transparent": bool(rs.film_transparent),
        }
        db_before = _db_counts()          # v0.8.10 (D1): baseline for the temporary-resource leak self-check
        db_after = None
        hidden_lights = []
        made_cam = None
        rig = []
        entries = []
        skipped_views = []
        stopped_early = False
        spent_ms = 0
        err = None
        # v0.8.10: even on a mid-run exception the result dict must carry these fields (otherwise NameError after except)
        warmup_info = None
        ladder = None
        ladder_idx = 0
        per_view_budget_ms = 0
        engine_check = None
        sheet_path = None
        sheet_metrics = None
        # v0.8.11 (A/B): parts_color live state + device recheck + legend artifact
        pc_state, pc_mats, pc_restore = [], {}, None
        # v0.9.1 (A2): view-transform restore verification result (filled in finally; must have a value on the exception path too)
        vt_restore = None
        pc_legend_json = None
        pc_err = None
        dev_after = None
        device_check = None
        device_used = dev_batch      # top-level summary: swapped for the post-render measured readback once rendering finishes
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def _qv_lock(st):
    a, eng_before, outdir, requested_count, samp_before = (
        st["a"], st["eng_before"], st["outdir"], st["requested_count"], st["samp_before"])
    sc, scope_warnings, tag, vlist = st["sc"], st["scope_warnings"], st["tag"], st["vlist"]
    try:
        # ---- v0.9.1 (E1): render lock -- acquired automatically before rendering (placed after every "no-render early
        # return" so an empty lock is not held; also outside this try so the finally below always releases)
        lock_on = a.get("lock", True)
        if isinstance(lock_on, str):
            lock_on = lock_on.strip().lower() not in ("0", "false", "off", "no", "")
        lock_enabled = bool(lock_on)
        lock_holder = str(a.get("lock_holder") or _lock_holder_default())
        lock_base = a.get("lock_dir")
        lock_path = _lock_path(lock_base)
        lock_res, lock_line = None, _lock_line(None)
        if lock_enabled:
            try:
                lock_wait_s = float(a.get("lock_wait_s") if a.get("lock_wait_s") is not None else 120.0)
            except Exception as e:
                scope_warnings.append("lock_wait_s=%r is not a number (%s) -> treating as 0" % (a.get("lock_wait_s"), str(e)[:80]))
                lock_wait_s = 0.0
            if lock_wait_s < 0:
                scope_warnings.append("lock_wait_s=%r < 0 -> treating as 0" % (a.get("lock_wait_s"),))
                lock_wait_s = 0.0
            lock_res = _lock_acquire(lock_path, lock_holder, LOCK_DEFAULT_TTL_S, lock_wait_s,
                                     note="qc_render_views tag=%s views=%s" % (tag, ",".join([str(v.get("name"))
                                                                                              for v in vlist[:8]])))
            lock_line = _lock_line(lock_res)
            if lock_res.get("stale_broken"):
                scope_warnings.append(lock_res.get("stale_note") or "broke a stale lock")
            if lock_res.get("parse_error"):
                scope_warnings.append("lock file failed to parse (age judged by mtime): %s" % lock_res["parse_error"])
            if not lock_res.get("ok"):
                # no lock -> **do not render** (rendering anyway yields inflated timings, i.e. incomparable numbers
                # written into the evidence chain).
                # v0.9.1: engine/samples were already changed before this point (they live outside try), and an early
                # return skips finally -> so restore and verify here, otherwise "lock failure" also pollutes the caller's
                # scene (the E2 self-check snapshot caught this).
                _pre = _restore_engine_samples(sc, eng_before, samp_before)
                if not _pre.get("ok"):
                    scope_warnings.append("engine/samples rollback on lock-timeout early return **failed verification**: %s" % _j(_pre))
                return _j({"ok": False, "version": QC_RENDER_VERSION,
                           "error": lock_res.get("error"), "hint": lock_res.get("hint"),
                           "lock": lock_line, "lock_dir": os.path.dirname(os.path.dirname(lock_path)),
                           "current_holder": lock_res.get("current_holder"),
                           "holder_age_s": lock_res.get("holder_age_s"),
                           "holder_ttl_remaining_s": lock_res.get("holder_ttl_remaining_s"),
                           "prelock_restore": _pre,
                           "rendered_count": 0, "count": 0, "requested_count": requested_count,
                           "file": bpy.data.filepath, "outdir": outdir, "tag": tag,
                           "views_requested": [str(v.get("name")) for v in vlist],
                           "scope_warnings": scope_warnings,
                           "note": "nothing rendered: no images without the render lock (lock=false explicitly skips the lock, you then own "
                                   "the timing semantics); engine/samples restored to their original values (prelock_restore verified item by item)"})
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")
