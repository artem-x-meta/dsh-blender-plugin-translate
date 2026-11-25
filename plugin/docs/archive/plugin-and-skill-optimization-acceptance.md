# Plugin and skill optimization · independent acceptance report

> ⚠️ **Historical archive (v0.9.6 acceptance snapshot, 2026-09-26)**: this document is the independent acceptance record made at the time for **v0.9.6** and **is not the current state**;
> its **27 family / 176 op**, test counts, version numbers, hashes and other numbers **are all outdated**; do not cite them or judge the present state from them.
> For the current facts see [Chinese README](zh/README.md) and `blender_rt_plan(op="catalog")`
> (**v2.6.0**: **15 model tools** / plan catalog **33 family / 217 op** / addon v1.10 · protocol 11).
> Per the "preserve historical evidence" principle the body below is **not rewritten**; only this banner is added.

> **Lead final integration status (2026-09-26 11:38 UTC)**: the TypeScript build and type check are done, `npm test` 197 passed, 2 skipped; the backend has been restarted (pid 2241613) and doctor's real round trip passes. The on-disk catalog is 27 family / 176 op, loaded/current=`11472e0667a4`, stale=false, and a clean process's catalog fingerprint matches. Restarting the backend does not reload the tool descriptions the host has already registered; the lib on disk has been updated, but refreshing descriptions still depends on a host plugin reload, so what the current verification confirms is the backend and the actual execution capability.
>
> Final real-channel probes: an isolated point `loose_verts=1 → clean=false,state=fail` (run-muiasnkw8veq); with gate v3, a healthy assembly with no interference source configured gives `mesh_health=pass,no_floaters=pass,no_clash=skipped → verdict=degraded,ok=false` (run-muibesxnqybr). Logs are under `blender-review-probes/final/`. The final gate regression 52/52, audit 78/78, and integration 107/107 have been re-run by the designated Flash agent.
>
> The skill finally removed the new unfounded "1–2× feature size" general rule; displayed overlap follows the project's `overlap_mm`, and real connections follow the design spec; rotational interfaces must be measured in the real interface coordinates. Lead synced the lightweight acceptance checklist's fields, the AABB scope of applicability, and the real fields of the print pre-screen. The stage reports below are kept as historical evidence; statements about the non-restarted backend or old document hashes no longer represent the final state.

> Acceptor: independent acceptance subagent (read-only on implementation files, does not modify implementation code) · 2026-09-26
> Scope: this round's three implementation reports (① `runtime/audit.py`+`runtime/calib.py` ② skill docs v4 ③ plugin runtime `engine.mjs`/`generator.py`/`config.mjs` etc.)
> Probe directory: `blender-review-probes/review/` (every number in this report can be re-run there)

> ⚠ **§0–§6 are a historical snapshot**: the following are the conclusions exactly as they stood at the time of the independent acceptance on 2026-09-26 (corresponding to `gate.py GATE_VERSION=2`,
> `lib/index.js` mtime 18:00:42, and the old process of the running backend pid 1989809). **Do not read this as the current state**.
> Of those, **F1 and F7 are resolved** (along with the three-fold stack in F2), and F3/F5 have also been handled; the final integration's overrides, changes, and re-run numbers
> are in the **§7 final integration appendix** at the end. Old conclusions are **not deleted** as required, only annotated.

---

## §-1 Current-state facts (evening of 2026-09-26 · added by Lead after re-check)

This section is the **current actual state** and takes precedence over the historical snapshot below and over §7.

| Item | Current state | How re-checked |
|---|---|---|
| Plugin | v0.9.6 · **27 family / 176 op** · 29 runtime py modules | read directly from `catalogPayload()` |
| Channel | `doctor`'s real round trip passes; **the new code is live** | real-machine op receipt |
| Blender-side regression | integration **107/107** · audit_review **78/78** · gate_review **52/52** = **237 assertions all green** | three headless re-runs |
| Node side | lossless-guard 40✓/2 skipped · lease-stale 20✓ · 28✓ · 51✓ · **workdir 14✓** (fixed, see below) · typecheck ✓ | `npm test` + `scripts/typecheck.mjs` |
| U1 / U2 (whether the new capabilities reach the model) | ✅ **Resolved**: on the real machine `audit_mesh` already has top-level `state/verdict/reason`, `gate_plan` already carries skipped⇒degraded semantics, and the catalog 27/176 is live | real-machine op |

### ⚠ About the "npm test 197 passed" number

That number was obtained **on another machine / under a different mount configuration**; on the first re-check on this machine there were **4 failures**, all in `tests/workdir_shared_selftest.mjs`, because **the test's premise did not match this machine**, not because of a product regression:

- The old assertion hard-coded "/tmp is not shared with Windows ⇒ it must be replaced". But on this machine `/tmp` sits on the **WSL root filesystem** (ext4 @ `/dev/sdd`, mount point `/`), and it **is** reachable via `\\wsl.localhost\Ubuntu\tmp\…` ⇒ the plugin judging `shared=true, why=distro-root-fs` and **not replacing** it is **correct** (the `usedWin` in the receipt is exactly that UNC path, and D1–D3 all pass).

**Fix applied (environment-independent)**:
1. A1 changed from "hard-coded `shared===false`" to a **self-consistent criterion** —— `shared===true ⇒ why==='distro-root-fs'`; `shared===false ⇒ why must name an independent mount`; both are legitimate on different machines;
2. section C **verifies the replacement contract by branch** according to `requestedShared` (not shared ⇒ it must be replaced and the note reports the reason + location; already shared ⇒ it must not be replaced and the note reports that the check passed);
3. the probe directory **dynamically selects a genuinely non-shared mount** (on this machine `/dev/shm`) ⇒ the replacement branch still gets genuinely exercised.

After the fix, on this machine: **workdir-shared-selftest 14 passed / 0 failed**.

> Conclusion: **"npm test all green" must be stated conditioned on the environment** —— the current state on this machine is "all Node-side tests pass (workdir 14/14) + 237 Blender-side assertions all green".

---

## 0. Verdict summary

**Overall verdict: pass (with 3 gaps that need a Lead decision + 3 numbers/facts needing correction + 5 unverified items).**
The features and numbers **declared by the three reports were all independently reproduced successfully**, and no "fake fix" was found. In the landing chain, however, **3 gaps fall outside both implementers' scope** (the F1 `acceptance-checklist` audit_scene criterion, F2 `gate_plan(preset="assembly")` necessarily failing, and the F7 `acceptance-checklist` audit_connectivity criterion being unable to read the field) —— following the docs would lead into a hole; there are also **3 inaccurate report numbers** (F3/F4/F6, of which F6 belongs to the skill docs themselves) plus one reproduced limitation note, F5.

| # | Implementer's claim | My independent conclusion | Evidence |
|---|---|---|---|
| 1 | `loose_verts>0` yet `clean=true` is fixed | ✅ pass | R1 B1–B3 |
| 2 | `loose_edges` changed from "always 0" to actually computed | ✅ pass | R1 B4–B5 |
| 3 | A reversed **detached** shell is no longer swallowed by the aggregated volume (judged per shell) | ✅ pass | R1 C1–C5 |
| 4 | A legitimate nested cavity **must not** be a false positive | ✅ pass (includes the reverse "healthy part raises no false positive" case) | R1 A1–A5 / D1–D4 |
| 5 | Cannot decide → `normals_state=unknown` → `degraded` | ✅ pass | R1 E1–E3 |
| 6 | Self-intersection **skipped** ⇒ `degraded`, `clean=false` | ✅ pass | R1 F1–F5 |
| 7 | Self-intersection **error** ⇒ `degraded`, evidence retained | ✅ pass (injected a BVH exception and measured it) | R1 G1–G5 |
| 8 | Large-mesh safety valve `SHELL_MAX_FACES` / `DSH_SHELL_MAX_FACES` | ✅ pass (semantics); ⚠ absolute performance values not reproduced | R1 H1–H4 · R6 |
| 9 | `audit_mesh` gains top-level `state/verdict/reason/analysis` | ✅ pass | R1 E3/F5, R7 |
| 10 | The calib catch criterion changed to "the corresponding gate `state=='fail'`" | ✅ pass | R2 L5–L9 |
| 11 | calib units unified at `CALIB_SCALE=0.001` + reset after the run | ✅ pass (all 8 `unit_scale` rows = 0.001) | R2 L3/L4/L5b/L5c/L10 |
| 12 | The implementer's regression suite, 78 items | ✅ 78 pass / 0 fail | re-ran `tests/audit_review_regression.py` |
| 13 | The existing `upstream_integration_selftest` 107 items show no regression | ✅ 107 pass / 0 fail | re-ran (preload 15 modules) |
| 14 | `generator_save` uses `code=`, `script=` is rejected | ✅ pass (catalog skeleton + real-machine rejection) | engine.mjs:641 / R2 M1–M2 |
| 15 | `generator_run` nested `args` is no longer flattened | ✅ pass (real machine `PARAMS={"n":3}`, creates 3 objects) | R2 M3–M4 |
| 16 | `npm test` all green | ✅ all green, but **the total is 197, not 182** | see §3 F3 |
| 17 | `typecheck` is reproducible + diagnoses a missing tsc + exit 2 + does not write lib | ✅ pass | §2 group A |
| 18 | Catalog self-proof changed to a **content fingerprint** (mtime does not participate) | ✅ pass (only mtime changed on an independent copy → still current) | prov_probe.mjs |
| 19 | `args={verify:true}` starts a clean process as the judge | ✅ pass (comment change → source stale, catalog fingerprint unchanged) | prov_probe2.mjs |
| 20 | workDir shared-ness decision (mount table, not "Node can write") | ✅ pass (implementer's 14 items; I re-checked by reading code only) | npm test |
| 21 | Skill docs: orthographic ⇏ shared px_per_mm | ✅ pass (0.48/0.24/0.96, 300% apart, parallax 0) | R3 P1 |
| 22 | Skill docs: cross-depth error = Δz/(D+Δz) | ✅ pass (six rows at D=8m match the analytic formula row by row) | R3 P2 |
| 23 | Skill docs: a homography corrects only the sampled plane | ✅ pass (0 / 9.906 / 40.194 / 103.464 px → 0/52/211/543 mm) | R3 P3 |
| 24 | Skill docs: there is no fixed modifier stack | ✅ pass (866/864/0.9904 vs 98/96/0.8395; 56/54 vs 8/6) | R3 M |
| 25 | Skill docs: Delete Loose cannot remove interior faces | ✅ pass (face count 12→12, buried faces 12→12) | R3 I |
| 26 | Skill docs: embed depth is set by the interface scale | ✅ pass (thin plate 1.5mm / Ø6 shaft 6mm / fully contained floater `overlap_bbox=true` on all three axes) | R3 E |
| 27 | Skill docs: Recipe 6b changed to a runnable closed-track shape | ✅ pass (the doc's code **extracted as-is** produces every number) | R4 |
| 28 | Skill docs: `multiview-calibration.md --selftest` four cases | ✅ pass (`SELFTEST PASS` A/B/C/D=True, script extracted as-is) | §B group |
| 29 | Skill docs: the deviation numbers for the equal-arc-length caliber | ✅ pass (6.0343 steps / 175.0210mm / −0.9790mm / −5.8740 / −11.7480 all match) | R4 analytic recomputation |
| 30 | `gate_plan(preset="assembly")` usable for project-level acceptance | ❌ **fail** (even a clean scene cannot reach pass) | §3 F2 |
| 31 | Acceptance checklist `audit_scene → clean=true` can serve as a gate | ❌ **fail** (with the new code the default is always `degraded`) | §3 F1 |
| 32 | Acceptance checklist `audit_connectivity → state=pass` | ❌ **fail** (there is no top-level `state` field) | §3 F7 |

---

## 1. Independent verification method (why these numbers are trustworthy)

**The running plugin backend was not used.** The running backend pid 1989809 started at **09:35:49Z**, earlier than the `lib` rebuild (18:00:42) and the `runtime/*.mjs` changes (18:41), so it loaded **old code** (measured: `/plan op=catalog` returns **26 family / 161 op**, and `/health` has no `provenance`; the code on disk is **27 / 176**). Therefore:

- All Blender-side probes call `blender.exe -b --factory-startup --python` **directly** (`/mnt/d/SteamLibrary/steamapps/common/Blender/blender.exe`, Blender **5.2.2 LTS**), with `blender-review-probes/review/_boot.py` replicating the plugin's `KERNEL_BOOTSTRAP`+preload semantics —— **what executes is the `runtime/*.py` on disk**, not the old copy inside the process;
- All node-side probes **directly `import('./runtime/engine.mjs')`** or run `tests/*.mjs` directly.

**A different path** (matching the acceptance checklist's "anti-Goodhart" requirement): for the documented numbers I did not accept the implementer's probe output —— for projective geometry I cross-checked with **my own** normalized DLT / analytic formulas; for modifiers and Delete Loose I used **my own** evaluated-mesh counting and ray casting; only for embed depth did I actually run the plugin's `audit_measure` (that value can only come from the plugin).

**No implementation file was modified**: the whole run was `read` + read-only commands; writes were limited to `blender-review-probes/review/**` and `dsh-blender-plugin/docs/plugin-and-skill-optimization-acceptance.md`. No `git reset`/`stash`, no backend restart, no connection to the Blender GUI (9876 was not listening), and no GUI scene was touched.

Re-run entry points:

```bash
R=/home/sixtyseven67/DSH/blender-review-probes/review
BL=/mnt/d/SteamLibrary/steamapps/common/Blender/blender.exe
W='\\wsl.localhost\Ubuntu\home\sixtyseven67\DSH'

# own probes (direct blender.exe)
"$BL" -b --factory-startup --python "$W\\blender-review-probes\\review\\r1_audit_boundaries.py"
"$BL" -b --factory-startup --python "$W\\blender-review-probes\\review\\r2_gate_calib_generator.py"
"$BL" -b --factory-startup --python "$W\\blender-review-probes\\review\\r3_skill_docs.py"
"$BL" -b --factory-startup --python "$W\\blender-review-probes\\review\\r4_recipe6b.py"
"$BL" -b --factory-startup --python "$W\\blender-review-probes\\review\\r7_audit_positive.py"

# implementer's suites (with the generic runner, preload identical to the plugin)
"$BL" -b --factory-startup --python "$W\\blender-review-probes\\review\\_runner.py" -- \
      "$W\\dsh-blender-plugin\\tests\\audit_review_regression.py" 'audit,calib,gate,printcheck'
"$BL" -b --factory-startup --python "$W\\blender-review-probes\\review\\_runner.py" -- \
      "$W\\dsh-blender-plugin\\tests\\upstream_integration_selftest.py" \
      'audit,sculpt,mesh_fix,uv_tools,printcheck,sweep,material,render_guard,gate,human,vehicle,clearance,shapegen,faceeval,imgtools'

# plugin runtime
cd /home/sixtyseven67/DSH/dsh-blender-plugin && npm test && node scripts/typecheck.mjs
node /home/sixtyseven67/DSH/blender-review-probes/review/prov_probe.mjs
python3 /home/sixtyseven67/DSH/blender-review-probes/review/extracted/multiview_calib_doc.py --selftest
```

---

## 2. Evidence by group

### Group A · plugin runtime (report ③)

```
npm test  → exit 0
  protocol       28 pass
  lossless       40 pass / 0 fail / 2 skip
  lease          20 pass / 0 fail
  frame_dedupe   15 pass            ← the report forgot to count this file
  discoverability 51 pass
  workdir-shared 14 pass / 0 fail
  provenance     16 pass / 0 fail
  generator      13 pass / 0 fail
  ── total 197 pass / 0 fail (the report says 182, see F3)

node scripts/typecheck.mjs
  normal path  → exit 0, resolves to $HOME/dsh-harness/node_modules/.bin/tsc; lib/index.js mtime unchanged (18:00:42)
  isolated env → exit 2 (no local tsc, empty HOME, no tsc on PATH): per-candidate ✗ diagnosis + four A/B/C/D fixes that avoid a global install
  DSH_TSC=/nonexistent → states plainly "**does not exist**" and then continues with the other candidates (does not give up halfway)
```

**generator reproduction on the real machine** (R2 M): `generator_save(script=…)` is rejected and returns the `expected` list; `run({name,args:{n:3}})` → `receipt.PARAMS={"n":3}`, `objects=3`, `names=["Cube","Cube.001","Cube.002"]`. The failure mode the report declares, "old code gives an empty PARAMS", matches the post-fix behavior.

**Catalog/self-proof** (code on disk, independent process):

```
node -e "import('./runtime/engine.mjs')"  → PLAN_CATALOG.length=27, planOpNames().length=176
                                              the generator skeleton sk uses code= (not script=)
                                              engineProvenance() → verdict=current, loaded==current
running backend /plan op=catalog           → 26 family / 161 op, **no provenance** (confirms the old process)
```

**Independent provenance re-check** (done on a copy, without touching the real sources):

```
utimes only (content byte-identical) → verdict=current, mtimeChanged=true, contentSame=true   ← mtime cannot fool it
append one comment line (content changed) → verdict=stale, staleReason gives both the loaded and current fingerprints
catalogPayload({verify:true}) → provenance.diskVerdict.ok=true; when only a comment changed
                                matchesLoadedCatalog=true (what is stale is the source, not the catalog), and the text says "catalog self-proof FAIL"
```

### Group B · skill docs (report ②)

**The `multiview-calibration.md` script extracted as-is** (`extracted/multiview_calib_doc.py`) ran `--selftest`:

```
SELFTEST PASS  (A simultaneous solve / B in-view residual red / C per-scale per-view usable / D cross-view cross-check red)  A=True B=True C=True D=True
Core regression C: when three views differ by 100% in px_per_mm while the in-view residual ≈0, it judges "usable per view" and no longer misjudges it as perspective.
```

**The document's "measured" numbers** (R3, all 25 assertions pass):

| Document claim | My measurement | Verdict |
|---|---|---|
| Three orthographic views (`ortho_scale` 4/8/2) `px_per_mm` = 0.48/0.24/0.96, 300% apart | 0.48 / 0.24 / 0.96, **300.00%** apart; bit-for-bit equal to the analytic formula `res_x/ortho_scale/1000` | ✅ |
| Parallax is 0 px everywhere | moving 2 m along the **true view axis** (camera local −Z), x/y displacement both **0.000000** | ✅ |
| D=8m: 0.25/0.5/1/2/3 m → −3.03/−5.88/−11.11/−20.00/−27.27% | matches row by row; matches the analytic formula `Δz/(D+Δz)` row by row (near-field ppm=0.295139) | ✅ |
| Homography: 0 / 9.906 / 40.194 / 103.464 px → 0 / 52 / 211 / 543 mm (1m≈190px) | 0.000 / 9.906 / 40.194 / 103.464 px → 0 / **52.035** / **211.134** / **543.483** mm (190.372 px/m at that camera position) | ✅ |
| Bevel→SubSurf = 866/864, bbox 0.9904; SubSurf→Bevel = 98/96, bbox 0.8395 | exactly identical | ✅ |
| Planar Solidify→Bevel = 56/54; Bevel→Solidify = 8/6 | exactly identical | ✅ |
| Delete Loose cannot remove interior faces | face count 12→12; ray-cast buried faces 12→12; `delete_loose` returns `FINISHED` | ✅ |
| 3mm plate lap 1.5mm / Ø6 shaft 6mm / a 10mm fully contained floater also gives `overlap_bbox=true` | 1.5 / 6.0 / true, the floater fully overlaps 10.0mm on each of the three axes; the receipt's `note` contains "bbox level (not triangle level)" | ✅ |
| Recipe 6b: `N=24`, `max|chord length−p|=3.3e-06mm`, closure 175.999998mm, `bbox=A+2R=1.736012m`, perimeter 4.248320, `N*p`=4.224000, 24 objects | the doc's code **extracted as-is** produces: `N=24  max|chord-p|=0.000003mm  closure=175.999998mm`, `bbox_x=1.736012 (expected=1.736012) perimeter=4.248320 N*p=4.224000`, the template deleted, exactly 24 `GEO-track_link_*` objects | ✅ |
| Equal-arc-length caliber: chord 175.021mm on the arc, −0.979mm per segment, 6.0343 steps for the half circle, −11.748mm for both arcs | independent analytic recomputation: 6.0343 steps / 175.0210mm / −0.9790mm / 6×−0.9790=−5.8740 / 12×=−11.7480 | ✅ |

Structural claims were checked too: `### Recipe` has **25** headings in total (`1 2a 2b 3 3b 4 5 6 6b 7 … 22`) ⇒ **22 numbers** (1–22; "2" appears only as 2a/2b, with no standalone "Recipe 2" heading) → the frontmatter's "22 numbered recipes (including the 2a/2b/3b/6b variants)" is **self-consistent**; `the single authoritative gate table` appears **only once** in the whole corpus (§6); `reference-image-reconstruction-sop.md` does have `### 3.1` (a homography corrects only one plane, the table's 0/9.906/40.194/103.464 px) and `### 3.2` (Δz/(D+Δz)).

### Group C · audit / calib (report ①)

**My own probes** (not a re-run of the implementer's suites): R1 **38/38**, R7 **7/7**, R2 **24/24** (R2 covers the four sections audit_scene/gate/calib/generator).

Key bidirectional evidence (quoted as-is):

```
R1 C  large outward shell (vol=+64) + small detached reversed shell (vol=−8): aggregated signed_volume=+56 (the old caliber would judge outward=true)
      → normals_outward=false; normals_shells = [{shell0, vol 64, pass}, {shell1, vol −8, fail}]
R1 D  outer shell 216 + fully nested cavity −8 → clean=true/state=pass; the inner shell nested=true, relation="nested" (negative volume exempt)
R1 E  a fully coincident reversed duplicate → normals_state=unknown, reason="AABB intersect but nesting/cavity cannot be confirmed … no pass conclusion given", clean=false
R1 A  healthy cube → clean=true/state=pass/normals_outward=true (**not** caught by the new criteria)
R1 F  self_intersect=false → self_intersections_state="skipped", analysis.self_intersections="skipped", clean=false/degraded
R1 G  injecting an exception from BVHTree.FromBMesh → state="error", analyzed=false, self_intersect_error has the original text, clean=false/degraded
R1 H  DSH_SHELL_MAX_FACES=100 on a 2304-face sphere → normals_state=unknown, degraded, reason names the environment variable; pass once lifted
R7 S1 real interpenetration (joined intersecting cubes) → self_intersections>0, clean=false/fail      ← the positive case must be caught
R7 S3 empty mesh → does not crash, empty=true, clean=false
R7 S5 open mesh → boundary_edges>0, closed=false, normals_outward=null, fail
R7 S7 zero-area face from three collinear points → degenerate_faces>0, fail
R2 J  clean scene audit_scene default → degraded (see F1); the same scene with self_intersect=true → clean=true/pass
R2 L  calib_run → ok=true, valid_run=true, missed=[], unit_ok=true, baseline_pass=true;
      the unit_scale set of the 8 defects rows = {0.001}; baseline.unit_scale=0.001; scene units reset after the run
      break_gates=["print"] → ok=false, gate_errors=["print"], missed=["thin_wall"];
      thin_wall.caught!=true while naive_caught=true (the old caliber mis-records it)
```

**Performance order of magnitude** (R6, a 132,000-face sphere): default (per shell + BVH self-intersection) **3362.6 ms**, pass; `DSH_SHELL_MAX_FACES=50000` → **910.1 ms**, degraded/unknown. The direction matches "O(F) Python, degrade past the limit"; **the report's 618k→11.2s / 155k→0.67s did not reproduce** (different caliber: that timed per-shell analysis alone, whereas I timed the whole `audit_mesh` call), see F4.

---

## 3. Failed items / gaps (with reproduction and fix suggestions)

### F1 ⚠ [medium] The acceptance checklist's `audit_scene` criterion no longer holds (cross-workflow gap)

- **File**: `dsh-skill-blender-modeling/references/acceptance-checklist.md`, **line 24**
  `| dirtiest in the whole scene | op="audit_scene", args={summary_only:true, top_k:5} | clean=true; otherwise only look at the worst score |`
- **Conflict**: the new `audit_scene` defaults `self_intersect` to **False** (a performance contract), while the new criterion honestly reads "check skipped" as `degraded/clean=false`. ⇒ **any** scene (even a single healthy cube) called as this row says cannot reach `clean=true`.
- **Reproduction** (clean factory scene + one healthy cube, R2 J):
  ```
  audit_scene({summary_only:true, top_k:5})
    → {"clean": false, "state": "degraded", "verdict": "degraded",
       "reason": "the pre-screen skipped the self-intersection check; 1 object cannot be decided (see worst[].normals_state/state)"}
  audit_scene({summary_only:true, top_k:5, self_intersect:true})
    → {"clean": true, "state": "pass", "verdict": "pass", "reason": ""}
  ```
- **Whose scope**: the `audit.py` change (report ①) is right, but it did not change `acceptance-checklist.md` (a file of report ②); report ② did not touch this row. ⇒ both implementers are "out of scope", so the Lead must assign someone to patch it.
- **Suggested fix (minimal)**: change that row to
  `op="audit_scene", args={summary_only:true, top_k:5, self_intersect:true}` → `clean=true`,
  and add one clause: **`degraded ≠ pass`; a scene conclusion usable as a gate must explicitly pass `self_intersect:true`**.
  (The gate table in `SKILL.md` §6 uses `audit_scene`'s `totals.nonmanifold_edges`/`tris` fields, **so it is unaffected** and needs no change.)

### F2 ⚠ [medium] `gate_plan(preset="assembly")` cannot reach pass now (three-fold stack)

- **Reproduction** (clean single-cube scene, R5):
  ```
  gate_run({preset:"assembly", detail:true})
    → verdict="fail", ok=false
      gates:
        mesh_health  state=degraded   ← new: collateral of F1 (audit_scene skips self-intersection by default)
        no_floaters  state=error      ← pre-existing: pass_if "state == 'pass'" but audit_connectivity **has no top-level state**
                                         error: "pass_if evaluation failed: pass_if references fields absent from the receipt: ['state'] (receipt top-level fields: ['aabb','analyzed','attached_count','components','floater_count',…,"ok"])"
        no_clash     state=error      ← pre-existing: the preset's args give no objects_a/objects_b/file_a/file_b
                                         error: "source failed: a: no source given for this side…"
  ```
- **Impact**: the project-level "run acceptance in one go" path (line 22 recommended in `AGENTS.md`) is currently **unusable**: even a clean scene necessarily `fail`s. The three causes differ; `mesh_health` was newly introduced this round and the other two are pre-existing.
- **Suggested fixes (ordered by cost-effectiveness, any combination)**:
  1. add `"self_intersect": true` to the mesh gate of `PRESETS["assembly"]` in `runtime/gate.py` (one line, directly resolves F1's collateral);
  2. change `no_floaters`'s `pass_if` to real receipt fields (e.g. `gate.state == 'pass'` or `floater_count == 0`), **or** add top-level `state`/`verdict` to the `audit_connectivity` receipt (copying the nested `gate.state`) —— the latter fixes F7 and line 25 of the acceptance checklist at the same time;
  3. when `no_clash` has no source, change it from `error` to **`degraded` + a skipped note** ("no source configured ⇒ not checked"), otherwise every preset call without a source is judged dead.
- **Note**: this touches the `gate.py` / `audit_connectivity` contract, is **within no implementation report's scope**, and needs the Lead to decide ownership.

### F7 ⚠ [medium] The acceptance checklist's `audit_connectivity` criterion cannot read the field (pre-existing, same root as F2)

- **File**: `references/acceptance-checklist.md`, line 25: `pass criterion = state=pass; degraded does not mean pass`
- **Measured** (R8, real collection `COL_REV`, two parts touching + one far away): the **top-level fields** of `audit_connectivity` are
  `["aabb","analyzed","attached_count","components","floater_count",…,"gate","gate_caliber",…,"ok","verdict_line","visible_floater_count"]`
  → **no top-level `state`**; `state`/`verdict` live in the nested `gate` (measured `gate.state="fail"`, `gate.verdict="fail"`, because I deliberately placed one far part).
- **Suggested fix**: change line 25 of the checklist to `gate.state == "pass"` (either this or F2's suggestion 2: if you choose "add top-level state", the checklist needs no change). This row **is within the skill docs' scope** and can be changed right now.

### F3 [low] Report ③'s test total is inaccurate: 182 → actually 197

- `npm test` actually chains **8** test files (`scripts.test` in `package.json` includes `frame_dedupe_selftest.mjs`), and I ran them one by one:
  `28 + 40 + 20 + 15 + 51 + 14 + 16 + 13 = 197` pass (plus 2 skip).
- The report's `182` = the sum of the 7 files it enumerated, **missing `frame_dedupe`'s 15 items**. The all-green conclusion is unaffected, but **the number must be corrected**, otherwise later reconciliation will assume 15 items were not run.
- Suggestion: change 182 to 197 in the report (or state explicitly "of which the 15 frame_dedupe items were not counted").

### F4 [low] The absolute performance values of `SHELL_MAX_FACES` did not reproduce (different caliber, not a defect)

- Report: 618k faces `audit_mesh` 14.3s → 3.0s; per-shell analysis 155k→0.67s, 618k→11.2s.
- My measurement (R6, the **whole `audit_mesh`** call, 132k faces): default 3362.6 ms, valve=50000 → 910.1 ms.
- Conclusion: **the valve semantics and the order-of-magnitude direction agree** (past the limit → second-scale degradation + `degraded`), but **absolute seconds cannot be compared across machines** (my numbers include boundary/nonmanifold/degenerate/loose + BVH self-intersection, whereas the report's 0.67s/11.2s timed per-shell analysis alone). Suggest that the report spell out both calibers so readers do not compare 11.2s against 3.36s for 132k faces.

### F5 [info] `src/index.ts`'s new description has not entered `lib` yet (a limitation, not a defect, reproduced)

```
src/index.ts  18:37:38  grep 'code=' → 1
lib/index.js  18:00:42  grep 'code=' → 0
```
⇒ what the model currently sees is the **old tool description** (no `code=` / nested `args=` reminder). This matches limitation #2 of report ③; it needs `build.sh` + a host reload and is **not part of this round**. The running backend also contains none of the new capabilities (26/161, no `provenance`).

### F6 [low | being fixed concurrently] The size numbers the acceptance checklist claims in its header are stale

- Line 3 of `references/acceptance-checklist.md` claims `SKILL.md` = 74,753 characters; line 4 claims this file = 3,918 characters.
- Measured (19:04:40 version): this file = **3,922** characters (+4, essentially matching); `SKILL.md` = **78,319** characters (3,566 more than the 74,753 cited).
- **Nature**: I observed a concurrent writer fixing this in real time (the 18:29 version still cited 68,823 → by 19:03 it had been changed to 74,753). The residual staleness is not an error but **the referenced file still growing**: `SKILL.md` went from 72,488 → 74,753 → 78,319 characters during this acceptance, so any hard-coded size expires immediately.
- **Suggestion**: stop hard-coding absolute numbers here and change it to "compute it now with `wc -m SKILL.md`" or give only an order-of-magnitude range; also update 74,753 to the current value and note "as of a given day". **No Lead decision is needed**.

---

## 4. Unverified items (listed honestly, do not treat them as pass)

| # | What is unverified | Why | How to fill it |
|---|---|---|---|
| U1 | The running backend's new capabilities: `/health`.provenance, `/plan args={verify:true}` end to end, the `WORKDIR_NOT_SHARED` receipt, the "catalog self-proof" line in the catalog text | backend pid 1989809 is still **old code** (26/161, no provenance); per instructions the backend was **not restarted** | after restarting the backend: `curl /health` to see `provenance.verdict`; `curl -X POST /plan -d '{"op":"catalog","args":{"verify":true}}'` to see `diskVerdict.matchesLoadedCatalog` |
| U2 | Whether the `code=`/`args=` reminders in the tool description actually reach the model | needs `build.sh` to write `lib` + a host reload (forbidden this round) | after building, grep `lib/index.js` for `code=`, and inspect the schema in the host |
| U3 | The **measured** difference of the Mirror↔Bevel order | report ② itself labels it "design intent, not measured"; my independent attempt also obtained no distinguishable difference (both orders have the same vert count, and the slanted faces at the seam are 0 in both) | test again with geometry that really has Bevel overlap on a mirror seam; otherwise keep the "design intent" wording |
| U4 | Quantifying the §11 #5 IoU blind spot | report ② itself says "an analytical conclusion, no quantitative experiment performed" (the blind spot is structural: depth/internal features are not in the silhouette mask) | if numbers are wanted: render the same object once at each of two depths and check whether IoU is insensitive to depth |
| U5 | The 618k-face absolute performance values (14.3s→3.0s) | see F4 (the cost/benefit of building a 600k-face mesh is not worth it) | when needed, diff with the `SHELL_MAX_FACES` and `self_intersect` switches |

> Also: **the skill docs were concurrently written to during my acceptance** (`SKILL.md` mtime 18:29 → 19:01:15 → 19:02:41 → **19:04:40**; character count 72,488 → 72,558 → 74,753 → **78,319**). I re-checked the verified key numbers on every version, and the last version (**19:04:40, `md5 f4c6d2c7…`, 78,319 characters**) still has: `1.736012`/`4.248320`/`0.9904`/`0.8395`/`175.999998`/`3.3e-06`/`−27.27`/`52 mm`/`543 mm`/`0.48 / 0.24 / 0.96` **present as-is**, `### Recipe` still 25, §6 still the single authoritative gate table, the multiview selftest still `PASS` (the same script extracted as-is and run). If the Lead changed `SKILL.md` again after 19:04:40, re-run the four steps of §2 group B of this report (1 blender headless + 1 python3 + 1 char count + 1 grep, about 1–2 minutes) —— **this report is only responsible for the md5 above**.

---

## 5. Workspace and scope discipline

- The whole run was `read` + read-only commands; **no implementation file was modified** (`runtime/*.py`, `*.mjs`, `SKILL.md`, `references/*`, `tests/*` were all left unwritten).
- My writes were only two places: `blender-review-probes/review/**` (probes + extracted doc code + isolated copies) and this file, `dsh-blender-plugin/docs/plugin-and-skill-optimization-acceptance.md`.
- No `git reset` / `git stash`; no `build.sh` (`lib/index.js` mtime still 18:00:42); no backend restart (pid 1989809, the lease holder untouched); no connection to or interaction with the Blender GUI (9876 was not listening, every Blender run was `-b --factory-startup` + self-built probe objects, and the scene was not saved to disk when a probe ended).
- **All existing user changes were preserved**: the workspace's `audit.py / calib.py / engine.mjs / config.mjs / server.mjs / generator.py / src/index.ts / package.json / scripts/*` plus the skill side's uncommitted v3/v4 changes were read only, never written. This report's output is **only** the "independent reproduction conclusions + gap list"; it contains no implementation output.

## 6. Three things that need a Lead decision

1. **F1 + F7**: change the criteria on lines 24/25 of `references/acceptance-checklist.md` to readings consistent with the new code (`self_intersect:true`, `gate.state`). This is the minimal fix **within the skill docs' scope that can be made immediately**.
2. **F2**: the three-fold stack makes `gate_plan(preset="assembly")` necessarily fail —— ownership and the minimal fix must be decided at the `gate.py` / `audit_connectivity` contract level (suggested: add `self_intersect:true` to the mesh gate; make `no_floaters` read `gate.state` or add a top-level `state`; when `no_clash` has no configured source, degrade it to `degraded` instead of `error`).
3. **The landing window for U1/U2**: `engine.mjs`'s catalog self-proof and `src/index.ts`'s new description only take effect after **restarting the backend + rebuilding lib**; until then users still get the old behavior (26/161, no `provenance`, old tool descriptions). Report ③'s limitations section states this honestly, and the acceptance side confirms it is correct.

---

# 7. Final integration appendix (2026-09-26 · integration wrap-up)

> Appended by the **final integration** step. **§0–§6 are not deleted by a single character**; they are a historical snapshot. This appendix records the current round: overrides, changes, re-run numbers, and boundaries.
> This round wrote **only 4 files**: `runtime/gate.py` · `tests/gate_review_regression.py` ·
> `docs/plugin-and-skill-optimization-acceptance.md` · `dsh-skill-blender-modeling/references/acceptance-checklist.md` (gate semantics).

## 7.1 Status changes (relative to the historical snapshot)

| Snapshot item | At snapshot time | Now | Evidence |
|---|---|---|---|
| **F1** the acceptance checklist's `audit_scene` criterion no longer holds | ❌ no scene could reach `clean=true` | ✅ **Resolved** | line 1 of the numeric gates in `references/acceptance-checklist.md` now explicitly passes `self_intersect:true` and states "not passing it ⇒ only `degraded` can be given, and that is not a pass" |
| **F7** the acceptance checklist's `audit_connectivity` criterion could not read the field | ❌ no top-level `state` | ✅ **Resolved** | line 25 of the same table now reads `gate.state` (or `gate.verdict`), and notes "`degraded` **does not equal** pass" and "do not use component count = 1 as the criterion" |
| **F2** `gate_plan(preset="assembly")` necessarily fails (three-fold stack) | ❌ even a clean scene fails | ✅ **Resolved (semantics redefined per the Lead's decision)** | all three are fixed: F2-a (mesh gate `self_intersect:true`) / F2-b (read the nested `gate.verdict`) / F2-c (empty args → `skip_if_missing`); **but that does not mean the default preset passes**: the Lead voided `pass+skipped=pass` ⇒ the default preset's top level is judged **`degraded`** (the correct behavior), and passing requires every gate to have really run and pass (§7.2 F8-a, §7.3 ①) |
| **F3** report ③'s test total 182 → actually 197 | number pending correction | ✅ Handled | the Lead reports `npm test` = **197 passed / 2 skipped** (consistent with the snapshot caliber) |
| **F5** `src/index.ts`'s new description had not entered `lib` | a limitation (source only) | ✅ The build has landed (read-only re-check on this machine) | `lib/index.js` mtime **18:00:42 → 18:59:05**, `grep -c 'code=' lib/index.js` = **1** (`src/index.ts` is also 1) |
| **U1** the running backend's new capabilities (`/health`.provenance etc.) | unverified (old process pid 1989809) | ⏳ **Still waiting for the Lead to restart the backend** | per instructions this round **the backend was not restarted and the GUI was not touched**; after restart, re-check with the two commands in §4 U1 |
| **U2** whether the tool description really reaches the model | unverified (needs build + host reload) | ⏳ the build has passed, **the reload waits on the backend restart** | same as above |
| F4 / F6 / U3 / U4 / U5 | snapshot conclusions | not touched this round, **left as they were** | — |

## 7.2 What was done this round (the Lead's hard constraints + two minimal fixes)

**The Lead's override (this round's constraint)**: **`pass + skipped ⇒ pass` is void**. When the required gate `no_clash` is `skipped` for lack of a source, **the top level must be `degraded` and `ok=false`**; the bar is not lowered just so a "healthy default preset" turns green.

**F8-a · minimal `_aggregate` fix (`runtime/gate.py`, `GATE_VERSION 2 → 3`)**
- New caliber: any `fail`/`error` ⇒ `fail`; **otherwise any `skipped` or `degraded` ⇒ `degraded`**; only "a real `pass` exists and none of the above states is present" gives `pass` (an empty package is also `degraded`).
- **Kept** `coverage` (`checked`/`skipped`/`all_gates_ran`/`checked_ids`/`skipped_ids`), `overrides` and `overrides_applied`, `skipped[]`, `degraded[]`, `failed[]`; `skipped_note` now states plainly that it "judges the top level as degraded".
- The preset semantics follow: assembly's `no_clash` with no configured source ⇒ `skipped` ⇒ **the default preset's top level is `degraded`**; to pass, use `overrides={"no_clash":{objects_a:[…],objects_b:[…]}}` or write your own spec.
- The conclusion is synchronized in four places: the `gate.py` module docstring + the `gate_run` docstring + the `gate_plan` note + `gate_help`.

**F8-b · the print preset's resolution false pass (`runtime/gate.py`)**
- **Verify the real fields first**: `print_report`'s top level has only `ok/walls_ok/overhang_ok/thin_samples_total/worst_min_mm/worst_p05_mm/params/detail`; "`min_mm` is below this mesh's measurement resolution ⇒ the conclusion is untrustworthy" is written **only** in `detail.walls.objects[].warning` / `resolution_mm` (set in `print_walls` when `thr_mm < res_mm`) —— the old `pass_if="thin_samples_total == 0 and walls_ok == True"` could not see it at all ⇒ **on a coarse mesh "it could not be measured at all" reads as green**.
- Fix (without touching `printcheck.py`; everything lands in `gate.py`): new spec keys **`degrade_if`** (a restricted expression sharing the AST allowlist and variable resolution with `pass_if`) and **`echo`** (dot paths that fetch real fields). The print preset now carries `degrade_if = "params['min_mm'] < detail['walls']['objects'][0]['resolution_mm']"`; when it hits, that gate is **`degraded`** (not fail and not pass), and `echo=[params.min_mm, …resolution_mm, …warning]` writes the three real readings into the receipt; `fail`/`degraded` are stronger conclusions and are not overridden by `degrade_if` (fail wins).
- **Boundary (stated honestly)**: `degrade_if` judges the **active object** (the preset's `scope=ACTIVE`, `objects[0]`); for multiple objects/resolutions write your own spec to judge per object (the preset's `note` says so). This round **did not expand its scope** and touched no other functionality.

**Tests and docs**
- `tests/gate_review_regression.py`: assertions changed accordingly and pinned **in both directions** —— default preset `degraded` (skipped is not transparent) ↔ `pass` once both sources are supplied (every gate really ran and passed); F8-a units (`pass+skipped=degraded`, `fail+skipped=fail`, all skipped=degraded); F8-b coarse mesh `degraded` (and `pass_if_value=true`, `resolution_mm ≫ min_mm`) ↔ fine mesh (face size ≪ wall thickness) `pass`. **37 → 52 items**.
- `dsh-skill-blender-modeling/references/acceptance-checklist.md`: necessary gate-semantics updates —— the interference row adds "no sources on either side records `skipped` (skipped is not pass)"; the manufacturability row adds "an untrustworthy resolution ⇒ `degraded`, not pass"; the caliber traps go **from three to four**, adding "a gate package's top level looks only at `verdict` / `skipped` is not transparent / `degrade_if`: a true criterion ≠ trustworthy evidence".

## 7.3 Re-run numbers for this round (reproducible)

```bash
BL=/mnt/d/SteamLibrary/steamapps/common/Blender/blender.exe
W='\\wsl.localhost\Ubuntu\home\sixtyseven67\DSH'
R="$W\\blender-review-probes\\review\\_runner.py"

# ① this task's targeted regression (gate 37 → 52)
"$BL" -b --factory-startup --python "$R" -- "$W\\dsh-blender-plugin\\tests\\gate_review_regression.py" \
      'audit,gate,printcheck,uv_tools,material'
#   → HEADLESS {"pass":52,"fail":0,"fails":[],"probe":"gate_review_regression"}

# ② audit regression (the snapshot's 78 items, verifying the aggregate change caused no regression)
"$BL" -b --factory-startup --python "$R" -- "$W\\dsh-blender-plugin\\tests\\audit_review_regression.py" \
      'audit,calib,gate,printcheck'
#   → HEADLESS {"pass":78,"fail":0,"fails":[],"probe":"audit_review_regression"}

# ③ upstream integration self-check (must be re-run after a gate behavior change)
"$BL" -b --factory-startup --python "$R" -- "$W\\dsh-blender-plugin\\tests\\upstream_integration_selftest.py" \
      'audit,sculpt,mesh_fix,uv_tools,printcheck,sweep,material,render_guard,gate,human,vehicle,clearance,shapegen,faceeval,imgtools'
#   → HEADLESS {"pass":107,"fail":0,"fails":[],"skipped":[],"objects_left":[]}

# ④ gate_selftest (module level; includes v3's new aggregate / degrade_if / echo units)
#    the temporary probe only calls K.dsh_gate_api("selftest", {}) and is deleted right after the run
#   → {"ok": true, … "nested_tri_ok": true, "degrade_if_ok": true, "print_resolution_ok": true,
#      "skip_ok": true, "print_resolution_case": {"state":"degraded","verdict":"degraded","ok":false,
#      "pass_if_value":true,"resolution_mm":1000.0,"min_mm":2.0}}
```

| Suite | This round's result | Note |
|---|---|---|
| `gate_review_regression` | **52 pass / 0 fail** | 37 at snapshot time; 15 added = contract 2 + assembly/coverage 4 + skipped non-transparency 5 + print resolution 4 |
| `audit_review_regression` | **78 pass / 0 fail** | consistent with the snapshot, no regression |
| `upstream_integration_selftest` | **107 pass / 0 fail** (`skipped:[]`) | no regression after the gate behavior change |
| `gate_selftest` (built into the module) | **`ok=true`** | the new `_aggregate` caliber + real-machine evidence for `degrade_if`/`echo` (`gate.py`'s built-in self-check) |
| Lead-side `tsc` build + `typecheck` | ✅ passed (Lead's report) | read-only re-check on this machine: `lib/index.js` 18:59:05, contains `code=` |
| Lead-side `npm test` | ✅ **197 pass / 2 skip** | consistent with the corrected caliber in F3 |

## 7.4 Skill-side workflow3 (existing results relayed by the Lead, recorded as-is)

The skill workflow **workflow3 is complete: t1 11 passed / t2 26 passed / t4 43 passed / t5 8 passed** (the relayed information has no t3 entry).
This appendix only **records** that conclusion; this round **did not** re-run that workflow.

## 7.5 Not done / will not do (explicit boundaries)

- **The running backend was not restarted** (§4 U1 remains open): everything Blender-side this round was an independent `-b --factory-startup` process + on-disk sources, **never through the running backend**; `lib`'s new description reaches the model only after a backend reload (U2).
- **The GUI was not touched**: port 9876 was not connected, no GUI Blender session was started, no scene file was changed, and no `.blend` was written to disk.
- **No other functionality was changed**: writes were only the 4 files listed in §7.2; `runtime/audit.py`, `runtime/printcheck.py`, `runtime/engine.mjs`, `runtime/server.mjs`, `lib/**` etc. were **not touched**.
- **One wording known but not changed this round**: the three-state description of the gate in `runtime/engine.mjs` does not mention `skipped`/`degrade_if` (outside this round's write scope). That text **does not conflict** with the v3 caliber, but it also does not cover the new semantics; to make the model-facing description fully synchronous you need to open another write scope, change the `src/index.ts`/`engine.mjs` description, and rebuild `lib`.
- **Write observations (not by this agent)**: during this round `dsh-skill-blender-modeling/SKILL.md` (mtime **19:25:38**) and `README.md` (**19:24:14**) were modified, and `blender-review-probes/skill-final/**` also holds a batch of artifacts from 19:05–19:17 —— by their shape they are **the wrap-up of the previous workflow (skill workflow 3)**; this round's integration **did not** write those two files. This agent's writes are only the 4 files in §7.2, with checksums (sha256, for the Lead to re-check against the final diff):

  ```
  2e03edf0827e61e52e2d0760254e3e037dde94bcf2aab6a4cdfdb352e6d94b65  runtime/gate.py
  5b95c1d2674484d9d89b03dd8f7daca860f4e01bb7cd5f618fee37ccc5c04610  tests/gate_review_regression.py
  39a7f0d6604ffbfde165866b4cd68c844f17ab6b4e5f2c7f42b2e12bc0b98012  references/acceptance-checklist.md
  (this file changes with this appendix itself, so its self-referential hash is not listed)
  ```
