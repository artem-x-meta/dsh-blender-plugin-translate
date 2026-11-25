# -*- coding: utf-8 -*-
"""img_digest orchestration: the stage functions live in separate modules of the same package; the public name is still img_digest."""
from ..common import *  # noqa: F401,F403
from ..hough import _digest_scale, _hough_lines
from .prepare import _digest_prepare, _digest_load
from .shape import _digest_shape
from .features import _digest_features, _digest_readability
from .numbers import _digest_numbers
from .verdict import _digest_verdict
from .visual import _digest_rois, _digest_visual, _digest_attach
from .result import _digest_result


def img_digest(path, views=None, known_len=None, scale_bar=True, rois=None, invert=False,
               threshold=None, max_px=16000000, out_dir=None, crop_max_px=900, attach=1):
    """**Measure the reference image in one pass**: contour/symmetry/lines/features/scale bar/readability + native crop atlas + annotated overview + verdict.

    Output discipline: without known_len ⇒ every mm field is null (**never invented**); px is on loaded scale (a source image above max_px
    is downsampled first, convert back to native with image.native_px / loaded_px). verdict ∈ ready_for_spec / needs_scale /
    needs_views / unreadable / degraded.
    """
    t0 = time.time()
    err, ctx = _digest_prepare(path, max_px, crop_max_px, known_len)
    if err:
        return err
    err, ctx = _digest_load(ctx)
    if err:
        return err
    err, ctx = _digest_shape(ctx, invert, threshold)
    if err:
        return err
    scale = _digest_scale(ctx["known_items"])
    ppm = scale.get("px_per_mm")
    ctx.update({"scale": scale, "ppm": ppm, "lines": _hough_lines(ctx["g"], ctx["cc"], max_lines=12)})
    ctx["features"], ctx["unreadable_rows"], ctx["conf_r"] = _digest_features(ctx)
    ctx["readability"] = _digest_readability(ctx["features"])
    ctx["numbers"] = _digest_numbers(ctx)
    ctx["roi_rows"] = _digest_rois(rois, ctx["m"], ctx["W"], ctx["H"])
    ctx["crops"], ctx["overlay"], ctx["overlay_path"] = _digest_visual(ctx, rois, out_dir, scale_bar)
    ctx["attach_paths"] = _digest_attach(ctx["overlay_path"], ctx["crops"], attach)
    ctx["verdict"], ctx["unknown"], ctx["to_confirm"], ctx["nexts"] = _digest_verdict(ctx, views)
    return _digest_result(ctx, t0)
