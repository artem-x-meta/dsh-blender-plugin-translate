# -*- coding: utf-8 -*-
"""DSH reference-image measuring tools (v0.9.6 · consolidated design) — turning "cannot see it clearly" into "no need to look".

Field problem (the flash tier): details in a reference image are not visible — the visual encoder downsamples first, so features below
a certain pixel scale are already lost during encoding, and counting and small-object recognition are known weak spots of VLMs too.
**Raising the resolution does not help**; what works is: **measure the reference image into numbers**, **crop and enlarge the region**
to be judged, **draw the measured things back onto the image**, and turn "does it look alike" into a **difference image + IoU**.

ops (all go through blender_rt_plan):
    img_scan(path, rois=None, invert=False, top_lines=5, sample_points=None)   # read-only: contour/bbox/aspect ratio/main axis angle/line angles/color sampling
    img_crop(path, x, y, w, h, scale=2.0, out=None)                            # ROI crop + upscale (feed it to the image-viewing tool)
    img_annotate(path, lines=[], boxes=[], crosses=[], grid=None, out=None)    # draw the measured coordinates/proportion lines back onto the image
    img_diff(a, b, out=None)                                                   # contour difference + IoU + per-axis profile difference
    img_digest(path, views=None, known_len=None, ...)                          # v2: measure everything at once → number table + crop atlas + readability + verdict
    img_probe(image_id|path, op="scan_y", ...)                                 # v2: on-demand sub-pixel measurement (scan_y/scan_x/circle/distance)
    img_measure(image_id|path, px_per_mm, targets=[...])                       # v2: pixels→mm + compare against the expectation (delta/pass|fail)
    img_calib(views=[...], shared=[...])                                       # v2: per-view calibration for each view + cross-view shared-dimension consistency
    img_selftest / img_help

Coordinate convention: **top-left origin** (the image habit); the returned bbox is [x, y, w, h]. Pixels↔millimeters must be calibrated by the caller (img_scan reports the pixel counts).
Limitation: for photo-type reference images without alpha it relies on Otsu brightness segmentation, which is inaccurate when the foreground/background contrast is low — in that case cut the subject out first (rembg) and feed that in.
"""
import hashlib as hashlib
import json as json
import math
import os
import time as time

import bpy
import numpy as np

IMG_VERSION = 2


import sys as _sys_kit
_KIT = getattr(_sys_kit.modules.get("dsh_rt_kernel"), "dsh_kit", None)
if _KIT is None:
    raise RuntimeError("imgtools needs the shared kernel K.dsh_kit (injected by KERNEL_BOOTSTRAP)")


_j = _KIT.j  # shared kernel (the former built-in implementation was removed)
def _win(p):
    s = str(p)
    if s.startswith("/") and ":" not in s[:3]:
        K = __import__("sys").modules.get("dsh_rt_kernel")
        if K is not None and hasattr(K, "win_path"):
            try:
                return K.win_path(s)
            except Exception:
                return s
    return s


def _load_ex(path, max_px=None):
    """Read an image → (arr, p, native_px, loaded_px); when max_px>0 and the native size exceeds it, **scale down before reading** (saves memory).

    Coordinate policy: arr's (H, W) is loaded_px; to map px back to native pixels multiply by native/loaded.
    """
    p = _win(path)
    if not os.path.exists(p):
        raise ValueError("image does not exist: %s" % p)
    img = bpy.data.images.load(p, check_existing=False)
    try:
        nw, nh = int(img.size[0]), int(img.size[1])
        if nw <= 0 or nh <= 0:
            raise ValueError("image size is 0: %s" % p)
        lw, lh = nw, nh
        if max_px and int(max_px) > 0 and nw * nh > int(max_px):
            s = math.sqrt(float(max_px) / float(nw * nh))
            lw = max(1, int(round(nw * s)))
            lh = max(1, int(round(nh * s)))
            img.scale(lw, lh)
        buf = np.empty(lw * lh * 4, dtype=np.float32)
        img.pixels.foreach_get(buf)
        arr = buf.reshape(lh, lw, 4)[::-1]        # Blender is bottom-origin → flip to top-origin
        return arr, p, [nw, nh], [lw, lh]
    finally:
        try:
            bpy.data.images.remove(img)
        except Exception:
            pass


def _load(path, max_px=None):
    """Read an image → (H, W, 4) float array (**flipped vertically to upright**, i.e. row 0 = the top of the image)."""
    arr, p, _n, _l = _load_ex(path, max_px=max_px)
    return arr, p


def _save(arr, path):
    h, w = arr.shape[0], arr.shape[1]
    p = _win(path)
    d = os.path.dirname(p)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    img = bpy.data.images.new(os.path.basename(p) or "dsh_img", width=w, height=h, alpha=True)
    try:
        img.pixels.foreach_set(np.ascontiguousarray(arr[::-1].reshape(-1)).astype(np.float32))
        img.filepath_raw = p
        img.file_format = "PNG"
        img.save()
        return p
    finally:
        try:
            bpy.data.images.remove(img)
        except Exception:
            pass


def _gray(arr):
    return (0.2126 * arr[:, :, 0] + 0.7152 * arr[:, :, 1] + 0.0722 * arr[:, :, 2]).astype(np.float32)


def _otsu(g):
    hist, _ = np.histogram(g, bins=256, range=(0.0, 1.0))
    total = hist.sum()
    if total == 0:
        return 0.5
    omega = np.cumsum(hist) / total
    mu = np.cumsum(hist * np.arange(256)) / max(1.0, total)
    mu_t = mu[-1]
    denom = omega * (1.0 - omega)
    denom[denom <= 0] = 1e-9
    sigma_b = (mu_t * omega - mu) ** 2 / denom
    # a plateau of ties has to take the **median** index: in a bimodal image the 0..pre-peak stretch has exactly equal sigma_b, so argmax lands on 0
    # (threshold 0 ⇒ an empty mask — hit this in practice)
    mx = float(np.max(sigma_b))
    idx = np.nonzero(sigma_b >= mx - 1e-12)[0]
    k = int(idx[len(idx) // 2]) if len(idx) else 128
    return k / 255.0


def _mask_of(arr, invert=False, threshold=None, use_alpha=True):
    """Foreground mask: prefer alpha (the most reliable when there is a transparency channel), otherwise Otsu brightness segmentation."""
    a = arr[:, :, 3]
    if use_alpha and float(a.min()) < 0.999:
        m = a > 0.5
    else:
        g = _gray(arr)
        thr = float(threshold) if threshold is not None else _otsu(g)
        m = g < thr            # a common reference image is a dark part on a light background
        if float(m.mean()) > 0.5:
            m = ~m
    if invert:
        m = ~m
    # mask self-check: an empty mask basically means "no foreground was separated" — fall back to the honest conclusion instead of inventing numbers from an empty mask
    if float(m.mean()) < 0.002:
        inv = ~m
        if float(inv.mean()) > 0.002:
            m = inv
    return m


def _bbox(m):
    ys, xs = np.nonzero(m)
    if len(xs) == 0:
        return None
    return [int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)]




__all__ = [name for name in list(globals()) if not name.startswith("__")]
