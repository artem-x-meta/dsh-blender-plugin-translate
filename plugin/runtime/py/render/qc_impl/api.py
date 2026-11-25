# -*- coding: utf-8 -*-
"""Split from qc.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403
from .pnggif import _gif_first_frame, gif_to_png
from .load import qc_compare, qc_crop, qc_iou, qc_load, qc_mask, qc_profile, qc_profile_diff, qc_resize_mask
from .align import _align_search, _iou_pair, _rotate_mask, qc_align_rotate, qc_mask_auto, qc_metrics
from .metrics import qc_compare_auto, qc_help, qc_mask_sweep, qc_robustness_check, qc_self_check

def m_aabb_err(obj_name, target_size):
    ob = bpy.data.objects.get(str(obj_name))
    if ob is None:
        return 1e9
    d = ob.dimensions
    t = [float(x) for x in target_size]
    return float(abs(d[0] - t[0]) + abs(d[1] - t[1]) + abs(d[2] - t[2]))


def _render_view(view_spec, label="measure"):
    K = _kernel()
    api = getattr(K, "dsh_view_api", None) if K is not None else None
    if api is None:
        raise RuntimeError("view.py (K.dsh_view_api) is required to render; in the plugin use preload='view' or let the engine inject it")
    spec = dict(view_spec or {})
    spec.setdefault("width", 480)
    spec.setdefault("height", 480)
    d = os.path.join(_out_dir(), "qc_renders")
    os.makedirs(d, exist_ok=True)
    spec["path"] = os.path.join(d, "%s_%s.png" % (str(label), time.strftime("%H%M%S")))
    info = json.loads(api["capture"](json.dumps(spec)))
    if not info.get("ok"):
        raise RuntimeError("render failed: %s" % info)
    return info["path"]


def m_silhouette_iou(view_spec, ref_path, ref_box, sat=0.13, v=0.74):
    """For the inner loop: render the given view → compare against the reference image → return 1-IoU (smaller is better).',
    **Fixed alignment on purpose (search=False)**: letting the objective be "scored up" by a search alignment pollutes the optimization
    (the model only has to scale the object to fit the silhouette) — the inner loop wants an honest metric; only offline QC uses search alignment."""
    png = _render_view(view_spec, "silhouette")
    res = json.loads(qc_compare_auto(ref_path, ref_box, png, label="silhouette", search=False))
    v2 = res.get("metrics", {}).get("iou_fixed", res.get("iou", 0.0))
    return float(1.0 - float(v2))


def m_profile_err(view_spec, ref_path, ref_box, bins=24, sat=0.13, v=0.74):
    png = _render_view(view_spec, "profile")
    res = json.loads(qc_compare_auto(ref_path, ref_box, png, label="profile", search=False, bins=bins))
    return float(res["profile"]["diff"]["mean_diff_px"])


# ---------------------------------------------------------------- render harness adapter (v0.8.8)

def _load_qc_render():
    """Get the API the qc_render module registered on the kernel —— only K.dsh_qc_render_api is accepted.

    The qc_render module is injected by preload (the qc_render route in config/routing.json fixes
    preload="qc,qc_render"; hand-written headless scripts must bring it along too), and its registration mounts the API
    on the kernel. The old "locate qc_render.py on the fly and exec(compile(...))" double-load fallback has been removed:
    under the domain package layout that path only loads a copy of the facade, bypassing the kernel injection, and
    could produce results inconsistent with the preloaded version (a silently wrong value is worse than an explicit failure).
    When it is missing, qc_render_views / qc_render_help return an explicit error with a hint.
    """
    K = _kernel()
    return getattr(K, "dsh_qc_render_api", None) if K is not None else None


def qc_render_views(**kw):
    """Adapter on the qc.py side: forward the whole argument package to qc_render.views (the multi-view render harness).

    Usage (tool side): blender_rt_plan(op="qc_render_views", args={views:["iso","front"], budget_s:60, ...})
    """
    api = _load_qc_render()
    if api is None:
        return _j({"ok": False, "error": "the qc_render module is unavailable: K.dsh_qc_render_api is missing (qc_render was not injected into the kernel)",
                   "hint": "headless: use preload='qc,qc_render'; GUI: use blender_rt_plan(op='qc_render_views')"})
    return api["render_views"](kw)


def qc_render_help():
    api = _load_qc_render()
    if api is None:
        return _j({"ok": False, "error": "the qc_render module is unavailable: K.dsh_qc_render_api is missing (qc_render was not injected into the kernel)",
                   "hint": "headless: use preload='qc,qc_render'; GUI: use blender_rt_plan(op='qc_render_views')"})
    return api["help"]()


def qc_dispatch(op, args=None):
    """Single entry point: the tool side calls qc_<op> (load/crop/mask/iou/profile/compare/help...)"""
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except Exception:
            args = {}
    kw = {}
    for k, v in (args or {}).items():
        if k == "args" and isinstance(v, dict):
            kw.update(v)
        else:
            kw[k] = v
    fn = qc_ops().get(str(op))
    if fn is None:
        return _j({"ok": False, "error": "unknown qc op", "op": op, "ops": sorted(qc_ops())})
    try:
        r = fn(**kw)
        return r if isinstance(r, str) else _j({"ok": True, "result": r})
    except TypeError as e:
        return _j({"ok": False, "error": "argument mismatch: %s" % e, "op": op, "given": sorted(kw), "sig_hint": qc_help()})


def qc_ops():
    return {"load": qc_load, "crop": qc_crop, "mask": qc_mask, "mask_auto": qc_mask_auto, "iou": qc_iou,
            "profile": qc_profile, "profile_diff": qc_profile_diff,
            "compare": qc_compare_auto, "compare_basic": qc_compare,
            "align_search": _align_search, "align_rotate": qc_align_rotate, "rotate_mask": _rotate_mask,
            "gif_to_png": gif_to_png, "metrics": qc_metrics, "self_check": qc_self_check,
            "robustness_check": qc_robustness_check, "mask_sweep": qc_mask_sweep,
            "resize_mask": qc_resize_mask, "write_png": write_png, "help": qc_help,
            # v0.8.8: render harness (the real implementation is in qc_render.py, this is the adapter)
            "render_views": qc_render_views, "qc_render_views": qc_render_views, "render_help": qc_render_help}


import sys as _sys
_K = _sys.modules.get("dsh_rt_kernel")
def qc_selftest():
    # QC self-test: IoU/scale/profile are all checked with **known-answer** synthetic masks (the numbers must still be right after converging onto the kit)
    import json

    def _d(x):
        return json.loads(x) if isinstance(x, str) else x

    import numpy as np
    ev = {}
    try:
        a = np.zeros((10, 10), bool)
        a[:5, :] = True            # 50 px
        b = np.zeros((10, 10), bool)
        b[:, :5] = True            # 50 px, intersection 25, union 75 => IoU = 1/3
        r = _d(qc_iou(a, b))
        ev["iou_known"] = abs(float(r.get("iou")) - (25.0 / 75.0)) < 0.002 and int(r.get("inter")) == 25 and int(r.get("union")) == 75
        m = qc_resize_mask(a, 5, 5)
        ev["resize_shape"] = tuple(np.asarray(m).shape) == (5, 5)
        prof = qc_profile(a, bins=5)
        ev["profile_len"] = len(prof) == 5
        return _j({"ok": all(x is True for x in ev.values()), "evidence": ev, "iou": r.get("iou")})
    except Exception as e:
        return _j({"ok": False, "evidence": ev, "error": "%s: %s" % (type(e).__name__, str(e)[:200])})



if _K is not None:
    _K.dsh_qc_api = _KIT.Api({"version": QC_VERSION, "dispatch": _KIT.wrap_dispatch(qc_dispatch, {"selftest": qc_selftest}), "compare": qc_compare_auto,
                     "compare_basic": qc_compare, "mask_auto": qc_mask_auto, "metrics": qc_metrics,
                     "self_check": qc_self_check, "mask_sweep": qc_mask_sweep, "load": qc_load, "crop": qc_crop, "mask": qc_mask,
                     "iou": qc_iou, "profile": qc_profile, "profile_diff": qc_profile_diff,
                     "compare_basic": qc_compare, "resize_mask": qc_resize_mask, "write_png": write_png,
                     "render_views": qc_render_views, "align_search": _align_search, "iou_pair": _iou_pair,
                     "align_rotate": qc_align_rotate, "rotate_mask": _rotate_mask,
                     "gif_first_frame": _gif_first_frame, "gif_to_png": gif_to_png,
                     "help": qc_help,
        "selftest": qc_selftest})
    _K.dsh_measure = {"aabb_err": m_aabb_err, "silhouette_iou": m_silhouette_iou,
                      "profile_err": m_profile_err}