# Acceptance Checklist (for independent verifiers only)

> **Read only this file.** Do not load the whole `SKILL.md` (currently about 52k characters / 82KB ≈ 20–25k tokens) or `references/*`——
> the verifier's fixed overhead is held down precisely by this rule: one verification's input ≈ tool schema 2.8k + **this file (about 4.2k characters ≈ 1.4–1.8k)** + AGENTS 3.7k + receipt
> (for comparison: loading the whole SKILL.md is ≈27–34k —— standing up one clean verifier has a fixed cost of ≈27–34k → ≈8.6–9.0k).
> To widen the check surface, read **only the §Numeric Gates Table + Output Format** sections, and don't drag SKILL.md in along the way.

## Task Template (copy straight to the verification subagent)

You are an **independent verifier**, not the builder. Read only this file + the receipt and images I give you.

- Input: `spec`=<spec file path or expected values> | `receipt`=<gate.json path or pasted text> | `images`=<1–2 same-camera renders> | `changes`=<list of changed objects/files>
- Requirements:
  1. **Run the numeric gates yourself** (table below); taking the builder's conclusions on trust is not allowed;
  2. **Key items must switch to a different computation path** (see "Anti-Goodhart" below);
  3. Reply in **4 lines** per "Output Format"; do not restate the build history, do not re-run the whole-scene inspection;
  4. If the evidence is insufficient, write `unresolved`; forcing a binary verdict on insufficient evidence is **forbidden**.

## Numeric Gates (run by script, don't hand them to the model)

| What is verified | Call (all go through `blender_rt_plan`) | Pass criterion |
|---|---|---|
| Single-object mesh health | `op="audit_mesh", args={objects:[…], summary_only:true}` | `state=pass` (= `verdict`) and boundary / nonmanifold / degenerate / loose_verts / loose_edges all 0; for normals check `normals_state=pass` (judge **per shell**, don't just look at the aggregate `signed_volume`) |
| Dirtiest across the whole scene | `op="audit_scene", args={summary_only:true, top_k:5, self_intersect:true}` | `state=pass`; ★ **without `self_intersect:true` the self-intersection check is skipped by default ⇒ only `degraded` can be returned**, which is not a pass; otherwise look only at the worst score |
| Assembly connectivity (floaters) | `op="audit_connectivity", args={scope:"COL_Geo"}` | ★ the top level **has no** `state` —— read `gate.state=pass` (or `gate.verdict`) and `floaters=[]`; `degraded` **does not equal** pass; **don't use "component count = 1" as the criterion** (touching but unwelded is naturally multi-component) |
| Interference / overlap (triangle level) | `op="audit_interference"` / `op="audit_overlap"` | `audit_interference.volume_mm3 ≈ 0` and `verdict="refuted"`; `unresolved` **does not equal** pass (too little sampling means no verdict); `analyzed=false` ≠ no overlap; ⚠ **designed contact fits produce `pair_count ≥ 1` and `unresolved`** —— designed contacts must be whitelisted, don't use `pair_count` as an interpenetration switch; **when both sides' sources aren't given the gate records `skipped` —— skipped is not a pass (see item 4 below)** |
| **Display join overlap** | `op="audit_measure", args={objects:[…], neighbors:true}` | cross-check against the project interface table's `overlap_mm`; `axis_overlap_mm` serves as a coarse pre-filter only when the interface normal aligns with a world axis and the geometry is applicable. For rotated interfaces, measure surfaces along the real interface's local coordinates, and re-check floating/abnormal interpenetration; do not judge structural connection strength from this |
| Shape drift | `op="audit_drift"` | chamfer ≤ the agreed threshold (default basis ≈ 2.5% of the longest edge) |
| Print pre-screen | `op="print_report", args={min_mm:…, max_angle_deg:45}` | `thin_samples_total=0` and `walls_ok=true`, and check the resolution/warnings in `detail.walls.objects[]`; the conclusion is untrustworthy when the threshold is below the measurement resolution. `gate_run(preset="print")` by default checks only the active object and degrades because of that, so multiple objects must be specified one by one; this does not constitute full manufacturing certification |
| Delivery completeness | `op="deliver_verify"` | md5 manifest complete, unit box normalized, textures shipped with the package |
| UV / materials | `op="uv_stats"` / `op="material_scan"` | a UV layer exists and zero-area UV faces = 0; materials non-empty, procedural items baked |
| Form | `op="qc_render_views"` (**separately per view**) + `audit_measure` + `clear_check` | dimensions/clearance numbers meet target; for IoU see below |

When the receipt is too large, slim it down first: `summary_only:true`, `top_k:N` (measured in practice on a 40-object scene: 9,176 → 1,148 characters, verdict unchanged).

**Four interpretation traps (otherwise you will read the conclusion backwards)**:

- ★ **Three-state, not two-state**: the top-level `state` (= `verdict`) of `audit_mesh` / `audit_scene` ∈ `pass` / `fail` / `degraded`.
  **`clean=false` has two causes**: `fail` (defects really exist, look at the non-zero fields in `totals`) or `degraded` (**not fully checked / undecidable**:
  the self-intersection check was skipped (`self_intersect=false`) or threw an exception, `normals_state=unknown`, per-shell analysis exceeded the face-count cap).
  ⇒ on seeing `clean=false`, **read `state` and `reason` first**: `degraded` needs **a supplementary check** (rerun with `self_intersect=true` / look at `normals_reason`),
  and you **must not** treat it as "didn't pass" nor as "passed"; `ok=false`, `analyzed=false` likewise are not a pass.
  Also don't judge normals from the aggregate `signed_volume` alone: it **sums all shells**, so a large positive shell plus a separate small inverted shell can still be positive ⇒ look at `normals_state` and `normals_shells[]` (per-shell `state`/`nested`); **`unknown` never gets a pass** (with no other defects → `degraded`, with defects → `fail`).
- `audit_measure`'s `axis_overlap_mm` is **per-axis AABB overlap** (the receipt carries `note: "bbox level (not triangle level)"`).
  It may serve as a coarse pre-filter only when the interface normal aligns with a world axis and the geometry is applicable; rotated interfaces must be measured on the surfaces in the real interface's local coordinates.
  A fully contained floater can also yield positive overlap on all three axes, so it must be combined with connectivity and interference checks; `volume_mm3` is intersection volume and cannot stand in for interface depth or structural strength.
- `audit_mesh` reads the **unevaluated** `ob.data`: modifiers that haven't been applied don't count; assembly-level `audit_*` uses the **evaluated mesh**. Don't mix the two.
- ★ **The gate bundle (`gate_run`/`gate_plan`)'s top level looks only at the `verdict` three-state**: `ok` is `true` only when **every gate really ran and every one passed**.
  **Any gate `skipped` or `degraded` ⇒ top level `degraded` (fail takes priority)** —— `skipped` = no configured source / the gate doesn't apply
  (e.g. the assembly preset's `no_clash` was not given both sides' objects), **skipped ≠ pass**: the default `gate_run(preset="assembly")`
  judging `degraded` is **correct behavior**; to pass you must supply `overrides={gate-id:{args…}}` or write the spec yourself;
  the receipt's `coverage.all_gates_ran=false` and `skipped[]` are the self-verification of "which gates didn't run".
  Likewise **a true criterion ≠ trustworthy evidence**: when `degrade_if` hits (e.g. `print_report`'s `min_mm` below the measurement resolution
  `resolution_mm`), that gate is judged `degraded`, and the real fields inside the receipt's `echo` are the degradation evidence.

## Anti-Goodhart: what counts as "switching to a different computation path"

The same item **must not** be re-verified along the path used at build time. Criterion: after switching paths, if the build logic itself has a bug, the conclusion flips.

- Build used `Object.dimensions` (local bbox × scale, **rotation excluded**) ⇒ verify by computing the world AABB with `matrix_world @ v.co`;
- Build used the inner-loop score ⇒ verify by recomputing with an independent script/independent op, without reading the inner loop's best;
- Build used the exporter's self-check ⇒ verify with `deliver_verify` against md5 and the unit box;
- Build said "looks right" ⇒ verification must give **two** pieces of evidence: **numbers + image** (neither is optional).

## Subjective Gates (only these need an unfamiliar perspective)

"Does it look like the reference image / composition / color scheme / layout / copy": first get numbers with `qc_render_views(ref_path=…)` + `qc_compare`
(IoU / profile difference), then look at the images and draw the conclusion. **≤2 images**, do not re-render the whole scene; an image where the subject occupies <5% of the frame is judged invalid outright and must be reshot.

> ⚠ **IoU is only "silhouette coincidence in that view"**, a **necessary but not sufficient** condition. It cannot see: depth/thickness, internal features
> (panel seams / grille / lights / feature-line positions), surface tension (surface feel), other views. And "filling the silhouette" alone inflates it.
> ⇒ on seeing "IoU 0.9", **do not** judge pass directly: require at least **each of several views computed separately** + one feature-line comparison (`parts_color`) +
> `clear_check` clearance; if you find "IoU went up but the image got uglier", judge `unresolved` and point out which layer is wrong
> (envelope / station table / feature lines).

## Output Format (fixed 4 lines; anything beyond gets deleted)

```
verdict: pass | fail | unresolved
evidence: <op name + key fields + measured values> (1–3 lines, must be reproducible)
failures: <failing items ≤3: object / field / measured value / threshold>
repro: <command that reproduces the same conclusion>
```

## Self-Check (signals you have drifted)

- You are reading `SKILL.md` or `references/modeling-overview.md` ⇒ **stop**, read this file instead;
- You are restating build steps ⇒ delete them, keep only the evidence lines;
- You are about to "re-inspect the whole scene once more" ⇒ first think: can I verify only the delta (drift / change list);
- You are planning to write "should be fine" ⇒ that is `unresolved`, or go add one more piece of evidence.

## P0–P2 Current Gates (v2.6, prefer these)

| What is verified | Call | Pass criterion |
|---|---|---|
| Assembly all-against-all | `asm_scan` (manifest/scope) | read the clash/contained/float/unresolved counts and verdict; hidden_ok is a declared allowance, not interpenetration |
| Assembly gate | `asm_gate` / `gate_run` | `verdict=pass`; explain degraded/skipped/failed item by item; export_allowed only on pass |
| Assembly repair | `asm_repair(policy="safe", dry_run=true)` | look at plan/risk/blocked first; after executing, rerun asm_scan, clash=0 or explained |
| Assembly delivery | `asm_export` (merge=true) | manifest + merge_ledger + GLB/FBX/OBJ md5; the merge export gate doesn't write to disk unless it passes |
| Reference-image numbers | `img_digest → probe/measure/calib` | without calibration verdict=needs_scale; px_per_mm recomputable; mm is never guessed |
| Contour fitting | `shapesolve_solve` | best/per-view IoU/sensitivity; **must be re-verified on another path**; the objective function may not serve as acceptance |
| Same-camera resemblance | `visualreport_report` | verdict three-state; same camera/same resolution; IoU is only a necessary silhouette condition |
| Defect/baseline | `eval_run` | capture_rate/missed/false_positive/baseline_pass; missing dependency → degraded, no false pass |
| Mandatory delivery | `gate_preflight → gate_checkpoint → gate_deliver` | if a gate doesn't pass, blocked and nothing is written; degraded requires an explicit allow_degraded |

> Architecture-first: "self-written criteria" beyond the gates above count for nothing; the verifier reads only this file + the receipt, does not read SKILL.md, and does not re-run the whole scene on the builder's behalf.
