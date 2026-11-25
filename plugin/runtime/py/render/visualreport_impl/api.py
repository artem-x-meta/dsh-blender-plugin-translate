# -*- coding: utf-8 -*-
"""Split from visualreport.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403
from .image import _load_rgb_alpha, _rgba_from_rgb, _save_png_rgba, _write_defect_crop
from .process import _fix_hint, _parse_box, _parse_targets, _process_view

# ────────────────────────────── op: report ──────────────────────────────
def _visualreport_report_p1(st):
    iou_fail, iou_pass, label, max_defects, max_extra_frac = (
        st["iou_fail"], st["iou_pass"], st["label"], st["max_defects"], st["max_extra_frac"])
    max_missing_frac, out_dir, px_per_mm, ref, ref_box_px = (
        st["max_missing_frac"], st["out_dir"], st["px_per_mm"], st["ref"], st["ref_box_px"])
    render, save_images, targets, views = st["render"], st["save_images"], st["targets"], st["views"]
    i, iou_f, iou_p, label_s, names, ppm, ref_clean, ref_srgb, root, rp, unknown, v, view_list, vp = (st.get("i"), st.get("iou_f"), st.get("iou_p"), st.get("label_s"), st.get("names"), st.get("ppm"), st.get("ref_clean"), st.get("ref_srgb"), st.get("root"), st.get("rp"), st.get("unknown"), st.get("v"), st.get("view_list"), st.get("vp"))
    try:
        t_start = time.perf_counter()
        try:
            if not isinstance(ref, str) or not ref.strip():
                raise ValueError("ref is required (reference image path)")
            ref_clean = _norm_path(ref.strip())
            if not os.path.isfile(ref_clean):
                raise ValueError("reference image not found: %s" % ref_clean)
            if render is not None and views is not None:
                raise ValueError("render and views are mutually exclusive; give one of them")
            view_list = []
            if views is not None:
                if not isinstance(views, (list, tuple)) or not views:
                    raise ValueError("views must be a non-empty list: [{name,path}]")
                if len(views) > MAX_VIEWS:
                    raise ValueError("views accepts at most %d views (got %d)" % (MAX_VIEWS, len(views)))
                for i, v in enumerate(views):
                    if not isinstance(v, dict):
                        raise ValueError("views[%d] must be a dict ({name,path})" % i)
                    unknown = sorted(set(str(k) for k in v.keys()) - set(["name", "path"]))
                    if unknown:
                        raise ValueError("views[%d] has unknown keys %s (available: name,path)" % (i, unknown))
                    vp = v.get("path")
                    if not isinstance(vp, str) or not vp.strip():
                        raise ValueError("views[%d].path is required" % i)
                    vp = _norm_path(vp.strip())
                    if not os.path.isfile(vp):
                        raise ValueError("the image for views[%d] does not exist: %s" % (i, vp))
                    view_list.append({"name": _safe_token(v.get("name") or ("v%d" % i), "views[%d].name" % i, 40),
                                      "path": vp})
                names = [v["name"] for v in view_list]
                if len(set(names)) != len(names):
                    raise ValueError("views names must be unique: %s" % names)
            else:
                if not isinstance(render, str) or not render.strip():
                    raise ValueError("render is required (render image path), or give views=[{name,path}]")
                rp = _norm_path(render.strip())
                if not os.path.isfile(rp):
                    raise ValueError("render image not found: %s" % rp)
                view_list.append({"name": "render", "path": rp})
            ppm = None
            if px_per_mm is not None:
                ppm = _num(px_per_mm, "px_per_mm", gt=0.0)
                if ppm > 10000:
                    raise ValueError("px_per_mm is unreasonably large (%g)" % ppm)
            target_rows = _parse_targets(targets)
            label_s = _safe_token(label or "qc", "label")
            md = int(_num(max_defects, "max_defects", default=DEFAULT_MAX_DEFECTS, minv=0.0, maxv=10.0))
            iou_p = _num(iou_pass, "iou_pass", default=0.95, gt=0.0, maxv=1.0)
            iou_f = _num(iou_fail, "iou_fail", default=0.85, gt=0.0, maxv=1.0)
            if iou_f > iou_p:
                raise ValueError("iou_fail (%.2f) cannot be greater than iou_pass (%.2f)" % (iou_f, iou_p))
            mmf = _num(max_missing_frac, "max_missing_frac", default=0.02, minv=0.0, maxv=1.0)
            mef = _num(max_extra_frac, "max_extra_frac", default=0.02, minv=0.0, maxv=1.0)
            save_img = _bool(save_images, "save_images", True)
            root = _root_outdir(out_dir)
        except ValueError as e:
            return _err(e, hint="report arguments: see K.dsh_visualreport_api['help'](); ref/render must be existing image paths",
                        op="report")
        except Exception as e:
            return _err("%s: %s" % (type(e).__name__, str(e)), hint="argument validation failed (nothing was read or written)", op="report")

        run_dir = os.path.join(root, "visualreport_%s_%s" % (label_s, _stamp()))
        try:
            os.makedirs(run_dir, exist_ok=True)
        except Exception as e:
            return _err("cannot create the artifact directory: %s (%s)" % (run_dir, str(e)[:120]), op="report")

        qc = _KIT.api("qc")
        img = _KIT.api("img")
        method = {"mask": "qc.mask_auto" if qc is not None else "numpy.otsu",
                  "metrics": "qc.metrics" if qc is not None else "numpy",
                  "crosscheck": "qc.compare" if qc is not None else ("imgtools.diff" if img is not None else None),
                  "qc_available": qc is not None, "imgtools_available": img is not None}
        warnings = []
        try:
            ref_srgb, ref_alpha = _load_rgb_alpha(ref_clean)
        except Exception as e:
            return _err("cannot read the reference image: %s: %s" % (type(e).__name__, str(e)[:200]),
                        hint="use PNG/JPEG; for GIF run qc's gif_to_png first; WSL paths are converted to Windows automatically", op="report")
        H, W = int(ref_srgb.shape[0]), int(ref_srgb.shape[1])
        try:
            ref_box = _parse_box(ref_box_px, "ref_box_px", W, H) if ref_box_px is not None else None
        except ValueError as e:
            return _err(e, hint="ref_box_px takes [x0,y0,x1,y1] (pixels)", op="report")
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def _visualreport_report_p2(st):
    img, iou_f, iou_p, label_s, md = (
        st.get("img"), st.get("iou_f"), st.get("iou_p"), st.get("label_s"), st.get("md"))
    mef, mmf, ppm, qc, ref_alpha = (
        st.get("mef"), st.get("mmf"), st.get("ppm"), st.get("qc"), st.get("ref_alpha"))
    ref_box, ref_clean, ref_srgb, render_box_px, run_dir = (
        st.get("ref_box"), st.get("ref_clean"), st.get("ref_srgb"), st["render_box_px"], st.get("run_dir"))
    save_img, target_rows, view_list, warnings = (
        st.get("save_img"), st.get("target_rows"), st.get("view_list"), st.get("warnings"))
    d, detail, i, overlay, rb, rec, row, rs, t, tag, v, view = (st.get("d"), st.get("detail"), st.get("i"), st.get("overlay"), st.get("rb"), st.get("rec"), st.get("row"), st.get("rs"), st.get("t"), st.get("tag"), st.get("v"), st.get("view"))
    try:
        if ref_box is None:
            warnings.append("ref_box_px not given: whole-image alignment (composition/framing differences go straight into the metrics; for same-camera QC give the view crop)")
        if ref_box and ref_box.get("clipped"):
            warnings.append("ref_box_px exceeds the reference image range, clipped to the image: %s" % ref_box["box"])
        opts = {"px_per_mm": ppm, "targets": target_rows, "iou_pass": iou_p, "iou_fail": iou_f,
                "max_missing_frac": mmf, "max_extra_frac": mef, "render_box": None}
        view_results = []
        overlays = {}
        for view in view_list:
            tag = "%s_%s" % (label_s, view["name"])
            try:
                if render_box_px is not None:
                    rs, _ra = _load_rgb_alpha(view["path"])
                    rb = _parse_box(render_box_px, "render_box_px", int(rs.shape[1]), int(rs.shape[0]))
                    if rb.get("clipped"):
                        warnings.append("render_box_px exceeds view %r range, clipped to the image: %s" % (view["name"], rb["box"]))
                    opts["render_box"] = rb["box"]
                else:
                    opts["render_box"] = None
                detail, overlay = _process_view(ref_srgb, ref_alpha, ref_clean,
                                                ref_box["box"] if ref_box else None,
                                                view, run_dir, tag, qc, img, opts)
                overlays[view["name"]] = overlay
                view_results.append(detail)
            except Exception as e:
                return _err("view %r analysis failed: %s: %s" % (view["name"], type(e).__name__, str(e)[:240]),
                            hint="confirm the image is readable and the mask is not empty (cut out the background for photographic references); bad input is never silently treated as a pass",
                            op="report", view=view["name"], run_dir=run_dir)
        if not save_img:
            for v in view_results:
                v["images"] = {k: None for k in v.get("images", {})}
        vs = [v["verdict"] for v in view_results]
        if "fail" in vs:
            verdict = "fail"
        elif "degraded" in vs:
            verdict = "degraded"
        else:
            verdict = "pass"
        all_defects = []
        for v in view_results:
            for d in v.get("defects") or []:
                all_defects.append(d)
        all_defects.sort(key=lambda d: (-float(d.get("area_frac") or 0.0), -int(d.get("area_px") or 0)))
        top = all_defects[:max(0, md)]
        crops = []
        if save_img:
            for i, d in enumerate(top[:3]):
                try:
                    rec = _write_defect_crop(overlays[d["view"]], d, run_dir, i)
                    d["crop"] = rec["path"]
                    crops.append(rec)
                except Exception as e:
                    warnings.append("failed to write defect crop (#%d): %s" % (i, str(e)[:120]))
        for d in top:
            d.setdefault("crop", None)
        for d in top:
            d["center_px"] = list(d.get("centroid_px") or [])
            if ppm:
                d["center_mm"] = [round(d["centroid_px"][0] / ppm, 3), round(d["centroid_px"][1] / ppm, 3)]
                d["size_mm"] = [round((d["bbox_px"][2] - d["bbox_px"][0] + 1) / ppm, 3),
                                round((d["bbox_px"][3] - d["bbox_px"][1] + 1) / ppm, 3)]
                d["area_mm2"] = round(d["area_px"] / (ppm * ppm), 3)
            else:
                d["center_mm"] = None
                d["size_mm"] = None
                d["area_mm2"] = None
        for v in view_results:
            v["defects_total"] = len(v.get("defects") or [])
            v["defects"] = (v.get("defects") or [])[:max(0, md)]
        all_targets = []
        for v in view_results:
            for t in v.get("targets") or []:
                row = dict(t)
                row["view"] = v["name"]
                all_targets.append(row)
        per = [{"view": v["name"], "info": v.get("metrics") or {}} for v in view_results]
        ious = [float(p["info"].get("iou") or 0.0) for p in per if p["info"]]
        dices = [float(p["info"].get("dice") or 0.0) for p in per if p["info"]]
        bnds = [float((p["info"].get("boundary") or {}).get("mean_px") or 0.0) for p in per if p["info"]]
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def _visualreport_report_p3(st):
    all_targets, bnds, crops, dices, iou_f = (
        st.get("all_targets"), st.get("bnds"), st.get("crops"), st.get("dices"), st.get("iou_f"))
    iou_p, ious, label_s, md, mef = (
        st.get("iou_p"), st.get("ious"), st.get("label_s"), st.get("md"), st.get("mef"))
    method, mmf, opts, per, ppm = st.get("method"), st.get("mmf"), st.get("opts"), st.get("per"), st.get("ppm")
    ref_box, ref_clean, render_box_px, run_dir, t_start = (
        st.get("ref_box"), st.get("ref_clean"), st["render_box_px"], st.get("run_dir"), st.get("t_start"))
    top, verdict, view_list, view_results, warnings = (
        st.get("top"), st.get("verdict"), st.get("view_list"), st.get("view_results"), st.get("warnings"))
    r, v = (st.get("r"), st.get("v"))
    try:
        summary = {
            "iou_min": round(min(ious), 4) if ious else None,
            "iou_mean": round(sum(ious) / len(ious), 4) if ious else None,
            "dice_min": round(min(dices), 4) if dices else None,
            "missing_px_total": int(sum(int(p["info"].get("missing_px") or 0) for p in per)),
            "extra_px_total": int(sum(int(p["info"].get("extra_px") or 0) for p in per)),
            "boundary_mean_px_max": round(max(bnds), 3) if bnds else None,
            "views": [{"view": p["view"], "iou": p["info"].get("iou"), "dice": p["info"].get("dice"),
                       "missing_px": p["info"].get("missing_px"), "extra_px": p["info"].get("extra_px"),
                       "missing_frac": p["info"].get("missing_frac"),
                       "extra_frac": p["info"].get("extra_frac"),
                       "boundary_mean_px": (p["info"].get("boundary") or {}).get("mean_px")} for p in per],
        }
        fix = _fix_hint(verdict, view_results, top, all_targets, opts)
        first = view_results[0] if view_results else {}
        images = {"overlay": (first.get("images") or {}).get("overlay"),
                  "sheet": (first.get("images") or {}).get("sheet"),
                  "crops": crops,
                  "per_view": [{"view": v["name"],
                                "overlay": (v.get("images") or {}).get("overlay"),
                                "sheet": (v.get("images") or {}).get("sheet"),
                                "crosscheck_overlay": (v.get("crosscheck") or {}).get("overlay"),
                                "crosscheck_sheet": (v.get("crosscheck") or {}).get("sheet"),
                                "crosscheck_image": (v.get("crosscheck") or {}).get("out")}
                               for v in view_results]}
        reasons = []
        degraded_reasons = []
        for v in view_results:
            for r in (v.get("reasons") or []):
                reasons.append("%s: %s" % (v["name"], r))
            for r in (v.get("degraded_reasons") or []):
                degraded_reasons.append("%s: %s" % (v["name"], r))
        out = {
            "verdict": verdict,
            "ok": True,
            "version": VISUALREPORT_VERSION,
            "op": "report",
            "label": label_s,
            "summary": _summary_text(verdict, summary, top, all_targets),
            "reasons": reasons,
            "degraded_reasons": degraded_reasons,
            "metrics": summary,
            "top_defects": top,
            "fix_hint": fix,
            "images": images,
            "views": view_results,
            "targets": all_targets,
            "method": method,
            "warnings": warnings,
            "run_dir": run_dir,
            "ref": ref_clean,
            "render": [v["path"] for v in view_list],
            "params": {"px_per_mm": ppm, "ref_box_px": (ref_box["box"] if ref_box else None),
                       "render_box_px": (list(render_box_px) if isinstance(render_box_px, (list, tuple))
                                         else render_box_px),
                       "max_defects": md, "iou_pass": iou_p, "iou_fail": iou_f,
                       "max_missing_frac": mmf, "max_extra_frac": mef},
            "ms": int(round((time.perf_counter() - t_start) * 1000.0)),
        }
        return out
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def visualreport_report(ref=None, render=None, views=None, px_per_mm=None, targets=None, out_dir=None,
                        max_defects=DEFAULT_MAX_DEFECTS, ref_box_px=None, render_box_px=None,
                        label=None, iou_pass=0.95, iou_fail=0.85,
                        max_missing_frac=0.02, max_extra_frac=0.02, save_images=True):
    st = dict(locals())
    for _fn_ in (_visualreport_report_p1, _visualreport_report_p2, _visualreport_report_p3):
        _r = _fn_(st)
        if _r is not None:
            return _r


def _summary_text(verdict, summary, top, targets):
    bits = ["verdict=%s" % verdict]
    if summary.get("iou_min") is not None:
        bits.append("IoU min %.4f / mean %.4f" % (summary["iou_min"], summary.get("iou_mean") or 0.0))
    if summary.get("missing_px_total"):
        bits.append("missing %d px" % summary["missing_px_total"])
    if summary.get("extra_px_total"):
        bits.append("extra %d px" % summary["extra_px_total"])
    if top:
        bits.append("top_defect %s %.1f%%" % (top[0]["kind"], float(top[0]["area_frac"]) * 100.0))
    if targets:
        npass = sum(1 for t in targets if t.get("status") == "pass")
        bits.append("targets %d/%d pass" % (npass, len(targets)))
    return "; ".join(bits)


# ────────────────────────────── op: selftest / help ──────────────────────────────
def _mk_test_png(arr_rgb, path):
    return _save_png_rgba(_rgba_from_rgb(arr_rgb), path)


def _self_image_base(n=128, square=72, at=28, notch=0):
    img = np.ones((n, n, 3), dtype=np.float32)
    x0, y0 = at, at
    x1, y1 = at + square, at + square
    img[y0:y1, x0:x1, :] = 0.18
    if notch:
        img[y0:y0 + notch, x1 - notch:x1, :] = 1.0
    return img


def visualreport_selftest():
    t0 = time.perf_counter()
    ev = {}
    run_root = _root_outdir(None)
    d = os.path.join(run_root, "visualreport_selftest")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        import tempfile
        d = tempfile.mkdtemp(prefix="dsh_visualreport_selftest_")
    try:
        base = _self_image_base()
        same_png = os.path.join(d, "same.png")
        notch_png = os.path.join(d, "notch.png")
        _mk_test_png(base, same_png)
        _mk_test_png(_self_image_base(notch=22), notch_png)
        r_same = visualreport_report(ref=same_png, render=same_png, out_dir=d, label="selftest_same")
        r_bad = visualreport_report(ref=same_png, render=notch_png, out_dir=d, label="selftest_notch")
        ev["same"] = {"ok": r_same.get("ok"), "verdict": r_same.get("verdict"),
                      "iou": (r_same.get("metrics") or {}).get("iou_min"),
                      "defects": len(r_same.get("top_defects") or []),
                      "warnings": len(r_same.get("warnings") or []),
                      "error": r_same.get("error")}
        first_bad = (r_bad.get("views") or [{}])[0]
        ev["notch"] = {"ok": r_bad.get("ok"), "verdict": r_bad.get("verdict"),
                       "iou": (r_bad.get("metrics") or {}).get("iou_min"),
                       "missing_px": (first_bad.get("metrics") or {}).get("missing_px"),
                       "defects": len(r_bad.get("top_defects") or []),
                       "crops": len((r_bad.get("images") or {}).get("crops") or []),
                       "error": r_bad.get("error")}
        ev["same_pass"] = (ev["same"]["ok"] is True and ev["same"]["verdict"] == "pass"
                           and ev["same"]["defects"] == 0)
        ev["notch_fail"] = (ev["notch"]["ok"] is True and ev["notch"]["verdict"] == "fail"
                            and ev["notch"]["defects"] > 0 and (ev["notch"]["missing_px"] or 0) > 0)
        bad = []
        bad.append(("ref_missing", visualreport_report(ref=os.path.join(d, "nope.png"), render=same_png)))
        bad.append(("no_render", visualreport_report(ref=same_png)))
        bad.append(("both", visualreport_report(ref=same_png, render=same_png,
                                                views=[{"name": "a", "path": same_png}])))
        bad.append(("max_defects", visualreport_report(ref=same_png, render=same_png, max_defects=-1)))
        bad.append(("bad_ppm", visualreport_report(ref=same_png, render=same_png, px_per_mm=0)))
        bad.append(("bad_target", visualreport_report(ref=same_png, render=same_png,
                                                      targets=[{"key": "weight", "expect_mm": 1, "tol_mm": 1}])))
        bad.append(("bad_box", visualreport_report(ref=same_png, render=same_png,
                                                   ref_box_px=[10, 10, 5, 5])))
        ev["bad_params"] = [{"case": k, "ok": bool(v.get("ok")), "error": str(v.get("error"))[:100]}
                            for k, v in bad]
        ev["bad_params_ok"] = all(not x["ok"] for x in ev["bad_params"])
        ok = bool(ev["same_pass"] and ev["notch_fail"] and ev["bad_params_ok"])
        return {"ok": ok, "evidence": ev, "ms": int(round((time.perf_counter() - t0) * 1000.0))}
    except Exception as e:
        return {"ok": False, "evidence": ev, "error": "%s: %s" % (type(e).__name__, str(e)[:260])}


def visualreport_help():
    return {
        "module": "visualreport.py", "version": VISUALREPORT_VERSION,
        "what": "same-camera QC visual report: verdict-first (pass/fail/degraded) + IoU/Dice/missing-extra area/boundary delta + "
                "largest defect bbox/area/position in mm + defect crops + overlay/sheet + fix_hint",
        "ops": {"report": {"doc": "produce the report (builds/modifies no geometry)",
                           "args": ["ref", "render | views", "px_per_mm", "targets", "out_dir",
                                    "max_defects", "ref_box_px", "render_box_px", "label",
                                    "iou_pass", "iou_fail", "max_missing_frac", "max_extra_frac",
                                    "save_images"]},
                "selftest": {"doc": "synthesize two images with a known difference (identical should pass / missing corner should fail) + bad-argument rejection"},
                "help": {"doc": "this help"}},
        "report_schema": {
            "ref": "reference image (PNG/JPEG/WebP)",
            "render": "render image path (one of render/views)",
            "views": "[{name,path}] multiple views (at most 8)",
            "ref_box_px": "[x0,y0,x1,y1]: the view crop inside a large reference (when given, normalized to that bbox)",
            "render_box_px": "crop of the render image (optional)",
            "px_per_mm": "pixels per millimetre of the render image (needed for mm units and target checks)",
            "targets": "[{key:width|height|diag|area, expect_mm, tol_mm}]",
            "max_defects": "number of defects returned/located (default 3; at most 3 crops)",
            "iou_pass": "0.95 (default)",
            "iou_fail": "0.85 (default)",
            "max_missing_frac": "0.02 (default, upper limit for the missing-area fraction)",
            "max_extra_frac": "0.02 (default, upper limit for the extra-area fraction)",
            "save_images": "true (default): write overlay/sheet/crop",
        },
        "verdict_rules": ["fail: IoU < iou_fail or missing/extra area fraction > limit or targets out of tolerance",
                          "degraded: empty mask / size mismatch was scaled / targets lack px_per_mm / IoU falls between the thresholds"
                          " (degraded ≠ pass)",
                          "pass: IoU >= iou_pass and missing/extra area within limits and every target passes"],
        "outputs": ["verdict / ok / summary / reasons",
                    "metrics{iou_min,iou_mean,dice_min,missing_px_total,extra_px_total,"
                    "boundary_mean_px_max,views[]}",
                    "top_defects[{kind,view,bbox_px,area_px,area_frac,center_px,center_mm,area_mm2,crop}]",
                    "images{overlay,sheet,crops[],per_view[]}",
                    "fix_hint / views[] (per-view metrics/crosscheck/defects/verdict/reasons) / warnings"],
        "protocol": ["run qc_render_views first to get same-camera images (ref_path also computes IoU), then visualreport_report for the verdict report;",
                     "a verdict that is not pass must not be treated as a pass: degraded needs more evidence (px_per_mm / crop box / transparent-background render);",
                     "give fix_hint and the top_defects crops to the model together, so it knows what to change and by how much;",
                     "same camera is the premise: scores are not comparable across a different camera/resolution/crop/engine."],
        "limits": ["contour/geometry objective comparison only; material/color/aesthetics are out of scope for this module",
                   "photographic references need the background cut out first (the mask heuristic cannot separate complex backgrounds)",
                   "without px_per_mm, positions/areas are in pixels (mm fields are null)",
                   "when qc is not injected, IoU/Dice/boundary fall back to numpy (boundary is a dilation approximation)"],
        "kernel": "shared kernel K.dsh_kit v%s" % getattr(_KIT, "version", "?"),
    }


# Registration (one line): K.dsh_visualreport_api["report"] / K.dsh_visualreport_api("report", {...})
_KIT.register("visualreport", VISUALREPORT_VERSION,
              {"report": visualreport_report, "selftest": visualreport_selftest,
               "help": visualreport_help})
