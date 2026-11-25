<!--
name: hypothesis-driven-modeling
description: Hypothesis-driven modeling methodology: use it when you need to "explicitly report unresolved instead of choosing one of two options when evidence is insufficient", when you need to translate a linguistic judgment into an executable behavior interval, when you need to flip a hypothesis with a probe, or when you need the Agent to explain "why it modeled it this way". Three layers: domain methodology / platform primitives (this plugin's tools) / delivery and acceptance SOP.
-->

# Hypothesis-Driven Modeling cookbook (three-layer skill structure)

> Structure note (from v0.8.x): this file is organized by the **three-layer skill method** (borrowing the skill layering of lurenjia-l/dsh-blender-stylized-shading: domain knowledge / platform bootstrap / delivery SOP).
> Every layer states "**when to use / what to use / what it produces / how it counts as passing**", so an AI can fetch it by trigger condition instead of reading the whole text.

## Layer 1 · Domain methodology (why it is done this way)

**When to use**: you have to choose between "the model guesses the structure for you" and "let the evidence decide the structure"; or the situation "the shape looks right but the structure has no basis" has already appeared.

- Core stance: **white-boxing is not about having the Agent explain a few more sentences**, it is "explicit hypothesis → translate into a behavior interval → the program searches and checks within the interval → evidence flips the hypothesis".
- Three-state verdict: `supported` / `refuted` / **`unresolved` (insufficient evidence is a first-class state)**; choosing one of two options while the evidence is insufficient is not allowed.
- Identifiability: when a parameter varies within its allowed range while **the external evidence does not change at all** (range≈0) → it must be reported as non-identifiable, together with a statement of which probe is needed.
- Probe first: do a probe whenever occlusion can be removed / an auxiliary measurement added; do not cover it up with confidence.
- Destructive operations get a pre-gate: Boolean/Weld/merge are forbidden while a connection is undecided.

**How it counts as passing**: every geometry decision can answer "what is the basis, and what evidence would overturn it".

## Layer 2 · Platform primitives (what to use)

**When to use**: you are in the execution phase and need concrete calls.

| What you are doing | Tool / API | Output |
|---|---|---|
| Record hypothesis and behavior interval | `blender_rt_plan(op="register_connection")` (candidates / params.range / forbidden / evidence_required) | Connection contract |
| Read-only checks (objects untouched) | `op="check_envelope" / "check_interference" / "check_interface"` | Out-of-bounds / interference / clearance results |
| Destructive gating | `op="destructive_guard"` | Allow/block + blocking detail |
| Automatic search within the interval | `blender_rt_loop` (setup/step/measure + penalize/anneal/board) | Candidate board + best parameters |
| Criterion (objective comparison) | `blender_rt_plan(op="qc_compare" / "qc_self_check" / "qc_robustness_check")` | IoU/Dice/missing-excess area/boundary distance + comparison image |
| Criterion rendering (multi-view) | `op="qc_render_views", args={views:[…], res, samples, budget_s, outdir, ref_path?}` | N PNGs + `render_views.jsonl` (one {view, ms, bytes, hash} per line) + within_budget |
| Flip and verdict | `op="verify" / "flip"` | supported/refuted/unresolved + history |
| Evidence and report | `op="evidence" / "ledger" / "report"` | images + md5 + provenance report |
| Reversible experiments | `blender_rt_txn` (mark/revert; snapshot before big changes) | Rollback point |
| Run long scripts / batches | `blender_rt_do(file=…)` / `rt_headless` / `rt_worker` | Artifacts + logs |
| Look at the frame (scene untouched) | `blender_rt_see({from, look_at, shading})` | Frame + hash |

**How it counts as passing**: every verdict is produced by the program (including unresolved), not by narrative.

## Layer 3 · Delivery and acceptance SOP (how delivery counts as finished)

**When to use**: wrapping up, handing over, or when you must give the user a trustworthy conclusion.

1. Write down the **goal and completion criteria** first (what counts as done, what it is measured with);
2. **Environment probe** (do it, do not guess): `blender_viewport(op="doctor")` channel health check, `rt_commands` integration status, `rt_perf(op="status")` engine and sampling;
3. **Execution**: use the layer 2 primitives, and keep process images/logs on record;
4. **Self-check**: `qc_self_check` (algorithm self-test) + `qc_robustness_check` (perturbation robustness) + md5 evidence for the key conclusions;
5. **Report**: give the conclusion + criterion numbers + undecided items (unresolved ones must be listed explicitly, with a clear statement of which probe is needed);
6. **Archiving and troubleshooting**: finished products go into `D:\Blender\<project>\`, QC/probes stay in the workspace; when troubleshooting, look first at `rt_perf status` / `rt_worker status` / the log path.

**How it counts as passing**: writer ≠ verifier (independent verification); every number is reproducible; undecided items have not been "averaged away".

---
# Hypothesis-Driven Modeling Cookbook (S0)

> Purpose: replace "the model starts building right away → in the end you only see the result" with an auditable loop of **hypothesis → behavior interval → program search → evidence verdict → hypothesis flip**.
> Origin: the phase-one deliverable for this repository's issue #3 (white-boxing + planner suggestions); the matching reproducible experiment is in `docs/examples/chair-backrest/`.
> Applies to: any modeling task that is "occluded / short on evidence / at risk of irreversible operations". **For simple tasks use lightweight mode** (see §1).

---

## 1. When to use it (thresholds)

| Situation | Which path |
|---|---|
| Unoccluded, single object, reversible (resize/move) | **Lightweight mode**: `blender_rt_do` + `blender_rt_see` directly, no hypothesis written |
| Occluded / insufficient evidence ("cannot see clearly but must decide") | **This cookbook**: explicit hypothesis + interval + probe plan |
| Involves Boolean / weld / merge / apply transform | **Must pass the contract first** (§6 forbidden items): none of these operations before the connection is decided |
| Multi-component assembly, many interface conventions, multi-person / multi-agent parallel work | Contract layer (S1) + object graph (S3) |

The empirical criterion for deciding "insufficient evidence" (measured in practice in this repository): **under one and the same piece of visible evidence, two different hypotheses both reach the same residual** — see the 184 / 184 in §4.

---

## 2. What a hypothesis must contain (template)

```json
{
  "id": "backrest_joint",
  "statement": "The connection between backrest and seat: is the board attached to the rear surface of the seat, or does the board have an internal tenon inserted into the seat",
  "candidates": {
    "attach": "The board is attached to the rear surface, with no internal tenon",
    "insert": "The same board + an internal tenon inserted into the seat (identical outer silhouette)"
  },
  "params": {
    "dy":        {"range": [0.000, 0.030], "unit": "m",   "meaning": "Normal offset of the board relative to the rear surface of the seat"},
    "tilt":      {"range": [-2.0, 6.0],    "unit": "deg"},
    "dz":        {"range": [-0.020, 0.020], "unit": "m"},
    "tenon_len": {"range": [0.030, 0.100], "unit": "m",   "only_for": "insert"}
  },
  "confidence": "medium",
  "forbidden_until_resolved": ["boolean_union", "weld", "apply_transform"],
  "evidence_planned": ["external_side", "external_rear", "probe_dismount_measure"],
  "flip_condition": "No parameter in the interval reaches the silhouette tolerance, or the probe reading contradicts the hypothesis → refuted, switch to the other candidate"
}
```

**Rules**

1. Write `statement` as a **decidable either-or / one-of-N**, not "it is probably ...";
2. Every parameter must have a `range` and a unit (the interval is "what may be done, how much may be changed");
3. `forbidden_until_resolved` explicitly states "what is forbidden before the decision";
4. `flip_condition` must be checkable by the program (a numeric criterion), not "if it feels wrong".

---

## 3. How to run the interval search (either option works)

**① GUI session: use the inner loop (costs no model turns)**

```text
blender_rt_loop(op="start", spec={
  "setup":   "<runs only once: build the scene / fetch the reference>",
  "step":    "<sample parameters within the interval: ns['params'] = {...}>",
  "measure": "<compare candidate against reference: ns['score']=silhouette error; ns['metrics']={...}; ns['violations']={...}>",
  "iterations": 5000, "budget_ms": 30000, "measure_every": 1, "top_k": 20, "interval": 0
})
blender_rt_loop(op="board")                        # candidate board: which parameter combinations, and their errors
blender_rt_loop(op="export", path="<host path>")     # write it out as a reusable script
```

**② Headless process: bounded blocking search (`blender_rt_headless`)**

> ⚠️ Measured in practice: `bpy.app.timers` **does not fire** under `blender -b` (0 firings within 1.2 s, measured in this repository) →
> do not use the inner loop headless, loop inside the script instead; this repository's example `run.py` works that way and produces all results in 3 s.

---

## 4. Identifiability: it is not "find the optimum and you are done"

For each parameter, collect "the minimum error over the values of that parameter" and look at the **range (max − min)**:

- large range → the evidence pins that parameter down (**identifiable**);
- range ≈ 0 → **not identifiable** under the current evidence → the program must **say so**, and must not just pick a value.

Measured in practice in this repository's chair-backrest experiment (external evidence = side view + rear view, with the seam hidden behind a shroud; 48 candidates per hypothesis):

| Parameter | Minimum external error per value | Range | Identifiable |
|---|---|---|---|
| `dy` | 0.000:476 / 0.010:184 / 0.020:485 / 0.030:974 | **790** | Yes (true value 0.010) |
| `tilt` | -2.0:184 / 6.0:495 | 311 | Yes |
| `dz` | -0.020:186 / 0.020:184 | **2** | No (flat) |
| `tenon_len` | 0.030:184 / 0.065:184 / 0.100:184 | **0** | No (flat) |

And **the two hypotheses have exactly the same external residual (attach 184 / insert 184)** → the external evidence is insufficient, and the verdict must be `unresolved`.

---

## 5. Verdict rules (three-state + probe)

```text
best_err <= tol and the key parameters are identifiable → supported (with evidence)
best_err >  tol                                         → refuted
best_err <= tol but the key parameters are not identifiable → unresolved + "what probe is needed"
several candidate hypotheses are all <= tol             → unresolved (list them all)
```

**The probe must be written as an executable action list** (non-destructive first). This example: remove the shroud + hide the seat + measure the tenon protrusion with a depth gauge.

| Stage | attach reading | insert reading | True value | Verdict |
|---|---|---|---|---|
| External view | residual 184 (same as insert) | residual 184 | — | **both unresolved** |
| Probe (depth gauge) | **0.000 m** | **0.065 m** | 0.060 m | attach **refuted** · insert **supported** |

> A probe reading is not "a more accurate image", it is **switching to a physical quantity that can decide the question**.
> In this example the image probe was still polluted by pose-estimation error (the first version hit it: in the probe view the board's position difference swamped the tenon-length difference); after switching to a depth gauge the verdict was immediately clean.

---

## 6. Forbidden items and gating (do not destroy reversibility before the decision)

| Operation | Why it is dangerous | Rule before the decision |
|---|---|---|
| `boolean_union` | Topology is rewritten, and it cannot be restored after the hypothesis flips | Forbidden (the contract layer blocks it outright) |
| `weld` / topology weld | Same as above, and hard to detect | Forbidden |
| `apply_transform` | Parametrization is lost (the interval loses its meaning) | Forbidden |
| `opt join` / merge | Components disappear, and the interface evidence is gone | `save_before` first, and it must not conflict with an "undecided connection" |

> S1 turns these three into **contract-layer gates** (not advice, but errors that get blocked), and reports diagnostics such as `Unsupported Destructive Merge` in the report.

---

## 7. provenance: every step is traceable

| Field | Actual value in this example |
|---|---|
| Hypothesis | `insert` (same-size board + internal tenon) |
| Interval | `tenon_len 0.03~0.10 m`, `dy 0~0.03 m` |
| Search | 48 external candidates + 5 probe candidates |
| Evidence | `gt_external_side.png` / `gt_external_rear.png` / `gt_probe_no_seat.png` (with md5) |
| Verdict | external `unresolved` → `supported` after the probe (reading 0.065 m, true value 0.060 m) |
| Counterexample | `attach` overturned by the probe reading of 0.000 m |
| Reproduce | `blender -b --factory-startup --python docs/examples/chair-backrest/run.py -- <outdir>` |

The report can be generated automatically: `results.md` in the example directory is produced by the script (it contains the basis for the verdict, the identifiability table and the reproduction command).

---

## 8. Pitfalls measured in practice (each one gives you a wrong conclusion that "looks right")

| # | Pitfall | Symptom | What to do |
|---|---|---|---|
| 1 | Scene changed without updating the depsgraph | In the reference image the shroud is still a 1 m cube and fills the whole frame → the mask is all True and the error is constantly 0 | `view_layer.update()` + `evaluated_depsgraph_get().update()` before rendering |
| 2 | Using `bpy.app.timers` headless | The inner loop never fires even once (0 firings measured) | Use a blocking loop headless; leave the inner loop to GUI sessions |
| 3 | The probe viewpoint is on "the wrong side" | The tenon is behind the board and is occluded when viewed from +y → both hypotheses read the same | The probe must see **the face being decided** (in this example from the -y side) |
| 4 | The occluder was not removed as well | The shroud sits exactly in front of the tenon, and the tenon is occluded in the probe view | Probe = remove the occluder + hide the seat body (restorable) |
| 5 | The measurement counts hidden objects | attach (no tenon) measures 0.07 m — that is the tenon hidden by the previous round | Measure visible objects only (filter with `hide_render / hide_viewport`) |
| 6 | Pose error pollutes the probe | In the image probe "board off by 2°" swamps "tenon off by 3 cm" | Switch to a physical quantity (depth gauge / feeler gauge), or fix the pose first and search only the internal parameters |
| 7 | The mask threshold treats the background as an object | The error is constantly 0 or constantly maximal | Turn off the viewport background when rendering (`background:false`) + threshold against the clear color |

---

## 9. Relation to later phases

| Phase | Content | Position of this cookbook |
|---|---|---|
| **S0** (this document) | Process and templates for hypothesis/interval/identifiability/probe/verdict/provenance | Already usable: zero code + one reproducible example |
| S1 | Contract layer: register Component/Connection, envelope/interference/interface checks, destructive gating, evidence ledger | Turns §2 / §6 / §7 into a machine-checkable API |
| S2 | Hypothesis lifecycle `proposed → testing → supported/refuted` + automatic flip when there is no solution + automatic report generation | Automates §5 / §7 |
| S3 | Object graph (Component/Connection/Feature) + compilation to bpy + dependency diagnostics | Upgrades the candidates and parameters of §2 into a plannable graph |

---

## 10. Minimal usage (usable today)

1. Write one hypothesis per §2 (JSON);
2. Search within the interval by either option in §3 (GUI inner loop / headless blocking);
3. Compute identifiability per §4 — put **the non-identifiable parameters into the delivery notes**;
4. Decide the three-state verdict per §5, and run a probe when needed;
5. Archive provenance + the reproduction command per §7.

> The example directory `docs/examples/chair-backrest/` contains: `run.py` (re-runnable), `results.md/json` (automatic report and raw data), `evidence/` (evidence images).

### Layer 3 supplement · Absolute scale cross-check (mandatory from v0.8.3)

**Background**: a review of the planetary engine found that the 4 key ratio deviations in the model self-check were only 0.03%–0.29%, yet the total height used 9,900 m (the officially licensed model) while the promotional figure is 11,000 m (an **11%** difference) — **ratios are completely unchanged under uniform scaling**, so ratio criteria / silhouette IoU **structurally cannot see an "absolute scale" difference**; measured in practice, a pure 11% scale difference can still be absorbed by "search alignment" by about **0.13 IoU**.

**Rule (mandatory check at delivery acceptance)**: any item involving an **absolute size** (total height / diameter / dike diameter / light column height / segment elevations, etc.) must get its own "absolute size cross-check table", stating **which scale convention is adopted**; **ratio/IoU acceptance cannot replace it**.

| Item | This model | Convention A (state the source) | Convention B (state the source) | Difference | Adopted | Basis for the verdict |
|---|---|---|---|---|---|---|
| Total height | 9,900 m | 9,900 m (officially licensed model) | 11,000 m ("The Wandering Earth 1" promotion) | 11% | A | Official assets take priority |
| … | | | | | | |

**Matching criterion conventions (from v0.8.3)**: in `qc_compare`, **`iou` = fixed alignment (the honest value)**; search alignment is reported separately in **`iou_search`** (for reference only). **A scale drift >5% raises a warning**, and `iou_search_gain >0.05` also raises a warning — when you see the warning, do not report just a single number.

**Applicability of the auto mask**: when the reference image's foreground share is >80% or <2%, auto **falls back automatically** to the threshold mode and states `satv-fallback` plus the reason in the receipt (example: a full-frame poster with 95.9% foreground → auto is not trustworthy).

## Appendix: tool applicability (v0.8.5 — when not to use them)

| Tool | Use it for | Do not use it for (the reality measured in practice) |
|---|---|---|
| blender_rt_job | Long tasks (over 5 minutes), rendering all night, batch image output | Short jobs (under 5 minutes) — using headless to get the result directly is simpler |
| blender_rt_txn | Large scenes / non-regenerable / long build pipelines (when rolling back is cheaper than rebuilding) | When rebuilding costs far less than rolling back (measured: a full rebuild takes 9–20 s and is cleaner than a snapshot rollback) |
| blender_rt_loop | When the target is scalarizable (size / silhouette IoU / profile difference) and manual tuning needs many rounds | Design-driven tasks (reference image → infer dimensions → parametric generation) — the contract layer and the inner loop have no trigger condition |
| Looking at an image (rt_see) | Immediate feedback (55–100 ms/frame, change one step and take a look) | When you need archivable / reviewable / high-fidelity images — render to a file with headless or a worker and then read the image; frequent calls crowd the main thread |
| blender_rt_plan (contract layer) | Hypothesis search under insufficient evidence, when an unresolved verdict is needed, when provenance is needed | Purely design-driven tasks whose structure is already fixed |

Having no window is a feature, not a defect: the worker is blender -b and GUI-only bpy.ops calls are unreliable → recommended posture: go through bmesh and the data API (deterministic, reproducible, zero context errors).

One-shot silhouette-fit recipe (turns manual alignment of several ratios into a single inner-loop search):

```python
# 1) reference image and crop box (once)
ref, box = '//ref/ref_all_views.png', [9, 38, 444, 545]
# 2) inner loop: search camera position and focal length so that silhouette IoU is maximal (measure uses fixed alignment, to prevent score gaming)
spec = {
  'setup':   'K.best = None',
  'step':    'ns[cam] = perturb the camera step by step (position/focal length)',
  'measure': 'ns[score] = K.dsh_measure[silhouette_iou](ns[cam], ref, box)',
  'iterations': 200, 'budget_ms': 60000, 'top_k': 5,
}
# blender_rt_loop(op=start, spec=spec) → op=board to take the best → op=export to export the script
```

Three clarifications on environment and paths (based on measurements on this machine):

1. UNC writes do not always fail silently: measured, Blender successfully writes a text file to a UNC path and it is visible from the WSL side (9 B); the conclusion depends on the environment (Windows version / permissions / 9p implementation), so do not make it absolute.
2. A double slash in Blender is a prefix relative to the current .blend: a path of the form double slash plus wsl.localhost gets resolved into a subpath under the blend directory (unreadable). Write UNC in backslash form; from v0.8.4 K.win_path() normalizes forward-slash UNC automatically, and K.stage() can serve as a fallback copy.
3. WSL environment variables are not passed into a Windows blender.exe: do not pass parameters via env (they get lost, measured), use command-line args, a mode file, or JSON inputs such as blender_rt_preset instead.

## Appendix: two Blender semantic pitfalls (from external feedback #4, each cost one round of iteration)

1. **`bpy.data.libraries.write` writes out "a library file with no scene"** — it cannot be opened with `blender -b file.blend` and cannot be rendered. **Split-part export should use** `bpy.ops.wm.save_as_mainfile(filepath=..., copy=True)` instead (`copy=True` does not change the current filepath).
2. **`transform_apply` does not scale the Bevel modifier width** — when doing "uniform normalization" you must **bake the modifier into the mesh first** (`bpy.ops.object.modifier_apply(modifier=...)`) and only then `transform_apply`, otherwise the bevel width does not change with the scaling and the finished size does not match.

## Appendix: measure template for rt_loop modeling (the second suggestion in external feedback #4)

Goal: turn "structural similarity" into a scalarizable score, so that the inner loop can search parameters automatically. Ready-made measure functions (`K.dsh_measure`):

| measure | Input | Returns |
|---|---|---|
| `aabb_err` | (obj_name, target_size) | Bounding-box size error (meters) |
| `silhouette_iou` | (view_spec, ref_path, ref_box) | **1 - IoU** (the smaller the better; fixed alignment prevents score gaming) |
| `profile_err` | (view_spec, ref_path, ref_box, bins) | Mean per-layer profile difference (pixels) |

Used as the score inside the inner loop:

```python
REF, BOX = "//ref/ref_all_views.png", [9, 38, 444, 545]
measure = "ns['score'] = K.dsh_measure['silhouette_iou']({'from':[0,-6,1],'look_at':[0,0,0.5]}, REF, BOX)"
spec = {
  "setup":   "REF, BOX = %r, %r" % (REF, BOX),
  "step":    "perturb the parameters step by step (size/angle/position)",
  "measure": measure,
  "iterations": 200, "budget_ms": 60000, "top_k": 5,
}
# blender_rt_loop(op="start", spec=spec) → op="board" to take the best → op="export" to export a reusable script
```

The discipline that goes with it: **the criterion** is re-checked with `blender_rt_plan(op="qc_compare")` (mind the convention: `iou` is fixed alignment); **before trial and error** leave a rollback point with `blender_rt_txn(op="mark")`; **long jobs** go through `blender_rt_job` (or `headless(as_job=true)` to convert automatically into a job).
