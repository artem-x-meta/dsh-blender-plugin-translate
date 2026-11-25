# -*- coding: utf-8 -*-
"""img_digest stage 1: parameter validation and image loading (behaviour identical to before the split)."""
from ..common import *  # noqa: F401,F403
from ..common import _j, _load_ex
from ..analysis import _md5_cached
from ..hough import _parse_known_lengths


def _digest_prepare(path, max_px, crop_max_px, known_len):
    """Validate parameters and parse known_len; returns (None, ctx) on success and (err, None) on failure."""
    if path is None or str(path).strip() == "":
        return _j({"ok": False, "error": "path is required (reference image path)",
                   "hint": "img_digest(path='D:/ref/front.png', known_len={'mm':100,'p1_px':[100,80],'p2_px':[420,80]})"}), None
    path = str(path)
    try:
        max_px = int(max_px) if max_px else 0
    except Exception:
        return _j({"ok": False, "error": "max_px must be an integer", "max_px": max_px}), None
    try:
        crop_max_px = int(crop_max_px or 900)
    except Exception:
        return _j({"ok": False, "error": "crop_max_px must be an integer", "crop_max_px": crop_max_px}), None
    if known_len is not None:
        known_items = _parse_known_lengths(known_len)
        if not known_items:
            return _j({"ok": False, "error": "known_len does not parse into (px, mm) pairs",
                       "hint": "give {'mm':100,'px':250} or {'mm':100,'p1_px':[x,y],'p2_px':[x,y]} (a list is also accepted)",
                       "known_len": known_len}), None
    else:
        known_items = []
    return None, {"path": path, "max_px": max_px, "crop_max_px": crop_max_px,
                  "known_items": known_items}


def _digest_load(ctx):
    """Load the image and build image_block; returns (None, ctx) on success."""
    path = ctx["path"]
    max_px = ctx["max_px"]
    try:
        arr, p, native_px, loaded_px = _load_ex(path, max_px=max_px)
    except Exception as e:
        return _j({"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:200]),
                   "path": path}), None
    H, W = int(arr.shape[0]), int(arr.shape[1])
    md5 = _md5_cached(p)
    image_id = md5[:12]
    image_block = {"path": p, "md5": md5, "image_id": image_id,
                   "native_px": [int(native_px[0]), int(native_px[1])],
                   "loaded_px": [W, H],
                   "downscaled": bool(int(native_px[0]) * int(native_px[1]) > W * H),
                   "max_px": int(max_px)}
    ctx.update({"arr": arr, "p": p, "native_px": native_px, "loaded_px": loaded_px,
                "H": H, "W": W, "md5": md5, "image_id": image_id, "image_block": image_block})
    return None, ctx
