# -*- coding: utf-8 -*-
"""Split from qc_render.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403
from .lock import render_lock
from .rig import _device_info, _device_line
from .main import qc_render_views
from .help import qc_render_help
from .selftest import qc_render_selftest
from .parts import PARTS_PALETTE

def qc_render_view_menu():
    """Plain-text quick reference (named views listed by group): copy it straight into a prompt or to a person."""
    return _j({"ok": True, "version": QC_RENDER_VERSION, "menu_text": view_menu_text(),
               "groups": [{"id": g, "label": lb} for g, lb in VIEW_GROUPS]})


def qc_render_device_info():
    """Measured render devices of the current process (no render, no setting changes) — the first stop when checking "did it quietly run on the CPU"."""
    info = _device_info()
    return _j({"ok": True, "version": QC_RENDER_VERSION, "device": info, "device_line": _device_line(info)})


def qc_render_dispatch(op, args=None):
    """Both spellings of op are accepted — engine routing strips the first 3 characters of `qc_render_<X>`, so what arrives is `render_<X>`:

        blender_rt_plan(op="qc_render_views", args={...})     → dispatch("render_views")
        blender_rt_plan(op="qc_render_help")                  → dispatch("render_help")
        blender_rt_plan(op="qc_render_selftest", args={...})  → dispatch("render_selftest")
        blender_rt_plan(op="qc_render_catalog")               → dispatch("render_catalog")
        blender_rt_plan(op="qc_render_device_info")           → dispatch("render_device_info")
        blender_rt_plan(op="qc_render_lock", args={...})      → dispatch("render_lock")   # v0.9.1 E1

    Pitfall (fixed in v0.8.11): the old dict only registered "render_views", so the
    `op="qc_render_help"` written in docs/operation-tutorial.md actually kept landing on unknown op (what really arrives is
    "render_help") — the render_* aliases are filled in here, and the old spellings (views/render_views/qc_render_views) are untouched.
    Arguments tolerate a JSON string / one more wrapper of {"args": {...}} (following the existing unwrapping convention of qc_render_views).
    v0.9.1 (B1/B2): dispatch **still returns str** (the engine contract is unchanged); for a dict go through a _DshApi call (api("render_views", {...})).
    """
    import inspect
    ops = {"views": qc_render_views, "render_views": qc_render_views, "qc_render_views": qc_render_views,
           "help": qc_render_help, "render_help": qc_render_help,
           "selftest": qc_render_selftest, "render_selftest": qc_render_selftest,
           "catalog": qc_render_view_catalog, "views_catalog": qc_render_view_catalog,
           "render_catalog": qc_render_view_catalog, "render_views_catalog": qc_render_view_catalog,
           "view_menu": qc_render_view_menu, "render_view_menu": qc_render_view_menu,
           "device_info": qc_render_device_info, "render_device_info": qc_render_device_info,
           # ---- v0.9.1 (E1): render lock (all three spellings render_lock / lock / qc_render_lock are accepted)
           # engine.mjs's render_* branch does dispatch(op.slice(7)), so op="render_lock"→"lock",
           # op="render_status"→"status", op="qc_render_lock"→"render_lock" all need a landing spot.
           "render_lock": render_lock, "lock": render_lock, "qc_render_lock": render_lock,
           "status": render_lock, "render_status": render_lock}
    fn = ops.get(str(op))
    if fn is None:
        return _j({"ok": False, "error": "unknown qc_render op", "op": op, "ops": sorted(ops)})
    # Whether to feed arguments is decided by the signature: **no more "retry on TypeError"** — a TypeError thrown mid-render would be retried (rendering twice)
    try:
        params = inspect.signature(fn).parameters
        wants = any(p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) for p in params.values())
    except Exception:
        wants = True
    try:
        if not wants:
            return fn()
        return fn(_unpack_args(args) if args is not None else {})
    except Exception as e:
        return _j({"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:200]), "op": op})


_DshApi = _KIT.Api  # shared kernel (the trailing registration lines need no change)
import sys as _sys
_K = _sys.modules.get("dsh_rt_kernel")
if _K is not None:
    _K.dsh_qc_render_api = _DshApi({
                            "version": QC_RENDER_VERSION, "dispatch": qc_render_dispatch,
                            "render_views": qc_render_views, "help": qc_render_help,
                            "selftest": qc_render_selftest,
                            # added in v0.8.11 (additions only):
                            "view_catalog": qc_render_view_catalog, "view_menu_text": view_menu_text,
                            "view_menu": qc_render_view_menu, "resolve_view_names": resolve_view_names,
                            "device_info": qc_render_device_info, "parts_palette": PARTS_PALETTE,
                            # added in v0.9.1 (additions only):
                            "render_lock": render_lock, "lock": render_lock,
                            "view_menu_full_text": view_menu_full_text, "vt_options": _vt_options,
                            "default_views_fallback": list(DEFAULT_VIEWS_FALLBACK),
                            "default_views_legacy": list(DEFAULT_VIEWS_LEGACY)},
                           default_op="render_views")
