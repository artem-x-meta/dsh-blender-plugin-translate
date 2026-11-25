# -*- coding: utf-8 -*-
"""DSH contract layer — turn "hypothesis / range / validation / evidence / gating" into a machine-checkable API.

The API hangs off the persistent kernel: K.dsh_contract_api (same convention as K.dsh_view_api / K.dsh_perf_api).

Core capabilities:
  help()                     contract quick reference
  reset()                    clear the contract (scene untouched)
  register_component(id, objects, tags, note)      component = semantic name for a group of objects
  register_connection(id, a, b, candidates, params, forbidden, confidence, evidence_required)
                             connection = relation between two components (candidate types / parameter ranges / forbidden items)
  register_envelope(id, min, max, scope, note)     envelope = allowed spatial range
  check_envelope(id)                               out-of-bounds list (read-only)
  check_interference(scope, use_bvh, limit)        AABB coarse filter + BVH fine check (read-only)
  check_interface(conn_id, mesh, samples)          gap/intrusion between two components (bbox-level legacy fields unchanged;
                                                   mesh=True appends a real mesh measurement block, additive only)
  destructive_guard(op, targets, conn_ids)         destructive operation gating (boolean/weld/merge/apply_transform)
  evidence(label, view)                            render + md5 + bookkeeping (reuses K.dsh_view_api)
  ledger() / status()                              evidence ledger / global overview
  report(path)                                     generate a Markdown report (includes verdicts and repro commands)

Hypothesis lifecycle (three-state):
  verify(conn_id, err, tolerance, identifiable, probe_err, probe_tolerance)
      external evidence + probe evidence → supported / refuted / unresolved (rules in docs/assumption-driven-modeling-cookbook.md §5)
  flip(conn_id, to, why)      flip a hypothesis (history is recorded, old verdicts are not deleted)
  advance(conn_id, status, why)  advance the state manually (proposed → testing → supported/refuted)

Assembly-level criteria (v0.9.0, all measured on the **real mesh**, no longer on the bbox):
  mate_check(conn_id, fit, nominal, tol_mm, samples, contact_max_mm, depth_eps_mm)
      mate gate: area-weighted sampling + BVH nearest point → contact area fraction / contact anchors / contact normal / per-side gap (mm)
      / penetration depth (mm) → supported / refuted / unresolved (three-state discipline: insufficient evidence forbids a binary answer)
  fit_help(fit, feature, m, d)
      assembly feature library reference (reads the assembly package assembly_features.json in runtime/py/assembly/): 9 fit features + the four asm_fit tiers
      + asm_lead lead-in chamfer + ISO 273 clearance hole + "how Blender recommends building it"
  interference_report(scope, use_bvh, limit, declared_ok, depth_eps, include_hidden)
      pairwise interference report (penetration depth mm + overlap volume fraction + severity ordering + grouping + design-intent allowlist exemption)
      — the old op check_interference is kept as is, return structure unchanged (backward compatible)

Conventions: state lives in K.dsh_contract (kept across calls); no "read-only" check ever changes the scene.
     Iron rules: empty output must be ok:false; numbers always carry units (the mm basis is converted by the scene scale_length); conclusions are three-state.
"""
import bpy, json as json, time, math as math, os

CONTRACT_VERSION = 3
DESTRUCTIVE_OPS = ("boolean_union", "weld", "merge", "join", "apply_transform")
# v0.9.0 (Procedura fusion #8): the threshold at which a verdict expires along with the geometry — center drift > 10% of the diagonal or size drift > 20%
# → the old verdict automatically degrades to unresolved (DRIFT_CENTER/SIZE_FRACTION from upstream assembly-seed.ts)
DRIFT_CENTER_FRACTION = 0.10
DRIFT_SIZE_FRACTION = 0.20

# --- v0.9.0: assembly-level thresholds (sources: the explanation block further down this file; changing a value means changing the rationale there too) ---
CONTACT_SAMPLE_CAP = 4000              # hard sampling cap (upstream CONTACT_SAMPLE_CAP=4000, same basis)
CONTACT_MIN_POINTS = 8                 # evidence floor: fewer than 8 contact points is always unresolved (upstream CONTACT_MIN_POINTS)
DEFAULT_CONTACT_DISTANCE_FRAC = 0.015  # contact distance = 1.5% × merged bbox diagonal (upstream DEFAULT_CONTACT_DISTANCE_FRAC)
FIT_TABLE = {"clearance": 0.25, "location": 0.15, "press": -0.05, "snap": 0.20}  # per-side mm
FIT_DEFAULT_CLS = "location"
FIT_DEFAULT_TOL_MM = 0.15              # default tolerance (rationale: third paragraph of the c_mate_check docstring)
MATE_DEPTH_EPS_MM = 0.2                # penetration depth allowed for in-plan contact (rationale: c_interference_report)
MATE_MAX_TRIS = 0                      # **0 = no cap (run everything by default)**; only an explicit non-zero makes it ok:false when exceeded
INSIDE_MAX_TRIS = 0                    # **0 = no cap (run everything by default)**; only an explicit non-zero reports skipped when exceeded
VOL_SAMPLES = 1200                     # Monte Carlo sample count for overlap volume (low-discrepancy sequence, deterministic)
VOL_MAX_TRIS = 0                       # **0 = no cap (run everything by default)**; only an explicit non-zero reports depth alone when exceeded
SEV_DEPTH_HIGH_MM = 2.0                # severity bands: depth
SEV_DEPTH_MED_MM = 0.5
SEV_FRAC_HIGH = 0.25                   # severity bands: volume fraction
SEV_FRAC_MED = 0.02
FEATURES_JSON_NAME = "assembly_features.json"
# All supported loaders provide __file__: normal import, preloadChunk,
# injectModule, and offline_bootstrap. A missing __file__ is an injection
# contract violation, so there is no compatibility fallback here.
_HERE = os.path.dirname(os.path.abspath(__file__))
FEATURES_JSON = os.path.join(_HERE, FEATURES_JSON_NAME)


import sys as _sys_kit
_KIT = getattr(_sys_kit.modules.get("dsh_rt_kernel"), "dsh_kit", None)
if _KIT is None:
    raise RuntimeError("contract requires the shared kernel K.dsh_kit (injected by KERNEL_BOOTSTRAP)")


_j = _KIT.j  # shared kernel (the original local implementation has been removed)
def _kernel():
    import sys
    return sys.modules.get("dsh_rt_kernel")


def _store():
    K = _kernel()
    if K is None:
        raise RuntimeError("requires the persistent kernel K (through the blender_rt_* channel)")
    if not hasattr(K, "dsh_contract"):
        K.dsh_contract = {"components": {}, "connections": {}, "envelopes": {}, "evidence": [], "log": []}
    return K.dsh_contract


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _log(action, detail):
    st = _store()
    st["log"].append({"t": _now(), "action": action, "detail": detail})
    del st["log"][:-200]


# ---------------------------------------------------------------- components / connections / envelopes

def c_reset():
    K = _kernel()
    K.dsh_contract = {"components": {}, "connections": {}, "envelopes": {}, "evidence": [], "log": []}
    return _j({"ok": True, "reset": True})
def _scope_objects(scope=None, include_hidden=False):
    out = []
    for ob in bpy.data.objects:
        if ob.type != "MESH":
            continue
        if not include_hidden and (ob.hide_render or ob.hide_viewport):
            continue
        if scope:
            if any(str(ob.name).startswith(str(s)) for s in scope):
                out.append(ob)
        else:
            out.append(ob)
    return out
def _bbox(ob):
    from mathutils import Vector
    pts = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
    xs = [p.x for p in pts]; ys = [p.y for p in pts]; zs = [p.z for p in pts]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))
def _component_objects(cid):
    st = _store()
    comp = st["components"].get(str(cid))
    if not comp:
        return []
    return [ob for ob in (bpy.data.objects.get(n) for n in comp["objects"]) if ob is not None]


__all__ = [name for name in list(globals()) if not name.startswith("__")]
