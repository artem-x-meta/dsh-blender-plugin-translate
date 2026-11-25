# Procedura → dsh-blender-plugin fusion analysis

> Subject: [SpatiaOS/Procedura](https://github.com/SpatiaOS/Procedura) (MIT, Agentic 3D Modeling with Procedural Control)
> Analysis date: 2026-09-17 · Basis: the repository's raw sources (already mirrored locally in `.procedura-ref/`) plus a side-by-side check of the current plugin's `runtime/*.py` and `src/index.ts`
> Conclusion first: **do not port its code stack (TS + OpenSCAD + Isaac), port only the "criteria and algorithms".** The current plugin is strong in "single-object mesh audit + pixel-level QC + contract/evidence/transaction"; Procedura is strong in "multi-object assembly-level criteria + numeric change measurement + verdicts invalidated by geometry" —— the fusion fills exactly the second half.

## Landing status (v0.9.0, 2026-09-17)

| # | Capability | Landing point | Measured in practice |
|---|---|---|---|
| — | Wire up the `audit_*` / `montage` routes (**finding: the audit op in the docs was never wired**) | engine.mjs + server.mjs | `audit_help` now actually answers |
| 1/2 | Connectivity gate + floater attribution + mesh-level re-check | audit.py `audit_connectivity` | cockpit: 0.3mm caliber → 178 floaters / 970 touching; 2mm → 63 |
| 3 | Micro-gap grading + snap (whole-part translation only) | audit.py `audit_snap_floaters` | self-check dry_run passes; falls back to mesh level automatically when bbox reads 0 |
| 4 | Shape drift measurement (BVHTree point-to-surface) | audit.py `audit_drift` | 20k samples 21,397 ms → **46 ms**; the same mesh reads 0.000000 |
| 5 | Render device line | qc_render.py | every jsonl line records the actual device (EEVEE→GPU + model string) |
| 6 | Per-part color rendering | qc_render.py `mode="parts_color"` | legend 5 rows == 5 parts; hue hits [1658,418,420,460,496] |
| 7/8 | Evidence fingerprint invalidation + verdict drift downgrade | contract.py (v3) | contract self-check 24 → 33 items; change the source → stale=true |
| 9 | Measurement pack | audit.py `audit_measure` | bbox/per-axis gap/neighbors (contract graph + spatial K) |
| 10 | Mate gate + feature library | contract.py `mate_check` / `fit_help` + assembly_features.json | one-side median 0.1498mm (design 0.1500) → supported; mate self-check 57 items |
| 11 | Interference upgrade | contract.py `interference_report` | depth 4.0mm/volume 400.0002mm³; planned contact exempted |
| 12 | Pending-edit transaction | txn.py (v3) | accept needs verified + re-check; revert is budget-free + debounced; txn self-check 55 items |
| 13 | Delivery export | deliver.py (new) | unit box + multi-group OBJ/MTL + manifest; change one byte → FAIL; self-check 53 items |
| 14 | View catalog + aliases | qc_render.py `qc_render_catalog` | 22 views / 4 groups; unknown names are no longer silently treated as iso |
| 15 | Trajectory JSONL | engine.mjs | one line per call; rotates past 16MB; disable with DSH_TRAJ=0 |
| 16 | Large-mesh protection + three-state | audit/contract | over the limit → `analyzed:false` / `attached:null` → the gate degrades |
| 17 | Mechanisms: joint measurement + sweep + URDF/USDA | motion.py (new) | axis angle 0.00°; a sweep hitting the stop block → refuted, naming MS_Blocker; URDF structural self-check fully passes |
| 18 | Code-driven modeling channel (lightweight version) | generator.py (new) | reproduction in a fresh process = compile gate; cache hit ms=0; change the source → the receipt expires |
| — | Not ported: vendor/harness, stage prompts, results-server, Isaac, FDM tolerances | — | skipped per the assessment |

**Infrastructure problems fixed along the way**: multiple preload modules overwrote each other's helpers (the engine now gives each its own namespace);
headless `ok:true/exit=0` ≠ script success (Blender's exit code is still 0 on an exception); the source-injection channel had no `__file__`.

**Not done / to be assessed**: real OpenSCAD/Manifold integration (neither side is installed on this machine; only with it can you get "a real CSG kernel + large boolean operations");
Isaac physics validation (not adopted per the assessment); `mate_check` writing state automatically (currently read-only).

## 0. Current-state comparison (who has what)

| Capability area | Current dsh-blender-plugin | Corresponding piece on the Procedura side |
|---|---|---|
| Mesh audit | `audit.py`: boundary/non-manifold/degenerate/self-intersection/normals/loose/duplicate/bounding box (single object) | `mesh/connectivity.ts` (cross-body connectivity), `mesh/stl.ts` |
| Interference/clearance | `contract.py`: `c_check_envelope`, `c_check_interference` (AABB+BVH), `c_check_interface` (**only down to bbox-level gap**) | `mesh/collisions.ts` (pairwise + grouped), `motion/geometry.ts` (triangle-level contact area/penetration) |
| Floater/detached part | **none** | `connectivity.ts` + `floater-attribution.ts` + `snap-floaters.ts` |
| Change measurement | `txn.py` can only save and roll back, it cannot quantify "how much changed" | `mesh/chamfer.ts` (symmetric Chamfer distance = mesh drift) |
| Image QC | `qc.py` (IoU/Dice/profile difference/alignment), `qc_render.py` (multi-view + lighting + budget + md5) | `render/{ao,parts_color,pbr}.ts` + three Blender scripts |
| Assembly semantics | `planner.py` component/connection/candidate, `contract.py` component/connection/envelope/evidence ledger/three-state verdict | `lib/assembly.scad` (mate feature library + fit tiers), `pipeline/assembly-seed.ts` |
| Articulation/mechanisms | **none** (zero hits for urdf/usda/articulation) | `motion/{urdf,usda,geometry}.ts` + `isaac_validate.py` |
| Delivery export | no unified delivery-mesh convention (outputs are png/json/.blend) | `mesh/normalize.ts` + `mesh/obj-mtl.ts` (unit box + multi-group OBJ/MTL) |
| Process traceability | CHANGELOG + evidence ledger | `_trajectory/*.jsonl`, `trajectory/emitter.ts` |

Cost caliber: XS <1h · S within half a day · M 1–3 days · L 1–2 weeks+

---

## 1. P0 — low-hanging fruit (pure Python, bpy-native, landable in a single session)

| # | Capability | Procedura source (key constants) | Fusion landing point | Cost | Benefit | Risk/boundary |
|---|---|---|---|---|---|---|
| 1 | **Disconnected-component (floater) gate** | `connectivity.ts`: `VISIBLE_SPAN_FRACTION=0.01`, `MICRO_GAP_MM=0.3`, `evaluateConnectivityGate`, `MAX_ANALYZE_TRIS=4e7` + the three-state `analyzed` | new `audit_connectivity(scope)` in `audit.py`: BMesh face adjacency → connected components (tri/volume/bbox/spanFraction); `contract.verify` consumes it as a factory gate | S | Turns "did the assembly actually take shape" from looking at images into a criterion; separates "photographic-level gaps" from "a part really fell off" | A mesh ceiling is mandatory and "not analyzed" must be labelled separately —— **never read not-analyzed as connected** (they were burnt by an 8–12h hang over this) |
| 2 | **Floater → component attribution** | `floater-attribution.ts`: bbox overlap ratio scoring, `confidence`, `moduleFraction`, `alsoOverlaps≥20%` for clusters drifting together | the component (semantic object group) in `contract.py` is naturally the attribution target; output `flt01 (span 3.2%) → component seat_rail [82% overlap]` | S | Upgrades from "there is a floater" to "which object/component to change"; saves trial and error in long sessions | bbox overlap is an approximation (the authors say so themselves), spanFraction must always be given alongside for re-check |
| 3 | **Micro-gap grading + snap** | `connectivity.floaterGapsMm` + `MICRO_GAP_MM` + `scad/snap-floaters.ts` | reports split "real gap / micro-gap (touching but not coincident)"; new `snap_floaters` op (dry-run by default) | S–M | The gate is not stuck on dozens of micro-gaps; 0.1mm-level gaps close in one step | translation touches modifiers/parenting → must go through a txn snapshot + dry_run |
| 4 | **Mesh drift measurement (symmetric Chamfer distance)** | `mesh/chamfer.ts`: normalize each → area-weighted sampling of 20k points → spatial-hash NN, deterministic seed; noise floor ≈0.01–0.02 | new `qc_mesh_drift(a,b)` (numpy is enough, reads .obj or an evaluated mesh), hooked to `txn.mark → change → revert` | S | **A numeric re-check path independent of rendering** (exactly what your loop's anti-Goodhart requirement wants); quantifies "how much this change moved" | Measures drift only, not quality; sample count and seed must be fixed for cross-run comparison |
| 5 | **Render device line** | `_blender_gpu.py` prints `[render] device:`; `device_line.ts` keeps it in the log (guards against a silent ≈7× CPU fallback) | add `device` to every jsonl line of `qc_render`; backfill into `perf.status` | XS | A silent 7× performance regression becomes visible | none |
| 6 | **Per-part color rendering** | `render/parts_color.ts` + `_render_parts_color_blender.py`: a 12-color cycle, one color per part, `parts_color_meta.txt` legend, per-part roughness/metallic overrides | add `mode="parts_color"` to `qc_render.py` (material override, restored after rendering) | S–M | Assembly relations/interpenetration/floating/mirror misalignment are readable at a glance, with far higher information density than an AO image | The override must be restored after rendering (you already have a site-restore discipline); do not pollute the finished .blend |
| 7 | **Evidence invalidated by changes** | `tools/state.ts`: `stlIsStale / hasFreshDiagnosis / pendingEdit`; accept enforces "compile+render first, only then may it be accepted" | bind every piece of evidence in `contract.ledger` to "object set + geometry fingerprint"; any write marks the related evidence stale, and only re-verification makes it green again | S–M | Closes off "claiming new conclusions with old evidence" —— turns the "Evidence grading and image-reading discipline" into a mechanism | Do not compute a full md5 on large meshes; use vertex count + bbox + sampled hash |
| 8 | **Drift downgrade thresholds** | `pipeline/assembly-seed.ts`: `DRIFT_CENTER_FRACTION=0.10`, `DRIFT_SIZE_FRACTION=0.20` → verdict downgraded to `unverified` | `c_verify` records the tested bbox snapshot; past the threshold it automatically sets `status: unresolved` + a reason | S | A verdict does not "quietly expire" in a long session | Parents carrying animation/shape keys/scale must be excluded to avoid false downgrades |
| 9 | **Measurement pack + neighbor context** | `tools/module_context.ts`: target + neighbors (assembly graph both directions + spatially nearest K=4), real-world bbox, per-axis gap/overlap (mm and %), cached by buffer hash | new `measure_pack(objects, neighbors=true, k=4)` | S–M | The model moves from "estimate by looking" to "derive the delta arithmetically" (they measured a wrong order of magnitude = two wasted rounds) | Units (m/mm) must be declared explicitly in the return |

## 2. P1 — worth doing (half a day to a few days)

| # | Capability | Procedura source | Fusion landing point | Cost | Benefit | Risk/boundary |
|---|---|---|---|---|---|---|
| 10 | **Mate gate (measured contact area/penetration)** | `lib/assembly.scad` (peg/socket/bolt_hole/bolt_circle/boss/snap_tab/snap_window/tab/slot, the four `asm_fit` tiers, `asm_lead` lead-in chamfer) + `motion/geometry.ts` (`analyzeContactRegion`: contact distance = 1.5% of the largest diagonal, take the larger of the two directional area ratios, contactAnchor/normal; `analyzeMateRegistration`; `computeMeshVolume` to measure penetration) | ① write "shared nominal" as a contract clause (male and female share the same nominal ± fit, two independent literals are forbidden) ② an assembly-feature generator/preset recipe on the bpy side ③ upgrade `c_check_interface` from bbox to triangle-level contact area ratio + penetration volume/depth + fit tolerance table | M | Assembly goes from "looks put together" to "actually assemblable"; directly relevant to your assembly/mechanism modeling | BVH sampling is heavier on the bpy side: cap the sample points (theirs caps at 4000), and only compute for registered connection pairs |
| 11 | **Interference analysis upgrade** | `mesh/collisions.ts` (pairwise report + grouping) + `tools/collision-check.ts` (uses the plan's parent edges to suppress "planned adjacency") | change `c_check_interference` output to "per pair + depth/volume + grouped by design intent", and treat the `planner` connection graph as a whitelist | S–M | Reports are readable and locatable without false positives; multi-object triage time drops a lot | The whitelist must be switchable off explicitly (otherwise it hides real interference) |
| 12 | **Pending-edit transaction** | `tools/edit-transaction.ts`: pending → `accept_edit(verified=...)` / `revert_edit(why=...)`, revert is budget-free but capped | destructive-operation protocol: `begin_edit → operate → must re-check → accept/revert`, chained with `destructive_guard` | S–M | Eliminates "guessed the wrong order of magnitude and found out two rounds later"; naturally produces a traceable record of the reason for the change | Semantics must align with the existing `txn.mark/revert`; do not end up with two rollback systems |
| 13 | **Delivery export convention** | `mesh/normalize.ts` (unit box) + `mesh/obj-mtl.ts` (multi-group OBJ+MTL with per-part materials) | `export_deliverable`: optional unit-box normalization, per-part materials, OBJ+MTL, md5 manifest | S–M | A unified delivery format, archivable and auditable (plugs into `D:\Blender\<project>\archive-manifest.md`) | Normalization changes scale, so keep the original transform record before archiving |
| 14 | **View catalog + alias normalization** | `render/views.ts`: 16 views in 4 groups, aliases `iso`/`iso-FR-top`→`isometric`, unknown names return a warning, stable DEFAULT_VIEWS | add the same catalog to `qc_render` (you can already solve views automatically; this only adds naming/tolerance/nameability) | XS–S | Views are reproducible, comparable across sessions, and can be named directly in prompts | Just make sure it does not conflict with the existing view naming |
| 15 | **Trajectory JSONL** | `_trajectory/procedura-*.jsonl` + `trajectory/emitter.ts` | the runtime writes `<outdir>/trajectory/<run>.jsonl` (tool calls/verdicts/evidence/elapsed), merged with the qc jsonl | S | Retrospectives, cross-run comparison, an audit ledger | Volume control/redaction |
| 16 | **Large-mesh protection ceiling** | `MAX_ANALYZE_TRIS` + an allocation-free fast path + the `analyzed:false` three-state | add "over the ceiling means explicitly skip and label as not analyzed" to the connectivity/interference/drift analyses | XS–S | Prevents accidents (you measured in practice the sync cost of a 2318-object scene) | none |

## 3. P2 — strategic (heavy, depends on the goal)

| # | Capability | Procedura source | Fusion landing point | Cost | Benefit | Risk/boundary |
|---|---|---|---|---|---|---|
| 17 | **Articulation/mechanisms: URDF + USDA + kinematic graph + sweep validation** | `motion/urdf.ts` (world-baked mesh, local frame = world anchor, degenerate joints downgraded to fixed, isolated links synthesized as fixed, `BBOX_FILL_FACTOR=0.4` inertia approximation), `usda.ts`, `geometry.ts:analyzeRotationalSymmetry` (area-weighted centroid + principal axis, 3000 samples, score threshold 0.55), `isaac_validate.py` | two steps: ① purely Blender-side "joint axis/anchor measurement + driven sweep sampling + self-collision self-check"; ② then URDF/USDA export | L | Opens the robot/mechanism category (a natural extension of planetary engines and space elevators); "kinematically correct" becomes a criterion | **Do not bring in Isaac right away** (multiple GB + account gating); use Blender sweeps instead first |
| 18 | **Code-driven modeling channel (OpenSCAD/Manifold)** | the whole SCAD pipeline (compile gate + module splicing + module-level cache + triple gate) | lightweight version: simulate "modules" with collection/join hierarchy + custom properties; heavyweight version: real OpenSCAD integration | L | Reproducible, diffable, programmatically re-generatable (the parametric family is worth the most) | **A Manifold backend is mandatory** (same `hull()`: CGAL 1774s vs Manifold 1.77s); installation/path conversion on the Windows side is extra cost; two mental models |

## 4. Not recommended to port

| Item | Reason |
|---|---|
| The whole `vendor/harness/` agent runtime, 16 stage prompts | You already have DSH's own harness + prompt system; reinventing the wheel has zero benefit |
| Its `results-server` scripts | `montage.py` + `qc_compare` already cover most of it; only for a "cross-run metrics table" is its comparison approach worth borrowing |
| Isaac Sim physics validation | Heavy dependency (multiple GB + an account), marginal benefit; use Blender-side kinematic sweeps first |
| FDM tolerance values (0.25/0.15/-0.05/0.2) | They are calibrated for FDM printing; recalibrate for your process, do not copy them |

## 5. Overall benefit after fusion (compounding points)

1. **The criteria level moves up**: from "a single mesh is healthy" → "whether a multi-object assembly takes shape and is assemblable" (#1/#2/#10/#11).
2. **One more numeric path independent of rendering**: Chamfer drift + contact area + per-axis gaps, which exactly satisfies the discipline "after the inner loop converges you must re-check through another path" (#4/#9/#10).
3. **Verdicts no longer expire**: geometry fingerprints bound to evidence + automatic drift downgrade (#7/#8), so conclusions stay trustworthy in long sessions and repeated model edits.
4. **Reports go from "an image" to "numbers + image"**: parts-color images + numeric tables + attribution by name (#2/#6/#11), lowering the cost of locating problems for both the model and the human.
5. **Delivery and archiving form a closed loop**: unit box + per-part materials + md5 manifest (#13), compatible with the `D:\Blender` archiving convention.

## 6. Recommended landing order

- **Batch 1 (half a day)**: #1 connectivity gate + #2 attribution + #4 drift measurement + #5 device line + #16 ceiling protection → an immediately usable "assembly physical examination".
- **Batch 2 (1–2 days)**: #3 snap + #6 per-part coloring + #7/#8 evidence invalidation/drift downgrade + #9 measurement pack + #14 view catalog.
- **Batch 3 (on demand)**: #10 mate gate + feature library, #11 interference upgrade, #12 edit transaction, #13 delivery export, #15 trajectory.
- **Batch 4 (strategic)**: #17 mechanisms/URDF (do the Blender-side sweep first); #18 code channel (if it is decided to be done).

## Appendix: local reference mirror

The key sources are already mirrored into the workspace at `.procedura-ref/` (45 files, 604 KB, MIT), including `lib_assembly.scad`, `src_mesh_connectivity.ts`, `src_mesh_floater-attribution.ts`, `src_mesh_chamfer.ts`, `src_motion_geometry.ts`, `src_render_*.ts`, `src_tools_*.ts`, three `_render_*_blender.py`, etc., ready for side-by-side porting.
