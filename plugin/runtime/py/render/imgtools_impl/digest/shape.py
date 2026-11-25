# -*- coding: utf-8 -*-
"""img_digest stage 2: mask, largest connected component, contour, silhouette and symmetry (behaviour identical to before the split)."""
from ..common import *  # noqa: F401,F403
from ..common import _bbox, _j
from ..analysis import _edge_strength_p50, _largest_cc_mask, _mask_v2, _principal_axis, _rnd
from ..contour import _curvature_landmarks, _holes_of, _hull, _simplify_closed, _symmetry, _trace_contour


def _digest_shape(ctx, invert, threshold):
    """Mask and geometric quantities; returns (err, None) on failure and (None, ctx) on success."""
    arr, H, W = ctx["arr"], ctx["H"], ctx["W"]
    image_block = ctx["image_block"]
    m, g, source, conf, minfo = _mask_v2(arr, invert=invert, threshold=threshold)
    if int(m.sum()) == 0:
        return _j({"ok": False, "error": "no foreground separated (mask is empty)", "verdict": "unreadable",
                   "image": image_block,
                   "hint": "matte the photo first (rembg) or pass threshold; for an alpha image check the alpha channel is valid"}), None
    cc, cc_frac, cc_info = _largest_cc_mask(m)
    bbox = _bbox(cc) if int(cc.sum()) > 0 else None
    if bbox is None or int(cc.sum()) < 16:
        return _j({"ok": False, "error": "foreground too small / too scattered (largest connected component <16px)", "verdict": "unreadable",
                   "image": image_block, "hint": "make sure the reference image is a close-up of the target; or pass rois to measure one region only"}), None
    holes_raw, filled = _holes_of(cc, bbox)
    if filled is None:
        filled = cc
    contour = _trace_contour(filled)
    poly = _simplify_closed(contour, 64) if contour is not None else None
    corners = _curvature_landmarks(poly) if poly is not None else []
    pcx, pcy, pdeg = _principal_axis(filled)
    crop_filled = filled[bbox[1]:bbox[1] + bbox[3], bbox[0]:bbox[0] + bbox[2]]
    fill_ratio = float(crop_filled.mean()) if crop_filled.size else 0.0
    aspect = float(bbox[2]) / float(max(1, bbox[3]))
    cand_hull_src = contour if contour is not None else np.column_stack(np.nonzero(filled)[::-1])
    hull_pts, hull_area, hull_per = _hull(cand_hull_src)
    outline = ([[int(round(float(xy[0]))), int(round(float(xy[1])))] for xy in np.asarray(poly)[:64].tolist()]
               if poly is not None else [])
    silhouette = {"bbox_px": [int(v) for v in bbox], "aspect_wh": round(aspect, 4),
                  "fill_ratio": round(fill_ratio, 4),
                  "principal_axis_deg": (round(float(pdeg), 2) if pdeg is not None else None),
                  "centroid_px": _rnd([pcx, pcy], 2),
                  "hull_px": hull_pts[:24], "hull_area_px": round(hull_area, 2),
                  "hull_perimeter_px": round(hull_per, 2),
                  "outline_px": outline, "outline_points": int(len(poly) if poly is not None else 0),
                  "contour_points": int(len(contour) if contour is not None else 0),
                  "curvature_landmarks": corners}
    sym = _symmetry(filled, bbox)
    es_p50 = _edge_strength_p50(g, cc)
    ctx.update({"m": m, "g": g, "source": source, "conf": conf, "minfo": minfo,
                "cc": cc, "cc_frac": cc_frac, "cc_info": cc_info, "bbox": bbox,
                "holes_raw": holes_raw, "filled": filled, "contour": contour, "poly": poly,
                "corners": corners, "pcx": pcx, "pcy": pcy, "pdeg": pdeg,
                "fill_ratio": fill_ratio, "aspect": aspect,
                "hull_pts": hull_pts, "hull_area": hull_area, "hull_per": hull_per,
                "silhouette": silhouette, "sym": sym, "es_p50": es_p50})
    return None, ctx
