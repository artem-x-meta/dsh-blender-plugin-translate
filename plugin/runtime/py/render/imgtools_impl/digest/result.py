# -*- coding: utf-8 -*-
"""img_digest stage 6: cache registration and final receipt (behavior identical to before the split)."""
from ..common import *  # noqa: F401,F403
from ..common import _j
from ..cache import _cache_put, _register_id


def _digest_result(ctx, t0):
    """Cache + image_id registration, and assemble the final JSON receipt."""
    md5 = ctx["md5"]
    image_id = ctx["image_id"]
    m = ctx["m"]
    entry = {"md5": md5, "path": ctx["p"], "shape": [ctx["W"], ctx["H"]],
             "native_px": [int(ctx["native_px"][0]), int(ctx["native_px"][1])],
             "gray": ctx["g"], "mask": ctx["cc"], "filled": ctx["filled"],
             "bbox_px": [int(v) for v in ctx["bbox"]],
             "source": ctx["source"], "confidence": round(float(ctx["conf"]), 4), "px_per_mm": ctx["ppm"],
             "silhouette": ctx["silhouette"], "features": ctx["features"]}
    try:
        _cache_put(entry)
        _register_id(image_id, entry, ctx["silhouette"], ctx["features"], ctx["numbers"])
    except Exception:
        pass
    return _j({
        "ok": True, "version": IMG_VERSION, "verdict": ctx["verdict"],
        "image": ctx["image_block"],
        "mask": {"source": ctx["source"], "fg_frac": round(float(m.mean()), 4),
                 "confidence": round(float(ctx["conf"]), 4),
                 "self_check": {"largest_cc_frac": round(float(ctx["cc_frac"]), 4),
                                "holes": int(len(ctx["holes_raw"])),
                                "edge_strength_p50": round(float(ctx["es_p50"]), 3)},
                 "components": int(ctx["cc_info"].get("n_components") or 0), "info": ctx["minfo"]},
        "silhouette": ctx["silhouette"],
        "symmetry": ctx["sym"],
        "lines": ctx["lines"],
        "features": ctx["features"],
        "scale": ctx["scale"],
        "numbers": ctx["numbers"],
        "readability": ctx["readability"],
        "unreadable": ctx["unreadable_rows"],
        "rois": (ctx["roi_rows"] if ctx["roi_rows"] else None),
        "crops": ctx["crops"],
        "overlay": ctx["overlay"],
        "attach": ctx["attach_paths"],
        "unknown": ctx["unknown"], "to_confirm": ctx["to_confirm"], "next": ctx["nexts"],
        "provenance": {"image_md5": md5, "image_id": image_id, "method": "alpha/border_otsu mask + "
                       "moore contour/DP + sobel-hough + kasa circle + least-squares scale",
                       "px_per_mm": ctx["ppm"], "coordinate_system": "left-top origin; px are loaded_px scale",
                       "elapsed_ms": round((time.time() - t0) * 1000.0, 1)},
        "honest_limits": ["no deep-learning matting: for complex photos use rembg first or pass threshold",
                          "Hough only catches strong straight lines; curves/low-contrast edges produce no lines",
                          "without known_len every mm value is null (never a guess)",
                          "symmetry only tests vertical/horizontal mirror axes"],
    })
