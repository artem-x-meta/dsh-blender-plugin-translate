# -*- coding: utf-8 -*-
"""Split from contract.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403
from .checks import c_check_envelope, c_check_interface, c_check_interference, c_destructive_guard, c_register_component, c_register_connection, c_register_envelope
from .fingerprint import c_advance, c_evidence, c_fingerprint, c_flip, c_ledger, c_report, c_status, c_verify
from .mate import c_mate_check
from .fit import c_fit_help, c_help, c_interference_report



def c_dispatch(op, args=None):
    """Single entry point: the tool side sends {op, args}, dispatching happens by parameter name here (args may be wrapped in another dict)."""
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
    fn = c_ops().get(str(op))
    if fn is None:
        return _j({"ok": False, "error": "unknown contract op", "op": op, "ops": sorted(c_ops())})
    try:
        return fn(**kw)
    except TypeError as e:
        return _j({"ok": False, "error": "parameter mismatch: %s" % e, "op": op, "given": sorted(kw),
                   "sig_hint": c_help()})


def c_ops():
    return {"reset": c_reset, "help": c_help, "status": c_status,
            "register_component": c_register_component, "register_connection": c_register_connection,
            "register_envelope": c_register_envelope,
            "check_envelope": c_check_envelope, "check_interference": c_check_interference,
            "check_interface": c_check_interface, "destructive_guard": c_destructive_guard,
            "evidence": c_evidence, "ledger": c_ledger, "report": c_report,
            "verify": c_verify, "flip": c_flip, "advance": c_advance,
            "fingerprint": c_fingerprint,
            "mate_check": c_mate_check, "fit_help": c_fit_help,
            "interference_report": c_interference_report}


import sys as _sys
_K = _sys.modules.get("dsh_rt_kernel")
def c_selftest():
    # contract-layer self-test: reset -> register a real component -> status is readable -> reset (the registry can take and clear)
    import json

    def _d(x):
        return json.loads(x) if isinstance(x, str) else x

    import bpy
    import bmesh as _bm
    ev = {}
    nm = "__dsh_ct_cube"
    try:
        c_reset()
        me = bpy.data.meshes.new(nm)
        ob = bpy.data.objects.new(nm, me)
        bpy.context.scene.collection.objects.link(ob)
        bm = _bm.new()
        _bm.ops.create_cube(bm, size=1.0)
        bm.to_mesh(me)
        bm.free()
        r = _d(c_register_component("cube1", objects=[nm], tags=["selftest"]))
        ev["register_ok"] = isinstance(r, dict) and r.get("ok") is not False
        st = _d(c_status())
        ev["status_dict"] = isinstance(st, dict)
        ev["components_counted"] = int(st.get("components") or 0) >= 1
        c_reset()
        ev["reset_ok"] = True
        return _j({"ok": all(v is True for v in ev.values()), "evidence": ev})
    except Exception as e:
        return _j({"ok": False, "evidence": ev, "error": "%s: %s" % (type(e).__name__, str(e)[:200])})
    finally:
        o = bpy.data.objects.get(nm)
        if o is not None:
            me2 = o.data
            bpy.data.objects.remove(o, do_unlink=True)
            if me2 is not None and me2.users == 0:
                bpy.data.meshes.remove(me2, do_unlink=True)



if _K is not None:
    _K.dsh_contract_api = _KIT.Api({
        "dispatch": _KIT.wrap_dispatch(c_dispatch, {"selftest": c_selftest}),
        "version": CONTRACT_VERSION,
        "reset": c_reset, "help": c_help, "status": c_status,
        "register_component": c_register_component, "register_connection": c_register_connection,
        "register_envelope": c_register_envelope,
        "check_envelope": c_check_envelope, "check_interference": c_check_interference,
        "check_interface": c_check_interface,
        "destructive_guard": c_destructive_guard,
        "evidence": c_evidence, "ledger": c_ledger, "report": c_report,
        "verify": c_verify, "flip": c_flip, "advance": c_advance,
        "fingerprint": c_fingerprint,
        "mate_check": c_mate_check, "fit_help": c_fit_help,
        "interference_report": c_interference_report,
        "selftest": c_selftest})

# ---- v0.9.1 (93-B1/B2): make the API callable (swap in a dict subclass instance that returns parsed objects) ----
# Background: K.dsh_x_api used to be a plain dict → calling api(args) in-process raised TypeError: 'dict' object is not callable;
# and dispatch returned a JSON string, so callers had to json.loads it themselves.
# Now: api("op", {…}) or api({…}) → dict; api["dispatch"](op, json_str) still returns str (the engine contract is unchanged).
# Note: dict is a static type, so __class__ cannot be assigned on an existing instance (TypeError in practice); hence a new instance.
_DshApi = _KIT.Api  # shared kernel (the registration line at the end needs no change)
import sys as _sys_api
_K_api = _sys_api.modules.get("dsh_rt_kernel")
if _K_api is not None and isinstance(getattr(_K_api, "dsh_contract_api", None), dict) \
        and not isinstance(getattr(_K_api, "dsh_contract_api", None), _DshApi):
    _K_api.dsh_contract_api = _DshApi(_K_api.dsh_contract_api)
