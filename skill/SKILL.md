---
name: blender-modeling
description: Blender modeling and delivery tutorial (v3.0.6, GUI-first, headless as backup) — first pick the shape by the decision tree (faceted hard surface / smooth hard surface / organic / repeated array / boolean), then run the pipeline (freeze the spec → scene preparation → blockout → rough shape refinement → modifier stack → cleanup → assembly/acceptance check → delivery). Covers reference-image measuring (img_digest/probe/measure/calib), headless multi-view contour fitting (shapesolve), assembly scan/manifest/merge/repair/gate/export (asm_*), blockout and Seedance reference packs (blockout_*, including 4 views and turntable MP4), same camera position QC (visualreport_report), defect injection evaluation (eval_run), interactive headless sessions (worker see/watch, rt_do/rt_see session) and mandatory gates (gate_/deliver_export require_gate). Used for making 3D objects, reconstructing from a reference image, measuring proportions, assembly health checks, fixing interpenetration/floating, batch blockouts, delivery export and acceptance checks.
license: MIT (merged from RobLe3/cc-blender-skill and arjun988/blender-skills, see NOTICE.md)
---

# Blender Modeling Pipeline

> **v3.0.6 · 2026-11-05**: matching plugin dsh-blender-plugin v3.0.6, 15 model tools, plan channel 34 families / 228 ops, addon v1.11 / protocol 11. **GUI-first by default**: open GUI Blender + Connect first; headless is the backup path (GUI unavailable/batch/long jobs), but headless can also rt_see, and can likewise "change one step, look at one step".
> Older notes under v2/v3/v7 recording "which section was added in which measured-in-practice pass" are no longer written in the body; for tracing, see CHANGELOG. Below only the **currently valid framing** is written.

Decide the shape first, then run the flow, and look after every change. **Do not write the whole model in one go and only come back to look afterwards** — every step needs visual or numeric evidence.

## 0. Local tools and channel semantics (read first, this decides how you write code)

### 0.1 Current tool surface (15 model tools)

| Tool | When to use | Key point |
|---|---|---|
| blender_rt_see | Look at the picture | Uses the viewport when GUI is available; **when GUI is absent/a session is passed it automatically goes to the persistent worker's Workbench offscreen**, 50–150 ms; giving from/look_at goes to a custom view without touching the user's viewport |
| blender_rt_do | Change one step, look once | Persistent kernel K; when a session is passed it does exec+see inside the same headless worker; auto-degrades when GUI is unreachable; not an async job |
| blender_rt_watch | Decide "did it move / is it right" | GUI time-window sampling; passing session goes to a headless frame sequence (per-frame hash + at most 6 frame images), supports frames/frame range/animation default range |
| blender_rt_loop | Parameter-search inner loop | GUI timers or a synchronously blocking inner loop with target=session; after convergence you must switch channels (render/measure/assembly gate) to re-verify |
| blender_rt_worker | Hot headless session | start/preload/warmup/exec/see/watch/reset/status/stop/restart; after preload you can call K.dsh_*_api directly; idle TTL default 15 min |
| blender_rt_headless | Batch/heavy work | Standalone blender -b; preload/outdir/args/attach_images/shots; long jobs go as_job; does not occupy the GUI |
| blender_rt_job | Extra-long jobs | start/status/wait/collect/kill; a timeout is not a failure, collect by id |
| blender_rt_txn | Rollback | Object-level mark/revert does not include topology; use a file-level snapshot before topology changes |
| blender_rt_plan | Contract layer + judging/acceptance check/export/modeling | op=catalog to look up 34 families / 228 ops first; passing session="auto" auto-starts a headless worker per family and runs synchronously, without depending on the GUI |
| blender_rt_perf | Render performance | analyze/apply/revert; persistent_data etc. |
| blender_rt_opt | Object slimming | analyze/join safe merge; zero geometry loss |
| blender_rt_preset | Recipe library | save/list/get/apply/delete/export/import |
| blender_rt_cmd / blender_rt_commands | addon command passthrough/capability lookup | Only commands that need the GUI addon go here; when unsure, commands first |
| blender_viewport | Channel operations | status/doctor/start/stop/restart/launch/lease/release; write ops pass the lease |

**Hard rules**:
1. **Look up the catalog first, do not guess ops**: blender_rt_plan(op="catalog"); single family args={family:"audit"}; operator details <family>_help. A misspelled op returns did_you_mean, a wrong parameter name returns "unrecognized parameter".
2. **Write operations must pass the write lease** (blender_viewport op=lease/who/release); read-only ops are exempt; with several sessions in parallel you must declare the write scope first.
3. **Read the receipt's verdict first, not ok**: gate/audit/asm/visualreport/eval are all pass|fail|degraded three-state; degraded ≠ pass; ok only means "finished running".
4. **Numbers must be recomputable**: dimensions, px_per_mm, bbox, md5, IoU must carry their source; without calibration you may not treat pixels as mm.
5. **In headless prefer bpy.data/bmesh, use bpy.ops with care**: GUI-style ops that depend on screen/context may fail in a headless session; if you must use them, verify in small steps first.

### 0.2 GUI-first (default): two interactive loops

- **GUI loop** (a person in front of Blender): rt_do / rt_see / rt_watch go through the addon, ~50–100 ms/step.
- **Headless loop** (nobody watching the picture): rt_worker start + preload, then rt_do(session="s1", see=true) / rt_see(session="s1"). See synchronously after every exec, the image comes straight back to the model; scene and K persist across calls. **This is a synchronous interaction, not "submit a job — wait for a round".**
- **plan headless**: blender_rt_plan(op="asm_scan", args={...}, session="auto"); the first cold start is about 2 s, then the worker is reused.
- **Open the GUI first by default**; only when nobody watches the picture/the GUI is unavailable do you use the headless loop. Headless must also be able to "change one step and immediately get an image/number", do not degrade into batch processing with no feedback for a long time.

### 0.3 Units and scale (decide first, then model)

- Scene units default to 1 BU = 1 m = 1000 mm (unit_settings.scale_length=1); read scene.unit_settings before writing code.
- Write all dimensions in mm into the spec, then convert uniformly; do not switch between m and mm.
- Assembly manifest / blockout / asm_scan all use the mm convention; confirm the units field before export.
- When the reference image has no ruler you can only give a pixel ratio; px_per_mm must be obtained from a known edge length, the two end points of a ruler, or img_calib calibration.

### 0.4 Evidence chain and receipts

Leave at least one kind of evidence for every key step:
- Picture: rt_see / rt_watch / blockout 3 views / refsheet 4 views;
- Numbers: audit_mesh / asm_scan / gate_run / visualreport_report / eval_run;
- Files: manifest/md5/GLB/FBX/OBJ/MP4.

In a receipt look first at: verdict, top_defects, failures, counts, gate, coverage, warnings, honest_limits. Do not treat warnings as pass.

## 0.5 Division-of-labor paradigm for multi-agent parallel modeling (★ must-read for large pieces)

The gain of parallel modeling comes from "doing several independent things at the same time", not from "letting several models freestyle". You must freeze the contract first, then split up and write.

### 0.5.1 The first step is always freezing the spec (spec.py)

Everyone reads only the same spec.py / manifest.json, nobody may define their own constants. The spec must freeze at least:
- Object list, and for each part its dimensions/position/orientation/material slot;
- Interface table: who connects to whom, interface plane, nominal clearance, allowed overlap;
- Units, coordinate system, forward axis (default -Y), up axis (+Z);
- Acceptance gates: audit_mesh thresholds, which gates asm_gate should run, the allowed hidden_ok overlap amount.

### 0.5.2 Write-scope protocol (who writes which file)

Each builder only writes its own .py and object prefix; before going parallel declare the collection/prefix scope with blender_viewport lease; before assembly use K.route_collections to put things in place. Do not let two agents write the same .blend or the same batch of objects at the same time.

### 0.5.3 No mutual testing during the parallel phase = inherent cost

During the parallel phase each part can only do "single-part self-proof" (audit_mesh + dimensions/bbox + single-part render); interfaces not matching is normal, and is absorbed by re-checking after assembly:
1) asm_manifest validates the manifest (id/file/md5/interface frame/allow list);
2) asm_scan classifies all against all (clash / hidden_ok / contact / gap / float / contained / unresolved);
3) asm_repair(policy="safe") only does low-risk translation/snap; high-risk actions like boolean/scaling are handed to human confirmation;
4) asm_gate uses the manifest connection graph to judge float/interface deviation; export_allowed is true only on pass;
5) asm_export exports GLB/FBX/OBJ + manifest + merge_ledger.

### 0.5.4 Parallel anti-patterns (measured in practice)

- Each agent invents its own constants and writes its own acceptance criteria → parts do not match at merge time, and nobody can reproduce it;
- Using "it looks connected" instead of numbers → interpenetration/hovering gets waved through by the eye;
- Doing Boolean/Weld directly before the connection relationship is judged → destructive_guard blocks it; register connections/interfaces first;
- Treating hidden_ok (by-design hidden overlap) as interpenetration and fixing it → read the manifest's allow list first.

## 0.6 Reference-image-driven shape reconstruction (the key to "does it look alike")

### 0.6.1 Measure first, then build: img_digest → img_probe/measure → img_calib

1) **img_digest**: give the reference image path, get the native-resolution bbox, contours, straight lines, circular holes, symmetry axis, corner points, readability, native crops and annotated images. Without calibration verdict=needs_scale, all mm fields are null, never guess.
2) **img_probe**: for a width at some height use scan_y/scan_x; for circular holes use circle; for local zoom use crop.
3) **img_measure**: known edge length/two-point distance → derive px_per_mm; then measure width/height/hole diameter/angle.
4) **img_calib**: multi-view calibration, derive px_per_mm for each view and the cross-view scale; homography only corrects the plane where the points are taken, cross-depth error is estimated as Δz/(D+Δz).
5) After calibration write all dimensions into the spec; an uncalibrated image can only be a ratio reference, you cannot write "width 2000 mm".

### 0.6.2 Contour fitting: shapesolve

Parametric shapes (box bodies/brackets/car shell base bodies) can have their dimensions fitted from the reference-image contour:
- Input: setup code (defining apply(p)), parameter ranges, views (ref/from/look_at/ortho_scale);
- Principle: analytic orthographic projection + numpy triangle rasterization, no rendering, no dependency on GUI/timers;
- Output: best/per-view IoU/sensitivity (strong/weak/unidentifiable)/reproducible script;
- Boundary: only compares the contour union; ortho_scale is absolute alignment, writing it wrong makes everything wrong; the reference image must be generated with the same camera parameters.
- The fitting result must be re-verified through **another channel** (blockout render + visualreport, or measuring dimensions directly); you cannot use the training target as the acceptance check.

### 0.6.3 Blockout and reference packs: blockout

- blockout_base: declarative parts (prim/size_mm/at_mm/rot) → low-poly + 3 views + GLB; default Workbench, single white material, mm/anchor.
- blockout_batch: batch N pieces, suitable for making base blockouts for video models.
- blockout_refsheet: front/side/top orthographic + iso perspective 4 views + 2x2 sheet + refsheet.json (units/bbox/forward_axis/camera/fps) + optional embedded turntable; makes reference packs for video models like Seedance.
- blockout_turntable: orbit around the Z axis, Blender built-in FFMPEG outputs MP4/H264; MP4 has no alpha; without an FFMPEG build it falls back to a PNG sequence and marks degraded.
- A blockout is not a high-poly model: details still go through the existing channels shape/vehicle/human/sculpt etc.; the blockout is only responsible for shape proportions and camera reference.

### 0.6.4 Same camera position acceptance check: visualreport_report

- Input: ref + render (or views), optional px_per_mm, targets, ref_box_px/render_box_px;
- Output: verdict (pass/fail/degraded), IoU/Dice/missing/extra/boundary, top_defects (bbox/area/position mm), defect crops, fix_hint;
- Premise: same camera position, same resolution, same crop; scores from different camera positions/engines are not directly comparable;
- Photo references need background removal first (the mask is a foreground heuristic); when px_per_mm is missing the mm fields are null.
- **IoU is only a necessary condition for a single-view contour, not "does the whole thing look alike"**; it must be combined with dimensions/interfaces/assembly gates.

### 0.6.5 Image-reading discipline (decides tokens and results)

- Look at the whole at low resolution first (420–560), zoom in locally only when in doubt; do not use 1600 px every step.
- The same image hash = unchanged, do not look again.
- Before looking, think "which number/which defect do I want to verify", otherwise looking is the same as not looking.
- When you find a defect, locate it first (bbox/center/direction), then fix; after fixing, re-look from the same camera position + re-run the numeric gate.

## 0.7 Modeling type → tool routing (★ check this table before starting)

| What I want to do | First choice | Note |
|---|---|---|
| Don't know what to use | blender_rt_plan(op="catalog") | 34 families / 228 ops; single family family=... |
| Primitive/faceted hard surface | bmesh / geo primitives + bevel | Do not use SubSurf for faceted parts |
| Smooth hard surface | Bevel + Subdivision + shade smooth | Bevel must come before SubSurf |
| Boolean holes/cuts | geo.boolean / K.dsh_geo_api | Judge connection/closure first; keep a cutter copy |
| Repeated array | Array / parametric generator_* | Write pitch/chord length into the spec |
| Curves/pipes/cables | sweep_build / shape_* | Compute the bend radius first |
| Organic/sculpting | sculpt_* (numpy displacement brush) | Do not use bpy.ops.sculpt.brush_stroke |
| Humanoid/head shape/car shell | human_* / vehicle_* / shape_* | With a reference image, get sections via shape_plan first |
| Measure proportions from a reference image | img_digest → probe/measure → calib | No mm without calibration |
| Contour fitting for dimensions | shapesolve_solve | After fitting, re-verify on another channel |
| Blockout/video reference pack | blockout_base/batch/refsheet/turntable | 4 views + MP4 |
| Multi-part assembly | asm_manifest → scan → repair → gate → export | Freeze the manifest first |
| Interpenetration/hovering | asm_scan / asm_repair / asm_gate | hidden_ok is not interpenetration |
| Same camera position look-alike | visualreport_report / qc_render_views | Only same camera position is comparable |
| Mesh problems | audit_mesh → fix_repair → audit_mesh | If nothing was fixed it returns ok=false |
| Print check | print_report | Warns below resolution |
| Delivery | asm_export / deliver_export + gate_deliver | No delivery if the gate does not pass |
| Parameter search | blender_rt_loop (target=session can be headless) | After convergence re-verify on another channel |
| Tell whether the animation moved | rt_watch(session=...) | Per-frame hash + images |
| Project-level acceptance check | gate_run / eval_run | verdict three-state |
| Parametric surfaces (loft/sweep/patch) | surface_loft/sweep/patch → tessellate → validate → export | Pure bpy+numpy; for details see references/surface-algorithms.md; M3 fit, M5 blend/offset not implemented |

### 0.7.1 Surface algorithms (surface_*) — shapes with curvature that must be reproducible

Suitable for: section lofting (bottle body/housing/fuselage segment), sweeping along a path (pipe/beam/skirt), four-sided patch (transition surface).
Not suitable for: primitives/faceted hard surfaces (use bmesh/geo+Bevel), organic sculpting (sculpt_*), things needing G2/CAD offset (needs OCCT).

The chain has four steps, all in mm, reproducible:

    surface_loft(sections=[{z_mm, points_mm:[[x,y]...]}], degree, continuity, closed, tessellation)
      → surface_tessellate(spec_or_object=<spec>)        # get the mesh object name
      → surface_validate(spec_or_object=<object>)        # read verdict: pass / fail / degraded
      → surface_export(spec_or_object=<object>, out_dir=..., name=...)   # produce GLB

Hard rules:
- fail does not silently become pass; degraded is "not measured", it does not equal pass;
- an open surface (patch) has thickness n/a, that is not fail;
- measure the reference image (img_*) before writing sections, do not write mm by feel;
- curvature/thickness are discrete approximations; before delivery you still must pass gate_* (three-state);
- M3 fit, M5 blend/offset are not implemented (explicitly ok:false), do not pretend they work.

Details and limitations: references/surface-algorithms.md.

## 0.8 Delivery and acceptance check (read this section first, then write the last step)

Before delivery, in order:
1) audit_mesh (single-part mesh) → 2) asm_scan (multi-part interpenetration/hovering) → 3) asm_gate / gate_run (project gate, three-state) → 4) visualreport (same camera position look-alike) → 5) asm_export (GLB/FBX/OBJ + manifest + merge_ledger) → 6) if a video reference pack is needed add blockout_refsheet/turntable.
- If the gate does not pass (verdict≠pass) do not deliver; degraded needs more evidence, it may not be treated as pass.
- Deliverables must have a manifest (units/bbox/objects/md5) + receipt + limitations statement; a "delivery" without md5 is not reproducible.
- For a non-merged asm_export, if the gate is not pass: the file is written but verdict=fail + warnings, it cannot be treated directly as a shipping artifact; the merged export does not write to disk if the gate does not pass.
- Before topology changes do txn.snapshot / gate_checkpoint; object-level mark/revert does not include topology.

## 1. Architecture-first: this plugin is the modeling flow itself (mandatory)

> This section is not advice, it is a **rework criterion**. AI modeling must follow the plugin architecture: look up the capability catalog first, then do it with plan-channel ops, get a receipt at every step, and finally accept with the same chain. Do not bypass the plugin and write your own geometry/acceptance.

### 1.1 The only correct call order

For any modeling task, from the first minute to delivery, the default order is:

1. **Look at the current state**: blender_rt_cmd get_scene_info / blender_rt_plan(op="audit_scene"); confirm units, objects, existing assets.
2. **Look up the catalog**: blender_rt_plan(op="catalog"); when unsure expand a single family args={family:"..."}; operator details <family>_help.
3. **Decide the flow**: pick the stage per the §2 state machine; write stage, inputs, acceptance gates into the task card.
4. **Pick the channel**: if the GUI is present use rt_do/rt_see; if not use rt_worker start + preload, then rt_do/rt_see(session=...); plan ops take session="auto".
5. **Execute one verifiable small step**: prefer plan ops; only write bpy/bmesh when there is no corresponding op; each step should bring back an image or a number where possible.
6. **Read the receipt**: read verdict first, then top_defects / failures / warnings / next; do not read only ok.
7. **Pass the gates**: audit_mesh → asm_scan → asm_gate/gate_run → visualreport; do not move to the next step without passing.
8. **Deliver**: asm_export/deliver_export + manifest/md5 + gate_deliver; keep artifacts and receipts on record together.

**There is only one allowed exception**: the catalog genuinely has no corresponding capability, and you have already proven it with catalog/help. Only then do you write bpy/bmesh, and you still must return to the plugin acceptance gates (audit/asm/gate/visualreport) to prove the result.

### 1.2 Three iron rules

**Iron rule A: op-first.**
- If a plan op exists you may not hand-write equivalent geometry/checks. For example for assembly interference use asm_scan first, do not write your own BVH sampling; for measuring dimensions from a reference image use img_digest/probe/measure first, do not read pixels and guess.
- If generators like blockout/shape/vehicle/human/sculpt exist you may not assemble shapes from scratch with bpy; the generator owns the baseline, details are added afterwards.
- Before writing an op check the <family>_help parameter table; a wrong parameter name returns "unrecognized parameter", fix it per the hint, do not guess a second time.

**Iron rule B: evidence-first.**
- At least one kind of evidence per step: image (rt_see/rt_watch/blockout views/refsheet), numbers (audit/asm/gate/visualreport/eval), files (manifest/md5/GLB/FBX/OBJ/MP4).
- "Looks right" is not evidence; a "done" without numbers is always treated as not done.
- Numbers must carry their source: which calibration the px_per_mm came from, which op the bbox came from, which file the md5 came from.

**Iron rule C: verdict-first.**
- audit/gate/asm/visualreport/eval are all pass | fail | degraded three-state; degraded is "not finished checking/insufficient evidence", not pass.
- Reading only ok leads to misjudgment: ok=true only means the program finished running; the conclusion is in verdict/state.
- skipped in a gate also pushes the top level down to degraded; skipping is not pass, you must supply parameters or explicitly record it as not checked.

### 1.3 How to read a receipt (where weak models most easily go wrong)

Priority is fixed:
1. **verdict / state**: pass/fail/degraded;
2. **top_defects / offenders / failures**: the 1–5 items most in need of fixing;
3. **next / hint / fix_hint**: the next command or the fix method;
4. **counts / coverage / warnings**: whether the check was complete, whether anything degraded;
5. **detail / full JSON**: drill down only when you need to recompute, do not read tens of thousands of characters first thing.

The plan channel returns a receipt.v2 envelope (contract/op/verdict/summary/top_defects/next/images/provenance). Large results get truncated, use out_json to write the full result to disk or look at results/; do not assume the op produced no result just because the text was truncated.

### 1.4 GUI-first; headless is the backup interaction loop

- **Open the GUI first by default**; only when nobody watches the picture/the GUI is unavailable do you use a persistent worker for "change one step, look at one step synchronously".
- Fixed session: worker start once, and every later rt_do/rt_see/rt_watch carries the same session; do not change the name every step and cause repeated cold starts.
- preload once to inject the modules you will use into K: imgtools/assembly/blockout/visualreport/shapesolve/gate/txn/deliver etc. After preload you can call K.dsh_*_api directly.
- 50–100 ms per see is normal; several seconds means you went through the wrong channel or cold-started.
- Long jobs (>1 min/long render/batch) go to rt_job/rt_headless as_job; the interactive loop only does small-step verification.

### 1.5 spec / manifest are the architecture's contract

- Have a spec before modeling (dimensions, units, interfaces, acceptance gates); freeze it before going parallel, everyone reads only.
- Multi-part assembly must have a manifest (id/file/md5/interface frame/allow list); asm_scan/asm_gate/asm_export all take it as authoritative.
- If you do not know the interface relationships before assembly, write the manifest; do not substitute "it looks connected" for the interface table.
- hidden_ok/allow in the manifest is by-design hidden overlap; it is not an indulgence for interpenetration, expanding allow must have a reason.

### 1.6 When you may write bpy/bmesh

- The catalog has no corresponding op (prove it with catalog + help first);
- You need local editing the op does not expose (e.g. tweaking one face), and the object/selection state is clear;
- The generator/plan op has already given the baseline, you only do local refinement.

Constraints for writing bpy:
- In headless prefer bpy.data/bmesh, use bpy.ops that depends on screen/context with care;
- Every piece of code must be re-runnable and depend little on selection state; take objects by name, do not rely on the "current selection";
- Immediately return to audit_mesh or the corresponding gate after writing, do not skip it;
- snapshot/checkpoint before topology changes; do not Boolean/merge without a rollback point.

## 2. Standard modeling state machine (every step has input/output/gate)

### 2.1 Stage overview

| Stage | Target | Main tools | Exit condition |
|---|---|---|---|
| S0 spec/draft | Fix scope, units, interfaces, acceptance gates | Task card + spec.py / manifest.json | Fields complete, no mm-level invention |
| S1 reference measuring | Turn the image into px_per_mm + dimensions | img_digest → probe/measure/calib | Calibration recomputable; without calibration only ratios |
| S2 blockout/baseline | Quickly produce shape proportions | blockout_base/batch, shape_*, vehicle_*, human_* | 3 views viewable, bbox reasonable |
| S3 shape refinement | Loft/sections/feature lines/sculpting | shape_loft/sections/crease, sculpt_* | Dimensions/proportions on target; key features identifiable |
| S4 hard-surface detail | Bevel/boolean/array/sweep | geo, fix, uv, sweep, material | No degenerate faces; normals correct; material slots stable |
| S5 single-part checkup | Mesh/normals/UV/print | audit_mesh, uv_stats, print_report | state=pass (degraded needs more checks) |
| S6 assembly | Manifest/scan/repair/gate | asm_manifest → asm_scan → asm_repair → asm_gate | gate verdict=pass; clash/contained/float explained |
| S7 visual acceptance check | Same camera position look-alike | visualreport_report / qc_render_views | verdict=pass or explicitly unresolved |
| S8 delivery | Export/reference pack/ledger | asm_export / deliver_export / blockout_refsheet/turntable | manifest+md5+gate receipts complete |

Do not skip stages. Doing S4 details without an S2 blockout gives the highest rework rate; entering S6 without the S5 checkup makes the assembly gate amplify the problems.

### 2.2 Task card (fill in before starting, no more than 10 lines)

    Target: one sentence (what you make, who it is for)
    Units/coordinates: mm or m; forward axis -Y; up axis +Z
    Delivery: GLB / FBX / OBJ / blend / MP4 / images
    Reference: image path + whether px_per_mm is already calibrated
    Main parts: object/collection list
    Interfaces: who connects to whom, nominal clearance, allowed overlap
    Acceptance gates: audit_mesh / asm_gate / gate_run / visualreport / eval
    Forbidden: things not to do (e.g. no boolean, do not change materials)
    Budget: time/face count/resolution

Starting to model without a task card is the same as having no contract; every later "does it look alike/does it pass" then cannot be judged.

### 2.3 Evidence artifacts per stage

- S1: img_digest receipt + calibration table (px_per_mm, two points/known edge length, error);
- S2: blockout 3 views + bbox + GLB;
- S3: sections/station table/feature-line parameters + dimension table;
- S4: modifier stack description + boolean/array parameters + audit_mesh;
- S5: audit_mesh receipt (state/each count/normals per shell);
- S6: manifest + asm_scan + asm_repair plan + asm_gate;
- S7: visualreport_report receipt + overlay/sheet;
- S8: manifest.json + merge_ledger.jsonl + per-file md5 + gate receipt.

A "completion" with incomplete evidence is only a half-finished product; do not hand it downstream.

## 3. Tool selection matrix (check this table first, then write code)

| Task | First choice (plugin architecture) | Second choice (only when there is no op) | Acceptance check |
|---|---|---|---|
| Primitive/blockout | blockout_base/batch | bmesh.ops.create_* | bbox + 3 views + audit_mesh |
| Parametric sections/loft | shape_plan/shape_sections/shape_loft | bmesh loft | shape_fit IoU + dimensions |
| Vehicle shell | vehicle_package → vehicle_base → clear_check | shape_* | clear_check + visualreport |
| Humanoid/head | human_* / face_* | sculpt + reference image | proportions/feature lines/visualreport |
| Organic/sculpting | sculpt_scan/setup/apply | bmesh displacement | audit_mesh + images |
| Hard-surface faceting | primitives + bevel/crease_lines | bmesh inset/extrude | facet look image + audit_mesh |
| Smooth hard surface | Bevel + Subdivision (modifier) | bmesh subdivision | facet look image + normals |
| Boolean holes/cuts | geo.boolean / K.dsh_geo_api | bpy.ops boolean | audit_mesh + interference |
| Array/repeated parts | generator_* / Array | bmesh duplicate | count/pitch/bbox |
| Pipes/cables/tracks | sweep_analyze → sweep_build | curve+bevel | bend radius + audit_mesh |
| Measuring dimensions from a reference image | img_digest → probe/measure/calib | numpy pixel reading | calibration error + recomputation |
| Contour fitting | shapesolve_solve | manual point measuring | re-verify on another channel |
| Mesh repair | audit_mesh → fix_repair | bmesh cleanup | counts before/after repair |
| UV/material | uv_* / material_* | bpy.ops uv | uv_stats + material check |
| Assembly | asm_manifest → scan → repair → gate | manual alignment | asm_gate verdict |
| Visual QC | visualreport_report / qc_compare | human eyes on images | same camera position IoU + defects |
| Delivery | asm_export / deliver_export + gate_deliver | manual export | manifest + md5 |
| Parameter search | rt_loop (target=session can be headless) | hand-written grid search | re-verify on another channel |
| Animation/modifier verification | rt_watch(session) | per-frame see | hash change + images |
| Defect evaluation | eval_run | self-written test cases | capture_rate/baseline |

**Criterion**: if the first choice can be used, do not use the second; the second choice must state in the receipt "why the plugin op was not used".

## 4. Current plan-channel quick reference (v3.0.6 · 34 families / 228 ops)

First blender_rt_plan(op="catalog") to see "when to use / when not to use / minimal skeleton", then expand a single family. Common families:

| family | Purpose | Representative ops |
|---|---|---|
| audit | Mesh/scene checkup | audit_scene / audit_mesh / audit_interference / audit_connectivity / audit_gate |
| asm | Assembly manifest/scan/merge/repair/export/gate | asm_manifest / asm_scan / asm_merge / asm_repair / asm_export / asm_gate |
| blockout | Declarative blockout/batch/reference pack | blockout_base / blockout_batch / blockout_export / blockout_refsheet / blockout_turntable |
| img | Reference-image measuring tools | img_digest / img_probe / img_measure / img_calib / img_rectify / img_crop / img_diff |
| visualreport | Same camera position QC report | visualreport_report |
| shapesolve | Headless multi-view contour fitting | shapesolve_solve |
| eval | Defect injection/baseline evaluation | eval_run |
| qc / qc_render | Rendering and image comparison | qc_render_views / qc_compare |
| gate | Project gate/flow | gate_plan / gate_run / gate_preflight / gate_checkpoint / gate_deliver |
| deliver | Delivery export/verification | deliver_export / deliver_verify |
| shape | Sections/loft/polyline family | shape_plan / shape_draft / shape_loft / shape_sections |
| vehicle / human / face | Vehicle/humanoid/head | vehicle_package / vehicle_base / human_* / face_* |
| sculpt / fix / uv / print / sweep | Sculpting/repair/UV/print/sweep | *_apply / fix_repair / uv_smart_project / print_report / sweep_build |
| material / motion / generator | Material/mechanism/parametric | material_build / motion_* / generator_save|run |
| surface | Parametric surface candidates/QC/export | surface_loft / surface_sweep / surface_patch / surface_tessellate / surface_validate / surface_export |
| clear / calib | Clearance/gate calibration | clear_check / calib_run |
| pipe / planner | Multi-step chain/planner | pipe_run / planner_* |

Rules:
- A misspelled op returns did_you_mean; a wrong parameter name returns "unrecognized parameter", fix it per the hint.
- Read-only ops do not go through the write lease; write ops lease first.
- Large results are written to the results/ directory; when the receipt text is truncated use out_json/the result file.
- When plan is passed session="auto" it auto-starts a headless worker per family; the first cold start is about 2 s, then it is reused.


## 5. P0–P2 new pipeline recipes (ready to copy)

### Recipe 5.1 Interactive headless modeling (nobody watching the viewport)

    # 1) start a persistent headless session (preload decides which K APIs you can call directly)
    blender_rt_worker(op="start", name="s1",
      preload="imgtools,assembly,blockout,visualreport,shapesolve,gate,txn,deliver",
      engine="workbench", warmup=true)
    # 2) change one step, see one step in sync (the image comes straight back to the model; not an async job)
    blender_rt_do(code="...bpy/bmesh code...", session="s1", see=true, max_size=560)
    # 3) re-check from another angle
    blender_rt_see(session="s1", from="7,-7,5", look_at="0,0,1")
    # 4) did animation/modifiers move
    blender_rt_watch(session="s1", frames=[1,10,20], max_size=420)
    # 5) run plan op without a GUI too
    blender_rt_plan(op="img_digest", args={path:"..."}, session="auto")

Criterion: the first start takes about 2–3 s; after that each exec step costs 0–2 ms and see 50–100 ms (320–560 px). If see takes several seconds, you are on the wrong channel / cold-starting on every step.

### Recipe 5.2 Reference image → dimensions → blockout → acceptance check

    # 1) measure first: without calibration you get needs_scale — do not guess mm
    blender_rt_plan(op="img_digest", args={path:"ref.png"}, session="auto")
    # 2) known edge length / two points → px_per_mm
    blender_rt_plan(op="img_measure", args={path:"ref.png", known_len:{...}}, session="auto")
    # 3) blockout (mm terms; freeze the spec first)
    blender_rt_plan(op="blockout_base", args={
      name:"robot",
      parts:[{id:"torso", prim:"box", size_mm:[300,180,420], at_mm:[0,0,900]}],
      render:{views:"auto3", res:[512,512]},
      export:{glb:"D:/out/robot.glb"}
    }, session="auto")
    # 4) same camera position similarity (same camera / same resolution)
    blender_rt_plan(op="visualreport_report", args={
      ref:"ref.png", render:"render.png", px_per_mm:0.16
    }, session="auto")

Note: IoU is only a necessary condition for a single-view contour; you also have to cross-check it against the dimensions / interfaces / assembly gate.

### Recipe 5.3 Assembly: manifest → scan → safe repair → gate → export

    # 1) manifest (id/file/md5/interface/allow)
    blender_rt_plan(op="asm_manifest", args={action:"build", parts:[...]}, session="auto")
    # 2) all-vs-all classification (clash/hidden_ok/contact/gap/float/contained/unresolved)
    blender_rt_plan(op="asm_scan", args={manifest:"assembly.json"}, session="auto")
    # 3) low-risk repair: safe only does translate/snap, hard-forbids boolean/scale; dry_run first
    blender_rt_plan(op="asm_repair", args={manifest:"assembly.json", policy:"safe", dry_run:true}, session="auto")
    # 4) gate (three-state verdict; export_allowed only on pass)
    blender_rt_plan(op="asm_gate", args={manifest:"assembly.json"}, session="auto")
    # 5) delivery export (GLB/FBX/OBJ + manifest + merge_ledger)
    blender_rt_plan(op="asm_export", args={
      manifest:"assembly.json", merge:true, dry_run:false,
      out_dir:"D:/out", name:"assembly",
      formats:["glb","fbx","obj"], ledger:true
    }, session="auto")

Boundary: hidden_ok is a hidden overlap declared as allowed in the manifest, not interpenetration; do not widen allow arbitrarily just to get clash=0. With a non-merge export and a gate that is not pass, the file is still written but verdict=fail + warnings — it must not be treated as a shipping asset.

### Recipe 5.4 Seedance reference package (4 views + turntable MP4)

    blender_rt_plan(op="blockout_refsheet", args={
      objects:["robot_torso","robot_arm"],
      out_dir:"D:/Blender/robot/ref",
      name:"robot", views:["front","side","top","iso"], res:[768,768],
      turntable:{frames:120, fps:24, elev_deg:15}
    }, session="auto")
    # turntable MP4 only
    blender_rt_plan(op="blockout_turntable", args={
      objects:["robot_torso"], out_dir:"D:/Blender/robot/ref",
      name:"robot", frames:120, fps:24, res:[512,512]
    }, session="auto")

Deliverables: 4 PNGs + 2x2 sheet + refsheet.json (units/bbox/forward_axis/fps) + optional MP4. MP4 has no alpha; builds without FFMPEG fall back to a PNG sequence and are marked degraded. A blockout is a reference package, not a high-poly model.

### Recipe 5.5 Contour fitting (shapesolve) and re-checking

    blender_rt_plan(op="shapesolve_solve", args={
      setup:"def apply(p): ...",
      params:[{name:"width",min:0.5,max:2.0,init:1.0}],
      views:[{ref:"front.png", from:[0,-5,1], look_at:[0,0,1], ortho_scale:3.0}],
      iterations:200, budget_ms:10000
    }, session="auto")

Re-check: write the best parameters back into the geometry → blockout/render → visualreport or img_measure to measure dimensions; do not use the fitting objective function as an acceptance check.

### Recipe 5.6 Gate-enforced delivery

    # preflight / leave a rollback point first
    blender_rt_plan(op="gate_preflight", session="auto")
    blender_rt_plan(op="gate_checkpoint", args={label:"before_delivery"}, session="auto")
    # pass the gate before exporting (no gate, no export — blocked, nothing written to disk)
    blender_rt_plan(op="gate_deliver", args={
      dir:"D:/out", spec_path:"gate.json", name:"model", fmt:"obj", verify:true
    }, session="auto")

deliver_export also supports require_gate=true; gate_deliver is the one-button enforcement path for weaker models / delivery flows. A degraded result requires an explicit allow_degraded and an explanation — it must not silently turn green.

### Recipe 5.7 Defect injection evaluation (run it first after changing a gate)

    blender_rt_plan(op="eval_run", args={
      suite:"assembly", out_json:"D:/out/eval.json"
    }, session="auto")

Reading: capture_rate / missed / false_positive / baseline_pass; green for assembly/reference with degraded on core when dependencies are missing is normal. capture_rate only represents the synthetic defect set and does not equal a real-project pass rate.

### 5.8 Multi-agent parallelism: divide work by plugin architecture

Multi-agent is not "several models modeling freely at the same time"; it is "sharing one contract, each writing only its own scope". Default division of labor:

1. **Lead / architecture owner**: freezes spec.py / manifest.json; runs catalog to pick a route; assigns write scopes; runs asm_gate/gate_run at the end.
2. **Reference builder**: img_digest/probe/measure/calib → dimensions table → updates spec; does not write geometry.
3. **Blockout builder**: blockout_base/batch → blockout + 3 views; writes only objects with its own prefix.
4. **Shape/vehicle/human builder**: generates the main body from the spec; outputs bbox / section comparison.
5. **Detail builder**: hard-surface detail / boolean / array / sweep; checkpoint before topology changes.
6. **Assembly owner**: asm_manifest → asm_scan → asm_repair(policy=safe) → asm_gate; works only on the assembly layer.
7. **Verifier**: independently runs audit/asm/visualreport/eval and does not take the builders' conclusions on trust.

Write scopes:
- each builder writes only its own object prefix and files; declare collection/prefix with a blender_viewport lease;
- before assembly use K.route_collections to route by prefix (COL_Lights/COL_Camera/COL_VFX/COL_Geo, etc.);
- nobody may modify anyone else's objects; interface changes must go back to spec/manifest — no "verbal agreements" allowed.

Assembly protocol:
- write the interface table first: a/b, interface, nominal_mm, tol_mm, allow_overlap_mm;
- hidden_ok/allow must have a reason (in-design hidden overlap), not merely to turn scan green;
- conflict handling order: asm_repair(policy=safe) translate/snap → manual confirmation of boolean/scale → re-run scan/gate;
- no gate, no merge, no export; a merged export requires gate=pass.

Acceptance checks during parallel work:
- single part: audit_mesh + bbox/dimensions + single-part render;
- assembly: asm_scan + asm_gate;
- visual: visualreport (same camera position);
- delivery: asm_export + manifest/ledger.

### 5.9 Anti-pattern list (any of these means rework)

| Anti-pattern | Why it is wrong | Correct approach |
|---|---|---|
| Writing bpy without checking catalog | Reimplements capabilities the plugin already has, with wrong parameters/acceptance terms | catalog first; if an op exists, use the op |
| Writing your own "does it look alike" criterion | Inconsistent with the plugin's IoU/gate terms, not reproducible | visualreport/qc_compare + dimensions gate |
| Reading ok but not verdict | ok only means it finished; degraded gets treated as pass | read verdict/state first |
| Treating skipped as pass | The gate never ran, which equals no check at all | supply args/overrides or record it as unchecked |
| Widening allow arbitrarily to make scan=0 | Real interpenetration gets hidden and blows up after delivery | allow must have a design reason |
| Stopping work when the GUI is offline | Headless can be interactive anyway | worker session + see |
| Switching session every step / cold-starting every step | Slow and loses state | fixed session + preload |
| Blocking synchronously on long jobs | A client timeout is misread as failure | as_job/rt_job |
| No snapshot before topology changes | Cannot roll back | txn.snapshot / gate_checkpoint |
| Using "it looks attached" instead of a manifest | Assembly cannot be re-checked | asm_manifest + interface table |
| Delivering without manifest/md5 | Not reproducible | asm_export/deliver_export |
| Delivering a blockout as a high-poly model | A reference package is not a finished asset | blockout is only a baseline/reference |
| Computing IoU straight from a photo reference | The background mask is unreliable | cut out the background first / provide a crop box |
| Writing mm without calibration | The numbers are invented | img_measure/img_calib or mark needs_scale |
| Having a VLM look at the whole image instead of a numeric gate | It cannot see mm-level defects | numeric gate + local crop |

### 5.10 New-session opening template (copy directly)

    You are modeling in the DSH × Blender plugin environment. You must follow the plugin architecture:
    1) run blender_rt_plan(op="catalog") first to check capabilities; do not invent geometry/acceptance checks;
    2) if a plan op exists, use the op (pass session="auto" for headless); only write bpy/bmesh when none exists, and state the reason;
    3) give me image or numeric evidence at every step; read verdict first in the receipt — degraded ≠ pass;
    4) for a reference image, use img_digest/probe/measure/calib first; no mm without calibration;
    5) for multiple parts, asm_manifest first, then asm_scan/asm_repair/asm_gate; no gate, no delivery;
    6) for delivery use asm_export/deliver_export with manifest/md5/ledger;
    7) long jobs go through rt_job/headless as_job; small interactive steps use rt_worker + rt_do/rt_see(session).
    Task: <target/units/delivery/reference image/budget/forbidden items>

### 5.11 The four shortest paths from scratch to delivery

**A. A single hard-surface prop**
catalog → blockout_base or primitives + Bevel/crease_lines → audit_mesh → material/UV (as needed) → qc_render_views → asm_export (works for a single part too, a manifest is still recommended).

**B. Reference-image reconstruction**
img_digest → img_measure/calib → spec dimensions table → blockout_base/shape_loft/vehicle_base → visualreport (same camera position) → audit_mesh → asm_export.
If the parametric features are strong: shapesolve_solve to reverse-engineer parameters → write back to the geometry → re-check through a different path.

**C. Multi-part assembly**
freeze the manifest → per-part builders → per-part audit_mesh → asm_scan → asm_repair(policy=safe, dry_run first) → asm_gate → asm_export(merge=true) → visualreport/refsheet.

**D. Seedance base blockout package**
blockout_batch produces N parts → blockout_refsheet (4 views + sheet + refsheet.json) → blockout_turntable (MP4) → check units/bbox/forward_axis → deliver to D:/Blender/<project>/.

### 5.12 Current terms for gates/evaluation (do not remember the old version)

- gate_run / asm_gate / visualreport / eval are all three-state: pass / fail / degraded; ok is true only on pass.
- a skipped entry inside a gate pushes the top level down to degraded; degraded needs more evidence — it must not silently turn green.
- eval_run's capture_rate only represents the synthetic defect set; run it once after changing a gate and record baseline/missed.
- same-camera-position visualreport IoU is a necessary condition for the contour, not overall similarity; scores across camera positions/engines are not comparable.
- with a non-merge asm_export and a gate that is not pass, the file is still written but verdict=fail + warnings — it must not be treated as a shipping asset.

## 6. Common failures and boundaries (current version)

| Symptom | Cause | Handling |
|---|---|---|
| GUI offline, rt_see/rt_do report a connection failure | The headless fallback was not used | pass session="s1" or auto; worker start first |
| worker see is very slow / cold-starts every time | The session name changed at every step, or the worker was reclaimed by TTL | fixed session; preload once; check idleMs in status |
| plan op fails with a headless routing message | That family is not wired to headless routes / the module was not preloaded | call the K API directly with blender_rt_headless(preload=...), or use the GUI channel |
| Wanting mm without calibration | img_digest verdict=needs_scale | provide known_len/a ruler/two points, or img_calib; do not guess |
| asm_scan reports an in-design overlap as clash | The manifest does not declare allow/hidden_ok | declare it with asm_manifest first; do not edit geometry directly |
| asm_repair does nothing / is blocked | There is a parent/animation/exceeds max_move, or policy=safe | clear the parent/keyframes, adjust max_move; booleans go to manual/aggressive |
| asm_gate degraded | There are skipped/unchecked gates | fill in the manifest/parameters; do not treat degraded as pass |
| visualreport score is abnormally low | Camera position/resolution/crop differ, or the photo background was not cut out | re-render at the same camera position; provide ref_box/render_box; cut out the background first |
| refsheet MP4 fails | The Blender build has no FFMPEG | check warnings/degraded, use the PNG sequence or switch builds |
| Cannot reproduce after delivery | No manifest/md5 | use the manifest + ledger from asm_export/deliver_export |
| Render hangs/times out | The main thread is occupied by rendering | render_state → render_wait; long jobs go through job |

Explicitly not covered / dependencies not installed: landmark/face (no cv2/MediaPipe), OCR, DXF, Open3D/manifold3d/glTF-Validator are not installed; do not write them up as supported. Creature/organic high-poly models, film-grade lighting/compositing, and character rigging/animation are also outside this skill's scope.

## 7. Final pre-delivery checklist (tick each item)

1. Units/forward axis/up axis confirmed; every dimension comes from calibration or the spec, not from guessing.
2. Per-part audit_mesh passes; a txn.snapshot or gate_checkpoint exists before topology changes.
3. Multi-part asm_manifest validation passes; the asm_scan classification has been reviewed (clash/contained/float/unresolved are 0 or explained).
4. asm_gate/gate_run verdict=pass; degraded/failed/skipped have been backed with evidence, not treated as pass.
5. Same-camera-position visualreport/QC has been reviewed; IoU agrees cross-wise with the dimensions/interfaces/assembly gate.
6. Delivery files have a manifest (units/bbox/objects/md5) + ledger; the receipt is recomputable.
7. Limitations/risks are written into the receipt: no calibration, no external dependencies, MP4 without alpha, non-merge gate not pass, etc.
8. For changed gates/tools, eval_run or the corresponding selftest has been run, with capture_rate/baseline recorded.

> Remember: **the image is evidence, the numbers are the criterion, the verdict is the conclusion**. Do not replace any one of them with "it looks right".



## Appendix A. General Blender deep-water reference (not the preferred path)

> The following content preserves general modeling knowledge / numeric gates / rendering experience, for reference when "the catalog really has no corresponding op".
> **The default path is always the architecture rules of §1–§3 + the plugin recipes of §4–§5**; after any reference approach is finished you must still come back to the plugin gates (audit/asm/gate/visualreport) for the acceptance check — you are not allowed to write your own criterion.

### A.4. The six pitfalls you are bound to hit

### A.4.1 How the six pitfalls are routed (P2-3: what can be decided mechanically goes to the gates, what cannot goes into the checklist)

| Pitfall | Mechanically decidable? | Where it lands |
|---|---|---|
| Pitfall five **normal direction** | ✅ | **acceptance gate**: `audit_mesh`'s `normals_state` (`pass`/`fail`/`unknown`/`n/a`) + `normals_shells[]` (per shell); ⚠ don't look only at the total `signed_volume` (a large positive shell + a small reversed shell cancel to a positive number), `closed=false` gives `normals_outward=null` (**not "no problem"**), `unknown` ⇒ at least `degraded` (if another defect is present at the same time it is `fail`), **in no case is a pass given** |
| Pitfall two **floater / dangling** | ✅ | **acceptance gate**: `audit_connectivity`'s `floaters[].{span_fraction, gap_mm, mesh_confirmed}` + **`gate.state`** (there is no `state` at the top level), `audit_snap_floaters` (reports only by default), `audit_gate`'s `state` |
| Pitfall two **interpenetration / hidden overlap** | ✅ | **acceptance gate**: `audit_interference` (three-state + `volume_mm3`; `unresolved` = cannot decide), `audit_overlap` (`pair_count`; **a contact fit gives ≥1**), `audit_measure`'s `pairs[].axis_overlap_mm` (**per-axis AABB: usable as a coarse filter only when the interface normal aligns with a world axis and the axis-aligned box approximation fits that geometry**; for rotated interfaces measure the real surface along the interface's local coordinates, see Pitfall two ③) |
| Pitfall one long axis / wide axis / thin axis semantics | ❌ semantic, a machine cannot decide | **pre-code checklist** |
| Pitfall three taper to a point: press onto the centerline, then merge | ❌ | **pre-code checklist** |
| Pitfall four be careful with bpy.ops under headless | ❌ | **pre-code checklist** |
| Pitfall six preview lighting / material / camera | ⚠ half (parameters go into `lib/preview.py`; after rendering check `coverage_estimate` and `warning.frame_looks_empty`) | rig defaults + gate ⑨ |

**Pre-code checklist (the three that cannot be decided mechanically — read each one through before you start)**:

1. **Long axis / wide axis / thin axis**: which axis of this part is the long one? Which axis is the wide face where "the shape is visible"? Which side is the camera on? — first write `(long, wide, thin) = (local?, local?, local?)` in a comment, then start (Pitfall one).
2. **Taper to a point**: for the ring of vertices that should taper to a point, do you **first press them onto the centerline (x=y=0) and then `remove_doubles`**? Proportional scaling alone always gives a flat head (Pitfall three).
3. **headless**: does this script contain `object.mode_set` / `mesh.*` / `loopcut` / `transform.*` / `uv.*`? If yes ⇒ switch to bmesh or the data API (Pitfall four table + recipes 3b/8).

**How to verify**: for each of the three checklist items you can point to the corresponding line in the code (the axis comment / the two lines that press onto the centerline / the absence of ops calls);
the three mechanically decided ones, on the other hand, must appear in the delivery receipt (§0.5.5).

### Pitfall one: the "long axis / wide axis / thin axis" semantics of slender objects

For anything slender or asymmetric (sword blade, knife, bottle, plank, bone, screwdriver tip), the three axes **mean different things**:

- **Long axis** = length (sword blade 78cm)
- **Wide axis** = wide face (sword blade 4.5cm; this is the face on which "you can tell it is a sword")
- **Thin axis** = cross-section thickness (sword blade 0.8cm, i.e. the direction of the edge)

**Always point the wide axis at the hero-shot camera.** A sword seen along its thin axis renders as a thin stick.

| Object | local X | local Y | local Z |
|---|---|---|---|
| sword blade | thin 0.8cm | wide 4.5cm | long 78cm (vertical) |
| knife blade | thin | wide | long (horizontal) |
| plank | thin | wide | long |
| bottle | symmetric (radius) | symmetric (radius) | long (height) |

After building, remember to **rotate the object** so the wide face points at the camera (with the camera along -Y, rotate the knife blade 90 degrees about Z and the local Y wide axis then faces world X, making the wide face visible).

### Pitfall two: part seams — visible joining and real connection are two different things (★ the single highest-value item of the whole set)

When assembling multiple parts (sword = blade + guard + grip + pommel; tank = hull + turret + suspension + skirts), **face against face** still renders with a visible seam even when the numbers say they touch; between different shapes (a cylindrical grip pushed into a boxy guard) it is even more obvious.
The display-model approach is **hidden overlap**: let the two parts press into each other slightly at a place that is not visible, and the seam disappears.

> ★ **Correcting a hard-coded general rule**: the old version treated "parts inserted into each other by **5–15mm**" as a hard rule; v4/v5 replaced it with "`1–2×` the interface feature size",
> but **that is still a prescriptive fixed multiple / lower bound**. **v6 withdraws all such general rules**: this skill no longer gives any universal multiple, percentage or lower bound.

**① Display layer (the part this skill is responsible for): hidden overlap + review against the spec**

- Joining may use **hidden overlap** **without changing the visible silhouette and without piercing through thin shells** (bury the overlap inside the larger part or between non-visible faces);
- **The overlap amount is explicitly specified by this project's spec** (`spec.py`'s interface table writes its own value for each item); **there is no general rule** — if the spec does not state it, go back and ask for the spec, do not invent a number yourself;
- After assembly, review three things against the spec: overlap amount (`audit_measure`), floating (`audit_connectivity`), true mutual penetration (`audit_interference`).

**② Real connection is not decided by a visual script**

Whether a thing **can carry load, resist torsion, resist bending, or even be assembled** is jointly determined by **the design fit (mating and tolerances), applicable standards, load cases, manufacturing process (wall thickness / draft / print orientation) and motion clearance** — all of these are design inputs that a human must supply.
**This skill's geometry scripts only answer "does it overlap, does it float, does it penetrate" — they cannot give structural-strength conclusions**: `volume_mm3` / `pair_count` / `axis_overlap_mm` are none of them a certificate of strength or connection.

**③ How to judge overlap with `audit_measure` (★ it has a measurement-convention pitfall)**

`pairs[].axis_overlap_mm` is a **per-axis AABB overlap**, and the receipt carries its own `note: "bbox level (not triangle level)"`.

- **A per-axis AABB can serve as a coarse filter only when "the interface normal aligns with one world axis and the axis-aligned box approximation fits this geometry"**; in that case read the value of **the axis of the interface normal** — not the maximum, and not the sum;
- **Rotated / inclined interfaces cannot be read this way**: when the interface normal is not aligned with a world axis, "picking one world axis" measures **the overlap of the boxes**, not the depth at the interface. You must **measure the real surface along the real interface's local coordinates** (take a section / measure the real triangles in the interface's local coordinate system), or switch to true triangle-level evidence;
- Reading example (the example only demonstrates "how to read an AABB", **it does not constitute any depth standard**): for a Ø6 shaft into a hub, if the interface axis matches z and the receipt gives `{x:6, y:6, z:6}`, the 6 in z is the box-level overlap; a 3mm thin plate lap gives `{x:180, y:200, z:1.5}` — the 180/200 in x/y are **how big the plate itself is** and have nothing to do with the overlap; looking at a single number or taking the maximum necessarily produces a wrong conclusion;
- **AABB intersection ≠ a real overlap**: a fully contained 10mm floater likewise gives `overlap_bbox=true` with 10mm on each of the three axes. So an overlap review must **be run in parallel with the floating gate** (`audit_connectivity` / `audit_gate`);
- For **true triangle-level** penetration evidence use `audit_interference`'s `volume_mm3` / `audit_overlap`'s `pair_count`;
  note that `audit_overlap` is "true triangle-triangle intersection", but **coplanar faces that cover each other are not reported** (the plugin receipt's original wording); for coplanar contact look at `contact_probe`.

**④ Turn on smooth shading for rounded parts**: `bpy.data.polygons[].use_smooth = True` (stable headless) or `bpy.ops.object.shade_smooth()` in the GUI. A flat-shaded cylinder shows every facet; box-type hard surfaces stay flat-shaded (Blender 5.x has removed `Mesh.use_auto_smooth` — use modifier-style smoothing or per-face flags).

> Measured in practice (500 objects / 7 agents): **assembly quality rested almost entirely on this one item**. Suspension-arm interpenetration, a floating drive-wheel cover, a fender floating 193mm — all of them were caught and converged by "hidden overlap + post-assembly re-check against the spec".
> When modeling in parallel, write it into the **team protocol + interface table** (§0.5.3; each interface writes its own `overlap_mm` and where it comes from in the spec).

When you want a **truly seamless** result (high-quality render), Boolean Union the parts with the same material into one mesh — but only when the material is the same.

### Pitfall three: tapering to a point cannot rely on scaling alone

Scaling the top vertices down to nearly 0 gives a "chisel-like flat head". The correct approach is **to press the vertices onto the centerline and then merge**:

```python
import bpy, bmesh
obj = bpy.data.objects['GEO-blade']
bpy.context.view_layer.objects.active = obj
bpy.ops.object.mode_set(mode='EDIT')

bm = bmesh.from_edit_mesh(obj.data)
bm.verts.ensure_lookup_table()
max_z = max(v.co.z for v in bm.verts)
top_verts = [v for v in bm.verts if abs(v.co.z - max_z) < 0.001]
for v in top_verts:
    v.co.x = 0.0
    v.co.y = 0.0
bmesh.update_edit_mesh(obj.data)

bpy.ops.mesh.select_all(action='DESELECT')
for v in top_verts:
    v.select = True
bmesh.update_edit_mesh(obj.data)
bpy.ops.mesh.remove_doubles(threshold=0.001)   # omit this step and you get a "fake point" on degenerate topology
bpy.ops.object.mode_set(mode='OBJECT')
print(f"tapered:{obj.name}")
```

### Pitfall four: be careful with bpy.ops under headless (★ saves you a lot of "unexplained failures")

Many `bpy.ops` operators are **context-dependent**: they require "currently in edit mode + it is the active object + there is a selection + there is a suitable area (VIEW_3D)".
Under `blender -b` (no window, no area) these preconditions often do not hold, and what you get is a failure like
`RuntimeError: Operator bpy.ops.mesh.xxx.poll() failed, context is incorrect` that gives **no clue about the cause**.

| Category | Behavior under headless | Recommendation |
|---|---|---|
| `primitive_*_add` (add primitives) | ✅ stable | use directly |
| `object.modifier_apply` / `modifier_add` | ✅ basically stable (just set `view_layer.objects.active`) | use directly, but remember to make the object active before apply |
| `object.mode_set` + `mesh.*` (extrude / inset / loop cut / remove_doubles…) | ⚠ frequent poll failures | **switch to bmesh** (recipes 3b / 8) |
| `mesh.loopcut_slide`, `transform.*`, `uv.*` | ⚠ depends on area / modal input | do not use; use bmesh or edit the data directly |
| `object.shade_smooth` / `object.select_all` | ⚠ depends on view_layer | use the data API (see below) |

Replacement patterns (**recommended**):

```python
# flat/smooth shading: change face attributes directly, don't touch ops
for p in obj.data.polygons:
    p.use_smooth = False        # or True

# make normals consistent: bmesh version (equivalent to normals_make_consistent)
import bmesh
bm = bmesh.new(); bm.from_mesh(obj.data)
bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
bm.to_mesh(obj.data); bm.free(); obj.data.update()
```

When you must use ops: fill in the context with `bpy.context.temp_override(...)`, or **switch to the GUI channel** (`blender_rt_do`, where there are real windows and areas).
Criterion: **the same script throws a poll/context error under headless but runs fine in the GUI → this is the pitfall**; do not go suspecting the geometry data.

### Pitfall five: normal direction is the precondition for every "interpenetration / containment" criterion (★ it can produce the reverse conclusion)

Any criterion of the form `(p − loc) · n < 0 → "inside"` (a point is inside, how deep a part is pushed into the body, whether a face points outward)
**assumes the normals point outward**. When the normals point inward the conclusion **flips sign across the board**.

Measured in practice: the outer surface normals of a hull side panel pointed inward → the audit misreported "a bracket sitting against the outer wall" as "150mm deep into the hull".
The nastiest part of this class of error is that **it looks like the geometry is wrong**, so you go and fix the geometry and make it worse with every change.

**Discipline**:

1. **Before** any interpenetration / containment judgment, verify the normals first:
```python
import bmesh, mathutils
def normal_health(obj, probe_point=None):
    """Return (whether consistently outward, signed volume). Signed volume < 0 = normals point inward overall."""
    bm = bmesh.new(); bm.from_mesh(obj.data)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    vol = 0.0
    for f in bm.faces:
        a, b, c = [v.co for v in f.verts]
        vol += a.dot(b.cross(c)) / 6.0
    bm.free()
    return (vol > 0), vol
```
   (A closed mesh with signed volume < 0 ⇒ normals point inward overall ⇒ recalc first, then judge.)
   ⚠ **This is only a quick check for "a single body, a single shell"**: one object can contain several disconnected shells, and `bm.calc_volume(signed=True)` **adds them up** —
   a large positive shell (+8) + a separate small reversed shell (−1) still totals +7 > 0 ⇒ the reversed piece is swallowed. Hand multi-shell parts to `audit_mesh`
   (from the current version on it judges **per connected shell**: `normals_state` ∈ `pass`/`fail`/`unknown`/`n/a`, with the details in `normals_shells[]`, including per-shell `state`/`signed_volume`/`nested`).
2. The assembly layer does **one blanket fallback** recalc (the line from Recipe 8); do not expect every builder to remember it.
3. When writing a criterion into a report, carry the **normal precondition**: "given normals pointing outward, X penetrates Y by 12mm".
4. Two-way confirmation: run the same pair through both `audit_interference` and `audit_measure`; if the conclusions disagree, check the normals first.
5. **`unknown` must not be treated as pass** (the current version's per-shell criterion):

   | `normals_state` | Meaning | Handling |
   |---|---|---|
   | `pass` | every shell is "verifiably an independent solid" and points outward; legitimate nested cavities are marked `nested` and exempt (negative volume not misreported) | record in the receipt |
   | `fail` | at least one **non-nested** shell is closed, consistently wound, with `signed_volume < 0` | recalc first, then re-check |
   | `unknown` | cannot be decided: shell AABBs intersect but nesting/cavity cannot be confirmed (mutual penetration, partial overlap, coincident duplicates), closure/winding/volume cannot be decided, or (when a limit is explicitly set) the face count exceeds the per-shell analysis limit | **not a pass**: with no other defect `state=degraded`; with a concurrent defect (e.g. mutual penetration caught as self-intersection) `state=fail` ⇒ **investigate further** (`normals_reason` gives the reason; for large meshes the env `DSH_SHELL_MAX_FACES` can relax it), and **do not** draw a "no problem" conclusion |
   | `n/a` | the mesh is not closed (`closed=false`), so "overall orientation" is meaningless | close it first, or for intentionally open parts verify only the mouth normals separately |

### Pitfall six: a preview rig for an agent must, by default, make geometric discontinuities visible

Measured in practice (three team members all complained): a white material on a white background gives a "**white on white**" preview — panel seams, weld seams and part divisions are all invisible, and panel-level QC is impossible — in the end the team members themselves changed it to "**gray material + strong sun from one side**" before anything was visible.

**Configure it this way by default** (write it into your `lib/preview.py` instead of tweaking it ad hoc every time):

- Material: neutral gray (`Base Color ≈ 0.18`, `Roughness ≈ 0.6`, `Metallic = 0`), **not pure white**;
- Lighting: **a strong sun from one side** (45° oblique, hard shadows with `angle ≈ 1–3°`) + very weak ambient — hard shadows reveal a 1–2mm step;
- Background: mid gray or a gradient, not pure white / pure black (the former eats the highlights, the latter eats the shadows);
- Part-level QC: use `mode="parts_color"` for per-part coloring + a legend; it makes "a piece is missing / installed backwards" easier to spot than "one gray for the whole thing";
- **At least two camera positions every time**: one "hero position" (does it look right) + one "45° oblique inspection position" (seams, floating, interpenetration).

Criterion: **if you cannot tell where the panel seam is in an image, that image cannot serve as QC evidence**.

### A.5. Modifier stack order and symptom table

> ★ **Correcting a hard-coded "fixed chain"**: the old version had people "memorize" this sequence —
> `Mirror → Array → Solidify → Bevel → Subdivision Surface → (Boolean when needed)`.
> **No such general order exists.** The modifier stack is an **evaluation chain ordered by the target function**: for the same base mesh,
> merely swapping the order of two or three entries **changes both the topology and the dimensions**. Measured in practice (Blender 5.2.2, the same 1m cube):

| Order | verts / faces | bbox longest edge |
|---|---|---|
| Bevel(0.2/2 segments) → SubSurf(2) | **866 / 864** | **0.9904 m** |
| SubSurf(2) → Bevel(0.2/2 segments) | **98 / 96** | **0.8395 m** |
| Solidify(0.03) → Bevel(0.05/2 segments) (flat) | **56 / 54** | — |
| Bevel(0.05/2 segments) → Solidify(0.03) (flat) | **8 / 6** | — |

Both results are **correct**; it depends on whether you want "the bevel preserved by subdivision" or "the subdivided low-poly then rounded";
a **15%** difference in `bbox` shows that this is not just a face-count issue. ⇒ The order is decided by the **target**, not by memory.

**How to fix the order**: work backwards from the target and ask, item by item, "what does this step consume from the previous one".

| Target | Order (relative) | Why (design intent) |
|---|---|---|
| A mirrored part must read as one solid | **Mirror first**, Bevel / SubSurf after | so that the mirror seam is welded into a continuous surface first, then beveled/subdivided uniformly; reversed, the seam is treated as a free edge |
| Every cell of a repeated array carries its own bevel | **Bevel first**, Array after | the later stage only copies the result of the earlier one; reversed, the bevel acts on the seams of "the whole row" |
| Thin shells (sheet metal / housings) need rounded edges | **Solidify first**, Bevel after | there must be thickness before there is a "solid edge" to bevel; measured in practice, reversed, the bevel is almost entirely eaten (54 faces → 6 faces) |
| Smooth surfaces that must keep their edges | **Bevel first**, SubSurf after | the bevel provides the support edge so that subdivision does not round the edge away (recipe 2b) |
| Faceted hard surfaces (armor plates / military models) | **No SubSurf** | subdivision rounds every edge into "soap" → take recipe 2a (small bevel + flat shading) |
| Boolean holes | Boolean **as late as possible**, apply right before export | keeps it non-destructive; the n-gons after a boolean also affect later subdivision |
| Mirror after the topology is final | **apply Mirror before changing topology** | once the topology changes, the alignment of the mirror seam is no longer guaranteed |

**Whether the order is right is decided with the receipt** (not by memory): `evaluated_get(depsgraph).to_mesh()` to get the evaluated
`verts / faces / bbox` and compare them against your target; then add the numeric gates of Appendix A.6. **Change the order and you re-run the gates.**

Additional rules: keep booleans live until just before export; apply the mirror only after the topology is final; **do not stack multiple subsurf levels without support edges**; apply scale (Apply Scale) before boolean / export.

| Symptom | Fix |
|---|---|
| It obviously looks like the default cube | add Bevel (0.02m / 3 segments) + SubSurf (**smooth parts only**) |
| **Armor edges rounded off, looks like a plastic toy** | a faceted part wrongly used SubSurf → delete the SubSurf, switch to recipe 2a (small bevel + flat shading) |
| Pinching appears on a circular form | Bevel must come **before** SubSurf |
| Black faces in the render | recalculate the normals (Pitfall five); check the signed volume first to see whether they point inward overall |
| Boolean produces n-gons | after applying the boolean, go into edit mode and turn them back into quads, then SubSurf |
| Symmetry broken | use the Mirror modifier, do not duplicate and flip |
| **Invisible interior faces / faces buried inside a solid in the mesh** | ★ **it is not `Delete Loose`** (it only deletes "verts/edges that belong to no face" — not a single face) → see the dedicated item below |
| Wrinkling / collapse after subdivision | missing support edges: add loop cuts to pin the structure, do not keep adding subdivision levels |
| Array ends do not line up (tracks / chain links) | the `FIT_CURVE` array in this recipe's convention cannot give an exact closed-loop pitch → recipe 6b's parameterized **pin chord length** path |
| ops throws a context/poll error under headless | Pitfall four: switch to bmesh / the data API, or use temp_override |

### A.5.1 The correct way to "delete interior faces" (★ the old version taught this wrong here)

The old version's symptom table said "invisible interior faces in the mesh → Clean Up → **Delete Loose**". **That is wrong**:
`Delete Loose` only deletes **vertices and edges that belong to no face** — it **does not delete a single face**.

**Measured in practice (Blender 5.2.2)**, for the two interior-face scenarios Blender itself prints a single `Info` line:

| Scenario | Interior faces | After running `delete_loose` |
|---|---|---|
| A loose floating quad stuffed inside a cube | 1 | `Info: Removed: 482 vertices, 992 edges, **0 faces**` → that face is still there |
| Two overlapping cubes joined (each shell has one face buried in the other) | 2 | `Info: Removed: 0 vertices, 0 edges, **0 faces**` → the face count is still 12 |

While we are at it, the second common misconception falls too: `bpy.ops.mesh.select_interior_faces()` **does not solve** this problem either —
for the overlapping pair produced by that join above it selects **0** faces (it only works for the case where "every edge has >2 face users").

**Correct approach (by cause)**:

```python
import bpy, bmesh
from mathutils.bvhtree import BVHTree

def buried_faces(obj, eps=1e-5):
    """Faces buried inside a solid: cast a ray from the face center along the **outward normal**; a hit = that face is occluded by other geometry.
    (clean cube -> 0; two overlapping cubes joined -> exactly 2)"""
    bm = bmesh.new(); bm.from_mesh(obj.data)
    bvh = BVHTree.FromBMesh(bm)
    out = []
    for f in bm.faces:
        c = f.calc_center_median() + f.normal * eps
        loc, nor, idx, dist = bvh.ray_cast(c, f.normal, 1e6)
        if idx is not None:
            out.append(f)
    bm.free()
    return out
```

| Cause | Correct handling |
|---|---|
| **Overlapping shells produced by join / duplication** (most common) | **Boolean UNION** (or the Boolean in `mesh.intersect`) to merge the two shells into one solid; **do not use "select and delete"** — measured in practice, deleting the buried faces leaves **8 open edges** (the shell is punctured) and you still have to fill them back in |
| Fragments left behind by the boolean solver | re-run with `solver='EXACT'`, or `fix_repair` (`merge_doubles` + `dissolve_degenerate` + `delete_loose` + `recalc_normals`) — note that here `delete_loose` does what it **actually** should do (clean up isolated verts/edges) |
| An inner wall made by accident while modeling | find and delete it with `buried_faces()` above; **after deleting you must fill the holes or switch to a boolean**, and re-check `audit_mesh`'s `boundary_edges` |
| Cause unknown | run `audit_mesh` first and look at `self_intersections` / `nonmanifold_edges` / `boundary_edges` — **`self_intersections` is the machine criterion for "penetrating into each other"** |

**Criterion**: after deleting interior faces `audit_mesh` must still report `clean=true` (`boundary_edges=0` / `nonmanifold_edges=0`).
Watching only "the face count went down" while ignoring open edges amounts to trading interpenetration for a broken surface.


### A.6. Numerical gate checklist (go through it item by item before delivery / handoff) ★**This section is the single authoritative gate table**; every other section refers to it

> In v1 this section held only a "cleanup checklist"; measured in practice, **acceptance by eye is unreliable** — so here every criterion is paired with a runnable command and fields.
> For a single-part delivery run ①–④; after assembly is complete run ①–⑧. **A missing field = it was not run**.
>
> ★ **Three-state convention (current version, one state more than "red/green")**: `audit_mesh` / `audit_scene` return a top-level `state` (equivalent field `verdict`) = `pass` / `fail` / `degraded`.
> `clean` is tightened to "**checked completely and free of defects**" ⇒ when `degraded`, `clean=false`. **`clean=false` has two causes** (a real defect / the check did not finish),
> and you must read `state` + `reason`; the handling for `degraded` is a **follow-up check** (neither letting it pass nor treating it as a failure).

| # | Gate | Criterion | How to run (command → fields to read) |
|---|---|---|---|
| ① | Duplicate vertices / loose geometry | 0 isolated verts, 0 loose edges | `audit_mesh` → `totals.loose_verts=0` **and** `totals.loose_edges=0` (+ `remove_doubles`) |
| ② | Manifold | 0 non-manifold edges (except intentional openings) | `audit_mesh` / `audit_scene` → `totals.nonmanifold_edges=0`; ⚠ `audit_scene` by default **does not run self-intersection** ⇒ `state=degraded`, so to use it as a gate you must pass `self_intersect=true` |
| ③ | Open edges | 0 open edges (closed-part convention) | `audit_mesh` → `totals.boundary_edges=0`, `objects[i].closed=true` |
| ④ | Normals | **per connected shell** consistently outward (not "overall `signed_volume > 0`") | `audit_mesh` → `objects[i].normals_state` (`pass`/`fail`/`unknown`/`n/a`) + `normals_shells[]` (per-shell `state`/`signed_volume`/`nested`); ⚠ `closed=false` ⇒ `normals_outward=null` (an open mesh has no such thing as an "overall orientation"); `normals_state=unknown` ⇒ **no pass is given** (with no other defects `state=degraded`, with defects `state=fail`, read `normals_reason`) |
| ⑤ | Dimensions | key bbox deviation from `spec.py` ≤ tolerance (scale-model grade ±3mm) | `audit_measure` → `items[].size_mm` |
| ⑥ | Floating parts | 0 hanging parts (a visible floating chunk = longest bbox edge ≥ 1% of the whole model) | `audit_connectivity` → `gate.state=pass` **and** `floaters=[]` (⚠ the top level has **no** `state`; **do not use "component count = 1" as the criterion** — touching but unwelded is naturally multi-component) / `audit_snap_floaters` (report-only by default) / the `state` of `audit_gate` |
| ⑦ | Interpenetration | no abnormal mutual penetration; allowed hidden overlaps whitelisted | `audit_interference` → `verdict` + `volume_mm3` (⚠ `unresolved` = **cannot be decided**, not "no interference"; conforming contact often returns `unresolved`) + `audit_overlap` → `pair_count` (⚠ conforming contact gives ≥1; `analyzed=false` ≠ no overlap) |
| ⑧ | Hidden overlap | per-interface overlap amount matched to the `overlap_mm` **stated explicitly in this spec** (pitfall two: **no universal multiplier / percentage / lower bound**; do not change the visible silhouette, do not pierce thin shells) | `audit_measure` → `pairs[].axis_overlap_mm` (**a coarse screen only, valid when the interface normal aligns with a world axis and axis-aligned boxes apply**; for rotated interfaces measure the real surface along the interface's local coordinates) + `audit_connectivity` (if the same pair is also reported as floating, the "overlap" does not hold) |
| ⑨ | Form | fixed-camera comparison renders + numerical bbox (both required) | `qc_render_views` (fixed camera + `max_size=900`) + `audit_measure`; **IoU judges the silhouette only**, for blind spots see §0.6.2 |
| ⑩ | Face count | against the triangle budget | `tris` of `audit_scene` / `audit_gate` (read the number only, not the state) |
| — | Evidence archive | void as soon as the source changes | `fingerprint.digest` + the md5 of the `.blend` |

**MUST**: stay non-destructive up to the export stage; name an object the moment it is created (GEO- prefix); keep blockout separate from the final product; apply transforms before boolean / export;
**with multiple agents, freeze spec.py and the interface table first**; every part delivery carries numerical evidence.
**MUST NOT**: delete the blockout before the silhouette is approved; apply all modifiers too early; leave default names; start modeling without a scale reference; skip cleanup;
**accept the form from a single finished render**; **draw interpenetration conclusions before normals are verified**; **use single-view IoU as "does the whole thing look alike"**.

### A.6.1 Must-run before handoff (P0-4): three commands + one receipt

Copy the commands verbatim; **for criteria and fields always consult the table in Appendix A.6** (this section does not repeat the gate table).

```python
# ① mesh health of a single part / collection (boundary / nonmanifold / degenerate / loose / self-intersections / normals)
blender_rt_plan(op="audit_mesh", args={"scope": "COL_Geo"})
# ② shipping gate: connectivity + envelope (★ assembly convention; if there is only a single part, use ① only)
blender_rt_plan(op="audit_gate", args={"scope": "COL_Geo", "envelope": [x0, y0, z0, x1, y1, z1]})
# ③ interpenetration / interference (pair by pair; hidden overlaps allowed by design must be whitelisted)
blender_rt_plan(op="audit_interference", args={"a": "GEO-rungear", "b": "GEO-hull"})
# ④ whole-scene first pass (★ delivery acceptance must explicitly enable the self-intersection check: it is not run by default ⇒ state=degraded, no pass obtained)
blender_rt_plan(op="audit_scene", args={"summary_only": True, "top_k": 10, "self_intersect": True})
```

> ★ **The self-intersection switch of `audit_scene` (measured in practice, current version)**: by its performance contract it **defaults to `self_intersect=false`** (a cheap first pass),
> and then no matter how clean the scene is, the receipt is `state=degraded` + `clean=false` + `warn: "DEGRADED ≠ pass"` +
> `hint: "Rerun with self_intersect=true for a complete verdict"` — **"check skipped" must not be read as "no problem"**.
> ⇒ **for the delivery/acceptance convention always pass `self_intersect=true`** (the cost scales with face count); a daily first pass that only asks "which ones are dirtiest" may leave it off,
> but then you **must not** treat the receipt as a gate.

**For the acceptance receipt template + three hard rules see §0.5.5** (including how to write the `.blend` md5 and `fingerprint.digest`).

**Three conventions (measured in practice, do not mix them up)**:
1. `audit_mesh` reads the **unevaluated `ob.data`** — unapplied modifiers do not count (a half part with a Mirror reports the base mesh's `verts=4 / boundary_edges=4`);
   the assembly-level `audit_connectivity` / `audit_gate` / `audit_measure` / `audit_interference` use the **evaluated mesh** (an unapplied Boolean still counts). To use `audit_mesh` to judge "is the change done", apply the relevant modifiers first.
2. `ok=false` / `analyzed=false` / `state="degraded"` **are not a pass** — they mean "not run" or "not fully analyzed", and must not be read as "no problem".
3. **`clean=false` has two causes**: `state=fail` (a real defect, look at the non-zero count fields in `totals`) or `state=degraded` (not finished / cannot be decided: self-intersection skipped or threw, `normals_state=unknown`, per-shell analysis exceeded the face limit). On getting `clean=false` **read `state` first**, then decide whether to "fix the geometry" or "run the follow-up check".

### A.6.5 Rendering / animation / long-running jobs (★ new in v7, added from measured work on the "QBZ-191 full disassembly video")

> §0–§3 and Appendices A.4–A.6 govern **whether the shape is right**; this section governs **whether the frame is right and whether the job can finish**.
> The two have completely different failure modes, and the pitfalls of the render stage are **more subtle**:
> get the geometry wrong and `audit_mesh` turns red; **get the framing wrong and it just quietly hands you a cropped image**.

### A.6.5.1 Framing: bounding-box estimation is not allowed, a per-frame projection self-check is mandatory ★highest value in this section

**Measured incidents (QBZ-191 exploded view, two rework rounds)**:

| Symptom | Root cause |
|---|---|
| All 4 exploded views cropped | Estimated camera distance from the axis-aligned AABB's `dx/dy/dz` — **the projection extent of a 3/4 view has nothing to do with those three numbers** |
| Framing off by **2.2×** | Changed `obj.location` but did not refresh the dependency graph ⇒ `bounds_all()` read the **pre-explosion** matrix (framed for 949 mm, actual 2129 mm) |
| Iteration diverged to `dist=6.1e15` | The **sign of the centering term in the hand-derived solution was flipped** (should add, not subtract) |
| Same divergence | Vertex samples were in **meters** and the bounding box in **millimeters**, and the two were mixed |

**Rule one: always solve camera distance / viewpoint from the post-projection screen extent, never from the AABB.**

```python
def cam_basis(direction):                       # d = target->camera; fwd = -d
    d = Vector(direction).normalized(); fwd = -d
    up = Vector((0, 0, 1))
    if abs(fwd.dot(up)) > 0.995: up = Vector((0, 1, 0))
    Z = -fwd
    Y = (up - Z * up.dot(Z)).normalized()
    X = Y.cross(Z).normalized()
    return d, fwd, X, Y, Z

def fit_view(bb, direction, lens=70, res=(1920, 1080), margin=1.18, points=None, iters=40):
    d, fwd, X, Y, Z = cam_basis(direction)
    tan_h = (36.0 / 2) / lens                                     # sensor 36mm
    tan_v = tan_h * (res[1] / float(res[0]))
    pts = points or [Vector((x, y, z)) for x in (bb[0], bb[1])
                     for y in (bb[2], bb[3]) for z in (bb[4], bb[5])]
    look = Vector(((bb[0]+bb[1])/2, (bb[2]+bb[3])/2, (bb[4]+bb[5])/2))
    dist = max(bb[1]-bb[0], bb[3]-bb[2], bb[5]-bb[4]) * 1.8 + 1.0
    target = 1.0 / margin
    for _ in range(iters):
        C = look + d * dist
        k, nx, ny, behind = 0.0, [], [], False
        for P in pts:
            V = P - C; dep = V.dot(fwd)                            # depth along the positive view direction
            if dep <= 1e-6: behind = True; break
            ax = V.dot(X) / (dep * tan_h); ay = V.dot(Y) / (dep * tan_v)
            nx.append(ax); ny.append(ay); k = max(k, abs(ax), abs(ay))
        if behind: dist *= 1.8; continue                           # a corner ran behind the camera
        dist *= (k / target) ** 0.85                               # nx,ny ∝ 1/dist
        cxm = (min(nx)+max(nx))/2; cym = (min(ny)+max(ny))/2
        look = look + X*(cxm*dist*tan_h) + Y*(cym*dist*tan_v)      # ★sign: add, not subtract
        if k <= target*1.002 and abs(cxm) < 0.004 and abs(cym) < 0.004: break
    return dist, (look.x, look.y, look.z)
```

**Rule two: after placing the camera you must verify, and what you verify is the projection, not "it looks about right".**

```python
# per-frame framing self-check: max NDC must be <= 1.0 (=1.0 means touching the edge)
sc.frame_set(f); bpy.context.view_layer.update()        # ★not refreshing the dependency graph = reading a stale matrix
mw = cam.matrix_world; C = mw.translation
X = mw.col[0].to_3d().normalized(); Y = mw.col[1].to_3d().normalized()
fwd = -mw.col[2].to_3d().normalized()
tan_h = (36.0/2)/cam.data.lens; tan_v = tan_h*(RES[1]/float(RES[0]))
for o in objs:
    for v in [o.data.vertices[i] for i in range(0, len(o.data.vertices), 14)]:   # ★step=14, same convention as fit_view
        V = (o.matrix_world @ v.co) - C; dep = V.dot(fwd)
        assert dep > 1e-4, "a corner ran behind the camera"
        worst = max(worst, abs(V.dot(X)/(dep*tan_h)), abs(V.dot(Y)/(dep*tan_v)))
assert worst <= 1.0, "cropped: worst NDC=%.3f" % worst
```

> ⚠ **The sampling density must match `fit_view`**. My first self-check took only 20 points per part and measured `0.737`,
> while the true value was `0.847` — **the self-check itself was lying to me**. A self-check looser than the thing it checks is no check.
>
> **Measured convention**: still-frame acceptance `worst <= 1.0`; final-video padding `margin 1.12–1.24` (corresponding to `worst ≈ 0.80–0.89`).

**Rule three: unify the units first.** `kit.bounds_all()` returns **mm**, `matrix_world @ v.co` is **m** — mix them and you get `dist=6.1e15`.
Anywhere vertices and the bounding box are mixed, `* 1000` first.

### A.6.5.2 Exploded view / disassembly animation: position, amplitude, floor, order

- **After changing `obj.location` you must call `bpy.context.view_layer.update()`**, otherwise `matrix_world` is still stale
  (the root cause of incident 2 in Appendix A.6.5.1). It is especially fatal for animations that compute a bounding box every frame.
- **Set the "total span" first, then distribute each part's displacement proportionally**; do not hand-tune part by part. Target **≈1.4–1.6× the object length**;
  measured in practice at 2.2× (2129 mm vs a 946 mm gun length) the parts went **tiny as star dots**, and a uniform scale of 0.42 → 1445×904 mm was needed before the skeleton read.
- **The floor eats the whole frame**: disassembled parts drop below the studio floor (measured Z down to −1146 mm).
  For disassembly / internals shots always put the floor away with `hide_render = True` and use a gradient world as the background.
- **One "reference part" must stay still** to give the viewer a frame of reference (mine was the upper receiver).
- **In the wave table, specific names must come before generic names**: `bolt_carrier` / `bolt_cam_pin` / `bolt_catch` must all come before `bolt`,
  otherwise `bolt` swallows them all. Likewise `buffer_tube` must come before `buffer`, and `trigger_guard` before `trigger`.
- **The wrap-up must print the unmatched list**; only `UNMATCHED []` means every part got scheduled (otherwise some part silently stays still).
- **Easing**: for a mechanical feel use **ease-out** (`1-(1-u)**2.4`), sampling 8 segments to place keyframes; it reads more like "coming apart" than the default Bezier.

### A.6.5.3 Long-running jobs (>2 min): must be interruptible by default ★

**Measured in practice**: the backend restarted during a 10-minute render ⇒ `blender_rt_job(op="wait")` returned `Error: terminated`,
and the job became `stale: pid no longer exists`. **This is the normal case, not an exception.**

**Rules (every one of them has saved time)**:
1. Write output to a fixed `outdir` **named by frame number** (`seq_0001.png`);
2. Before rendering `if os.path.exists(p) and not FORCE: continue` — **if it exists, skip it**;
3. Provide `--force` to start over. **"Resumable" is the first property of a long-running job, not an optimization** —
   measured in practice, re-rendering 1 frame of a 301-frame video took **6 seconds** instead of re-running 10 minutes;
4. Print progress every N frames + **measured s/frame + ETA**; compute the ETA from the **number of frames already rendered**, not from the loop index (the latter lies to you on a resume);
5. **Drafts and finals must live in separate directories**: otherwise "skip if it exists" takes a 480p draft for a 1080p final frame;
6. **Know which registry owns the job handle**: `as_job=true` returns a **Blender-side ledger id**, collected with `blender_rt_job(op=wait/collect)`;
   passing it to DSH's `job_output` returns `unknown job` (two separate registries).

### A.6.5.4 Render cost: measure 3 frames first, then schedule

**Measured model** (Cycles/OptiX + denoising, 138 parts / 191k faces, every part moving on every frame, RTX 4060 Laptop):

| Resolution | Samples | s/frame |
|---|---|---|
| 1920×1080 | 64 | 1.78 |
| 1920×1080 | 128 | 2.00 |
| 1920×1080 | 256 | 2.50 |
| 1920×1080 | 320 | 2.45 |
| 3840×2160 | 320 | 9.71 |

**Key conclusion: about 60% of a frame is fixed overhead** (scene evaluation + BVH rebuild + denoising + PNG write).
So **"save money by lowering samples" is nearly useless** (320 → 64 saves only 30%); **the real lever is frame count = duration × frame rate**;
resolution is close to linear in pixel count (4K ≈ 3.8 × 1080p). **Before scheduling, spend 1 minute rendering 3 frames as a measurement; do not apply someone else's numbers.**

⚠ **In Blender 5.2 `use_persistent_data` lives on `scene.render`, not on `scene.cycles`.**
Wrapped in `try/except` it becomes a **silent failure** (I failed **26 times** in a row before noticing) —
**no setter is allowed to fail silently; you must read back and verify** (the same discipline as "a silent empty output must fail" in Appendix A.6):

```python
sc.render.use_persistent_data = True
assert sc.render.use_persistent_data is True, "did not take effect: the property may be on another object"
```

### A.6.5.5 Video: low-frame-rate render + optical-flow interpolation (3× cheaper, but measure the per-frame displacement first)

**The criterion is not "I think it moves" but "how many pixels of displacement per frame"**:

```
px_per_frame = part_total_travel_mm / (duration_s × render_fps) ÷ (frame_width_mm / frame_width_px)
< 30 px/frame  ⇒ optical-flow interpolation is essentially lossless
> 80 px/frame  ⇒ tearing / ghosting begins
```

Measured in practice (1080p, frame width ≈1450 mm mapped to 1920 px): the most violent part was **17 px/frame** ⇒ render at 10 fps, output at 30 fps, safe.

**Acceptance requires a ground-truth comparison**: have the renderer **render the real timeline frame that each interpolated frame corresponds to separately** as ground truth, and compare pixel by pixel.

| Comparison | PSNR |
|---|---|
| Source frames passed straight through (verifies the pipeline is lossless) | **51.6 dB** |
| **Interpolated frames vs ground truth** | **40.1 / 40.4 dB** |
| Decoded frames after encoding vs source PNG | 43.0 dB |

The residual error concentrates in **subpixel aliasing on high-frequency edges** (rail teeth, grip serrations); **enlarging the search window does not help** (40.13 → 40.20 dB)
⇒ **this is the inherent cost of low-frame-rate sampling, not a parameter problem; stop tuning parameters**. At 3× magnification it is visually indistinguishable.

```bash
# for continuous single-shot motion use scd=none; do not let scene-change detection mistake it for a cut point
ffmpeg -start_number 1 -framerate 10 -i seq_%04d.png \
  -vf "minterpolate=fps=30:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1:scd=none" \
  -fps_mode cfr -frames:v 900 -c:v libx264 -preset slow -crf 15 -pix_fmt yuv420p out.mp4
```
> ⚠ ffmpeg 7: `-vsync vfr` conflicts with `-r` (it reports `One of -r/-fpsmax was specified together a non-CFR`); use `-fps_mode cfr` instead.
> ⚠ Leave 3 extra frames on the timeline, otherwise the 30 fps output comes up 2 frames short of a full 30.000 s.

### A.6.5.6 Blender 5.2 API changes (measured in practice, they raise errors directly)

| Symptom | Cause | Fix |
|---|---|---|
| `'Action' object has no attribute 'fcurves'` | 5.2 switched to layered / slotted actions | do not iterate `action.fcurves`; to control easing **place keyframes yourself from eased samples** |
| `bpy_prop_collection[slice]: slice steps not supported` | `vertices[::n]` does not support stepped slicing | `[o.data.vertices[i] for i in range(0, n, step)]` |
| `CyclesRenderSettings has no attribute 'use_persistent_data'` | the property moved to `scene.render` | see Appendix A.6.5.4 |
| `Scene.frame_set()` expected int, not float | the frame number must be an integer | `int(1 + round(t * fps))` |
| empty mesh after `open_mainfile` in the GUI | it uses "the user's current viewport" | pass `from=` / `look_at=` to use a custom viewpoint |
| `module 'dsh_rt_kernel' has no attribute 'dsh_audit_api'` | that module **was not preloaded into the kernel** | `blender_rt_headless(..., preload="audit")`; or query what is loaded: `K.dsh_kit.kapi("audit")` (when it is not found it lists the available module names) |
| `'Scene' object has no attribute 'node_tree'` | **since 5.0 the compositor is a node group** (`scene.node_tree` was removed) | `ng = bpy.data.node_groups.new("Comp","CompositorNodeTree"); scene.compositing_node_group = ng`; first `ng.interface.new_socket(name="Image", in_out='OUTPUT', socket_type='NodeSocketColor')`, and use **`NodeGroupOutput`** for output (`CompositorNodeComposite` no longer exists) |
| `AttributeError: type ... is read-only` / `glare_type` has no effect | 5.x turned Glare's **Type/Quality into MENU input sockets**, and the parameters moved into inputs too | `gl.inputs['Type'].default_value = 'Fog Glow'`, `gl.inputs['Quality'].default_value = 'High'`, `gl.inputs['Threshold'] / ['Size'] / ['Strength']`; do not write `gl.glare_type` / `gl.threshold` |
| `Error: Node type CompositorNodeMixRGB undefined` (likewise `CompositorNodeMath` / `CompositorNodeComposite`) | 5.x removed the old Mix/Math/Composite from the compositor | **use shader nodes instead** inside the compositor tree: `ShaderNodeMix` / `ShaderNodeMath` / `ShaderNodeValToRGB` can still be created with `nodes.new`; use `CompositorNodeAlphaOver` for compositing, and `CompositorNodeColorBalance` / `CompositorNodeCurveRGB` for grading |
| `'CyclesMaterialSettings' object has no attribute 'displacement_method'` | 5.2 moved it onto the Material itself | `mat.displacement_method = 'BUMP'` (**not** `mat.cycles.displacement_method`); for alpha blending use `mat.surface_render_method = 'BLENDED'` (the enum only has `DITHERED`/`BLENDED`) |
| the console spams `Shadow buffer full (3040 / 2048)` every frame, and `scene.eevee.shadow_pool_size='4096'` **silently has no effect** | the shadow pool is an **enum** whose upper limit is exactly `'2048'` (2 GB) | ① `scene.eevee.shadow_pool_size='2048'`; ② the main fix is **removing shadow-casting lights**: `light.use_shadow=False` (point and area lights both count), keep only 2–4; ③ for large scenes lower `scene.eevee.shadow_resolution_scale` as well; ④ run it all in one line with `K.light_hygiene(apply=True)` (built in since v2.6) |


**Minimal working 5.2 compositor snippet (Fog Glow bloom; copy it as is)**:

```python
import bpy
sc = bpy.context.scene
ng = bpy.data.node_groups.get("Comp") or bpy.data.node_groups.new("Comp", "CompositorNodeTree")
sc.compositing_node_group = ng          # 5.0+: not sc.node_tree
ng.nodes.clear()
ng.interface.new_socket(name="Image", in_out='OUTPUT', socket_type='NodeSocketColor')
rl = ng.nodes.new('CompositorNodeRLayers')
gl = ng.nodes.new('CompositorNodeGlare')
gl.inputs['Type'].default_value = 'Fog Glow'      # a MENU socket, not gl.glare_type
gl.inputs['Quality'].default_value = 'High'
gl.inputs['Threshold'].default_value = 1.0
gl.inputs['Size'].default_value = 8.0
gl.inputs['Strength'].default_value = 0.45
out = ng.nodes.new('NodeGroupOutput')             # not CompositorNodeComposite
ng.links.new(rl.outputs['Image'], gl.inputs['Image'])
ng.links.new(gl.outputs['Image'], out.inputs['Image'])
sc.render.use_compositing = True
```
### A.6.5.7 Acceptance receipt for rendering / animation

```text
[Render receipt] <shot name / agent>   <ISO time>
  Framing     worst NDC = 0.804 (<=1.0)   sampling = every 14 vertices   camera key points = 21
  Resolution  1920x1080   samples 320   measured 2.02 s/frame   frames 301   total 605 s
  Continuity  all parts scheduled UNMATCHED=[]   reference part = upper_receiver (static)
  Resume      skip if it exists: this round re-rendered 1 frame / 6 s
  ⚠ Uncertainties: <list them honestly>
```

### A.7. Deep-dive reference

When you need precision beyond the recipes, read `references/modeling-overview.md` (original English text; it covers: rules for choosing between the bpy.ops.mesh and bmesh APIs, the professional choice of the 8 primitives, item-by-item description of the edit-mode toolbox, the bmesh precision API, hard-surface bevel-weight workflow, the boolean toolbox, key modifiers, a complete bpy.ops.mesh quick reference, and the unfinished items the author flagged himself).

When to read it: the recipe does not match (you need bmesh-level precision or custom operations); topology requirements are stricter than usual (animation-ready, game LOD); performance sensitive (foreach_set, batch operations); you need an operator the recipes do not list.

**`references/multiview-calibration.md`** (bundled with this skill): a runnable script for joint calibration from three views (pure standard library, self-check with `--selftest`) + criterion table + point-picking rules + a self-proving convention for "how do I know the calibration is right" — read it when you go through §0.6.1.

### A.8. Sources and license

This skill is a merged rewrite of the **modeling-workflow portions** of the following two MIT-licensed projects; every tool call was replaced with the local `blender_rt_*` direct-connection chain:

- **RobLe3/cc-blender-skill** (`blender-modeling` and its `references/overview.md`) — decision tree, recipes, pitfall table, deep-dive reference
- **arjun988/blender-skills** (`blender-modeler`) — the six-step outline, collection structure, modifier rules, cleanup checklist, MUST / MUST NOT

Full attribution and license are in `NOTICE.md` in the same directory. The upstream originals target MCP (mcp__blender__*); this version has been rewritten for the local direct-connection toolchain.
