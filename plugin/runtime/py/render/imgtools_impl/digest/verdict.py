# -*- coding: utf-8 -*-
"""img_digest stage 5: verdict and unknown/to_confirm/next (behaviour identical to before the split)."""
from ..common import *  # noqa: F401,F403


def _view_count(views):
    if views is None:
        return None
    if isinstance(views, str):
        return 1
    try:
        return len(list(views))
    except Exception:
        return None


def _digest_verdict(ctx, views):
    """verdict three-state + unknown/to_confirm/next; returns (verdict, unknown, to_confirm, nexts)."""
    ppm = ctx["ppm"]
    unknown, to_confirm, nexts = [], [], []
    n_views = _view_count(views)
    if ppm is None:
        verdict = "needs_scale"
        unknown.append("px_per_mm not calibrated: all mm fields are null (no guessing)")
        nexts.append("Pass known_len (the two ruler end points or a known edge length) and rerun img_digest, or shoot a ruler first")
    elif n_views == 1:
        verdict = "needs_views"
        nexts.append("Add one more orthographic view (front/side/top) and rerun; only then will verdict reach ready_for_spec")
    elif float(ctx["cc_frac"]) < 0.5 or float(ctx["conf"]) < 0.3 or float(ctx["filled"].mean()) > 0.98:
        verdict = "degraded"
        to_confirm.append("Suspicious mask (largest connected component %.0f%%, confidence %.2f): matte the image first or pass threshold before measuring"
                          % (ctx["cc_frac"] * 100.0, ctx["conf"]))
    elif ctx["contour"] is None or len(ctx["poly"]) < 3:
        verdict = "degraded"
        to_confirm.append("Contour tracking failed: the image may be too small/fragmented")
    else:
        verdict = "ready_for_spec"
        nexts.append("The mm numbers can go straight into spec.py; use img_measure to get a delta table against expected values")
    native_px, W, H = ctx["native_px"], ctx["W"], ctx["H"]
    if int(native_px[0]) * int(native_px[1]) > W * H:
        unknown.append("Source image %dx%d > max_px, downsampled to %dx%d: px coordinates are in loaded scale (native = loaded × %s)"
                       % (native_px[0], native_px[1], W, H,
                          round(float(native_px[0]) / float(W), 4)))
        to_confirm.append("Double-check key features with crops (native crop, no scaling)")
    if float(ctx["cc_frac"]) < 0.85:
        to_confirm.append("Foreground splits into several pieces (largest connected component %.0f%%): separate parts or occlusion are likely" % (ctx["cc_frac"] * 100.0))
    if float(ctx["conf"]) < 0.5:
        to_confirm.append("Mask confidence %.2f is low: matte the photo first (rembg) or pass threshold explicitly" % float(ctx["conf"]))
    if not ctx["lines"]:
        to_confirm.append("No stable straight lines: the image may be blurry/low-contrast, or all curves")
    if not ctx["holes_raw"]:
        unknown.append("No internal holes detected (if there are holes, alpha may have swallowed them or contrast is too low)")
    if ctx["unreadable_rows"]:
        to_confirm.append("There are %d features <8px: counts/shapes are unreliable, do not put them in spec" % len(ctx["unreadable_rows"]))
    sym = ctx["sym"]
    if sym.get("score") is not None and float(sym["score"]) < 0.8:
        unknown.append("Weak symmetry (mirror IoU=%.2f): it may not be a mirrored part, or the framing has perspective" % float(sym["score"]))
    nexts.append("For a width at a given height: img_probe(op='scan_y', y_px=…); for a circular hole: img_probe(op='circle', x_px=…, y_px=…)")
    return verdict, unknown, to_confirm, nexts
