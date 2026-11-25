# -*- coding: utf-8 -*-
"""img_digest stage: ROI statistics / native crops / annotated overview / attachment picking (behaviour identical to before the split)."""
from ..common import *  # noqa: F401,F403
from ..common import _save
from ..analysis import PALETTE, _norm_roi, _rnd
from ..cache import _draw_box, _draw_circle, _draw_line


def _choose_scale_bar(ppm, W):
    """Choose the scale-bar length: with a calibration prefer whole mm with the pixel length in 50..0.35W; without one use a quarter of the width (in px)."""
    if ppm and float(ppm) > 0:
        for mm_v in (1, 2, 5, 10, 20, 25, 50, 100, 200, 500, 1000, 2000, 5000):
            px = float(mm_v) * float(ppm)
            if 50.0 <= px <= 0.35 * float(W):
                return px, float(mm_v), "mm"
        mm_v = 1.0
        while float(mm_v) * float(ppm) < 40.0 and mm_v < 100000.0:
            mm_v *= 10.0
        return float(mm_v) * float(ppm), float(mm_v), "mm"
    return float(max(20.0, min(0.25 * float(W), 120.0))), None, "px"


def _overlay_digest(arr, bbox, features, lines, scale, scale_bar=True, grid=True):
    """Draw the measured boxes/circles/lines/grid/scale bar back onto the image; no text is drawn, the legend goes out as JSON (the model just reads the numbers)."""
    out = arr.copy()
    H, W = out.shape[0], out.shape[1]
    legend = {"coordinate_system": "left-top origin, x right, y down",
              "boxes": [], "circles": [], "lines": [], "grid": None, "scale_bar": None}
    if grid:
        step = int(max(16, round(max(W, H) / 24.0)))
        col = [0.1, 0.55, 0.65]
        for x in range(0, W, max(1, step)):
            out[::2, x, :3] = col
        for y in range(0, H, max(1, step)):
            out[y, ::2, :3] = col
        legend["grid"] = {"step_px": step, "rgb": col, "note": "one cell = step_px pixels"}
    if bbox:
        _draw_box(out, bbox, PALETTE[3], 2)
        legend["boxes"].append({"id": 0, "kind": "silhouette_bbox",
                                "box_px": [int(v) for v in bbox], "rgb": PALETTE[3]})
    for i, f in enumerate((features or [])[:10]):
        col = PALETTE[(i + 1) % len(PALETTE)]
        g = f.get("geom") or {}
        if g.get("bbox_px"):
            _draw_box(out, g["bbox_px"], col, 2)
            legend["boxes"].append({"id": i + 1, "kind": f.get("kind"),
                                    "box_px": [int(v) for v in g["bbox_px"]], "rgb": col})
        elif g.get("center_px") and (g.get("radius_px") or g.get("diameter_px")):
            r = float(g.get("radius_px") or (float(g.get("diameter_px") or 0.0) / 2.0))
            _draw_circle(out, g["center_px"], r + 1.0, col, 1)
            legend["circles"].append({"id": i + 1, "kind": f.get("kind"),
                                      "center_px": _rnd(g["center_px"], 2),
                                      "radius_px": round(r, 2), "rgb": col})
        elif g.get("xy_px"):
            x, y = int(g["xy_px"][0]), int(g["xy_px"][1])
            _draw_line(out, [x - 5, y], [x + 5, y], col, 1)
            _draw_line(out, [x, y - 5], [x, y + 5], col, 1)
            legend["lines"].append({"id": i + 1, "kind": f.get("kind"),
                                    "at_px": [x, y], "rgb": col})
    for i, ln in enumerate((lines or [])[:6]):
        col = PALETTE[(i + 2) % len(PALETTE)]
        pts = ln.get("endpoints_px")
        if pts and len(pts) == 2:
            _draw_line(out, pts[0], pts[1], col, 2)
            legend["lines"].append({"id": "L%d" % (i + 1), "theta_deg": ln.get("theta_deg"),
                                    "span_px": ln.get("span_px"), "rgb": col})
    if scale_bar:
        px_len, mm_v, unit = _choose_scale_bar((scale or {}).get("px_per_mm"), W)
        y = int(H - 12)
        x0 = 12
        col = [1.0, 0.1, 1.0]
        _draw_line(out, [x0, y], [x0 + px_len, y], col, 2)
        _draw_line(out, [x0, y - 5], [x0, y + 5], col, 2)
        _draw_line(out, [x0 + px_len, y - 5], [x0 + px_len, y + 5], col, 2)
        legend["scale_bar"] = {"x0_px": x0, "y_px": y, "length_px": round(px_len, 2),
                               "mm": mm_v, "unit": unit, "rgb": col,
                               "note": "the length of this horizontal bar is the mm value above (a pixel reference when there is no calibration)"}
    return out, legend


def _digest_dir(p, out_dir):
    base = os.path.dirname(str(p)) or "."
    stem = os.path.splitext(os.path.basename(str(p)))[0] or "img"
    d = out_dir if out_dir else os.path.join(base, stem + "_digest")
    return str(d), stem


def _write_digest_crops(arr, bbox, features, rois, out_dir, stem, crop_max_px):
    """Native-resolution crops (**no scaling**): user ROIs first, then feature neighbourhoods, then the silhouette bbox; each side <=crop_max_px."""
    H, W = arr.shape[0], arr.shape[1]
    max_side = max(16, int(crop_max_px))
    boxes = []
    for i, r in enumerate(rois or []):
        box = _norm_roi(r, W, H)
        if box:
            boxes.append(("roi%d" % (i + 1), box))
    for i, f in enumerate((features or [])[:4]):
        g = f.get("geom") or {}
        if g.get("bbox_px"):
            bx = [int(v) for v in g["bbox_px"]]
            pad = max(6, int(0.35 * max(bx[2], bx[3])))
            boxes.append(("feat%d_%s" % (i + 1, f.get("kind") or "f"),
                          [bx[0] - pad, bx[1] - pad, bx[2] + 2 * pad, bx[3] + 2 * pad]))
        elif g.get("center_px") and (g.get("radius_px") or g.get("diameter_px")):
            cx, cy = float(g["center_px"][0]), float(g["center_px"][1])
            d = float(g.get("diameter_px") or (2.0 * float(g.get("radius_px") or 6.0)))
            side = max(24.0, d * 2.4)
            boxes.append(("feat%d_%s" % (i + 1, f.get("kind") or "circle"),
                          [cx - side / 2.0, cy - side / 2.0, side, side]))
    if bbox and not boxes:
        boxes.append(("bbox", [bbox[0], bbox[1], bbox[2], bbox[3]]))
    rows = []
    for (name, bx) in boxes[:6]:
        try:
            x, y, w, h = [float(v) for v in bx]
        except Exception:
            continue
        if w > max_side:
            x = x + (w - max_side) / 2.0
            w = float(max_side)
        if h > max_side:
            y = y + (h - max_side) / 2.0
            h = float(max_side)
        x0 = int(max(0, min(W - 1, round(x))))
        y0 = int(max(0, min(H - 1, round(y))))
        x1 = int(max(x0 + 1, min(W, round(x + w))))
        y1 = int(max(y0 + 1, min(H, round(y + h))))
        row = {"name": str(name), "box_px": [x0, y0, x1 - x0, y1 - y0], "scale": 1.0,
               "size_px": [int(x1 - x0), int(y1 - y0)], "path": None}
        try:
            row["path"] = _save(arr[y0:y1, x0:x1], os.path.join(out_dir, "%s_%s.png" % (stem, name)))
        except Exception as e:
            row["error"] = "%s: %s" % (type(e).__name__, str(e)[:100])
        rows.append(row)
    return rows


def _digest_rois(rois, m, W, H):
    """ROI foreground-fraction statistics."""
    roi_rows = []
    for i, r in enumerate(rois or []):
        box = _norm_roi(r, W, H)
        if not box:
            roi_rows.append({"roi": r, "error": "bad roi"})
            continue
        sub = m[box[1]:box[1] + box[3], box[0]:box[0] + box[2]]
        roi_rows.append({"roi": box, "fg_frac": round(float(sub.mean()), 4), "fg_px": int(sub.sum())})
    return roi_rows


def _digest_visual(ctx, rois, out_dir, scale_bar):
    """Crop atlas + annotated overview; returns (crops, overlay, overlay_path)."""
    ddir, stem = _digest_dir(ctx["p"], out_dir)
    try:
        crops = _write_digest_crops(ctx["arr"], ctx["bbox"], ctx["features"], rois, ddir, stem,
                                    ctx["crop_max_px"])
    except Exception as e:
        crops = [{"error": "%s: %s" % (type(e).__name__, str(e)[:120]), "why": "the crop directory cannot be written"}]
    overlay = None
    overlay_path = None
    try:
        ov_arr, ov_legend = _overlay_digest(ctx["arr"], ctx["bbox"], ctx["features"], ctx["lines"],
                                            ctx["scale"], scale_bar=bool(scale_bar))
        overlay_path = _save(ov_arr, os.path.join(ddir, stem + "_overlay.png"))
        overlay = {"path": overlay_path, "labels": ov_legend}
    except Exception as e:
        overlay = {"path": None, "labels": {}, "warning": "%s: %s" % (type(e).__name__, str(e)[:120])}
    return crops, overlay, overlay_path


def _digest_attach(overlay_path, crops, attach):
    """Pick the images to attach for the model: the overview first, then the crops."""
    try:
        attach_n = int(attach or 0)
    except Exception:
        attach_n = 0
    attach_paths = []
    if overlay_path:
        attach_paths.append(overlay_path)
    attach_paths.extend([c.get("path") for c in crops if c.get("path")])
    return attach_paths[:max(0, attach_n)]
