# -*- coding: utf-8 -*-
"""Split from imgtools.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403

def img_scan(path, rois=None, invert=False, threshold=None, top_lines=5, sample_points=None):
    """Read-only: measure a reference image into numbers (contour bbox / aspect ratio / fill ratio / principal-axis angle / dominant line angles / color sampling at given points)."""
    arr, p = _load(path)
    h, w = arr.shape[0], arr.shape[1]
    m = _mask_of(arr, invert=invert, threshold=threshold)
    bb = _bbox(m)
    out = {"ok": True, "path": p, "size": [w, h], "foreground_pixels": int(m.sum()),
           "foreground_fraction": round(float(m.mean()), 4)}
    if float(m.mean()) > 0.95:
        out["mask_warning"] = ("foreground covers %.0f%% of the frame — the background was probably not separated out (for photos, cut the subject out with rembg first, or pass threshold explicitly); "
                               "bbox / aspect ratio are unreliable on such input" % (m.mean() * 100))
    if bb is None:
        out.update({"empty": True, "note": "no foreground separated out — for photo references, remove the background first (rembg), or pass threshold explicitly"})
        return _j(out)
    x, y, bw, bh = bb
    sub = m[y:y + bh, x:x + bw]
    # principal-axis angle (image moments)
    ys, xs = np.nonzero(m)
    cx, cy = xs.mean(), ys.mean()
    vxx, vyy = ((xs - cx) ** 2).mean(), ((ys - cy) ** 2).mean()
    vxy = ((xs - cx) * (ys - cy)).mean()
    ang = 0.5 * math.atan2(2 * vxy, (vxx - vyy) + 1e-12)
    # dominant line angles: gradient-orientation histogram (0–180°, peaks are the main edge directions)
    g = _gray(arr)
    gx = np.zeros_like(g); gy = np.zeros_like(g)
    gx[:, 1:-1] = g[:, 2:] - g[:, :-2]
    gy[1:-1, :] = g[2:, :] - g[:-2, :]
    mag = np.hypot(gx, gy) * m
    ori = (np.degrees(np.arctan2(gy, gx)) + 180.0) % 180.0
    hist, edges = np.histogram(ori, bins=36, range=(0, 180), weights=mag)
    tops = sorted(range(36), key=lambda i: -hist[i])[:max(1, int(top_lines))]
    out.update({
        "bbox": bb, "aspect_wh": round(bw / float(bh), 4), "fill_ratio": round(float(sub.mean()), 4),
        "centroid": [round(float(cx), 2), round(float(cy), 2)],
        "principal_axis_deg": round(math.degrees(ang), 2),
        "edge_orientation_top": [{"deg": int((edges[i] + edges[i + 1]) / 2), "weight": round(float(hist[i]), 1)} for i in tops],
        "note": "bbox is in pixels; for millimeters, calibrate against a known length first (give a scale bar or two endpoints via sample_points)",
    })
    # per-column top/bottom boundary (station-table raw material: used for outer-surface reconstruction) — sampled per column inside the bbox, at most 512 columns
    step_c = max(1, bw // 512)
    col_top, col_bot, col_w = [], [], []
    for c in range(0, bw, step_c):
        colm = m[y:y + bh, x + c]
        idxs = np.nonzero(colm)[0]
        if len(idxs) == 0:
            col_top.append(None); col_bot.append(None); col_w.append(0)
        else:
            col_top.append(int(idxs.min())); col_bot.append(int(idxs.max())); col_w.append(int(len(idxs)))
    out["col_top"] = col_top          # row index relative to the bbox top (None = column is empty)
    out["col_bottom"] = col_bot
    out["col_fill"] = col_w
    out["col_px_per_step"] = step_c
    # foreground width per row (for human/contour proportions): sampled per row inside the bbox, at most 256 rows
    step = max(1, bh // 256)
    out["row_profile"] = [int(sub[r].sum()) for r in range(0, bh, step)]
    if rois:
        rows = []
        for r in rois:
            rx, ry, rw, rh = [int(v) for v in (list(r) + [0, 0, 0, 0])[:4]]
            rm = m[max(0, ry):ry + rh, max(0, rx):rx + rw]
            rows.append({"roi": [rx, ry, rw, rh], "foreground_fraction": round(float(rm.mean()), 4) if rm.size else None,
                         "foreground_pixels": int(rm.sum())})
        out["rois"] = rows
    if sample_points:
        rows = []
        for pt in sample_points:
            px, py = int(pt[0]), int(pt[1])
            px = min(max(px, 0), w - 1); py = min(max(py, 0), h - 1)
            c = arr[py, px]
            rows.append({"point": [px, py], "rgba": [round(float(v), 4) for v in c],
                         "foreground": bool(m[py, px])})
        out["samples"] = rows
    return _j(out)


def img_crop(path, x, y, w, h, scale=2.0, out=None, label=None):
    """ROI crop + upsample, then write to disk — "foveated viewing": look at one region at a time and fill as much of the vision encoder's input as possible."""
    arr, p = _load(path)
    H, W = arr.shape[0], arr.shape[1]
    x, y, w, h = int(x), int(y), int(w), int(h)
    if w <= 0 or h <= 0:
        raise ValueError("w/h must be > 0")
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("ROI is entirely outside the image: the image is %dx%d" % (W, H))
    sub = arr[y0:y1, x0:x1]
    s = float(scale or 1.0)
    if s > 1.0:
        sh, sw = sub.shape[0], sub.shape[1]
        nh, nw = int(round(sh * s)), int(round(sw * s))
        yi = np.clip((np.arange(nh) / s).astype(int), 0, sh - 1)
        xi = np.clip((np.arange(nw) / s).astype(int), 0, sw - 1)
        sub = sub[yi][:, xi]                     # nearest neighbor: introduces no fake interpolation detail
    outp = out or (os.path.splitext(p)[0] + "_crop_%d_%d_%d_%d_x%s.png" % (x0, y0, x1 - x0, y1 - y0, str(s).replace(".", "p")))
    saved = _save(sub, outp)
    return _j({"ok": True, "source": p, "roi": [x0, y0, x1 - x0, y1 - y0], "scale": s,
               "out": saved, "out_size": [int(sub.shape[1]), int(sub.shape[0])], "label": label,
               "note": "hand the out path to the image-viewing tool; look at this one patch at a time, with an explicit question (yes/no or a number)"})


def img_annotate(path, lines=None, boxes=None, crosses=None, grid=None, out=None, thickness=2):
    """Draw the measured coordinates / proportion lines / reference boxes **back onto the image** — let the model "read annotations" instead of "guess the shape".
    Color semantics are fixed in the receipt's legend (read colors on the image, numbers in the receipt)."""
    arr, p = _load(path)
    H, W = arr.shape[0], arr.shape[1]
    out_arr = arr.copy()
    t = max(1, int(thickness))
    legend = []

    def put(x, y, color):
        if 0 <= x < W and 0 <= y < H:
            out_arr[y, x, 0:3] = color

    def hline(x0, x1, y, color):
        for x in range(max(0, int(x0)), min(W, int(x1))):
            for d in range(t):
                put(x, int(y) + d, color)

    def vline(x, y0, y1, color):
        for y in range(max(0, int(y0)), min(H, int(y1))):
            for d in range(t):
                put(int(x) + d, y, color)

    for i, ln in enumerate(lines or []):
        d = dict(ln)
        col = d.get("color") or ([1.0, 0.2, 0.2] if i % 3 == 0 else ([0.2, 1.0, 0.3] if i % 3 == 1 else [0.3, 0.5, 1.0]))
        x1, y1, x2, y2 = [float(d.get(k, 0)) for k in ("x1", "y1", "x2", "y2")]
        n = int(max(abs(x2 - x1), abs(y2 - y1))) + 1
        for k in range(n):
            xa = x1 + (x2 - x1) * k / max(1, n - 1)
            ya = y1 + (y2 - y1) * k / max(1, n - 1)
            put(int(round(xa)), int(round(ya)), col)
            for dd in range(1, t):
                put(int(round(xa)) + dd, int(round(ya)), col)
        legend.append({"kind": "line", "label": d.get("label"), "coords": [x1, y1, x2, y2],
                       "rgb": [round(float(c), 3) for c in col],
                       "length_px": round(math.hypot(x2 - x1, y2 - y1), 2)})
    for i, bx in enumerate(boxes or []):
        d = dict(bx)
        col = d.get("color") or [1.0, 0.85, 0.1]
        x, y, w, h = [float(d.get(k, 0)) for k in ("x", "y", "w", "h")]
        hline(x, x + w, y, col); hline(x, x + w, y + h, col)
        vline(x, y, y + h, col); vline(x + w, y, y + h, col)
        legend.append({"kind": "box", "label": d.get("label"), "box": [x, y, w, h],
                       "rgb": [round(float(c), 3) for c in col]})
    for i, cr in enumerate(crosses or []):
        d = dict(cr)
        col = d.get("color") or [1.0, 0.1, 1.0]
        x, y = float(d.get("x", 0)), float(d.get("y", 0))
        arm = float(d.get("arm", 8))
        hline(x - arm, x + arm, y, col); vline(x, y - arm, y + arm, col)
        legend.append({"kind": "cross", "label": d.get("label"), "at": [x, y], "rgb": [round(float(c), 3) for c in col]})
    if grid:
        gd = dict(grid) if isinstance(grid, dict) else {}
        step = int(gd.get("step") or max(8, min(W, H) // 10))
        col = [0.15, 0.85, 0.95]
        for x in range(0, W, step):
            for y in range(0, H, 2):
                put(x, y, col)
        for y in range(0, H, step):
            for x in range(0, W, 2):
                put(x, y, col)
        legend.append({"kind": "grid", "step_px": step, "rgb": col,
                       "note": "the grid is for reading values: cell count×step is the pixel distance"})
    outp = out or (os.path.splitext(p)[0] + "_annot.png")
    saved = _save(out_arr, outp)
    return _j({"ok": True, "source": p, "out": saved, "size": [W, H], "legend": legend,
               "note": "read colors on the image, numbers in the legend; place proportion lines against known dimensions of the reference image"})


def img_diff(a, b, out=None, align=True, invert_a=False, invert_b=False):
    """Contour difference of two images: IoU + pixels unique to each + profile difference + a red/blue overlay (models are far more sensitive to "where there is too much/too little" than to "does it look alike")."""
    aa, pa = _load(a)
    ab, pb = _load(b)
    ma = _mask_of(aa, invert=invert_a)
    mb = _mask_of(ab, invert=invert_b)
    if align:
        ba, bb2 = _bbox(ma), _bbox(mb)
        if ba and bb2:
            ma = ma[ba[1]:ba[1] + ba[3], ba[0]:ba[0] + ba[2]]
            mb = mb[bb2[1]:bb2[1] + bb2[3], bb2[0]:bb2[0] + bb2[2]]
    H = max(ma.shape[0], mb.shape[0]); W = max(ma.shape[1], mb.shape[1])
    A = np.zeros((H, W), bool); B = np.zeros((H, W), bool)
    A[:ma.shape[0], :ma.shape[1]] = ma
    B[:mb.shape[0], :mb.shape[1]] = mb
    # metrics converge on the shared kernel (single implementation)
    iou, inter, union = _KIT.iou(A, B)
    a_only = int((A & ~B).sum()); b_only = int((B & ~A).sum())
    # per-axis profiles (foreground fraction difference per column/row) — shows "which stretch got fatter/thinner"
    col_a, col_b = A.mean(axis=0), B.mean(axis=0)
    row_a, row_b = A.mean(axis=1), B.mean(axis=1)
    over = np.zeros((H, W, 4), np.float32)
    over[:, :, 3] = 1.0
    over[:, :, 0] = np.where(A & B, 0.25, 0.0) + np.where(A & ~B, 1.0, 0.0)
    over[:, :, 1] = np.where(A & B, 0.35, 0.0)
    over[:, :, 2] = np.where(A & B, 0.30, 0.0) + np.where(B & ~A, 1.0, 0.0)
    outp = out or (os.path.splitext(pa)[0] + "_vs_" + os.path.splitext(os.path.basename(pb))[0] + "_diff.png")
    saved = _save(over, outp)
    return _j({"ok": True, "a": pa, "b": pb, "aligned_bbox": bool(align), "size": [W, H],
               "iou": (round(float(iou), 4) if iou is not None else None),
               "intersection_px": inter, "union_px": union, "a_only_px": a_only, "b_only_px": b_only,
               "worst_columns": [{"x": int(i), "delta": round(float(col_a[i] - col_b[i]), 4)}
                                 for i in np.argsort(-np.abs(col_a - col_b))[:5]],
               "worst_rows": [{"y": int(i), "delta": round(float(row_a[i] - row_b[i]), 4)}
                              for i in np.argsort(-np.abs(row_a - row_b))[:5]],
               "out": saved,
               "legend": {"white/gray": "overlap", "red": "A only (too much)", "blue": "B only (too little)"},
               "note": "IoU and pixel counts are both numeric criteria; the overlay shows \"where it differs\"; alignment normalizes by each contour's own bbox"})

def img_rectify(path=None, quad=None, out=None, out_w=None, out_h=None, aspect=None,
                known_w_mm=None, invert=False, threshold=None):
    """Four corner points → rectangle (**homography rectification**): stretch a skewed quadrilateral in a photo into a front-facing rectangle, so that measuring it afterwards is accurate.

    quad = [[x,y], [x,y], [x,y], [x,y]], given in the order "top-left → top-right → bottom-right → bottom-left" (image pixel coordinates).
    Output size: give out_w/out_h; or only out_w + aspect (width/height); given known_w_mm it returns mm_per_px.

    Pure numpy: 8-parameter homography from the 4-point DLT (mapping rectangle coordinates back to the source image) + bilinear sampling, **no OpenCV dependency**.
    ⚠ the four rectification points must be a **rectangle on one single plane** (e.g. a wheelbase/vehicle-length rectangle on a vehicle's side, or a calibration box on the ground);
      the stronger the skew, the more the four points' picking error gets amplified — it is advisable to look at the contour with img_scan first, then pick points.
    """
    import numpy as np
    if not path:
        return _j({"ok": False, "error": "pass path"})
    if not quad or len(quad) != 4:
        return _j({"ok": False, "error": "quad must be 4 points [[x,y]×4] (top-left/top-right/bottom-right/bottom-left)"})
    try:
        loaded = _load(path)          # ⚠ _load returns (arr, path), not a bare array
        arr = loaded[0] if isinstance(loaded, (tuple, list)) else loaded
        if arr is None:
            return _j({"ok": False, "error": "cannot read image: %s" % path})
        src_h, src_w = arr.shape[0], arr.shape[1]
        wo = int(out_w or 0)
        ho = int(out_h or 0)
        if wo <= 0 and ho <= 0:
            return _j({"ok": False, "error": "pass out_w (or out_w+aspect / out_h)"})
        if wo <= 0:
            wo = int(round(ho * float(aspect or 1.0)))
        if ho <= 0:
            ho = int(round(wo / float(aspect))) if aspect else int(round(wo * 0.5))
        wo, ho = max(8, wo), max(8, ho)
        # destination rectangle corners (top-left/top-right/bottom-right/bottom-left) → the corresponding four source points, solving the "rectangle → source" homography
        rect = [(0.0, 0.0), (float(wo - 1), 0.0), (float(wo - 1), float(ho - 1)), (0.0, float(ho - 1))]
        A, b = [], []
        for (u, v), (x, y) in zip(rect, quad):
            u, v, x, y = float(u), float(v), float(x), float(y)
            A.append([u, v, 1, 0, 0, 0, -u * x, -v * x]); b.append(x)
            A.append([0, 0, 0, u, v, 1, -u * y, -v * y]); b.append(y)
        h = np.linalg.solve(np.array(A, dtype=np.float64), np.array(b, dtype=np.float64))
        yy, xx = np.mgrid[0:ho, 0:wo].astype(np.float64)
        den = h[6] * xx + h[7] * yy + 1.0
        den = np.where(np.abs(den) < 1e-12, 1e-12, den)
        sx = (h[0] * xx + h[1] * yy + h[2]) / den
        sy = (h[3] * xx + h[4] * yy + h[5]) / den
        x0 = np.floor(sx).astype(np.int64); y0 = np.floor(sy).astype(np.int64)
        fx = (sx - x0)[..., None]; fy = (sy - y0)[..., None]
        x0c = np.clip(x0, 0, src_w - 2); y0c = np.clip(y0, 0, src_h - 2)
        x1c = x0c + 1; y1c = y0c + 1
        a00 = arr[y0c, x0c]; a01 = arr[y0c, x1c]; a10 = arr[y1c, x0c]; a11 = arr[y1c, x1c]
        outarr = (a00 * (1 - fx) * (1 - fy) + a01 * fx * (1 - fy) +
                  a10 * (1 - fx) * fy + a11 * fx * fy).astype(np.float32)
        op = out or (str(path).rsplit(".", 1)[0] + "_rect.png")
        p = _save(outarr, op)
        res = {"ok": True, "out": p, "out_size": [wo, ho], "src_size": [src_w, src_h],
               "homography_rect_to_src": [round(float(t), 6) for t in h],
               "note": "only feed the rectified image to vehicle_sections / img_scan to be accurate; the less the skew, the more accurate"}
        if known_w_mm:
            res["mm_per_px"] = round(float(known_w_mm) / float(wo), 6)
        return _j(res)
    except Exception as e:
        return _j({"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:220])})
