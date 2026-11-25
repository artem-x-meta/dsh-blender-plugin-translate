# -*- coding: utf-8 -*-
"""Split from gate.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403
from .plan import gate_plan
from .run import gate_run
from .selftest import gate_help, gate_selftest

def gate_preflight():
    """Pre-work health card: scene/units/available modules/gates worth running first (read-only, touches no objects)."""
    import bpy
    try:
        sc = bpy.context.scene
        objs = list(bpy.data.objects)
        meshes = [o for o in objs if o.type == "MESH"]
        tris = 0
        for o in meshes:
            try:
                tris += len(o.data.polygons)
            except Exception:
                pass
        K = _kernel()
        available = []
        if K is not None:
            for name in ("dsh_audit_api", "dsh_assembly_api", "dsh_qc_api", "dsh_gate_api",
                         "dsh_txn_api", "dsh_deliver_api", "dsh_blockout_api", "dsh_img_api"):
                available.append(name.replace("dsh_", "").replace("_api", ""))
        return _j({
            "ok": True, "op": "preflight", "version": GATE_VERSION,
            "scene": str(getattr(sc, "name", "")), "file": str(bpy.data.filepath or ""),
            "units": {"system": str(getattr(sc.unit_settings, "system", "")),
                      "scale_length": float(getattr(sc.unit_settings, "scale_length", 1.0) or 1.0)},
            "objects": len(objs), "meshes": len(meshes), "triangles": tris,
            "available_modules": available,
            "recommended": [
                {"op": "audit_scene", "args": {"summary_only": True, "self_intersect": True}, "why": "mesh baseline (is it clean)"},
                {"op": "gate_run", "args": {"preset": "assembly"}, "why": "assembly/factory gate (three-state)"},
                {"op": "asm_scan", "args": {"scope": None}, "why": "multi-part interpenetration/floating (needs the assembly module)"},
            ],
            "notes": ["write ops take the write lease; read-only ops are exempt", "run gate_checkpoint / txn.snapshot before topology changes",
                      "deliver_export(require_gate=true) can wire the factory gate in front of the export"],
            "next": "gate_checkpoint → model/repair → gate_run or gate_deliver",
        })
    except Exception as e:
        return _j({"ok": False, "op": "preflight", "error": "%s: %s" % (type(e).__name__, str(e)[:240])})


def gate_checkpoint(label=None, note=""):
    """File-level rollback point before topology changes (wraps txn.snapshot; an object-level mark does not protect against boolean/merge)."""
    K = _kernel()
    api = getattr(K, "dsh_txn_api", None) if K is not None else None
    if api is None:
        return _j({"ok": False, "op": "checkpoint",
                   "error": "K.dsh_txn_api does not exist: add txn to preload (or run blender_rt_txn first)",
                   "hint": "headless preload: preload=\"txn\""})
    try:
        r = api("snapshot", {"label": label, "note": note})
        if isinstance(r, str):
            r = json.loads(r)
        if not isinstance(r, dict):
            return _j({"ok": False, "op": "checkpoint", "error": "txn.snapshot returned an unexpected type"})
        r["op"] = "checkpoint"
        r["hint"] = "take this snapshot before topology-class changes; on failure you can blender_rt_txn(op=\"restore\", label=…)"
        return _j(r)
    except Exception as e:
        return _j({"ok": False, "op": "checkpoint", "error": "%s: %s" % (type(e).__name__, str(e)[:240])})


def gate_deliver(dir=None, objects=None, scope=None, name="model", fmt="obj",
                 spec=None, spec_path=None, preset=None, overrides=None,
                 allow_degraded=False, force=False, reason="", verify=True, **kw):
    """Pass the gate before exporting: verdict != pass (or allow_degraded not given explicitly) ⇒ blocked, no files written.

    This is the fix for "the gate exists but is not enforced": deliver_export itself can still be called standalone (for old flows),
    but this op is the one-call enforced path for weaker models / delivery flows.
    """
    if force and not str(reason or "").strip():
        return _j({"ok": False, "op": "deliver", "blocked": True,
                   "error": "force=true requires a reason (recorded in the receipt for audit)"})
    gate_spec = {"spec": spec, "spec_path": spec_path, "preset": preset, "overrides": overrides}
    try:
        gr = gate_run(**gate_spec)
        if isinstance(gr, str):
            gr = json.loads(gr)
    except Exception as e:
        return _j({"ok": False, "op": "deliver", "blocked": True,
                   "error": "gate_run failed: %s: %s" % (type(e).__name__, str(e)[:240])})
    verdict = (gr or {}).get("verdict")
    pass_ok = (verdict == "pass") or (allow_degraded and verdict == "degraded") or bool(force)
    if not pass_ok:
        return _j({"ok": False, "op": "deliver", "blocked": True, "verdict": verdict,
                   "gate": gr,
                   "error": "gate not passed (verdict=%s): not exporting" % verdict,
                   "hint": "see gate.failed/degraded/skipped; for a degraded delivery pass allow_degraded=true explicitly; to really force it, pass force=true+reason"})
    K = _kernel()
    api = getattr(K, "dsh_deliver_api", None) if K is not None else None
    if api is None:
        return _j({"ok": False, "op": "deliver", "verdict": verdict,
                   "error": "K.dsh_deliver_api does not exist: add deliver to preload"})
    try:
        dr = api("export", {"dir": dir, "objects": objects, "scope": scope, "name": name, "fmt": fmt,
                            "require_gate": False})
        if isinstance(dr, str):
            dr = json.loads(dr)
    except Exception as e:
        return _j({"ok": False, "op": "deliver", "verdict": verdict,
                   "error": "deliver_export failed: %s: %s" % (type(e).__name__, str(e)[:240]), "gate": gr})
    out = {"ok": bool(dr.get("ok") is not False), "op": "deliver", "verdict": verdict,
           "gate": gr, "delivery": dr,
           "export_allowed": pass_ok, "forced": bool(force), "allow_degraded": bool(allow_degraded)}
    if verify and dr.get("ok") is not False:
        try:
            vr = api("verify", {"path_or_dir": dir})
            if isinstance(vr, str):
                vr = json.loads(vr)
            out["verification"] = vr
            out["ok"] = out["ok"] and bool(vr.get("ok") is not False)
        except Exception as e:
            out["verification"] = {"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:200])}
            out["ok"] = False
    return _j(out)


def gate_dispatch(op, args_json):
    args = {}
    if isinstance(args_json, str) and args_json.strip():
        try:
            args = json.loads(args_json)
        except Exception as e:
            return _j({"ok": False, "error": "args is not valid JSON: %s" % str(e)[:120]})
    kw = {}
    for k, v in (args or {}).items():
        if k == "args" and isinstance(v, dict):
            kw.update(v)
        else:
            kw[k] = v
    try:
        kw = _KIT.resolve_refs(kw)   # single-step calls also support "@artifact"
    except KeyError as e:
        return _j({"ok": False, "error": "reference resolution failed: %s" % str(e)[:160]})
    ops = {"plan": gate_plan, "run": gate_run, "selftest": gate_selftest, "help": gate_help,
           "preflight": gate_preflight, "checkpoint": gate_checkpoint, "deliver": gate_deliver}
    fn = ops.get(str(op))
    if fn is None:
        return _j({"ok": False, "error": "unknown gate op", "op": op, "ops": sorted(ops)})
    import inspect
    try:
        allowed = set(inspect.signature(fn).parameters)
        unknown = sorted(set(kw) - allowed)
        if unknown:
            return _j({"ok": False, "error": "unknown parameter %s" % unknown, "op": op, "allowed": sorted(allowed)})
    except (TypeError, ValueError):
        pass
    try:
        return fn(**kw)
    except Exception as e:
        return _j({"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:220]), "op": op,
                   "help": gate_help() if op not in ("help",) else None})


_DshApi = _KIT.Api  # shared kernel (the registration line at the tail needs no change)
import sys as _sys
_K = _sys.modules.get("dsh_rt_kernel")
if _K is not None:
    _K.dsh_gate_api = _DshApi({"version": GATE_VERSION, "dispatch": gate_dispatch, "plan": gate_plan,
                               "run": gate_run, "selftest": gate_selftest, "help": gate_help,
                               "preflight": gate_preflight, "checkpoint": gate_checkpoint, "deliver": gate_deliver})
