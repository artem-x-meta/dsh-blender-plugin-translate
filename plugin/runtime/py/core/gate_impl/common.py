# -*- coding: utf-8 -*-
"""DSH spec-driven gate pack (v0.9.6 · field feedback #3) — turns "rewriting the gates for every project" into one spec.

Field background: in one assembly modeling job with 95 objects / 3.05 M faces the author wrote three scripts,
interference / redcheck / selfint_diag, about 600 lines, to do the gates. This belongs in the plugin:
**criteria come from the spec file, the plugin handles execution and evidence gathering**.

spec form (JSON or a .py module, pick one):
    {"name":"MK1","units":"mm","tolerance_mm":3.0,
     "gates":[
       {"id":"mesh",    "op":"audit_scene",        "args":{"summary_only":true,"top_k":5,"self_intersect":true},
        "pass_if":"clean == True"},
       {"id":"floaters","op":"audit_connectivity", "args":{"scope":"COL_Geo"},
        "pass_if":"gate['verdict'] == 'pass'"},
       {"id":"clash",   "op":"audit_interference", "args":{"objects_a":["Body"],"objects_b":["Lid"]},
        "pass_if":"verdict == 'refuted'"},
       {"id":"print",   "op":"print_report",       "args":{"min_mm":2.0},
        "pass_if":"thin_samples_total == 0 and walls_ok == True"}
     ]}
.py form: the module provides SPEC = {...} (or module-level NAME/UNITS/TOLERANCE_MM/GATES).

**Three states, not two**: each gate's result is pass / fail / degraded / error, plus a fourth "did not run" state, skipped;
the total verdict = any fail/error → fail; otherwise any degraded **or skipped** → degraded; otherwise pass.
@@ok@@ **is true only when verdict==pass** — a lesson from the field: "degraded looks too much like green", so always read @@verdict@@ at the top level, never @@ok@@.

**v3 tightening (the Lead rejected "pass + skipped = pass")**: `skipped` (no configured source / the gate does not apply) **is no longer invisible** —
as soon as one gate in the pack is skipped the top level is `degraded` with `ok=false`. Reason: `no_clash` in the assembly preset is skipped by default,
and the old rule let a healthy scene where "interference was never measured" come out green; **skipped ≠ pass, and the bar must not be lowered for a "healthy default preset"**.
There is only one way to get pass: **every gate really ran and every one passed** (add `overrides={gate_id:{args…}}` to the preset, or write your own spec).
"Default with no configured interference source ⇒ top level degraded" is **correct behaviour**, not a bug.

**The three states are not always at the top level (v0.9.6 review fix)**: `audit_connectivity`'s top-level `ok` only means "the analysis finished";
the gate conclusion lives in the **nested `gate`** (`gate.state` / `gate.verdict`) — there is no top-level `state` to read, so the old form
`pass_if="state == 'pass'"` makes that gate `error` outright. The correct form is `pass_if="gate['verdict'] == 'pass'"`
(the verified three-state the receipt itself provides). `_status_of` also honours the nested three-state, so "not analyzed / not confirmed ⇒ degraded" is neither
pressed down to fail by pass_if nor lifted to pass (`degraded ≠ pass`). The domain name `unresolved` (interference "insufficient evidence")
likewise reads as degraded.

**skipped is a fourth kind of "result" (v0.9.6; v3 tightens the aggregation rule)**: a gate may declare `skip_if_missing` (groups of "candidate key names or") —
when not one key of a group is given, that gate records `state=skipped` (**not configured / not applicable ⇒ did not run**). It does **not** join the per-gate naming of fail/degraded,
but **it pushes the whole pack to degraded** (`_aggregate`: any skipped or degraded ⇒ degraded, fail wins), and it always appears explicitly in
the receipt's `skipped[]` and `coverage` (`skipped ≠ pass`: a gate that did not run must never be read as green). Typical example:
`audit_interference / audit_overlap` are **pairwise** operators, and a preset cannot know "which two parts to compare", so `no_clash` in the assembly preset
is skipped by default — hence **the top level of the default assembly preset is degraded** (correct; not a bug); to really judge it, write a spec that provides
`objects_a`/`objects_b`, or `gate_run(preset="assembly", overrides={"no_clash":{...}})` —
**it is pass only when all three gates really ran and all passed**.

**degrade_if**: when a gate's criterion is true but **the evidence itself is untrustworthy**, use `degrade_if` (also a restricted expression) to demote that gate —
typically the print preset: `walls_ok=true` only says "no thin walls were measured", and when `min_mm` is below this mesh's measurement resolution that statement
**means nothing** (`print_walls` only writes it into the per-object `detail.walls.objects[].warning`/`resolution_mm`, and the top level has none of those fields).
The print preset now uses `degrade_if = params['min_mm'] < detail['walls']['objects'][0]['resolution_mm']` to read **real fields** ⇒
when the resolution is untrustworthy that gate is `degraded` (no false pass); `echo=[…]` brings these real readings (resolution / min_mm / warning) into the receipt, so it is auditable.

@@pass_if@@ is a **restricted expression** (ast allowlist: comparisons, booleans, arithmetic, attributes/subscripts, min/max/len/abs/round/all/any/sum);
variables are resolved from the top-level fields of that gate's receipt — whatever fields you write, the receipt returns **only those fields** (slimming built in). `degrade_if` uses **the same**
restricted expressions and the same variable resolution; `echo` takes real fields as evidence through dot paths (`detail.walls.objects.0.resolution_mm`).
"""
import ast as ast
import hashlib
import json as json
import os as os
import sys
import time as time

import bpy as bpy



import sys as _sys_kit
_KIT = getattr(_sys_kit.modules.get("dsh_rt_kernel"), "dsh_kit", None)
if _KIT is None:
    raise RuntimeError("gate needs the shared kernel K.dsh_kit (injected by KERNEL_BOOTSTRAP)")


def _kernel():
    """There is no K in the module namespace (K lives on the dsh_rt_kernel module) — the same lookup as sculpt.py / uv_tools.py."""
    return sys.modules.get("dsh_rt_kernel")

GATE_VERSION = 3   # 3 (v0.9.6 final integration): **any skipped/degraded ⇒ top level degraded** (the old pass+skipped=pass rule
                   #   was rejected by the Lead) + gate.degrade_if / gate.echo (untrustworthy resolution ⇒ degraded, no false pass);
                   #   2 (v0.9.6 review fix): skipped state + gate.skip_if_missing + gate_run(overrides=) +
                   #   receipt coverage / nested three-state (audit_connectivity's gate.verdict)

# plan-level op → (module API attribute in the kernel, that module's sub-op)
OP_MAP = {
    "audit_scene": ("dsh_audit_api", "scene"),
    "audit_mesh": ("dsh_audit_api", "mesh"),
    "audit_connectivity": ("dsh_audit_api", "connectivity"),
    "audit_interference": ("dsh_audit_api", "interference"),
    "audit_overlap": ("dsh_audit_api", "overlap"),
    "audit_gate": ("dsh_audit_api", "gate"),
    "audit_drift": ("dsh_audit_api", "drift"),
    "audit_duplicates": ("dsh_audit_api", "duplicates"),
    "print_report": ("dsh_print_api", "report"),
    "print_walls": ("dsh_print_api", "walls"),
    "uv_stats": ("dsh_uv_api", "stats"),
    "material_scan": ("dsh_material_api", "scan"),
    "fix_repair": ("dsh_fix_api", "repair"),
    "motion_measure": ("dsh_motion_api", "measure"),
    "sweep_analyze": ("dsh_sweep_api", "analyze"),
    "deliver_verify": ("dsh_deliver_api", "verify"),
    "audit_measure": ("dsh_audit_api", "measure"),
    "human_base": ("dsh_human_api", "base"),
    "human_measure": ("dsh_human_api", "measure"),
    "human_head": ("dsh_human_api", "head"),
    "human_spec": ("dsh_human_api", "spec"),
    "audit_file_mesh": ("dsh_audit_api", "file_mesh"),
    "interference_report": ("dsh_contract_api", "interference_report"),
    "audit_clash_all": ("dsh_assembly_api", "scan"),
    "asm_scan": ("dsh_assembly_api", "scan"),
    "asm_gate": ("dsh_assembly_api", "gate"),
}
ALLOWED_FUNCS = {"min": min, "max": max, "len": len, "abs": abs, "round": round,
                 "all": all, "any": any, "sum": sum, "float": float, "int": int, "str": str}

# The three "packs" hand-written in the field, made into presets (usable directly as gate_run(preset="…"))
PRESETS = {
    "assembly": {
        "name": "assembly", "units": "mm", "tolerance_mm": 3.0,
        "gates": [
            # (v0.9.6 review fix): **self_intersect=true is mandatory** — audit_scene skips the self-intersection check by default,
            # and the new rule honestly reads "check skipped" as degraded/clean=false ("not checked" must not read as "no problem"). Without this line
            # even a perfectly healthy scene cannot get pass.
            {"id": "mesh_health", "op": "audit_scene",
             "args": {"summary_only": True, "top_k": 5, "self_intersect": True},
             "pass_if": "clean == True",
             "note": "whole-scene mesh audit. self_intersect=true is a **prerequisite of the gate**: the default (false) honestly yields degraded (clean=false)"},
            # (v0.9.6 review fix): read the **verified three-state of the receipt's nested gate** — audit_connectivity has no top-level
            # state/verdict (the top-level ok only means "the analysis finished"), so writing state == 'pass' always errors.
            {"id": "no_floaters", "op": "audit_connectivity", "args": {},
             "pass_if": "gate['verdict'] == 'pass'",
             "note": "assembly-level connectivity gate: it judges 'some component touches none of the other components' (reads the real three-state of the receipt's nested gate)."
                     "In a single-part / single-connected-component scene this criterion **cannot hold** (receipt components[].evidence=single-body) —"
                     "for shell fitting / interpenetration inside one part use audit_mesh(island_split=true); do not use the assembly gate as a single-part gate."
                     "not analyzed / not confirmed ⇒ degraded (pass_if does not lift it to pass)"},
            # (v0.9.6 review fix; v3 tightens the aggregation rule): audit_interference is a **pairwise** operator
            # (a/b or objects_a/objects_b or file_a/file_b), and a preset cannot know the part pairs ⇒ empty args always error.
            # So skip_if_missing is declared here: no configured source ⇒ state=skipped (listed explicitly in the receipt's skipped[]/coverage).
            # v3: skipped **pushes the whole pack to degraded** — therefore **the top level of the default assembly preset is degraded, ok=false**
            # (correct behaviour: interference never measured must not read as green); to get pass both sources must be supplied.
            {"id": "no_clash", "op": "audit_interference", "args": {},
             "skip_if_missing": [["a", "objects_a", "file_a"], ["b", "objects_b", "file_b"]],
             "pass_if": "verdict == 'refuted'",
             "note": "cross-part interference needs **both sources**: refuted=interference provably absent (pass) / supported=real interference (fail) / "
                     "unresolved=insufficient evidence (degraded). With no configured source this gate is skipped (not checked, not passed;"
                     "from v3 on skipped pushes the top level to degraded) —"
                     "to really judge: gate_run(preset=\"assembly\", overrides={\"no_clash\":{objects_a:[…],objects_b:[…]}}),"
                     "or write your own spec"},
        ],
    },
    "print": {
        "name": "print", "units": "mm", "tolerance_mm": 1.0,
        "gates": [
            # Same defect class (v0.9.6 review fix): the old pass_if referenced thin_samples /
            # resolution_mm / min_mm, which do not exist in the receipt ⇒ that gate always errored. Changed to print_report's real top-level fields:
            #   thin_samples_total=number of samples across all objects below min_mm; walls_ok=per-object ok (including "the ray did not hit").
            # (v3 · final integration): **judging only walls_ok gives a false pass** — a coarse mesh (voxel/low-poly) may have a measurement
            # resolution orders of magnitude larger than min_mm, and then "no thin walls were measured" is meaningless: print_walls only writes that into the per-object
            # warning/resolution_mm, where the top-level pass_if cannot see it. ⇒ add degrade_if reading the **real fields**
            # (params.min_mm vs detail.walls.objects[0].resolution_mm): untrustworthy resolution ⇒ that gate is degraded
            # (not fail, not pass); echo brings the three real readings into the receipt for auditing.
            {"id": "walls", "op": "print_report", "args": {"min_mm": 2.0, "scope": "ACTIVE"},
             "pass_if": "thin_samples_total == 0 and walls_ok == True",
             "degrade_if": ("params['min_mm'] < detail['walls']['objects'][0]['resolution_mm']"
                            " or len(warnings) > 0"),
             "echo": ["params.min_mm", "detail.walls.objects.0.resolution_mm",
                      "detail.walls.objects.0.warning", "warnings",
                      "params.bed_mode", "params.bed_level_mm"],
             "note": "manufacturing gate: the number of samples with wall thickness < min_mm must be 0, **and that conclusion must be trustworthy**. The resolution reading is on the per-object "
                     "detail.walls.objects[].warning / resolution_mm (the top level has no such field) ⇒ degrade_if reads them directly:"
                     "when min_mm is below this mesh's measurement resolution it judges degraded (the top level turns degraded, not false green);"
                     "since v1.0.5 (issue #14) the overhang side works the same way: a non-empty top-level warnings[] (print_overhang's bed_warning — "
                     "the bed plane cannot be judged reliably, so a real overhang may be written off as lying on the bed) also judges degraded."
                     "It judges the active object (scope=ACTIVE, objects[0]); for multiple objects/resolutions write your own spec and judge per object"},
        ],
    },
    "delivery": {
        "name": "delivery", "units": "mm", "tolerance_mm": 1.0,
        "gates": [
            # Same defect class: the old pass_if "zero_area_faces == 0" names a field that does not exist (uv_stats' top level has only
            # ok/objects/note; zero-area UV faces are in objects[].degenerate_uv_faces) ⇒ that gate always errored.
            {"id": "uv", "op": "uv_stats", "args": {}, "pass_if": "ok == True",
             "note": "uv_stats top-level ok = per object 'has a UV layer and zero-area UV faces = 0' (details in objects[].degenerate_uv_faces)."
                     "scope defaults to ACTIVE ⇒ the delivery gate needs the active object selected first"},
            {"id": "materials", "op": "material_scan", "args": {}, "pass_if": "count > 0",
             "note": "material_scan raises straight away when an object has no material (it does not return count) ⇒ that gate errors; run material_build/apply first."
                     "scope defaults to ACTIVE"},
        ],
    },
}



_j = _KIT.j  # shared kernel (the former local implementation has been removed)
def _md5_text(t):
    return hashlib.md5(t.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- spec parsing



__all__ = [name for name in list(globals()) if not name.startswith("__")]
