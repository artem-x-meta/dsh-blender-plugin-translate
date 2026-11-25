# -*- coding: utf-8 -*-
"""motion dispatch/reset + kernel API registration (entry surface preserved)."""
from ..common import *  # noqa: F401,F403
from ..infer import motion_infer_axis, motion_joint, motion_joints
from ..measure import motion_measure
from ..urdf import motion_export_urdf
from ..usda import motion_export_usda
from .joints import motion_help, motion_status
from .selftest import motion_selftest


# ============================================================ dispatch

def motion_reset():
    K = _kernel()
    if K is None:
        return _j({"ok": False, "error": "persistent kernel K required"})
    K.dsh_motion = {"joints": {}, "exports": [], "log": [], "seq": 0}
    return _j({"ok": True, "op": "reset", "note": "only clears K.dsh_motion (does not touch the scene, does not delete files)"})


def motion_dispatch(op, args=None):
    """Unified entry: the tool side sends {op, args}; a nested {"args": {...}} is unwrapped too (same convention as the contract layer)."""
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
    fn = motion_ops().get(str(op))
    if fn is None:
        return _j({"ok": False, "error": "unknown motion op", "op": op, "ops": sorted(motion_ops())})
    try:
        return fn(**kw)
    except TypeError as e:
        return _j({"ok": False, "error": "argument mismatch: %s" % str(e)[:200], "op": op,
                   "given": sorted(kw), "sig_hint": motion_help()})
    except Exception as e:
        return _j({"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:200]), "op": op,
                   "traceback": traceback.format_exc()[-800:]})


def motion_ops():
    return {"joint": motion_joint, "joints": motion_joints, "infer_axis": motion_infer_axis,
            "measure": motion_measure, "export_urdf": motion_export_urdf,
            "export_usda": motion_export_usda, "status": motion_status, "help": motion_help,
            "selftest": motion_selftest, "reset": motion_reset}


import sys as _sys
_K = _sys.modules.get("dsh_rt_kernel")
if _K is not None:
    _K.dsh_motion_api = _KIT.Api({"version": MOTION_VERSION, "dispatch": motion_dispatch,
                         "joint": motion_joint, "joints": motion_joints,
                         "infer_axis": motion_infer_axis, "measure": motion_measure,
                         "export_urdf": motion_export_urdf, "export_usda": motion_export_usda,
                         "status": motion_status, "help": motion_help,
                         "selftest": motion_selftest, "reset": motion_reset,
                         "ops": motion_ops})

# ---- v0.9.1 (93-B1/B2): make the API callable (switch to a dict subclass instance that returns parsed objects) ----
# Background: K.dsh_x_api used to be a plain dict → in-process api(args) raised TypeError: 'dict' object is not callable;
# and dispatch returned a JSON string, so callers had to json.loads themselves.
# Now: api("op", {…}) or api({…}) → dict; api["dispatch"](op, json_str) still returns str (engine contract unchanged).
# Note: dict is a static type, so __class__ cannot be assigned on an existing instance (TypeError measured in practice); swap in a new instance instead.
_DshApi = _KIT.Api  # shared kernel (the tail registration line needs no change)
import sys as _sys_api
_K_api = _sys_api.modules.get("dsh_rt_kernel")
if _K_api is not None and isinstance(getattr(_K_api, "dsh_motion_api", None), dict) \
        and not isinstance(getattr(_K_api, "dsh_motion_api", None), _DshApi):
    _K_api.dsh_motion_api = _DshApi(_K_api.dsh_motion_api)
