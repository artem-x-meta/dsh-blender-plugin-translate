# Historical route: headless first (v0.9.3, superseded by GUI first)

> ⚠ **2026-10-21 correction**: this file is a historical route recommendation. The current priority has changed to **GUI first**: open GUI Blender + Connect by default;
> headless is only a fallback for no-GUI / batch / long work (no-GUI can still rt_see). The body below is a historical record only and is no longer the current baseline.

| Item | Value |
|---|---|
| Decision | **Headless batch processing (`blender_rt_headless` / `blender_rt_job`) is the first route; direct GUI (9876 addon + `rt_do` / `rt_see` / `rt_watch` / `rt_cmd`) is an interactive bonus** |
| Status | **Decided** (effective since v0.9.3); this document is the sole baseline for this route |
| Basis | `docs/feedback/plugin-improvement-handover-2026-09-24.md` §1 / §5 / §6 / Appendix A (7 collaborators · ≈120 tool-call samples) |
| Blast radius | tool defaults (D1 wait window / `as_job`), receipt structure, docs and examples, **task templates**, parallel division of labor |
| Reversal conditions | see §6 (a majority of tasks that "must be done on the live scene" appear, or headless cold start becomes the bottleneck) |

> Companion reading: new parameters and pitfalls in [operation-tutorial.md](operation-tutorial.md) §7; image-reading and measuring discipline in [evidence-grading-and-image-reading.md](evidence-grading-and-image-reading.md) §6/§7;
> environment variables and path space in [configuration-reference.md](configuration-reference.md) §3/§10.

---

## 0. In one sentence

> **Default headless; Connect only when "you need to look at it / you need to modify the live scene the user has in hand / you need GUI context".**

This is a **ranking**, not cutting features: none of the 15 tools is deleted; the semantics, leases and doctor of `rt_do/rt_see/rt_watch/rt_loop/rt_cmd` are all retained.

---

## 1. What was decided

1. **First route = headless**: any work that "can be finished offline" (modeling scripts, batch geometry, validation, QC renders, final renders, delivery export) goes to `blender_rt_headless` / `blender_rt_job` by default — **it does not require a Blender GUI to be running, nor the addon to be Connected**.
2. **GUI direct = interactive bonus**: used only when "a human is in the loop, look one step then change one step" (`rt_see` / `rt_do {see:true}` / `rt_watch` / `rt_loop` / `rt_cmd`).
3. **Parallel division of labor does not explore the GUI by default**: templates do not say "run doctor first"; if a task does not need a GUI, do not write "please Connect" (§4.3 gives fill-in-the-blank templates).
4. **Pure-bpy ops must be callable directly from headless**: `audit_*` / `qc_*` / `deliver_*` / `motion_*` / `generator_*` / `montage` / `contract` / `plan` — per-item examples in §4.1.
5. **Timeouts no longer swallow results** (D1 landed): when the client wait window expires it returns `{kind:"promoted", jobId:"run-…"}`, and the result can always be retrieved from the job layer (§4.5).
6. **Long tasks are observable**: three spawn sites inject `PYTHONUNBUFFERED=1` + a script-side `dsh_stage()` heartbeat → `op=status.stage` (§4.6).

---

## 2. Evidence (2026-09-23~24, Star Citizen RSI Aurora Mk I MR part-by-part modeling)

| Observation | Number |
|---|---|
| Collaborators headless the whole time | **7 / 7** |
| addon 9876 `Connect` count | **0** (at the start `blender_viewport(op="doctor")` was already `blender-unreachable`) |
| `rt_do` / `rt_see` / `rt_watch` / `rt_cmd` / `rt_commands` / `blender_viewport` call counts | **0 each** |
| Main channel | `blender_rt_headless(script= / script_file=, args=, env=, engine=, timeout_ms=)`; the Lead side sent long renders through `blender_rt_job` |
| Longest single task | 6 × 1920×1080 / 256 samples ≈ **20 minutes** (job layer) |
| Ops they wanted to use but did not | `audit_duplicates` / `audit_snap_floaters` / `audit_*` / `qc_compare` — replaced by hand-written scripts (hull_fore ≈60 lines of world-vertex hashing + AABB; hull_aft with a self-written BVH nearest-distance scan; the reviewer's subject mask was reworked 3 times) |

**Three reasons** (converged from the collaborators' own words):

1. **No GUI session** — 9876 was never Connected, and `rt_do/rt_see` depend on the main-thread realtime channel;
2. **Parallel safety** — 6 part-modelers running at once would pollute each other and fight over the main thread if they touched the live scene; headless is a clean process every time;
3. **Unavailable means bypass** — they chose headless without even running `doctor`.

**Conclusion**: the GUI channel is **not explored by default** in parallel division-of-labor scenarios. Either require it explicitly in the template, or admit it is an optional second route — this decision chooses the latter.

**The most expensive one**: `audit_* / qc_*` could already be called directly from headless, but their descriptions had no copy-paste example of "pass a collection name, get a per-part report" → everyone hand-wrote it. §4.1 fills each one in.

---

## 3. Blast radius

| Area | Change (v0.9.3) |
|---|---|
| headless default behavior | when the wait window (default 100 s, `DSH_HEADLESS_WAIT_MS`) expires the result is **no longer dropped** → returns `{kind:"promoted", jobId:"run-…"}` |
| new headless parameters | `shots` (multi-view in one call) · `as_job` · `wait_s` |
| job layer | `op=start` accepts `script_file/args/env/factory_startup/bootstrap/workdir/include_noise`; new `op=wait`; `kill` on an unknown id does not error; `status` gains `stage/stageAt/lastOutputAt/idleMs/lines/pidAlive` and stale convergence |
| receipt | **two text blocks**: the 1st is a single-line JSON envelope (directly `JSON.parse`-able), the 2nd is a human-readable summary → no more hand-written regex |
| paths | `outdir` / `out_json` accept WSL paths and return the real write path |
| docs | this document + operations tutorial §7 + evidence grading §6/§7 + configuration reference §10 |
| task templates | one hard declaration line added: "does this task need GUI + Connect" (§4.3) |

---

## 4. Migration guide

### 4.1 Which ops can be called directly from headless (with copy-paste examples)

| What you want to do | How to write it in the GUI (v0.9.2) | Direct headless call (recommended) |
|---|---|---|
| Mesh audit (self-intersection / non-manifold / degenerate faces / normals) | `blender_rt_plan(op="audit_mesh", args={objects:[...]})` | `preload="audit"` → `K.dsh_audit_api('mesh', {...})` |
| Whole-scene audit / out-of-bounds parts | `audit_scene` | same, `('scene', {...})` |
| Connected components / assembly gate | `audit_connectivity` / `audit_gate` | same |
| Duplicate-name resources / orphan cleanup | `audit_duplicates` / `audit_purge_orphans` | same |
| Cross-part / **cross-file** interpenetration and overlap (v0.9.1) | `audit_interference` / `audit_overlap` | same, pass `file_a` / `file_b` |
| Shape drift / measurement bundle / floaters | `audit_drift` / `audit_measure` / `audit_snap_floaters` | same |
| Reference image vs render silhouette comparison | `blender_rt_plan(op="qc_compare", args={...})` | `preload="qc"` → `K.dsh_qc_api["compare"](ref, box, render, label=…)` |
| Multi-view QC renders | `qc_render_views` | **`blender_rt_headless(shots=[...])` (new in v0.9.3)**, or `preload="qc,qc_render"` |
| Montage (L2 evidence) | `blender_rt_plan(op="montage")` | `preload="montage"` → `K.dsh_montage_api["montage"]({...})` |
| Delivery export + item-by-item verification | `deliver_export` / `deliver_verify` | `preload="deliver"` → `K.dsh_deliver_api['export']({...})` / `['verify'](dir)` |
| Mechanism joints / sweep / URDF | `motion_*` | `preload="motion"` → `K.dsh_motion_api(...)` |
| Generator reproduction + comparison | `generator_run` | `preload="generator"` → `K.dsh_generator_api["dispatch"]("run", …)` |
| Contract layer (envelope / interference / three-state / ledger) | `blender_rt_plan(op=…)` | `preload="contract"` → `K.dsh_contract_api["dispatch"](op, args_json)` |
| Planner (object graph → bpy) | `blender_rt_plan(op="plan_build")` | `preload="planner"` → `K.dsh_plan_api["dispatch"](op, args_json)` |
| Render performance presets / object slimming | `rt_perf` / `rt_opt` | `preload="perf"` → `K.dsh_perf_api["apply"]` / `["opt_join"]` |
| Transactions / preset library | `rt_txn` / `rt_preset` | `preload="txn"` / `preload="preset"` |
| In-loop search | `rt_loop` | `preload="runner"` → `K.dsh_loop_api["start"](json)` |

> Memory hook: **the preload name = the module name under runtime** (`view, perf, runner, contract, planner, txn, qc, qc_render, preset, audit, montage, motion, deliver, generator`).
> `K.dsh_<name>_api` supports both `api["fn"](...)` (old form, returns a string) and `api("fn", {...})` (since v0.9.1 it returns an **already-parsed dict**).

**① Mesh audit (without running doctor, without Connect)**

```python
blender_rt_headless(
  file="/mnt/d/work/aurora/parts/hull_aft.blend",     # WSL paths are fine (v0.9.3)
  preload="audit",
  script="""
import json
r = K.dsh_audit_api('connectivity', {'scope': 'Hull_Aft', 'micro_gap_mm': 2.0})
print('HEADLESS ' + json.dumps(r, ensure_ascii=False))
""")
```

**② Cross-file interpenetration (most used when part-modelers work in parallel)**

```python
blender_rt_headless(
  preload="audit",
  script="""
import json
r = K.dsh_audit_api('interference', {
    'file_a': '/mnt/d/work/aurora/parts/05_barrel.blend',   'a': '05_barrel',
    'file_b': '/mnt/d/work/aurora/parts/07_handguard.blend','b': '07_handguard',
    'samples': 200000})
print('HEADLESS ' + json.dumps(r, ensure_ascii=False))
""")
```

**③ Silhouette comparison (the headless form of `qc_compare`)**

```python
blender_rt_headless(
  preload="qc",
  script="""
import json
r = K.dsh_qc_api["compare"]("/mnt/d/work/ref/ref_front.png", [9, 38, 444, 545],
                             "/mnt/d/work/out/front.png", label="front",
                             out_dir="/mnt/d/work/out/qc")
print('HEADLESS ' + (r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)))
""")
```

**④ Multi-view renders (`shots`, v0.9.3)**

```python
blender_rt_headless(
  file="/mnt/d/work/aurora/Aurora.blend",
  outdir="/mnt/d/work/out/shots",
  as_job=True,                     # 3 views at 1024×576 will certainly exceed the wait window -> background it directly
  shots=[
    {"name": "iso",   "from": [9, -9, 6],  "look_at": [0, 0, 1], "lens": 35, "res": [1024, 576], "samples": 64},
    {"name": "front", "from": [0, -14, 2], "look_at": [0, 0, 1], "lens": 50, "res": [1024, 576], "samples": 64},
    {"name": "top",   "from": [0, 0, 16],  "look_at": [0, 0, 1], "ortho": True, "ortho_scale": 16, "res": 1024},
  ])
# receipt res.shots = [{name, path, ms, bytes, md5, coverage_estimate, warning?}]
```

**⑤ Delivery export (`deliver_export` + `deliver_verify`)**

```python
blender_rt_headless(
  file="/mnt/d/work/house/House.blend", preload="deliver",
  script="""
import json
print('HEADLESS ' + json.dumps(K.dsh_deliver_api['export'](
    {'dir': '/mnt/d/work/deliver/house', 'scope': 'House', 'name': 'house'}), ensure_ascii=False))
print('HEADLESS ' + json.dumps(K.dsh_deliver_api['verify']('/mnt/d/work/deliver/house'), ensure_ascii=False))
""")
```

### 4.2 When the GUI channel is worth using

**Criterion: Connect only if any one of the three below is true; if none is true, go headless.**

| # | Condition | Typical action | Why GUI is indispensable |
|---|---|---|---|
| ① | **Human in the loop**: you need to "look at the result before deciding the next step" | `rt_see` → judge → `rt_do {see:true}` (≈105 ms/step) | interaction latency 55–105 ms vs headless cold start 1 s+ import |
| ② | **The live scene is itself the deliverable**: you are modifying the unsaved scene the user has in hand | `rt_do` / `rt_loop` / `rt_txn` | headless opens the .blend on disk and cannot modify the in-memory copy |
| ③ | **GUI context is required** | `bpy.ops` that depend on `bpy.context.screen` / the viewport / modality; `gui_frame` / `gui_shading` / `gui_open`; `rt_see(full=true)` to see the whole window UI | a headless process has `bpy.context.screen is None` |

Auxiliary judgment (does not constitute a reason on its own, but can stack):

- `rt_watch` (time-window sampling + per-frame hash): the cheapest way to tell "did it move" — but `dsh_stage` + log deltas also work headless;
- `rt_perf(op="analyze")` (a differential measurement that occupies the main thread for a dozen seconds): only worth it when you want to change settings in the **current GUI session** right away;
- multiple coexisting sessions need `blender_viewport {op:"who"/"lease"}`: **read-only ops do not need it**.

### 4.3 How to write "does this task need GUI + Connect" in a task template

Copy this section straight to the top of the task brief (or the dispatch prompt), **fill in the blanks and it works**:

```markdown
## Execution agreement
- GUI: **no**          # no | yes; if "yes" -> before starting you must get kind=ok from blender_viewport(op="doctor") to continue
- Channel: headless       # headless | gui | mixed
- Expected duration: ~8 min     # >100 s always as_job=true (or let the default wait window expire into promoted)
- Output dir: /mnt/d/work/out/<task>/    # do not write /tmp (see operations tutorial §7.5)
- Result contract: print("HEADLESS " + json.dumps({...}, ensure_ascii=False))
```

How to fill in the three kinds of tasks:

```markdown
# A. One-off script (geometry self-check / data validation, 2-5 s)
- GUI: no | Channel: headless | Expected duration: ~3 s | as_job: not needed
- Call: blender_rt_headless(preload="audit", script="…")

# B. Long render (multi-view / final images, minutes)
- GUI: no | Channel: headless (job layer) | Expected duration: ~20 min | as_job: **yes**
- Call: blender_rt_headless(file=…, shots=[…], as_job=True) -> get {kind:"promoted", jobId} or the jobId directly
- Observe: blender_rt_job(op="status", id="run-…") to watch stage / idleMs

# C. Interactive modeling (the user has Blender open and is waiting)
- GUI: **yes** (doctor first -> kind=ok) | Channel: gui | Expected duration: ~105 ms per step
- Call: blender_rt_do(code=…, see=True); long renders still go to headless, do not occupy the main thread
```

> **Red line**: for a task filled in as "GUI: yes", the first thing on starting is `doctor`; if you cannot get `kind=ok`, **fall back to headless or stop and report an error**,
> do not try to find out by firing commands repeatedly (this is exactly where the friction of 6/7 collaborators in this round came from).

### 4.4 Old form → new form

| Old (v0.9.2 habit) | New (v0.9.3) |
|---|---|
| outer `run_code` without `timeoutMs`, after 120 s only a one-line deadline error comes back | pass `as_job=true`; or take `{kind:"promoted", jobId}` directly and then `op=collect` |
| hand-written regex `result: (\{.*?\})` to extract JSON | `JSON.parse` the 1st text block (single-line envelope) |
| `rt_job(op="start")` + wrapper script + JSON parameter file for passing arguments | `op="start"` accepts `script_file` / `args` / `env` directly |
| loop `op=status` polling (hits harness's repeated-call detection) | `op="wait"` (blocks until completion or timeout, returns a structured receipt) |
| hand-assembled `\\wsl.localhost\Ubuntu\…` UNC strings | `outdir="/home/…"` give the WSL path directly |
| every modeler writes their own 50~60 lines of camera / three-point light / AgX boilerplate | `shots=[{name, from, look_at, lens, res, samples, ortho, ortho_scale, margin}]` |
| 20-minute task is a black box the whole way (log 0 bytes) | `PYTHONUNBUFFERED=1` + `dsh_stage("building")` → `op=status.stage` |
| hand-written world-vertex hashing / BVH floater scan | `audit_duplicates` / `audit_snap_floaters` / `audit_connectivity` (§4.1) |

### 4.5 The three exits for long work (remember this one table)

| Situation | How to start | How to collect |
|---|---|---|
| expected < wait window (default 100 s) | `blender_rt_headless(script=…)` | take the envelope of the 1st block directly (`status:"finished"`) |
| expected > 100 s | `blender_rt_headless(…, as_job=True)` | returns `{kind:"promoted", jobId:"run-…"}` → `blender_rt_job(op="collect", id=…)` |
| want to wait a while first | `blender_rt_headless(…, as_job=True, wait_s=15)` | if it finishes within 15 s you get the result on the spot; if not, `{kind:"promoted", jobId}` |
| already running | — | `op="wait"` (blocking) / `op="status"` (see stage, idleMs) / `op="kill"` (idempotent) |

`run-…` and `job-…` are **the same id space**: `status / collect / kill / wait` all accept both prefixes.

### 4.6 Long-task observability (script-side contract)

```python
# stage heartbeats from the script (bootstrap-injected dsh_stage, equivalent to K.progress)
dsh_stage("loading")          # -> the plugin side parses stage="loading"
dsh_stage("building", part="hull_aft")     # custom keys are allowed
for i, ob in enumerate(objs):
    ...
    dsh_stage("rendering", done=i + 1, total=len(objs))
```

The plugin side parses the last one into `op=status.stage` (also giving `stageAt` / `lastOutputAt` / `idleMs` / `lines` / `pidAlive`);
together with `PYTHONUNBUFFERED=1` already injected at the three spawn sites, `<jobdir>/stdout.log` has deltas **while running**.

```python
blender_rt_job(op="status", id="run-abc123")   # → stage / idleMs / pidAlive
blender_rt_job(op="wait",   id="run-abc123", timeout_ms=600000)
blender_rt_job(op="kill",   id="job-nonexistent")   # does not error: returns "already finished / does not exist"
```

---

## 5. Migration checklist (a taking-over session just follows it)

1. First fill the five lines of §4.3 into the task brief (GUI / channel / expected duration / output dir / result contract).
2. "GUI: no" → **do not** run `doctor`, go headless directly; if you need an audit, copy §4.1 ①②③.
3. Expected > 100 s → `as_job=True`; once the receipt gives a `jobId`, note it down first, then decide whether to `wait` or do something else.
4. Always parse receipts as "two text blocks" (envelope + summary); no more regex.
5. Temporary files go into the **workspace**, not `/tmp` (reason in [operation-tutorial.md](operation-tutorial.md) §7.5).
6. Image reading and measuring per [evidence-grading-and-image-reading.md](evidence-grading-and-image-reading.md) §6/§7 (`[::-1]`, BVHTree, provenance).

---

## 6. Boundaries and reversal conditions

**Cases in which this decision does not hold (should go back to GUI)**:

- The task's **intermediate judgments** must be made by a human looking at the picture (aesthetic tweaks, manual placement);
- The deliverable is **that unsaved scene in the user's memory**;
- `bpy.ops` / modal operations / viewport screenshots that depend on GUI context.

**Reversal conditions (re-evaluate this decision if any one appears)**:

1. The share of tasks that "must be done on the live scene" is **> 50%**;
2. headless cold start + import cost becomes the bottleneck (→ first use a `blender_rt_worker` hot session, and only discuss further if that is still not enough);
3. The GUI channel gains a **new capability** that headless cannot do (for example render / interaction features only the GUI can provide).

**Hard constraint of parallelism** (unchanged by this decision): rendering EEVEE in multiple processes at once fights over the same GPU —
`qc_render_views` already has `render_lock` built in (`<workdir>/locks/render.lock`, waits for the lock 120 s by default);
part-modelers **must not** invent their own render lock.

---

## 7. Acceptance: how to confirm this route really works

**① Without opening the GUI, without Connect, you can still get an audit report** (copy and run):

```python
blender_rt_headless(preload="audit", script="""
import json
print('HEADLESS ' + json.dumps(K.dsh_audit_api('selftest'), ensure_ascii=False))
""")
# expected: envelope status="finished", resultJson.ok true -- not a single 9876 interaction anywhere
```

**② promoted semantics** (D1's acceptance, equivalent to item 1 of §8 of the handover document):

```python
blender_rt_headless(script="import time; time.sleep(200); print('HEADLESS {"a": 1}')", timeout_ms=900000)
# expected: the wait window (default 100 s) returns {kind:"promoted", jobId:"run-…"} first, not a deadline error
blender_rt_job(op="collect", id="run-…")     # → resultJson.a == 1
```

**③ Long-task observability** (D5's acceptance):

```python
blender_rt_headless(script="""
import time
for i in range(10):
    dsh_stage('tick', i=i); time.sleep(2)
print('HEADLESS {"done": true}')
""", as_job=True)
# meanwhile: blender_rt_job(op="status", id=…) stage is changing and idleMs is growing; stdout.log has deltas
```

All three pass = this route holds in your environment.
