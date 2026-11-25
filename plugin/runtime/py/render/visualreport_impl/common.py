# -*- coding: utf-8 -*-
"""DSH same-camera QC visual report (verdict-first) — turns "does it look right" into one page of actionable conclusions.

Field problem: qc_render_views gives you images and the model still has to "look"; yet a VLM looking at two images cannot say "where the difference is, how many mm it is, and what to change next". This module only does **same-camera** objective comparison (same camera, same resolution/crop) and outputs:

    verdict  pass / fail / degraded          ← **first field** (degraded ≠ pass)
    metrics  IoU / Dice / missing / extra / boundary (how much is missing, how much is extra, mean boundary error)
    top_defects  the N largest defects: bbox_px / area delta / position mm / kind(missing|extra) / the matching view
    crops    one zoomed difference image per defect (up to 3 written to disk)
    images   overlay (red = in the reference but not the render / blue = extra in the render / yellow = overlap), sheet (reference|render|overlay triptych)
    fix_hint an actionable next step (per defect direction)

ops (through blender_rt_plan or K.dsh_visualreport_api):
    report(ref, render | views, px_per_mm, targets, out_dir, max_defects, ref_box_px, render_box_px,
           label, iou_pass, iou_fail, max_missing_frac, max_extra_frac, save_images)
    selftest / help

Parameters:
    ref           reference image path (required)
    render        render image path (one of render/views)
    views         [{name, path}] multi-view same-camera comparison (up to 8; one of views/render)
    ref_box_px    view crop of the reference image [x0,y0,x1,y1] (or {"x0","y0","x1","y1"} / {"x","y","w","h"})
    render_box_px view crop of the render image (as above) — when given, normalise by bbox; when not, align the whole images and add warnings
    px_per_mm     pixels per millimetre in the render image (optional; only with it can a defect's bbox/area be converted to mm — targets rely on it too)
    targets       [{key, expect_mm, tol_mm}] known-dimension check; key ∈ width|height|diag|area
    out_dir       root output directory (default K.out_dir; each run creates <out_dir>/visualreport_<label>_<timestamp>/)
    max_defects   number of defects returned / located (default 3; at most 3 crops written)
    iou_pass      pass threshold (default 0.95) | iou_fail fail threshold (default 0.85)
    max_missing_frac / max_extra_frac upper bounds on the missing/extra area fraction (default 0.02 = 2% each)

Verdict (read verdict first, then metrics; three-state semantics match gate):
    fail       IoU < iou_fail, or the missing/extra area fraction exceeds its bound, or a targets entry is out of bounds (wrong size)
    degraded   computable but the evidence is insufficient: empty mask, reference/render sizes differ and were scaled, targets cannot be judged without px_per_mm,
               IoU falls between fail and pass, or neither qc nor imgtools is available for cross-checking
    pass       everything else (IoU ≥ iou_pass with missing/extra area within the thresholds, and all targets pass)

Metric sources (three-level fallback, spelled out by metrics_source / crosscheck in the receipt):
    ① qc is preloaded: masks come from qc.mask_auto, metrics from qc.metrics (the same IoU/Dice/boundary algorithm as qc.compare),
       plus a qc.compare cross-check and its overlay/sheet;
    ② no qc but imgtools present: numpy computes masks/metrics itself, and imgtools diff/scan cross-checks (IoU / missing-extra pixels / bbox);
    ③ neither: pure numpy fallback (boundary is a dilation approximation, explained in the receipt's note).
This module generates overlay/sheet/crop itself (pure numpy + bpy PNG save), with no montage/PIL dependency.

Honest limits:
  · only usable for **the same camera**: with a different camera/focal length/resolution/crop the IoU is systematically low (that is an input problem, not a model problem);
  · only silhouette/geometry-type objective comparison; material/colour/aesthetic judgement is not in this module (for colour differences use qc.compare's profiles/images);
  · the masks of both reference and render come from a "foreground vs background" heuristic, so photo-style references need their background cut out first (otherwise the mask is unreliable);
  · top_defects areas are **pixel deltas**; without px_per_mm they are reported in pixel terms only (the mm fields are null).
"""
import json as json
import math
import os
import re
import sys
import time

import bpy as bpy

import numpy as np  # noqa: F401  # re-exported to the split visualreport modules


VISUALREPORT_VERSION = 1

_K = sys.modules.get("dsh_rt_kernel")
_KIT = getattr(_K, "dsh_kit", None)
if _KIT is None:
    raise RuntimeError("visualreport.py needs the shared kernel K.dsh_kit (injected by KERNEL_BOOTSTRAP)")
_j = _KIT.j

DEFAULT_MAX_DEFECTS = 3
MAX_VIEWS = 8
TARGET_KEY_ALIASES = {
    "width": "width", "w": "width", "x": "width", "bbox_w": "width", "bbox_width": "width",
    "height": "height", "h": "height", "y": "height", "bbox_h": "height", "bbox_height": "height",
    "diag": "diag", "diagonal": "diag", "d": "diag", "diag_mm": "diag",
    "area": "area", "area_mm2": "area", "area_mm^2": "area",
}


# ────────────────────────────── small helpers ──────────────────────────────
def _err(msg, hint=None, op=None, **kw):
    d = {"ok": False, "error": str(msg)[:320]}
    if hint:
        d["hint"] = str(hint)[:420]
    if op:
        d["op"] = op
    d.update(kw)
    return d


def _safe_token(s, what="label", maxlen=48):
    t = re.sub(r"[^\w.-]+", "_", str(s if s is not None else "").strip(), flags=re.UNICODE).strip("_.-")
    return (t or "qc")[:maxlen]


def _num(v, what, default=None, gt=None, minv=None, maxv=None):
    if v is None:
        if default is None:
            raise ValueError("%s is required" % what)
        return float(default)
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError("%s is not a number: %r" % (what, v))
    if not math.isfinite(x):
        raise ValueError("%s is not finite: %r" % (what, v))
    if gt is not None and not x > gt:
        raise ValueError("%s must be > %g (got %g)" % (what, gt, x))
    if minv is not None and x < minv:
        raise ValueError("%s must be >= %g (got %g)" % (what, minv, x))
    if maxv is not None and x > maxv:
        raise ValueError("%s must be <= %g (got %g)" % (what, maxv, x))
    return x


def _bool(v, what="argument", default=False):
    if v is None:
        return bool(default)
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on", "y")
    raise ValueError("%s must be a bool (got %r)" % (what, v))


def _win(p):
    s = str(p)
    try:
        if s.startswith("/") and _K is not None and hasattr(_K, "win_path"):
            return _K.win_path(s)
    except Exception:
        pass
    return s


def _norm_path(p, base=None):
    s = str(p)
    if s.startswith("/"):
        s = _win(s)
    elif base and not os.path.isabs(s) and not re.match(r"^[A-Za-z]:[\\/]", s):
        s = os.path.join(str(base), s)
    return s


def _root_outdir(raw):
    if raw:
        p = _norm_path(raw)
        try:
            os.makedirs(p, exist_ok=True)
        except Exception as e:
            raise ValueError("cannot create out_dir: %s (%s)" % (p, str(e)[:120]))
        return p
    base = getattr(_K, "out_dir", None) or getattr(_K, "workdir", None) or os.path.join(os.path.expanduser("~"), "dsh_out")
    base = _norm_path(base)
    try:
        os.makedirs(base, exist_ok=True)
        return base
    except Exception:
        return _norm_path(os.path.expanduser("~"))


def _file_info(path):
    p = _norm_path(path)
    return {"path": p, "bytes": int(os.path.getsize(p)), "exists": os.path.isfile(p)}


def _md5(path):
    import hashlib
    h = hashlib.md5()
    with open(_norm_path(path), "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _stamp():
    return time.strftime("%Y%m%d_%H%M%S")




__all__ = [name for name in list(globals()) if not name.startswith("__")]
