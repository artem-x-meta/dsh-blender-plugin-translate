# Operations tutorial -- from zero to fluent

> For someone holding this package for the first time: **install → connect → use it → debug it**, about 40 minutes in total (5 minutes once you are fluent).
> Current version: plugin **v3.0.6** (15 model tools) · Blender addon **v1.11 / protocol 11** · backend `127.0.0.1:9877` / addon `127.0.0.1:9876`.
> Prerequisites (Blender + `DSH Blender Bridge` addon + Node ≥ 24.9 + DSH; **the headless path does not require the GUI to be open**) see [README §2](../README.md#requirements).
> Configuration items (work dir / blender.exe / ports / lease / worker TTL) see [configuration-reference.md](configuration-reference.md).

---

## 0. Mental model: understand these 4 things first

1. **Three lanes running in parallel**
   - **GUI direct channel**: TCP `127.0.0.1:9876` → addon; millisecond-level and real-time, but **requires the Blender GUI to be open**, and every command occupies it serially.
   - **Interactive headless session**: a persistent `blender -b` worker (`blender_rt_worker`); `rt_do` / `rt_see` / `rt_watch` with `session` (or automatic downgrade when the GUI is unreachable) go through it, and with `session="auto"` most plan ops in `rt_plan` also execute synchronously inside the worker -- **no GUI needed**.
   - **One-off headless process**: `blender.exe -b` (`blender_rt_headless` / `blender_rt_job`), an independent process; for heavy rendering / batch geometry / data validation, **does not occupy the GUI channel**, and can run at the same time as the two lanes above.
2. **Three kinds of "looking"** (all produce images through `blender_rt_see`, but with different semantics; without a GUI pass `session` to use the worker's Workbench offscreen frame)
   - Viewport frame = **the angle the user is currently looking at** (including viewport shading and overlays);
   - Custom view = **the camera you specify** (`from` + `look_at`; no camera is created and the user's viewport is not touched);
   - `full=true` = **the whole Blender window** (goes through `screenshot_area`; for looking at the UI / panels / other editors).
3. **Inner loop vs outer loop**: a model turn (seconds) is expensive, the Blender event loop (160 tick/s) is cheap →
   **put search on the Blender side (`blender_rt_loop`), put decisions and acceptance on the model side**. See [operation-tutorial.md](operation-tutorial.md) for details.
4. **Concurrency**: write operations are protected by a "lease". Invisible by default; once another session holds it, your write operations get `409 leased` (read-only operations are not restricted).

> Methodology: how to clearly report unresolved when evidence is insufficient, flip a hypothesis with a probe, and write down "why it was modeled this way" -- see the [hypothesis-driven modeling cookbook](assumption-driven-modeling-cookbook.md).

### When to use which tool

| What you want to do | Which to use | Why |
|---|---|---|
| Take a look at what it looks like now | `blender_rt_see` | 50-160 ms, the cheapest; **pass `session` when there is no GUI** |
| Look from another angle (without moving the user's viewport) | `blender_rt_see {from, look_at}` | Zero scene changes, repeatable (stable md5); without a GUI it goes through the worker offscreen |
| Change one step and verify immediately | `blender_rt_do {see:true}` | One atomic step ≈105 ms; **pass `session` when there is no GUI** (50-150 ms/step) |
| Judge "did it move / is it right" | `blender_rt_watch` | Continuous sampling over a time window + per-frame hash, at most 6 frames at a time; headless can pass `session` |
| Search / fit parameters (thousands of iterations) | `blender_rt_loop` | Runs in the inner loop, costs no model turns; headless passes `target:"session"` |
| Measurement with multiple objectives + constraints | `blender_rt_loop` + `penalize` | Penalty terms fold violations into a single score |
| Cross-check / reuse after convergence | Recompute through another pathway + `blender_rt_loop op=export` | Guards against "only optimized the objective function you wrote" |
| Run the same script repeatedly / interact without a GUI | `blender_rt_worker` | Persistent `blender -b`; preload injects modules, see produces frames; idle 15 min auto-reclaim |
| Run a plan op headless (verdict/acceptance/export) | `blender_rt_plan {session:"auto"}` | Automatically starts a worker + injects preload by family, returns synchronously |
| Cycles final render / large batch geometry / validation | `blender_rt_headless` | Independent process: does not occupy the GUI, does not hit a CUDA context, can be killed on timeout |
| Long work / batch processing (>100 s) | `blender_rt_job` | Background job + wait/collect, results are not lost on timeout |
| Offline multi-angle batch rendering | `blender_rt_headless {preload:"view"}` | Use `K.dsh_view_api` directly in the headless process |
| Measure sizes / calibrate from reference images | `img_digest / img_probe / img_measure / img_calib` | Turns "cannot see clearly" into a numeric table instead of eyeballing |
| Assembly merge / interpenetration / repair / delivery | `asm_scan / asm_manifest / asm_merge / asm_repair / asm_export / asm_gate` | manifest-driven + three-state verdict + export only after the gate |
| Blockout / Seedance reference pack | `blockout_base / batch / export / refsheet / turntable` | Declarative parts + 4-view PNG/montage + MP4 turntable |
| Same-camera-position QC with a one-page verdict | `visualreport_report` | IoU / missing and excess area / defect crops + mm localization |
| Back-solve sizes from a reference image | `shapesolve_solve` | Headless multi-view contour fitting, no render, no dependency on timers |
| Defect evaluation (can the plugin catch it) | `eval_run` | Synthetic defect set capture_rate + baseline replay |
| Pre-work check-up / rollback point / forced delivery | `gate_preflight / gate_checkpoint / gate_deliver` | No export without passing the gate; drill into the delivery flow |
| Rendering is slow, need to tune | `blender_rt_perf` status → analyze → apply first | Measure before tuning; the preset can be reverted |
| Too many scene objects makes each round's sync slow | `blender_rt_opt` analyze → join | ≈1.4 ms/object; zero geometry loss, always save a rollback point first |
| Something is broken and you do not know where it is stuck | `blender_viewport {op:"doctor"}` | Really runs one bpy round trip + three-level verdict + fix |
| Several sessions fighting over one Blender | `blender_viewport {op:"who"}` → `op:"lease"` | A 409 states the holder and the remaining time explicitly |

---

## 1. Installation and connectivity

### 1.1 Blender side: install the addon and Connect

1. Put the `DSH Blender Bridge` addon into Blender's addon directory (`Edit ▸ Preferences ▸ Add-ons ▸ Install...` pick the zip / or unzip it into the Blender user addons directory; module name `dsh_blender_bridge`).
2. Enable it (tick the checkbox).
3. Open a **3D View**, press `N` to open the right sidebar → find the "DSH Blender Bridge" panel → click **Connect** (default port 9876).
4. In the panel you can casually enable the integrations you need (PolyHaven / Hyper3D / Sketchfab / Poly Pizza / Hunyuan3D); **these switches are scene properties** -- remember to save them into your startup / project file after changing them (restarting Blender loses unsaved changes).

> ⚠️ **addon migration**: only this repository's `DSH Blender Bridge` **v1.11+ / protocol 11** is supported. The old `MCP for Blender` / `blender_mcp` are **no longer supported**; disable the old addon first, then install/enable this repository's addon (both occupy 9876 and cannot be enabled simultaneously). Migration points: see [../MIGRATIONS.md](../MIGRATIONS.md).

> To tell whether the addon is listening: run `curl -sS http://127.0.0.1:9877/doctor` in a terminal; or just `node lib/runtime/_probe_tools.js` to see the command surface.

### 1.2 Install the plugin from npm (ordinary users)

Ordinary users do not need to clone or build; the npm package ships the built `lib/`.

```bash
dsh plugin --profile <profile> add dsh-blender-plugin@3.0.6
dsh --profile <profile> --dump-config | grep -A3 dsh-blender-plugin
# then restart DSH
```

> DSH Desktop users can install the bundle `dsh-blender-plugin@3.0.6` from the Plugins page.
> Do not use both "runtime injection" and "bundle assembly" at the same time: the two fibers would register the same tool names twice.

### 1.3 Build from source (developers)

Only needed when you modify the plugin source:

```bash
git clone https://github.com/sixtysevenlf/dsh-blender-plugin.git
cd dsh-blender-plugin
npm ci --legacy-peer-deps && npm run build   # builds lib/ and lib/runtime/
```

Then link the checkout into the profile the way developers do: create a junction at `node_modules/dsh-blender-plugin`,
add `"dsh-blender-plugin": "link:<absolute path to this directory>"` to the profile's `dependencies`,
add `"dsh-blender-plugin"` to `dsh.profile.bundles`, then rehearse with `--dump-config` and restart DSH.

### 1.4 Backend self-check (three commands)

```bash
curl -sS http://127.0.0.1:9877/health   # {"ok":true,...}    the backend process is alive
curl -sS http://127.0.0.1:9877/doctor   # ⭐ only kind=ok means "Blender is connected too"
curl -sS http://127.0.0.1:9877/who      # lease + channel metrics + current effective config
```

**The only acceptance criterion**: `/doctor` returns `kind=ok` (or `blender_viewport(op="doctor")` returns `kind=ok`). Failure of the other self-checks only means that particular function has a problem and **cannot replace** this acceptance check.

Key fields in the `/doctor` response:

| Field | Meaning |
|---|---|
| `kind` | `ok` / `blender-unreachable` / `main-thread-busy` / `addon-thread-stuck` / `addon-unresponsive` / `addon-error` |
| `summary` `fix` | One-sentence conclusion + one-sentence fix (just do it) |
| `ping_ms` `roundTripMs` | Timing of `ping` (does not touch bpy) and `status` (really runs bpy) |
| `config` | **Current effective config**: work dir, blender.exe, ports, source of the config file -- look at it first when debugging |

### 1.5 Plugin tool self-check

```text
blender_viewport(op="doctor")          # same as /doctor but more readable in the tool response; kind=ok is the only acceptance criterion
blender_rt_plan(op="catalog")          # should be 34 families / 228 ops (15 model tools)
blender_rt_commands()                  # addon command table (resident + integration-gated) + 5 integration states
blender_rt_see(max_size=560)           # with the GUI online: should return an image, 50-100 ms
blender_rt_worker(op="start")          # fully headless: after worker start, op="see" should also return a frame
```

### 1.6 addon compatibility probe

```bash
node lib/runtime/_probe_tools.js
# calls ping / get_scene_info / get_object_info(name) / get_viewport_screenshot / execute_code ... one by one
# prints ok and timing for each command; whichever fails means that addon version lacks that command
```

### 1.7 Bundled skill self-check

**No separate installation needed**: the `blender-modeling` skill is right in the plugin package's `skills/blender-modeling/`, and DSH registers it as a bundled skill on startup
(rank 600; if you have your own user-level 400 copy at `~/.dsh/skills/blender-modeling`, that one still takes priority).

```text
# after restarting DSH: have the model load the skill; being able to read the full modeling flow means it passes
skill(name="blender-modeling")

# you can also verify the in-package assets and registration convention offline without restarting:
npx vitest run tests/unit/js/contract/skill-bundle.test.ts     # Vitest contract test (includes SkillRegistry integration with signal; skipped when there is no host)
```

---

## 2. Getting started with the fifteen tools one by one

> Convention: all tools require **the backend to be running** (the plugin starts it automatically); tools that go through the GUI channel additionally require Blender's addon to be Connected.
> `blender_rt_headless` / `blender_rt_job` / `blender_rt_worker`, and the `session` path of `rt_do|rt_see|rt_watch|rt_plan` **do not need a GUI**.
> Parameter names are the original names in the tool schema (the same on WSL / Windows).

### ① `blender_rt_see` -- look

| Parameter | Description |
|---|---|
| `max_size` | Longest-side pixels, default 560 (420 is faster, 900 is sharper; cap 1600) |
| `full` + `area` | Whole-window screenshot / the Nth area (for looking at the UI) |
| `from` `look_at` | Custom view: camera position / look-at point, `"x,y,z"` or an array |
| `lens` `ortho` `ortho_scale` | Focal length in mm (default 50) / orthographic toggle / orthographic scale (fits the long edge) |
| `view_size` | `"widthxheight"`, e.g. `"1280x720"`; by default it renders 16:9 according to `max_size` |
| `shading` `overlays` | Temporarily switch shading (WIREFRAME/SOLID/MATERIAL/RENDERED) / overlays, restored after rendering |
| `view_mode` | `viewport` (default, zero scene changes) / `render` (temporary camera + quick Workbench render) |
| `session` / `auto` | `session="s1"` **goes to the persistent headless worker directly** (no GUI probing); `auto` (default true) = automatically downgrade to headless see when the GUI is unavailable |

```text
blender_rt_see(max_size=560)
blender_rt_see(from="9,-9,6", look_at="0,0,1", lens=35)
blender_rt_see(from="0,0,12", look_at="0,0,1", ortho=True, ortho_scale=12, shading="MATERIAL", view_size="1024x1024")
blender_rt_see(full=True, area=0)     # the whole Blender window
```

Note: `viewport` mode renders the "look of the viewport", **not** a Cycles final render; for a final render use `blender_rt_headless`.
Without a GUI: `blender_rt_see(session="s1", from=…, look_at=…)` uses the worker's Workbench offscreen frame (the same custom-view parameters apply; `full` whole-window screenshots require a GUI).

### ② `blender_rt_do` -- do (plus a quick look)

```text
blender_rt_do(code="K.n = getattr(K, 'n', 0) + 1
bpy.data.objects['Cube'].rotation_euler.z += 0.4", see=True)

# no GUI: explicit session (the same name reuses the same blender -b process; K is retained across calls)
blender_rt_do(session="s1", preload="audit,assembly", code="…", see=True)
```

- The code executes on the **Blender main thread**, with `bpy / math / mathutils / Vector` pre-set;
- **Persistent kernel `K`**: `execute_code` gets a brand-new namespace each time, so cross-call state must hang off `K`;
- `see=true` (default) returns a frame along the way; a full step with a GUI is ≈105 ms;
- **P0 headless interaction**: when the GUI is offline or `session` is passed, it downgrades automatically to the persistent headless worker (`exec` + Workbench `see`, the same hot path, not a job/async); the first cold start is ~2 s, then each step is **50-150 ms**; a fixed `session` name reuses the same Blender session, and `auto=false` disables the downgrade.

### ③ `blender_rt_watch` -- continuous observation

```text
blender_rt_watch(code="bpy.app.timers.register(tick)", seconds=2.5, fps=4, max_size=420)
```

Returns ≤6 frames + **per-frame hash**: all hashes identical = the image did not change (the animation did not run / the parameter did not take effect). Do not set `fps` too high (each frame occupies the main thread for ~55-100 ms and will stutter the user's experience).
**Headless**: pass `session="s1"` to go directly to the worker's `_watch` (per-frame Workbench offscreen + hash); without `session`, a full-frame failure in the GUI also downgrades automatically.

### ④ `blender_rt_loop` -- inner-loop search (the most central one)

```text
blender_rt_loop(op="start", spec={
  "setup":  "import random\nK.ob = bpy.data.objects['Cube']",
  "step":   "px = ns['i'] % 7; ns['params'] = {'sx': 1 + px * 0.1}",
  "measure":"ns['score'] = abs(bpy.data.objects['Cube'].dimensions.x - 2.0)",
  "iterations": 3000, "budget_ms": 20000, "interval": 0, "measure_every": 5,
  "minimize": True, "top_k": 20, "group_key": None
})
blender_rt_loop(op="status", history=12)
blender_rt_loop(op="board", limit=10)
blender_rt_loop(op="export", path="/tmp/best_fit.py", top=3)
blender_rt_loop(op="stop")            # emergency stop
```

- `setup/step/measure` source shares the namespace `ns`; `measure` must write `ns["score"]` and may write `ns["params"] / ns["metrics"] / ns["violations"]`;
- Pre-set: `bpy / K / math / random / numpy(np) / i / frac / penalize / anneal / record`;
- **You must give `iterations` or `budget_ms`** (safety valve); `interval=0` is fastest; `redraw_every=0` (no redraw) is fastest;
- Multiple objectives: `ns['score'] = penalize(errors_dict, violations, weights, lam)`; step annealing: `anneal(v0, v1, ns['frac'])`;
- `top_k + group_key` = candidate table (for cross-object batches, keep the best per object group);
- **Headless**: `target="session"` (optionally with a `session` name) uses the worker's blocking inner loop `dsh_loop_sync`, independent of GUI timers; the tool starts a worker with `preload="runner"` automatically (measured: 20 iterations in 56 ms);
- `op=help` prints the full contract.

### ⑤ `blender_rt_cmd` -- pass through arbitrary addon commands

```text
blender_rt_cmd(name="ping")
blender_rt_cmd(name="get_object_info", params={"name": "Cube"})
blender_rt_cmd(name="get_scene_info")
```

⚠️ **Pass arguments according to the addon's real signature**: `get_scene_info()` takes no arguments, `get_object_info(name)` uses `name`. The direct channel has no schema layer to rename things for you; passing the wrong name gives `unexpected keyword argument`.

### ⑥ `blender_rt_commands` -- command surface and integration state

Returns: the list of available commands (resident + those gated by integration switches), the 5 integration switch states and messages. **Ask it before calling `blender_rt_cmd`.**

### ⑦ `blender_rt_perf` -- render performance

```text
blender_rt_perf(op="status")     # current state (engine/device/samples/denoise/persistent/object count)
blender_rt_perf(op="analyze")    # differential measurement: CPU-side sync per round vs GPU cost per sample (occupies the main thread for a dozen seconds)
blender_rt_perf(op="apply")      # preset: persistent_data + automatic denoiser choice + auto_tile off + sample cap
blender_rt_perf(op="revert")     # restore the state before apply (a snapshot is saved automatically)
```

Rule of thumb (author's machine, 2318 objects): **CPU sync per round ≈4.2 s; persistent_data takes repeated rendering from 14.6 s → 0.79 s**; cutting samples barely helps the CPU side.

### ⑧ `blender_rt_opt` -- object slimming

```text
blender_rt_opt(op="analyze")
blender_rt_opt(op="join", args={dry_run=True})                      # dry run first and read the report
blender_rt_opt(op="join", args={dry_run=False, save_before="/tmp/pre_join.blend"})
```

Merge rules (safe): same collection / same material / same parent / no modifiers / no animation / no shape keys / no custom properties / no instances / not library-linked → **zero geometry loss** (face and vertex counts unchanged). Always give `save_before` first.

### ⑨ `blender_rt_headless` -- headless process

| Parameter | Description |
|---|---|
| `script` / `script_file` | Python source / run a .py file directly (the latter injects `__file__` + sys.path automatically, which is handier for multi-file projects) |
| `file` | The .blend to open (WSL or Windows paths both work, mapped automatically) |
| `outdir` / `out_json` | Artifact directory / structured-result output path (both accept WSL paths) |
| `preload` | Preload runtime modules (comma-separated) → `K.dsh_*_api`, e.g. `"audit,qc,qc_render"`, `"assembly,audit,contract,clearance,gate,mesh_fix,geo,txn"`, `"imgtools"` |
| `engine` | `eevee` (default, with the ray-tracing preamble) / `cycles` / `keep` / `none` (pure numpy/image tasks save 1-1.5 s) |
| `shots` | Multi-view rendering in one go (see §7.2), can be combined with `attach_images` to attach images |
| `attach_images` | `true` = attach at most 3 `shots` images; `"sheet"` = attach only the montage |
| `as_job` / `wait_s` | Background immediately / keep waiting a few more seconds after backgrounding; use directly for work expected to exceed 100 s |
| `timeout_ms` | Default 180000, cap 1800000 (SIGKILL on timeout) |
| `factory_startup` | Default true (clean, fast, does not fight a running addon for 9876); set false to use user preferences/startup file |
| `use_user_config` | Pass through `BLENDER_USER_CONFIG/SCRIPTS` (together with `factory_startup=false`) |
| `bootstrap` | Default true (injects `K`); when false the script runs as-is |
| `env` / `args` / `workdir` | Subprocess environment variables / extra command-line arguments (paired quotes are not split: `--flag "a b"`) / chdir inside the script + sys.path first position |
| `expect` | Assertions (such as `{"minNewObjects":1}`): an empty run fails immediately |
| `include_noise` | Whether the artifact list includes `__pycache__` / `*.blend1` (filtered by default) |

Convention: `print("HEADLESS {json}")` in the script → the tool parses the last line into `result`. **Headless needs no GUI and does not occupy 9876.**

> **Long-work boundary**: the per-call limit = `timeout_ms` (default 180 s, cap 30 min).
> **Work exceeding ~100 s should use `as_job:true` directly**: when the wait window (default 100 s) expires it returns `{kind:"promoted", jobId}` -- the child process keeps running, and you collect the result with `blender_rt_job(op="wait"/"collect")`; **a timeout ≠ a failure**. For batch / all-night tasks use `blender_rt_job`.

```text
blender_rt_headless(file="D:\\work\\scene.blend", outdir="D:\\work\\out", timeout_ms=600000,
  preload="view",
  script="import json,bpy;bpy.ops.render.render(write_still=True)" +
         "\nprint('HEADLESS ' + json.dumps({'objs': len(bpy.data.objects)}))")
```

### ⑩ `blender_rt_job` -- job layer (long work / batch)

```text
blender_rt_job(op="start", script_file="/home/me/proj/tools/build.py", args="--part hull",
               env={"STAGE": "qc"}, outdir="/home/me/proj/out", timeout_ms=1200000)
blender_rt_job(op="status", id="run-…")            # stage / idleMs / pidAlive / lines
blender_rt_job(op="wait",   id="run-…", timeout_ms=600000)   # block until done or timeout; returns a structured receipt
blender_rt_job(op="collect", id="run-…")          # collect the final result (stdout tail + resultJson + artifacts)
blender_rt_job(op="kill",   id="run-…")           # idempotent: returns ok even if already finished / nonexistent
blender_rt_job(op="list")                          # all jobs
```

- `start` takes the **same-shape** parameters as `blender_rt_headless` (`script_file/args/env/factory_startup/bootstrap/workdir/outdir/include_noise/engine/preload`);
- **`run-…` and `job-…` share one id space**: `status / wait / collect / kill` all accept both prefixes;
- A job does not hold a client connection and will not be cut off by tool timeouts; after a backend restart it recovers state from the on-disk ledger (a stale running job converges to `stale`);
- The receipt is isomorphic to headless (single-line JSON envelope + human-readable summary); `dsh_stage("building")` heartbeats in the script go into `status.stage`.

### ⑪ `blender_rt_plan` -- the single entry point for verdict / acceptance / export / modeling

> Currently **34 families / 228 ops**. If you are unsure which to use, `op="catalog"` first; for a single family `args={family:"audit"}`; for operator details `<family>_help`.
> **Headless execution**: `blender_rt_plan(op="asm_scan", session="auto", args={…})` -- `session="auto"` starts a persistent worker automatically, injects the preload the family needs, and returns the result synchronously; it covers verdict/acceptance/modeling families such as `asm_/blockout_/img_/gate_/eval_/visualreport_/shapesolve_/audit_/qc_/sculpt_/fix_/…` (ops without a headless mapping report an explicit error; check with `catalog` first).
> The receipt is a verdict-first single-line receipt (verdict / top_defects / next), and `attach_images=true` can attach ≤2 artifact images.

**Contract layer** (turning "hypothesis / interval / validation / evidence / gating" into something machine-checkable):

```text
blender_rt_plan(op="register_component",  args={cid:"backrest", objects:["Backrest","Tenon"], tags:["backrest"]})
blender_rt_plan(op="register_connection", args={cid:"joint", a:"seat", b:"backrest",
    candidates:["attach","insert"], params:{dy:{range:[0,0.03]}, tenon_len:{range:[0.03,0.10]}},
    forbidden:["boolean_union","weld"], confidence:"medium", evidence_required:["probe_dismount"]})
blender_rt_plan(op="register_envelope",   args={eid:"env", mn:[-0.5,-0.5,0], mx:[0.5,0.6,1.5], scope:["Seat","Backrest"]})
blender_rt_plan(op="check_envelope",      args={eid:"env"})                       # out-of-bounds list (read-only)
blender_rt_plan(op="check_interference",  args={scope:["CH_"], use_bvh:true})      # AABB scan + BVH fine check
blender_rt_plan(op="check_interface",     args={conn_id:"joint"})                 # clearance / intrusion between two components
blender_rt_plan(op="destructive_guard",   args={op:"boolean_union", targets:["Backrest"]})   # not yet discriminated → blocked
blender_rt_plan(op="evidence",            args={label:"side", view:{...}})         # render + md5 accounting
blender_rt_plan(op="verify", args={conn_id:"joint", err:184, tolerance:220, identifiable:["dy"]})  # → unresolved
blender_rt_plan(op="verify", args={conn_id:"joint", probe_err:0.005, probe_tolerance:0.01})       # → supported
blender_rt_plan(op="report", path="D:\\DSH\\blender\\out\\plan_report.md")
```

**Planner** (object graph → diagnosis → compilation):

```text
blender_rt_plan(op="plan_load",  args={plan:{...}})     # diagnosing starts on load (UnresolvedConnection / Cycle / ParamOutOfRange…)
blender_rt_plan(op="plan_order")                        # topology: components → connections → features
blender_rt_plan(op="plan_build", args={dry_run:true})   # look at the plan first (no scene changes)
blender_rt_plan(op="plan_build", args={dry_run:false})  # compile into PLAN_* objects (expanded by hidden_when / offset / feature)
blender_rt_plan(op="plan_graph", args={fmt:"mermaid"})  # export graph text
```

Criteria and flow (including "insufficient external evidence must report unresolved" and 7 pitfalls measured in practice): `docs/assumption-driven-modeling-cookbook.md`.

#### Multi-view render harness -- one command for N images + jsonl + budget decision

```text
blender_rt_plan(op="qc_render_views", args={
  views: ["iso","front","right"],        # named view / "az=35,el=20" / {name, from, look_at, lens, ortho}
  res: [512,512], samples: 64,           # samples are written to both EEVEE taa_render_samples and Cycles samples
  budget_s: 120,                         # alias thr; stop immediately once the cumulative render exceeds it, keep the images already produced
  outdir: "D:/DSH/blender/out/qc_render_p21",
  ref_path: "D:/work/ref_front.png", ref_box: [9,38,444,545]   # optional: run qc_compare per image (fixed alignment by default)
})
```

- **Automatic framing**: merge the AABB of all visible meshes (`targets:[names]` can restrict it) → solve the camera distance per angle + `margin` (default 1.12);
  if `from`/`look_at` are given, use the explicit camera position and do not auto-frame.
- **Fixed three-point light**: SUN key 3.2 / fill 1.0 / rim 2.4, angles fixed and relative to the camera azimuth (+35°/45°, -50°/8°, +165°/30°);
  **built temporarily only inside this process**, deleted after rendering, and all scene render settings restored (`lights_mode:"only"` can temporarily mask the scene's lights, also restored).
- **Output**: `<outdir>/<tag>_<view>.png` + `<outdir>/render_views.jsonl`, one line per image
  (`{view, ms, bytes, hash, path, res, engine, samples, camera, frame{bbox, margin_px, coverage, pred_bbox_px, proj_err_px}}`).
- **Budget**: `within_budget=false` + `stopped_early` + `skipped_views`; completed rows/images are **not deleted**.
- **Long work**: `args.asJob=true` hands over to the job layer (a headless process isolates the scene naturally); retrieve the result with `blender_rt_job(op="collect", id=...)`;
  you can also run it directly in headless: `blender_rt_headless(file=..., preload="qc,qc_render", script="print('HEADLESS ' + K.dsh_qc_render_api['render_views']({...}))")`.
- **No scene changes**: inside a GUI process it refuses to open another `.blend` by default (pass `allow_open_file=true` to open one); temporary cameras/lights are deleted right after use.
- Self-check: `blender_rt_plan(op="qc_render_help")` gives a parameter quick reference; `K.dsh_qc_render_api["selftest"]()` runs the framing/projection self-check.

Measured (350 visible meshes / 512×512 / 64 samples / EEVEE+RT): 3 views 2124 / 798 / 565 ms, 3487 ms in total, 3 jsonl lines,
36 px margin on all four sides of the 512 frame (predicted bbox vs actual alpha bbox differ by ≤2 px); a control run with a 1.0 s budget produced only 1 image, stopped, and kept it.

#### Mesh inspection / montage / glass optics

```text
blender_rt_plan(op="audit_scene", args={envelope:[-10,-5,0,10,5,3]})    # whole-scene inspection: dirtiest objects + out-of-bounds parts
blender_rt_plan(op="audit_mesh",  args={objects:["P01_Fuselage"]})       # single-object deep-dive (self-intersection/boundary edges/degenerate faces/normals)
blender_rt_plan(op="audit_duplicates")                                  # forked same-name materials/meshes (first-wins overwrite hazard)
blender_rt_plan(op="audit_purge_orphans")                               # purge lights/cameras/meshes/materials with users==0
blender_rt_preset(op="glass", args={targets:"OBJ:Canopy", use_alpha:true, alpha:0.3})
```

- **Hard rule**: 0 meshes among the inspected objects ⇒ `ok=false` ("a build dry run" must fail; stop relying on your eyes to find it).
- Self-intersection uses BVHTree and reports the **number of intersecting face pairs** plus sample coordinates; `normals_outward` is only meaningful for closed meshes (given only when `closed=true`).
- Montage: `K.dsh_montage_api["montage"](paths, cols, tile, out, labels, grid, scale_m)` -- default tile 420,
  total width ≤1700 px (beyond that the harness rescales again and small-panel detail blurs first), with grid/scale bar/numbering/per-panel metrics.
- Image-reading discipline (L0-L3, ≤6 images per round, write assertions before reading) see `docs/evidence-grading-and-image-reading.md`.
- New `qc_render_views` parameters: `warmup` (compilation frames are not timed, on by default), `ladder`+`per_view_budget_s` (quality ladder),
  `aabb`/`focus` (world-space framing), `sheet=N` (panel grid), `chunk=[i,n]` (sharding).
- New headless parameters: `expect={"minNewObjects":1}` (an empty run fails immediately), `workdir=…`, `engine="none"` (pure python, no preamble).


### ⑫ `blender_rt_worker` -- interactive headless session / hot worker

A persistent `blender -b` process: saves the cold start and repeated imports/rebuilds each time when you **iterate repeatedly / interact without a GUI**.

```text
blender_rt_worker(op="start", name="s1", preload="audit,assembly,imgtools")  # preload injects K.dsh_*_api; warmup defaults to true
blender_rt_worker(op="exec", name="s1", code="K.i = getattr(K, 'i', 0) + 1\nprint('HEADLESS {\"i\": K.i}')")
blender_rt_worker(op="see",  name="s1", from="7,-7,5", look_at="0,0,1", view_size="560x315")  # Workbench offscreen frame
blender_rt_worker(op="reset", name="s1")            # clear the scene (when switching tasks)
blender_rt_worker(op="status", name="s1")           # uptime / calls / objects / idleMs / loaded K.*_api
blender_rt_worker(op="list")                        # all hot sessions
blender_rt_worker(op="stop", name="s1")             # clean exit (restart = stop+start for a fresh process)
```

Semantics:

- `preload` (at start): injects `audit/qc/qc_render/runner/assembly/blockout/imgtools/...` into `K.dsh_*_api`; **if preload fails, `start` errors out directly** (no silently missing modules). `warmup=true` (default) warms up the renderer;
- **Idle reclamation**: the worker pool is reclaimed automatically after **15 min** without requests by default (`DSH_WORKER_TTL_MS` adjustable, 0=off; see [configuration-reference.md](configuration-reference.md)); `status` and receipts carry `idleMs`;
- Limits: **serial** (long code occupies the worker); **no window** (`bpy.ops` that depend on GUI context may fail; use `temp_override` or switch to the GUI channel); does not interfere with the GUI channel (separate process, does not occupy 9876/9877);
- The `session` of `rt_do` / `rt_see` / `rt_watch`, `rt_plan`'s `session="auto"`, and `rt_loop target="session"` all reuse this worker set (same session name = same Blender process + persistent `K`).

Supporting semantics:

- `blender_rt_headless` injects the **GPU preamble** (`gpu:"auto"`) by default and reports a `gpu` field back -- a headless process cannot read user preferences, and Cycles silently falls back to CPU (measured 15.4×);
- On failure it gives **structured** information: `logs` (full log path), `lastException`, `traceback`, `reason`;
- `outdir` artifacts **filter out** `__pycache__ / *.pyc / *.blend1|2 / tmp*` by default;
- **A client timeout ≠ a task failure**: the server-side child process keeps running to completion and artifacts still land on disk (for >100 s use `as_job` / the job layer / a hot session);
- `/headless` `/worker` `/txn` `/preset` stream one heartbeat line every 15 s and the client takes the last line -- long calls no longer show `exit=undefined`, and the receipt is complete.

### ⑬ `blender_rt_txn` -- transactions / rollback

```text
blender_rt_txn(op="snapshot", label="before_join")   # file level: saves <out_dir>/snapshots/before_join.blend
blender_rt_txn(op="mark", label="iter7", objects="Cube,Wheel_L")   # object level: records transform/material/visibility
… changes …
blender_rt_txn(op="revert", label="iter7")          # in-place rollback (objects whose topology changed are skipped and reported)
blender_rt_txn(op="list")                              # snapshots + marks inventory
```

Boundary: the object level **does not include topology/UV/vertex-level changes** (you cannot go back after a Boolean/merge/face deletion) → use the file-level `snapshot/restore` (it loses the current unsaved state, but `restore` backs it up for you by default).

The filepath convention of `restore(label, into="auto", backup=True)`: with the default `into="auto"`, after loading the snapshot it **puts the session back on the file the snapshot came from** (saving lands back in your own project, no longer written into the snapshot directory); `into="snapshot"` is non-destructive (just take a look, do not write the original file); `into="original"` requires that writing back is possible, otherwise `ok:false`. `backup=True` first leaves a `_pre_restore_*` snapshot, and when the session is dirty and the original file is to be overwritten it additionally leaves an on-disk copy `_pre_restore_file_*`.

Also: exceptions return partial stdout/traceback; inside scripts you can use `K.win_path / K.wsl_path / K.blend_path / K.out_dir`; `rt_do(file=...)` can run a workspace script directly; for **QC** use `blender_rt_plan(op="qc_compare")` (IoU/Dice/missing area/excess area/boundary distance + comparison image).

### ⑭ `blender_viewport` -- channel operations

| op | Effect |
|---|---|
| `status` | Backend health / viewport area / counts |
| `doctor` | Really runs one bpy round trip + three-level verdict + effective config |
| `who` | Lease holder + channel metrics (look at it first with multiple sessions) |
| `lease` `release` | Take / grab / release the write-permission lease (`force=true` to preempt, `ttl_ms` validity period) |
| `start` `stop` `restart` | Manage the backend process (`stop` pauses the 15 s watchdog) |

### ⑮ `blender_rt_preset` -- recipe library

Turns a "parameter combination" into a saveable, applicable, distributable asset (domain-agnostic: material / object / scene / custom JSON).

```text
blender_rt_preset(op="save", name="hard-surface metal", kind="material", tags="metal,hard", \
                  data='{"inputs.Metallic": 1.0, "inputs.Roughness": 0.25}')
blender_rt_preset(op="list")                                  # inventory (filterable by kind/tag)
blender_rt_preset(op="apply", name="hard-surface metal", targets="MAT:steel_shell,MAT:bolt")   # actually writes
blender_rt_preset(op="apply", name="hard-surface metal")              # no targets → preview only (dry_run)
blender_rt_preset(op="export")                                # a single bundle, easy to share with other machines
blender_rt_preset(op="import", path="D:/DSH/blender/tmp/presets/presets_bundle_x.json")
```

Key points: data uses **dot paths**; `targets` supports `MAT:name` / `OBJ:name` / `SCENE`; the receipt gives `applied / skipped / errors` (a nonexistent path is reported as an error, never silently ignored).
Measured: store `{"render.resolution_x":640}` → `apply targets="SCENE"` → scene resolution 720 → **640** really takes effect; a dry_run preview does not write to disk.

> Tool division quick note: `blender_rt_headless`'s file is a .blend project; to execute a .py script use `blender_rt_do(file="//x.py")` (internally `K.run`, which collects stdout) or `headless(script=...)`.
> `qc_compare` criteria: `iou` is **fixed alignment** (the honest value), and search alignment is given separately as `iou_search`; **scale drift >5%** and **search absorption >0.05** both raise a warning; `ref_box` may be omitted (defaults to the whole image); the auto mask falls back to the threshold convention with a written reason when the foreground share is >80%/<2%.

---

## 3. Seven hands-on recipes

### Recipe 1: change one step, take one look (the most common)

```text
blender_rt_do(code="ob = bpy.data.objects['Truck']; ob.location.z += 0.05", see=True)
```
Suggested rhythm: do 10-30 steps in a row before stopping to look at the whole; grabbing a frame at every step saturates the main thread (55-100 ms per frame).

### Recipe 2: multi-angle acceptance (without disturbing the user)

```text
blender_rt_see(from="9,-9,6", look_at="0,0,1", view_size="900x506")     # front right above
blender_rt_see(from="-9,-9,5", look_at="0,0,1")                          # front left above
blender_rt_see(from="0,0,14", look_at="0,0,1", ortho=True, ortho_scale=14)  # orthographic top view
```
The same parameter set **repeatedly renders images with the same md5** (hash `3a7bee2a` measured on the author's machine) → usable as an "acceptance fingerprint": when the model says it is done, re-render the same angle; if the hash is unchanged, it really is unchanged.

### Recipe 3: inner-loop fitting (let the search run on the Blender side)

Goal: tune 6 size parameters to a target bounding box (illustrative).

```text
blender_rt_loop(op="start", spec={
  "setup": "TARGET=(3.2,1.4,1.1)\nK.target=TARGET",
  "step": "import random\nns['params']={'w':round(random.uniform(2.6,3.8),3),'h':round(random.uniform(0.9,1.9),3)}",
  "measure": "bpy.data.objects['Cube'].dimensions=ns['params']['w'],ns['params']['h'],1.0"
             "\nerr=[abs(bpy.data.objects['Cube'].dimensions.x-K.target[0]),abs(bpy.data.objects['Cube'].dimensions.y-K.target[1])]"
             "\nns['metrics']={'ex':err[0],'ey':err[1]}"
             "\nns['violations']={'ratio':max(0.0, 1.6-bpy.data.objects['Cube'].dimensions.x/max(1e-6,bpy.data.objects['Cube'].dimensions.y))}"
             "\nns['score']=penalize({'ex':err[0],'ey':err[1]},{'ratio':ns['violations']['ratio']},lam=5.0)",
  "iterations": 5000, "budget_ms": 30000, "measure_every": 1, "top_k": 20, "interval": 0
})
blender_rt_loop(op="status")   # look at best / tps / history
blender_rt_loop(op="board")    # candidate table
blender_rt_loop(op="export", path="/tmp/fit_best.py")   # bake into a reusable script
```

**The easier road (declarative)**: the same thing can also be handed to `blender_rt_plan(op="shape_search", …)` in one call -- `objective` (`silhouette_iou` / `profile_err` / `aabb_err`) + `params` intervals + `apply` (code that lands `ns["params"]` on the scene each round; remember `view_layer.update()` after changes). It picks grid / random automatically, manages start → polling → board → export, and leaves the scene on best (the inner loop itself stops at "the last iteration"); `dry_run=true` first validates only and returns the spec (does not start the inner loop and does not need Blender connected). For `penalize` / `anneal` / multiple objectives / `group_key` batching, come back to the hand-written spec above. **It can also run headless**: `blender_rt_plan(..., session="auto")` uses the worker's synchronous inner loop (`dsh_loop_sync`, no dependency on GUI timers); when hand-writing an `rt_loop` spec, pass `target="session"` instead.

**After convergence you must re-check through another pathway** (for example re-measure the bounding box/volume/render with `blender_rt_do`), because the inner loop only optimizes the `score` you wrote.

### Recipe 4: render performance pipeline

```text
blender_rt_perf(op="status")     # record the baseline: engine / device / samples / persistent / object count
blender_rt_perf(op="analyze")    # get "CPU sync per round X s, GPU per sample Y s"
blender_rt_perf(op="apply")      # apply the preset
blender_rt_perf(op="status")     # compare
# revert if unsatisfied; if there are too many objects go to recipe 5
```

### Recipe 5: object slimming

```text
blender_rt_opt(op="analyze")                                   # see candidate groups and expected savings
blender_rt_opt(op="join", args={dry_run=True})                 # dry-run report
blender_rt_opt(op="join", args={dry_run=False, save_before="/tmp/pre_join.blend"})
blender_rt_do(code="print('faces', sum(len(o.data.polygons) for o in bpy.data.objects if o.type=='MESH'))")  # re-check zero geometry loss
```

### Recipe 6: headless final render / batch rendering

```text
blender_rt_headless(file="D:\\work\\scene.blend", outdir="D:\\work\\out", timeout_ms=900000,
  preload="view,perf", factory_startup=False,      # use the user startup file (with Cycles presets)
  script="...multi-camera loop K.dsh_view_api['capture'](...)  / or bpy.ops.render.render(write_still=True)...")
```

Headless also supports custom views (Blender 5.x's `gpu.init()`): after `preload="view"`, use `K.dsh_view_api["capture"](json.dumps({...}))` directly.

### Recipe 7: multi-view QC rendering (N images in one go + timing + budget)

```text
blender_rt_plan(op="qc_render_views", args={views:["iso","front","right","top"],
  res:[768,768], samples:64, budget_s:180, outdir:"D:/work/qc", tag:"hero"})
```

After rendering: the `hash` (md5) of each line in `render_views.jsonl` is the evidence; to compare against a reference image give `ref_path` (+ `ref_box`,
which can be a dict per view `{"front":[..],"iso":[..]}`), and the harness calls `qc_compare` per image and writes IoU/profile difference into the same line.
For long work (>5 min) add `asJob:true` and retrieve with `blender_rt_job(op="collect", id="job-…")`.

### Recipe 8: headless interaction loop (no GUI needed)

```text
blender_rt_worker(op="start", name="s1", preload="audit,assembly,imgtools")
blender_rt_do(session="s1", code="bpy.data.objects['Cube'].location.x += 0.1", see=True)   # 50-150 ms/step
blender_rt_see(session="s1", from="9,-9,6", look_at="0,0,1", view_size="900x506")
blender_rt_plan(op="asm_scan", session="auto", args={"objects": ["Cube", "Cube.001"]})
blender_rt_watch(session="s1", code="…", seconds=2)          # per-frame hash, at most 6 frames
```

The same `session` name reuses the same Blender process (`K` is persistent); reclaimed automatically after 15 min idle (`DSH_WORKER_TTL_MS`); when `session` is not passed it also downgrades automatically if the GUI is unreachable.

### Recipe 9: assembly delivery loop (manifest → scan → repair → gate → export)

```text
blender_rt_plan(op="asm_manifest", args={action:"validate", path:"D:/proj/assembly.json"})
blender_rt_plan(op="asm_scan",     args={manifest:"D:/proj/assembly.json"})         # all-pairs clash/floater classification
blender_rt_plan(op="asm_repair",   args={manifest:"D:/proj/assembly.json", dry_run:true, policy:"safe"})
blender_rt_plan(op="asm_gate",     args={manifest:"D:/proj/assembly.json"})         # three-state verdict; export_allowed only on pass
blender_rt_plan(op="asm_export",   args={manifest:"D:/proj/assembly.json", out_dir:"D:/Blender/proj",
                                         name:"proj", merge:true, dry_run:false, formats:["glb","fbx","obj"]})
```

`merge=true` runs `asm_merge` first (internal gate + snapshot, **no export without passing the gate**); artifacts include `<name>_manifest.json` (bbox/units/per-file md5/gate) and an append-only `merge_ledger.jsonl` (ts/action/manifest_md5/files/md5/gate_verdict).

---

## 3.5 P0-P2 new pipelines quick reference (v2.6.0)

> In one sentence: **is the assembly actually assembled**, **how much was changed**, **will a verdict expire**, **can a reference image be measured**, **can blockout/delivery run with one click** -- all of these now have criteria and entry points.

### 3.5.0 Boundaries and acceptance (read first)

- **The single acceptance criterion**: `/doctor` (or `blender_viewport(op="doctor")`) returns `kind=ok`; the other self-checks only localize a single function.
- **Explicitly not covered / dependencies not installed by default** (do not use them as if supported):
  - **Face/landmark detection**: no face detection is bundled -- `face_*` requires you to supply landmarks (annotate them yourself or produce them with external MediaPipe/EMOCA); this machine has no cv2/MediaPipe;
  - **OCR**: not supported;
  - **DXF**: not supported (neither import nor export);
  - **External second pathway**: `ext.gltf_validate` / `ext.ext_mesh_check` depend on glTF-Validator / Open3D installed locally under `runtime/ext/` (not installed in the default deployment; the hint gives the install command; when not installed it reports an explicit `ok:false`); manifold3d is not installed either.
- All "new capabilities" follow the three-state discipline: `degraded` (insufficient evidence/downgraded) **does not equal passing**; `unresolved` does not guess.

### 3.5.1 Interactive headless (P0 fallback; GUI first by default)

```text
blender_rt_worker(op="start", name="s1", preload="audit,assembly,imgtools", warmup=True)
blender_rt_do(session="s1", code="…", see=True)          # exec + Workbench offscreen frame, 50-150 ms/step
blender_rt_see(session="s1", from="7,-7,5", look_at="0,0,1")
blender_rt_plan(op="asm_scan", session="auto", args={…}) # starts a worker + preload automatically, returns synchronously
blender_rt_watch(session="s1", code="…", seconds=2)      # per-frame hash, ≤6 frames
blender_rt_loop(op="start", target="session", spec={…})  # synchronous inner loop, no dependency on GUI timers
```

- The same `session` name = the same `blender -b` process + persistent `K`; **the worker is reclaimed automatically after 15 min idle** (`DSH_WORKER_TTL_MS`, 0=off), and `status` carries `idleMs`;
- Measured (author's machine): worker `start` 2.24 s (including first-frame initialization ≈1.1 s) → `exec` 0-2 ms, `see` 53-85 ms (320×180); `rt_plan session="auto"` cold start ~2 s the first time, then reused synchronously; headless watch of a 3-frame animation distinct=3/58 ms;
- The GUI channel is required **only** for "looking at the user's viewport / whole-window screenshots (`full`) / `rt_cmd`, `gui_*` that need GUI context, and the user's live scenes".

### 3.5.2 Reference-image measuring tools (img_digest / img_probe / img_measure / img_calib)

Protocol: **looking at an image must produce numbers** (written into spec.py), otherwise it counts as not looking; at most 2 images per call and each with an explicit question.

```text
blender_rt_plan(op="img_digest", args={path:"D:/ref/front.png", known_len:{mm:2000, px:320}})
  # → contour/bbox/symmetry/lines/features/scale bar/readability + native crop atlas + annotated overview + verdict (ready_for_spec / needs_scale / needs_views / unreadable / degraded)
blender_rt_plan(op="img_probe",  args={image_id:"…", op:"scan_y", y_px:420})        # sub-pixel edge/width/circular hole/distance/gray profile
blender_rt_plan(op="img_measure",args={image_id:"…", px_per_mm:0.16, targets:[{key:"width", feature:"bbox_w", expect_mm:2000, tol_pct:2}]})
blender_rt_plan(op="img_calib",  args={views:[…], shared:[{key:"width", views:{"front":640,"side":638}}]})   # per-view calibration + cross-view consistency
```

- Without `known_len`, all mm fields are `null` (**never invented**); px is the loaded scale, and the receipt gives the `native_px / loaded_px` conversion;
- `img_digest` gives "confirmable numeric table + native crop atlas + readability + next step" in one call; `img_probe/img_measure` measure on demand; `img_calib` outputs per-view `px_per_mm` and cross-view deviation;
- To judge "does it look alike", use `img_diff`'s IoU (L2 evidence) instead of eyeballing.

### 3.5.3 Assembly (asm_scan / manifest / merge / repair / export / gate)

```text
blender_rt_plan(op="asm_manifest", args={action:"init", path:"D:/proj/assembly.json", assembly:"Aurora"})
blender_rt_plan(op="asm_manifest", args={action:"add_part", path:…, part:{id:"P1", file:"…/part_a.blend", objects:["GEO_A"]}})
blender_rt_plan(op="asm_manifest", args={action:"seal", path:…})
blender_rt_plan(op="asm_scan",     args={manifest:"D:/proj/assembly.json"})     # clash/contained/float/unresolved all-pairs
blender_rt_plan(op="asm_merge",    args={manifest:…, dry_run:true})              # look at the append plan first
blender_rt_plan(op="asm_merge",    args={manifest:…, out_blend:"D:/proj/merged.blend", dry_run:false})
blender_rt_plan(op="asm_repair",   args={manifest:…, dry_run:true, policy:"safe"})   # plan; only dry_run=false acts (snapshot first, re-scan)
blender_rt_plan(op="asm_gate",     args={manifest:…})                            # export_allowed only with verdict=pass
blender_rt_plan(op="asm_export",   args={manifest:…, out_dir:"D:/Blender/proj", name:"proj", merge:true})
```

- **asm_repair policy**: the default tier (safe behavior) automatically does only **translate / snap**; an explicit `policy="safe"` hard-forbids boolean/scale; `policy="manual"` plans without executing (even with `dry_run=false` it returns only a read-only plan); `policy="aggressive"` keeps the boolean path (still requires `allow_boolean=true`; booleans change topology and require a file-level snapshot). `plan[].risk` / `blocked[].blocked_reason` are readable item by item. ⚠ Backward compatibility: without a policy, `allow_boolean=true` is still treated as explicit authorization.
- **asm_export**: `merge=true` runs `asm_merge` first (gate+snapshot, no export without passing); GLB/FBX/OBJ official exporters (automatically enables `io_scene_gltf2`/`io_scene_fbx`); `dry_run=true` returns only the plan without writing; `manifest_md5` + per-file md5 + append-only ledger; **if all formats fail, `ok:false`**.
- **Criteria**: `hidden_ok` = hidden overlap inside the declaration (not reported); `clash` = real interpenetration; `contained` = fully contained (the patch for the old all-pairs miss); `unresolved` = insufficient evidence; `asm_gate` judges floaters using the manifest connection graph.

### 3.5.4 Blockout + Seedance reference pack (blockout_*)

```text
blender_rt_plan(op="blockout_base", args={name:"robot", parts:[{id:"torso", prim:"box", size_mm:[300,180,420], at_mm:[0,0,900]}],
                                          render:{views:"auto3", res:[512,512]}, export:{glb:"D:/out/robot.glb"}})
blender_rt_plan(op="blockout_batch", args={models:[{…}, {…}], outdir:"D:/out/batch"})       # batch of N items
blender_rt_plan(op="blockout_export", args={name:"robot", export:{glb:"…", obj:"…"}})
blender_rt_plan(op="blockout_refsheet", args={name:"robot", out_dir:"D:/out/refsheet", turntable:true})
  # → 4-view PNGs (orthographic front/side/top + perspective iso) + 2×2 montage + refsheet.json (+ optional turntable MP4)
blender_rt_plan(op="blockout_turntable", args={name:"robot", out_dir:"D:/out/tt", frames:96, fps:24, fmt:"mp4"})
```

Defaults to Workbench, a single white material, no auditing; the hot-session per-item target is ≤2.5 s; if the GLB exporter is not enabled it calls `addon_enable` automatically; the turntable uses Blender's built-in FFMPEG to produce MP4 (on failure it falls back to a PNG sequence with `degraded` + warnings in the receipt). Blockout's positioning is "providing the base shape for video models/downstream"; details still go through the existing pathways such as shape/vehicle/human.

### 3.5.5 Same-camera-position QC (visualreport_report)

```text
blender_rt_plan(op="visualreport_report", args={ref:"D:/ref/front.png", render:"D:/out/front.png",
                                               px_per_mm:2.0, out_dir:"D:/out/qc"})
```

One-page verdict (pass/degraded/fail): IoU, missing/excess area, top_defects (bbox/area/center_mm), per-defect crop paths and fixes. Three-level degradation qc→imgtools→numpy (a missing module is marked degraded, never a fake pass); **only the same camera position/resolution is comparable**. Render with `qc_render_views`, report with this op.

### 3.5.6 Headless contour fitting (shapesolve_solve)

```text
blender_rt_plan(op="shapesolve_solve", args={
  setup:"def apply(p):\n    bpy.data.objects['Base'].dimensions = (p['w'], p['d'], p['h'])",
  params:[{name:"w", min:1.0, max:3.0}, {name:"d", min:0.8, max:2.0}, {name:"h", min:0.5, max:1.6}],
  views:[{ref:"D:/ref/front.png", from:[0,-10,1], look_at:[0,0,0.8], ortho_scale:4.0}],
  objective:"silhouette_iou", iterations:200, resolution:256})
```

Headless multi-view orthographic analytic projection + numpy rasterization, **no rendering, no dependency on GUI timers**; the receipt contains best / per-view IoU / sensitivity (`unidentifiable` = that parameter carries no information at the current view); `ortho_scale` is the world size of the frame width; the reference image must be homologous with the camera parameters.

### 3.5.6b Parametric surfaces (surface_*)

```text
blender_rt_plan(op="surface_loft", args={
  sections:[{z_mm:0, points_mm:[[-60,-30],[60,-30],[60,30],[-60,30]]},
            {z_mm:80, points_mm:[[-52,-26],[52,-26],[52,26],[-52,26]]}],
  degree:2, continuity:"G1", closed:true, tessellation:{u:24,v:8}, name:"Cowl"})
blender_rt_plan(op="surface_tessellate", args={spec_or_object:<the spec from the previous step>})   # get the object name
blender_rt_plan(op="surface_validate", args={spec_or_object:"SURF_loft_xxx"})   # read the three-state verdict
blender_rt_plan(op="surface_export", args={spec_or_object:"SURF_loft_xxx", out_dir:"D:/out", name:"Cowl"})
```

Pure bpy+numpy: loft (cross-section B-spline interpolation) / sweep (parallel transport frame + twist + per-point scale) / patch (tensor-product B-spline patch) → tessellate → validate (G0/G1/G2 seams, curvature, BVH self-intersection, ray thickness, mesh quality; `fail` never silently becomes pass, `degraded ≠ passing`) → export (GLB). Units are unified in mm; the same spec (including tessellation) ⇒ the same `spec_hash` + the same vertices. **M3 fit and M5 blend/offset are not implemented** (explicit `ok:false`, requires OCCT). For details see [surface-algorithms.md](../skills/blender-modeling/references/surface-algorithms.md).

### 3.5.7 Defect evaluation (eval_run)

```text
blender_rt_plan(op="eval_run", args={suite:"all", out_json:"D:/out/eval.json"})
# suite: core (gate baseline calib) / assembly (D1 shallow interpenetration, D3 full containment, D4 allow hidden overlap, D5 face contact, D7 floater, D8 inverted normals)
#        / reference (rectangular/annular/oblique reference images → img_digest/probe/measure)
```

`verdict` three-state + per-suite cases + `capture_rate / missed / false_positive / baseline_pass`; **a missing module → skipped/degraded, never pretending to pass**; it touches only `__eval_`-prefixed objects, cleans up at the end, and resets scene units. capture_rate only represents the synthetic defect set and does not equal the pass rate of a real project (real projects go through `gate_run` / `asm_gate`).

### 3.5.8 Forced gates (gate_preflight / checkpoint / deliver)

```text
blender_rt_plan(op="gate_preflight")                                  # pre-work check-up card: scene/units/available modules/gates worth running first (read-only)
blender_rt_plan(op="gate_checkpoint", args={label:"before_boolean"})  # file-level rollback point before topology changes (wraps txn.snapshot)
blender_rt_plan(op="gate_run",        args={preset:"assembly"})       # three-state; ok is true only on pass
blender_rt_plan(op="gate_deliver",    args={dir:"D:/Blender/proj", name:"proj", preset:"assembly"})
  # verdict != pass ⇒ blocked, nothing written; a degraded delivery requires an explicit allow_degraded=true; a forced export requires force=true + reason
blender_rt_plan(op="deliver_export",  args={dir:"…", scope:"…", name:"…", require_gate:true})   # the gate is wired in before export
```

`deliver_export` itself is still callable on its own (backward compatible with old flows); for a process-driven delivery use `gate_deliver` or `require_gate=true`.

### 3.5.9 Existing capabilities that still apply (quick reference)

> Evaluation table: `docs/procedura-fusion-analysis.md`; historical version notes are in `CHANGELOG.md` (history only; this document governs operation).

#### 3.5.9.1 Mesh inspection and the assembly gate (`blender_rt_plan`, op prefix `audit_`)

```python
blender_rt_plan(op="audit_scene")                       # whole scene: which objects are the dirtiest (read-only)
blender_rt_plan(op="audit_connectivity")                # connected components: how many chunks does this pile form? who is not touching whom? (read-only)
blender_rt_plan(op="audit_connectivity", args={"micro_gap_mm": 2.0})   # convention: assemblies with design clearance get it per process
blender_rt_plan(op="audit_gate")                        # factory gate: connectivity + envelope + three-state (unconfirmed → degraded, not a pass)
blender_rt_plan(op="audit_drift", args={"a": "objA", "b": "objB"})     # shape drift (symmetric Chamfer, BVHTree point to surface)
blender_rt_plan(op="audit_measure", args={"scope": "Cockpit", "k": 4}) # measurement pack: bbox + per-axis gap/overlap mm/% + neighbours
blender_rt_plan(op="audit_snap_floaters", args={"scope": "Cockpit"})   # snap floaters to their nearest neighbour (dry_run by default, report only)
blender_rt_plan(op="montage", args={"paths": [], "cols": 4})           # montage (evidence level L2)
```

Criteria (also in `audit_help`):

- **Visible floater** = the component's longest bbox edge ≥ **1%** of the whole model's longest edge (severity looks only at that, not at volume).
- **Contact convention** `micro_gap_mm`: default **0.3 mm** (single solid / 3D printing convention); assemblies with design clearance get it per process (1-2 mm is common).
  The convention and the gap distribution are returned with the result (`gate_caliber` / `gap_histogram` / `floater_gap_range_mm`).
- The criterion is **no longer** "the largest component is the body and everything else is a floater" (two equally large parts would get one picked at random as the floater); instead **every component is asked "do you touch any other component"**.
- bbox gaps are always 0 in multi-object assemblies (pervasive overlap) → the micro decision must go through a **mesh-level re-check** (BVH + surface sampling);
  **by default there is no face-count cap (everything runs; acceptance does not degrade with scale)**; only an explicit `DSH_*` env or `max_tris` parameter enables a cap -- then exceeding it skips the re-check → `attached=null` → **the gate degrades (ok=null)**; unconfirmed is never treated as passed.
- `audit_drift` measures **shape drift**: normalization removes translation and uniform scale, so it does not see displacement → look at `bbox_delta.moved_mm`.
  0.05 ≈ 2.5% of the longest edge; the same mesh reads 0.
- Measured reference (COCKPIT_DELIVERY, 14 objects / 97,438 faces): 0.3 mm convention → 178 floaters (0.33-1.14 mm from their nearest neighbour) + 970 contacts; 2.0 mm → 63 floaters.

#### 3.5.9.2 Contract layer (`blender_rt_plan`)

```python
blender_rt_plan(op="fingerprint", args={"scope": "Cockpit"})     # geometry fingerprint (objects/faces/vertices/bbox + digest)
blender_rt_plan(op="ledger")                                     # evidence ledger: entries whose source changed are marked stale=true automatically
blender_rt_plan(op="mate_check", args={"conn_id": "pin_fit", "fit": "location"})   # fit gate: contact area/one-sided gap/intrusion
blender_rt_plan(op="fit_help", args={"feature": "socket"})       # assembly feature library (9 features + four tiers + ISO 273 + shared-nominal discipline)
blender_rt_plan(op="interference_report", args={"scope": ["IX", "IY"]})  # per-pair depth/volume share/severity + in-plan exemptions
```

- A verdict **expires with the geometry**: `verify` records a bbox snapshot; afterwards, if the centre drifts > 10% of the diagonal or a dimension drifts > 20% → it automatically degrades to `unresolved` (`verdict.demoted` keeps the reason).
- `mate_check`'s `nominal` semantics = **expected one-sided gap in mm** (can be negative); it only inspects and does not write state; to record state call `verify` / `advance`.

#### 3.5.9.3 Edit transactions and delivery (`blender_rt_txn` / `blender_rt_plan`)

```python
blender_rt_txn(op="edit_begin",  args={"label": "tenon_12mm", "targets": ["Backrest"]})
blender_rt_txn(op="edit_check",  args={"kind": "audit", "result": {...}})
blender_rt_txn(op="edit_accept", args={"verified": "audit clean + target in place"})     # empty verified / not re-checked → rejected
blender_rt_txn(op="edit_revert", args={"why": "head is 4mm short, revert and recompute first"})          # no cost budget but capped + debounced
blender_rt_plan(op="deliver_export", args={"dir": "D:/Blender/house", "scope": "House", "name": "house"})
blender_rt_plan(op="deliver_verify", args={"path_or_dir": "D:/Blender/house"})    # changing one byte/adding one face makes it FAIL
```

#### 3.5.9.4 The render harness trio (`blender_rt_plan(op="qc_render_views")`)

```python
blender_rt_plan(op="qc_render_views", args={"mode": "parts_color", "views": ["iso", "front", "top"]})
blender_rt_plan(op="qc_render_catalog")          # 22 views / aliases / ortho semantics (unknown names are returned, no longer silently treated as iso)
blender_rt_plan(op="qc_render_device_info")      # measured current device (read-only, no render)
```

- Every jsonl line has the **measured `device`** (a silent Cycles fallback to CPU is a ≈7× regression with no symptoms; this targets exactly that; if it cannot be obtained it is `null` + an explanation, no guessing).
- `parts_color` rendering **restores everything completely** (including isolated copies of shared meshes); the legend is in `<outdir>/parts_color_meta.txt`.

#### 3.5.9.5 Mechanisms and generators

```python
blender_rt_plan(op="motion_joint",  args={"jid": "hinge", "parent": "Base", "child": "Door"})  # no axis → inferred by measurement
blender_rt_plan(op="motion_measure", args={"jid": "hinge", "phases": 8})   # sweep validation: zero interference and real displacement → supported
blender_rt_plan(op="motion_export_urdf", args={"dir": "D:/Blender/mech", "meters_per_unit": "scene"})
blender_rt_plan(op="motion_help")
```

> ⚠️ `meters_per_unit` defaults to **0.001** (the upstream stage convention); **for metric scenes (Blender's default `scale_length=1.0`) pass `"scene"`**,
> otherwise mass/inertia will be off by several orders of magnitude (the module reports a "units suspect" warning + `units.scene_units_suspect`, but will not change it for you).
> The sweep is a **kinematics + BVH** validation (zero interference + real displacement), not a physics simulation; when there is no bystander object it judges `unresolved` rather than passing.
> The three-state discipline applies equally: a thin flat plate about a hinge axis has no rotational symmetry → `unresolved` (the 0.55 threshold is not relaxed); for a square plate the two pieces of evidence contradict → report both axes, do not choose for the user.

```python
blender_rt_plan(op="generator_save", args={"name": "daybed", "code": "<python>", "params": {}})
blender_rt_plan(op="generator_run",  args={"name": "daybed", "args": {"h": 0.4},
                                          "expect": {"objects": 12, "names": ["leg_01"]}})   # reproduce in a fresh process + compare
blender_rt_plan(op="generator_diff", args={"name": "daybed"})   # did the source change (if it did → the last receipt expired)
```

#### 3.5.9.6 Trajectory (side channel, no need to call)

Every top-level call writes one line to `<work dir>/trajectory/blender_rt-<date>.jsonl`: `route / op / ms / ok / argument digest + hash`.
`DSH_TRAJ=0` disables it, `DSH_TRAJ_FULL=1` records more arguments; the path is also in `blender_viewport(op="status")` → `trajectory.dir`.

---

## 4. Safety and concurrency (do read once)

1. **Leave a rollback point before writing**: `bpy.ops.wm.save_as_mainfile(filepath="...")` or `opt join`'s `save_before`.
2. **The inner loop must have a safety valve**: `iterations` / `budget_ms`; if it runs away use `blender_rt_loop(op="stop")` for an emergency stop (it exits at the next tick).
3. **Do not call `render.render()` repeatedly** (in a GUI session it easily hits a CUDA context and occupies the main thread throughout) → use `blender_rt_headless` instead.
4. **GPU / driver-related operations must be on the main thread**: calling `cycles.preferences.get_devices()` in the addon socket thread crashes Blender outright (it crashed once on the author's machine); use `bpy.app.timers` if you need to drain the thread.
5. **Lease semantics**: write routes = `/act /cmd /loop /perf(write ops) /opt(join) /headless`; read-only ops are exempt.
   - Single agent: the plugin carries `holder` automatically, invisible;
   - Multiple agents: on `409 leased {holder, expiresInMs}` → either wait, or take over with `blender_viewport {op:"lease", force:true}`;
   - `/who` shows the current holder and the remaining time.
6. **`execute_code` is a universal channel** (intentionally kept): it amounts to executing arbitrary Python inside the Blender process.
   - The channel listens only on `127.0.0.1` (do not change it to `0.0.0.0` and expose it to the public internet);
   - Do not write API keys / private data into strings that will be logged;
   - Use it only with trusted Blender projects and a trusted model side.

---

## 5. Troubleshooting quick reference

### 5.1 Three-level diagnosis (`/doctor`'s `kind`)

| kind | Meaning | Disposition |
|---|---|---|
| `ok` | TCP + ping + bpy round trip all work | Nothing to do |
| `blender-unreachable` | Nothing is listening on `127.0.0.1:9876` | **One click: `blender_viewport op=launch` (§8)**; manually: start Blender → N panel → "DSH Blender Bridge" → Connect |
| A write returns 409 `leased` but the other session is actually closed | `blender_viewport op=who` → look at `holderAlive` | **Dead sessions' leases are reclaimed automatically** (`holderAlive:false`); `null` = liveness undecidable → use `op=lease force=true` |
| `main-thread-busy` | The addon is alive (ping works) but bpy commands time out | Blender is rendering / in a modal operation / running heavy work → wait until it frees up; for long renders switch to `blender_rt_headless` |
| `addon-thread-stuck` | The port is reachable but even ping does not come back | The previous long command is still in the addon thread; do not fire more, wait for it to finish; restart Blender if needed |
| `addon-unresponsive` | Port `9876` is reachable (`addon.tcp:true`) but the addon did not return `execute_code`'s bpy round trip within budget (doctor 4s, /status 5s) (timeout); `addon.ping` says whether ping works | First confirm Blender is running and "DSH Blender Bridge" is Connected; then wait for the long command/render to finish, restarting Blender if needed. **`op=start` only manages the 9877 backend process and does not fix this channel** |
| `addon-error` | The addon explicitly returned an error (not a timeout, e.g. "AI operations paused" / a script error / `BUSY_RENDER`) | Fix per the error; if rendering, wait for it to finish or use `render_wait`; this is not a busy main thread, so do not retry repeatedly |

`/status` has its own set of `code`s at the tool layer: `addon_unresponsive` (addon timeout), `addon_error` (addon returned an error), `busy_render` (Blender is rendering, wait for `render_wait`), `backend_timeout` (the host timed out waiting for /status), `backend_unreachable` (connection-level failure, including ETIMEDOUT / ECONNREFUSED).

### 5.2 High-frequency pitfalls (ordered by cost)

| Pitfall | Symptom | What to do |
|---|---|---|
| Frame / script paths not shared between the two ends | Rendering reports "file does not exist" / the tool cannot read it | Check with `doctor`'s `config.workDir`; change to a directory both ends can read and write |
| Writing files to UNC (`\\\\wsl.localhost\\...`) | "Returns success but there is no file" | Always use Windows drive paths (`D:\...`) for disk writes |
| `execute_code` is stateless | The previous variables cannot be read | Hang cross-call state off the persistent kernel `K` |
| The addon panel was not Connected after a restart | Every command times out | Connect again; save the switches you need into the startup file |
| Parameter names written per MCP docs | `unexpected keyword argument` | Follow the addon's real signature (`get_object_info(name)`) |
| The backend will not start / the port is taken | The tool reports "backend unavailable" | `blender_viewport op=restart`; or change `httpPort` |
| blender.exe cannot be found | `blender_rt_headless` / `blender_rt_worker(op="start")` / `blender_rt_job(op="start")` report `blender_exe_missing` (with configuration guidance, returned in <1s) | For the three configuration methods see [configuration-reference.md](configuration-reference.md) §4; Windows Steam installs are auto-detected (source `auto:steam`) |
| `rt_plan ... session="auto"` headless execution fails | Reports "headless execution failed" | That op has no headless mapping (check with `op="catalog"` first) or the worker will not start; first verify manually with `blender_rt_worker(op="start", name="…", preload="…")`, or run `blender_viewport(op="doctor")` |
| GLB / FBX export fails | `asm_export` / `deliver_export` reports `ok:false` for one format | Look at `exports[].error`; GLB needs `io_scene_gltf2`, FBX needs `io_scene_fbx` (the tool enables them automatically); OBJ uses `wm.obj_export` |
| More and more workers / memory grows | `blender_rt_worker op=list` shows several hot sessions | 15 min idle auto-reclaim by default (`DSH_WORKER_TTL_MS`, 0=off); you can also `op=stop` explicitly |
| `asm_export` export rejected / nothing written | `ok:false` + merge/gate receipt | With `merge=true` it must first pass `asm_merge`'s internal gate (no export without passing); look at `merge.gate` and `blocked/error` |

### 5.3 Get the full context with one command

```bash
curl -sS http://127.0.0.1:9877/who | python3 -m json.tool | head -40
# contains: lease (who is writing), metrics (calls/errors/timeouts/inflight/lastCmd), stats, config (effective config)
```

---

## 6. Acceptance self-check (re-runnable)

> **The single acceptance criterion is still §1.4's `doctor kind=ok`**; the self-checks below serve to localize a specific function and do not replace it.
> Each new capability family has its own real-machine self-check (see [../tests/README.md](../tests/README.md)): `assembly_selftest / assembly_repair_selftest / assembly_export_selftest / img_digest_selftest / blockout_selftest / evalharness_selftest / visualreport_selftest / shapesolve_selftest`.

Details and expected values are in [../tests/README.md](../tests/README.md):

1. **view.py self-check** (matrix comparison + offscreen + PNG bytes): `blender_rt_headless {preload:"view", script:"print('HEADLESS ' + K.dsh_view_api['selftest']())"}` → `ok:true`, the three deltas ≈1e-7, `first_px=[25,153,51,255]`.
2. **Matrices only**: `K.dsh_view_api["matrices"]('{"from":[7,-7,5],"look_at":[0,0,1],"width":640,"height":360}')` → projection matrix first row `2.777778`, second row `4.938272`.
3. **PNG byte read-back**: `python3 tests/helpers/png_decode.py <png>` → `px [25, 153, 51, 255]` (proves no double gamma and no vertical flip).
4. **Lease in 7 steps**: see tests/README.md §4 (take → someone else gets 409 → no preemption → force preemption → who → read-only exemption → release).
5. **Channel triple**: `/health` + `/doctor` (`kind=ok`) + `/who`.

All passing = your environment matches the behavioral baseline of the author's machine.

> End-to-end example (hypothesis-driven modeling: insufficient external evidence → probe discrimination): [docs/examples/chair-backrest/results.md](examples/chair-backrest/results.md).

## Appendix: render engines (EEVEE + ray tracing by default)

| Engine | When to use | How to specify | Key points |
|---|---|---|---|
| EEVEE + ray tracing (default) | Iteration / QC / final images that are good enough | Pass no parameter, or engine="eevee" | Pure GPU (graphics backend, this machine OPENGL + RTX 4060); does not depend on device preferences → headless never silently falls back to CPU; the first frame involves shader compilation (cold ~16 s), so for iteration use a `blender_rt_worker` hot session (afterwards about 1.35 s per frame @360 objects) |
| Cycles (optional) | When real GI / caustics / maximum fidelity is needed | engine="cycles" | Automatically configures OptiX + device + cycles.device=GPU; has persistent_data / OptiX denoise / auto_tile presets (blender_rt_perf) |
| Keep current state | You manage the engine yourself | engine="keep" (equivalent to the old gpu:"false") | Changes nothing |

QC receipts carry engine_at_qc -- criteria are only comparable within the same engine.

> EEVEE-specific hard limits, material pipeline division of labor and gradient-group pitfalls see [docs/eevee-essentials.md](eevee-essentials.md).

---

## 7. Path choice: GUI first, headless as fallback (current)

> Route decision and evidence (historical archive, superseded by GUI first): [`docs/archive/headless-first-route-decision.md`](archive/headless-first-route-decision.md).
> In one sentence: **by default start the GUI Blender + Connect first**; go headless only when there is no GUI / for batch processing / long work / when nobody needs to look at the image; headless can also rt_see, so it is never blind.

### 7.1 Thirty-second decision

| Your situation | Default path | What to write first |
|---|---|---|
| Change one step and look / the user's live scene / a human must look at the image to judge | **GUI (default)** | `blender_rt_do(code=…, see=True)` / `rt_see` |
| Look at the user's viewport / whole-window screenshot / `bpy.ops` that depend on the screen or modals | **GUI (default)** | `rt_see` (viewport/`full`) / `rt_cmd` / `gui_*` |
| No GUI, batch processing, long work, data probes | **headless fallback** | `blender_rt_headless(preload="audit", script="…")` |
| No GUI but still interactive image inspection | **worker + session (fallback)** | `blender_rt_worker(op="start", name="s1", preload="…")` → `rt_do(session="s1", see=True)` |
| plan verdict/acceptance/export (no GUI) | **plan + `session="auto"` (fallback)** | `blender_rt_plan(op="asm_scan", session="auto", args={…})` |
| Multi-view QC / final render (minute-scale) | **headless + `shots` + `as_job` (fallback)** | `blender_rt_headless(file=…, shots=[…], as_job=True)` |
| Reference-image comparison / delivery export / generator reproduction | **headless + `preload` (fallback)** | see §7.3 skeleton C |

**Start the GUI first by default.** Go headless only when it is explicitly "no GUI / batch processing / long work / nobody needs to look at the image"; headless is not the default route, but it can also rt_see and is never blind. When you need a live scene/viewport/screen context, you must go through the GUI.

### 7.2 Headless fallback channel parameter and receipt quick reference (current)

#### `blender_rt_headless` key parameters

| Parameter | Type | Description |
|---|---|---|
| `shots` | JSON array | **Multi-view in one go**: uses the built-in harness (`qc_render_views`) -- saving 50-60 lines of camera / three-point light / AgX boilerplate per modeler |
| `attach_images` | bool / `"sheet"` | `true` = attach ≤3 images; `"sheet"` = attach only the montage |
| `as_job` | bool | `true` = **background immediately**, returning `{kind:"promoted", jobId}` on the spot (or just the `jobId`), without waiting |
| `wait_s` | number | **How many seconds at most to wait** after backgrounding; if not done by then → `{kind:"promoted", jobId}` |
| `script_file` | string | Run a .py directly (injects `__file__` + sys.path automatically; long scripts need not be stuffed into arguments) |
| `preload` | string | Preload modules (comma-separated) → `K.dsh_*_api`, e.g. `"audit,qc,qc_render"` / `"assembly,audit,contract,clearance,gate,mesh_fix,geo,txn"` |
| `engine` | string | `eevee` (default) / `cycles` / `keep` / `none` (pure python tasks save 1-1.5 s) |
| `outdir` / `out_json` | string | **Accepts WSL paths** (§7.4); the receipt gives the real write path |

Element fields of `shots` (same shape as the `views` elements of `qc_render_views`):

| Field | Required | Description |
|---|---|---|
| `name` | ✔ | View name (goes into the filename and the receipt) |
| `from` | ✔ | Camera position `[x,y,z]` (world coordinates) |
| `look_at` | ✔ | Look-at point `[x,y,z]` |
| `lens` | | Focal length in mm (default 50) |
| `res` | | `[w,h]`; giving **a number** = square (`res: 1024` ≡ `[1024,1024]`) |
| `samples` | | Sample count |
| `ortho` / `ortho_scale` | | Orthographic projection / orthographic scale |
| `margin` | | Auto-framing margin (same as `qc_render_views`, default 1.12) |

**Receipt**: `res.shots = [{name, path, ms, bytes, md5, coverage_estimate, warning?}]`;
**subject occupying < 5% of the frame → `warning.code = "subject_too_small"`** (framing self-diagnosis: accidents like an 18.1 m part leaving a 1.92 m engine ring only ~140 px now warn at render time).

```python
blender_rt_headless(
  file="/mnt/d/work/aurora/Aurora.blend",
  outdir="/mnt/d/work/out/shots",          # a WSL path is fine (§7.4)
  as_job=True,                             # 3 views at 1024×576 will certainly exceed the wait window → background directly
  shots=[
    {"name": "iso",   "from": [9, -9, 6],  "look_at": [0, 0, 1], "lens": 35, "res": [1024, 576], "samples": 64},
    {"name": "front", "from": [0, -14, 2], "look_at": [0, 0, 1], "lens": 50, "res": [1024, 576], "samples": 64},
    {"name": "top",   "from": [0, 0, 16],  "look_at": [0, 0, 1], "ortho": True, "ortho_scale": 16, "res": 1024},
  ])
```

#### Wait window / job layer (results are never lost)

| Item | Value |
|---|---|
| Client wait window | Default **100 s**, adjustable with `DSH_HEADLESS_WAIT_MS` ([configuration-reference.md](configuration-reference.md) §11) |
| Window expires and it is not done | Returns `{kind:"promoted", jobId:"run-…"}` (**not a failure**: the child process keeps running, the result is collectable) |
| How to collect the result | `blender_rt_job(op="wait")` blocks, / `op="collect"` collects |
| id space | **`run-…` and `job-…` share the same id space**: `status / collect / kill / wait` all accept both prefixes |
| Automatic job conversion | `DSH_HEADLESS_AUTO_JOB_MS` (default 0=off): when the estimated budget is ≥ it, do not wait for the window, background directly |

```python
# expected > 100 s: do not gamble, use as_job directly
r = blender_rt_headless(script_file="/mnt/d/work/aurora/tools/preview.py",
                        args="--part hull_aft", timeout_ms=900000, as_job=True)
# r's envelope has kind="promoted", jobId="run-…" (or status="finished" if already done)
blender_rt_job(op="collect", id=r.jobId)
```

> The inner `timeout_ms` (default 180 s, cap 30 min) and the outer `run_code` deadline are still **two separate budgets**:
> now an expiry no longer loses the result, but it is still recommended that the **outer deadline > the inner `timeout_ms`**, saving one `collect` round trip.

#### `blender_rt_job` (job layer)

| Item | Behavior |
|---|---|
| `op="start"` parameters | **Same shape** as headless: `script_file` / `args` / `env` / `factory_startup` / `bootstrap` / `workdir` / `include_noise` / `engine` / `preload` |
| `op="wait"` | Blocks until done or timeout, returning a structured receipt (no need to loop `op=status` and trip the repeated-call detection) |
| `op="status"` | `stage` / `stageAt` / `lastOutputAt` / `idleMs` / `lines` / `pidAlive`; a stale running job after a backend restart is converged to `stale` with an explanation |
| `op="kill"` | Idempotent for unknown ids: returns "already finished / nonexistent" and the caller's flow is not interrupted |
| `op="collect"` / `op="list"` | Collect the final result / list all jobs |

```python
blender_rt_job(op="start", script_file="/mnt/d/work/aurora/tools/preview.py",
               args="--part hull_aft", env={"AURORA_STAGE": "qc"},
               outdir="/mnt/d/work/out/hull_aft", timeout_ms=1200000)
blender_rt_job(op="status", id="run-abc123")                  # stage / idleMs / pidAlive / lines
blender_rt_job(op="wait",   id="run-abc123", timeout_ms=600000)   # block until done or timeout
blender_rt_job(op="kill",   id="job-nonexistent")                    # idempotent: returns "already finished / nonexistent"
```

#### Structured receipts: two text blocks

| block | Content |
|---|---|
| The 1st | **Single-line JSON envelope** (directly `JSON.parse`-able): `status` / `kind` / `runId` / `jobId` / `resultJson` / `resultPath` / `resultTruncated` / `stdoutTail` / `stderrTail` / `artifacts` / `inputFile{path,size,mtime,md5}` / `stage` / … |
| The 2nd | Human-readable summary (preamble + log tail + fix suggestions) |

**Stop writing regexes like `result: (\{.*?\})`** (double escaping + truncation will throw). The robust way to get the envelope:

```ts
// in run_code: find the first text block that parses into an object
function envelope(res: any) {
  for (const b of res?.content ?? []) {
    if (b?.type !== "text") continue;
    try { const j = JSON.parse(b.text); if (j && typeof j === "object") return j; } catch {}
  }
  return null;
}
const env = envelope(await tools.blender_rt_headless({ script: "print('HEADLESS {\"a\": 1}')", as_job: true }));
const done = env.kind === "promoted"
  ? envelope(await tools.blender_rt_job({ op: "collect", id: env.jobId }))
  : env;
console.log(done.resultJson.a);                  // 1 -- the parsed HEADLESS JSON, no regex needed
console.log(done.resultTruncated, done.resultPath);   // large-result output path (always present when truncated)
```

#### stage heartbeat: long tasks are observable

```python
# emit stage heartbeats in the script (injected by bootstrap; K.progress is equivalent)
dsh_stage("loading")
dsh_stage("building", part="hull_aft")            # custom keys allowed
for i in range(total):
    ...
    dsh_stage("rendering", done=i + 1, total=total)
```

- Output shape: a single line `DSH_STAGE {"name":"building",...}`; the plugin side parses the **last one** in `op=status`;
- All three spawn sites inject **`PYTHONUNBUFFERED=1`** → `<jobdir>/stdout.log` has increments **while running** (it does not wait for the process to exit before landing on disk).

```python
blender_rt_job(op="status", id="run-abc123")   # → stage="rendering" / idleMs=1200 / pidAlive=true / lines=42
```

### 7.3 Three copyable skeletons

**Skeleton A · one-off self-check (2-5 s, the most common)**

```python
blender_rt_headless(
  file="/mnt/d/work/aurora/parts/hull_aft.blend",
  preload="audit",
  script="""
import json
print('HEADLESS ' + json.dumps(
    K.dsh_audit_api('connectivity', {'scope': 'Hull_Aft', 'micro_gap_mm': 2.0}), ensure_ascii=False))
""")
```

**Skeleton B · multi-view long render (minute-scale)**

```python
blender_rt_headless(
  file="/mnt/d/work/aurora/Aurora.blend", outdir="/mnt/d/work/out/shots",
  as_job=True, wait_s=15,                     # wait 15 s first; if not done, hand over to the job layer
  shots=[{"name": "iso", "from": [9, -9, 6], "look_at": [0, 0, 1], "res": [1920, 1080], "samples": 256},
         {"name": "front", "from": [0, -14, 2], "look_at": [0, 0, 1], "res": [1920, 1080], "samples": 256}])
# the receipt res.shots gives path / ms / md5 / coverage_estimate for every image
```

**Skeleton C · headless direct QC / delivery (`preload` lookup table)**

| What to do | preload | Call |
|---|---|---|
| Silhouette comparison (IoU / Dice / profile difference + comparison image) | `qc` | `K.dsh_qc_api["compare"](ref, ref_box, render, label=…, out_dir=…)` |
| Multi-view render harness | `qc,qc_render` | `K.dsh_qc_render_api["render_views"]({views:[…], res:[…], outdir:…})` |
| Montage (L2 evidence) | `montage` | `K.dsh_montage_api["montage"]({paths:[…], cols:4, tile:420})` |
| Delivery export / verification | `deliver` | `K.dsh_deliver_api['export']({dir:…, scope:…, name:…})` / `['verify'](dir)` |
| Mesh inspection | `audit` | `K.dsh_audit_api('mesh', {objects:[…]})` |
| Mechanisms / generators / contracts / planner | `motion` / `generator` / `contract` / `planner` | `K.dsh_<name>_api(...)` |

> `preload` names = module names under `runtime/`; separate multiple modules with commas and **each gets its own namespace** (`preload="qc,qc_render"`).
> `K.dsh_<name>_api` supports both forms: `api["fn"](...)` (returns a string) / `api("fn", {...})` (returns an already-parsed dict).

### 7.4 Path space: `outdir` / `out_json` accept WSL paths

| Parameter | Current behavior |
|---|---|
| `outdir` / `out_json` / `file` | **Accept WSL paths** (`/home/…`, `/mnt/…`), mapped internally; the receipt gives the **real write path** (Windows form + WSL-visible form) |
| A script handing a WSL path to a Windows API | Detected "Windows API received `/home/…` or `/mnt/…`" → **explicit error**, no more silent drift |

```python
blender_rt_headless(outdir="/home/sixtyseven67/DSH/test/modeling/aurora/out",   # ✅ give a WSL path directly
  script="import os, json; open(os.path.join(K.out_dir, 'probe.txt'), 'w').write('ok'); "
         "print('HEADLESS ' + json.dumps({'out': K.out_dir}))")
# the receipt gives the real write path; ls of that WSL path in bash should show the file
```

> Still note: `/mnt/c|d|e|f` are **read-only mounts** (you cannot write into them), and when artifacts land on a read-only mount `read_image` cannot open them →
> temporary artifacts always go in the **workspace** (§7.5), and finished items are copied out later per the archiving convention.

### 7.5 Pitfall: the bash sandbox's `/tmp` is **not shared** with the fs tools (burned on every bash call)

**Symptom** (reproduced on this machine's web profile):

```bash
# within the same bash call: visible
echo hello > /tmp/dsh_probe.txt && ls -la /tmp/dsh_probe.txt      # ✅ the file is there
```

```bash
# in the **next** bash call immediately after: gone
ls -la /tmp/dsh_probe.txt     # ❌ No such file or directory
```

And fs tools such as `read` / `read_image` **never see** bash's `/tmp` (`not found`).
This round engine / hull_aft / gear-arms each wasted 1-2 rounds on this pitfall (engine's exact words: "in the same bash call `ls` shows it,
immediately after `read_image` says not found, and a separate `ls` shows an empty directory").

**Rule: temporary files must land in the workspace** (or the artifact directory agreed for the task), not in `/tmp`, `/var/tmp`, `$TMPDIR`.

```bash
# ✅ correct: a temporary directory under the workspace, visible across bash calls and to the fs tools
mkdir -p /home/sixtyseven67/DSH/.tmp/<task> && python3 probe.py > /home/sixtyseven67/DSH/.tmp/<task>/probe.json
```

```python
# ✅ same on the Blender side: give the artifact directory a path both ends can read and write (neither a read-only mount nor bash's /tmp)
blender_rt_headless(outdir="/home/sixtyseven67/DSH/.tmp/hull_aft",
  script="import os, json; print('HEADLESS ' + json.dumps({'dir': os.getcwd()}))")
```

| ❌ Do not write it like this | ✅ Change to |
|---|---|
| `bash: … > /tmp/x.json` and then `read` it | Write `<workspace>/.tmp/<task>/x.json` |
| `blender_rt_headless(outdir="/tmp/out")` | `outdir="<workspace>/.tmp/<task>/out"` |
| Artifacts land in `/mnt/d/...` and then `read_image` | Land in the workspace; during archiving copy to `D:\Blender\<project>\` per convention |
| Hand-assemble a `\\wsl.localhost\Ubuntu\…` UNC path | Give a WSL path directly (§7.4) |

### 7.6 Common misuse (self-check against this table)

| Misuse | Consequence | Correct approach |
|---|---|---|
| The outer `run_code` passes no `timeoutMs` and runs headless for >100 s | Returns a promoted envelope, but you wasted 100 s waiting | For expected >100 s use `as_job=True` directly |
| Looping `op=status` to poll | Trips the harness's repeated-call detection | `op="wait"` gets the result in one go |
| Hand-writing a regex to extract `result:` | Double escaping + truncation throws | Parse the 1st text block (§7.2) |
| Large output relying on stdout | The middle is elided (`…[N characters omitted in the middle]…`) | Give `out_json=`; on truncation look at `resultTruncated` + `resultPath` |
| Using `scene.ray_cast` for per-pixel batch rays | Per pixel goes through the depsgraph → hits the 120 s / 600 s limit | `BVHTree.FromPolygons + bvh.ray_cast` ([evidence-grading-and-image-reading.md](evidence-grading-and-image-reading.md) §6) |
| Comparing `image.pixels` directly against PIL/cv2 | Vertically flipped → a falsely low IoU (0.463 vs 0.955) | Apply `[::-1]` first (same §6) |
| Each modeler writing its own camera / lights / AgX boilerplate | 50-60 lines × N people | `shots=[…]` (§7.2) |
| Running EEVEE in parallel, each making its own render lock | Fighting over the GPU; someone waits 48 s for the lock | Use the built-in `render_lock` (`qc_render_views` acquires automatically) |
---

## 8. One-click Blender launch (when a GUI is needed): `blender_viewport(op="launch")`

> Background: the GUI channel needs "Blender open + addon Connected", and an agent has no human hand to press the N panel.
> `launch` hardens "write the boot script → spawn the GUI Blender → wait for the addon port → doctor check-up" into a single call;
> **purely headless tasks do not need it** (just use `blender_rt_headless` / `blender_rt_worker`).

### 8.1 One command

%%%json
{ "op": "launch" }                                  // minimal form (waits 90s, auto-detects the addon)
{ "op": "launch", "file": "/mnt/d/Dsh/…/tank.blend" }   // conveniently open a project
{ "op": "launch", "wait_ms": 180000 }                // slow cold start (mechanical disk / first plugin load) → raise it
{ "op": "launch", "dry_run": true }                  // only show the command that would run, do not launch
%%%

What it does internally: writes the boot script (enable the addon inside the GUI → start the socket server) → `detached spawn blender.exe`
→ **polls ports 9776…9876** → once the port is open, runs `doctor` once for a diagnosis.
The criterion is **the port really being open**, not "the process started" -- the latter is exactly the half-finished state at which the manual flow most often stops.

### 8.2 Idempotence and concurrency

- **Already listening** → returns `already: true` and will **not** start another Blender (safe for repeated calls by multiple agents).
- Several agents calling at the same time: the later ones see already (or, after a brief race, also already).
- To restart: close that Blender first (or `op=restart`, which restarts only the **backend**, not Blender; do not confuse the two).

### 8.3 Parameters

| Parameter | Default | Description |
|---|---|---|
| `wait_ms` | 90000 | Upper bound for waiting on the addon port (a Blender cold start + plugin load takes dozens of seconds) |
| `file` | — | The .blend to open on launch (WSL / Windows paths both accepted) |
| `exe` | config chain | Explicitly specify blender.exe (overrides `DSH_BLENDER_EXE` / `dsh-blender.config.json` / auto-detection) |
| `addon_module` | auto | addon module names to enable (comma-separated); by default it scans for "module name containing mcp" |
| `addon_file` | — | Absolute path of an addon .py to import by file (the fallback for Blender 5.x extension layouts where `addon_utils` cannot scan the old-style addons directory) |
| `dry_run` | false | Only report the command that would run |

### 8.4 How to read the receipt

%%%
LAUNCH ok · spawned pid=12345 · addon port 9876 · waited 8123ms
blender.exe: /mnt/d/SteamLibrary/steamapps/common/Blender/blender.exe (source config)
Hint: GUI Blender is up and the addon is Connected (port 9876) -- you can now use viewport rt_see / rt_cmd (for write operations remember blender_viewport op=lease to take the lease; purely headless tasks could have run without a GUI anyway)
· spawned … (detached, decoupled from the backend process)
· addon port 9876 is listening (8123ms)
boot conclusion (launch-status.json written by the GUI side itself): loaded_by=addon_utils:dsh_blender_bridge · server_running=True · enabled=["dsh_blender_bridge"]
post-launch check-up: channel healthy: TCP + ping + bpy round trip all work
boot script: \\wsl.localhost\Ubuntu\…\dsh_headless_xxx.py (run it directly if you want to debug by hand)
%%%

- `statusFile` points at `<workDir>/launch-status.json`: **we cannot get the GUI process's stdout**, so the boot script
  writes the conclusions (enabled / loaded_by / errors / addon_modules_seen / env) to disk itself.
- On failure look at `boot.errors`: commonly "the addon was not scanned" (→ try `addon_file`) or "background mode"
  (the addon explicitly refuses to start the server under `-b`; a GUI is required).

### 8.5 Relation to headless (do not mix them up)

- `op=launch` manages **GUI Blender** (it must light up 9876, for viewport screenshots `rt_see`, `rt_cmd`, and the interaction loop that "changes the user's live scene").
- `blender_rt_headless` / `blender_rt_job` / `blender_rt_worker` **do not need** a GUI and do not occupy 9876 (independent `blender -b` processes); neither do `rt_do / rt_see / rt_watch` with `session`, or `rt_plan session="auto"`.
  **For multi-agent parallel batch processing use headless / worker**; the GUI is needed only for "looking at the user's viewport / changing the user's live scene / needing GUI context".

### 8.6 What to do when the receipt reports `value is not lossless JSON`

The host gate rejects the receipt (common when the plugin version and the old modules loaded by the host/DSH do not match). **Upgrade to the current v3.0.6 and restart DSH** (the plugin is a module loaded when DSH starts);
meanwhile the result itself is not lost: submit with `blender_rt_job(op="start")` and then read the `HEADLESS {…}` in `jobs/<id>/stdout.log` as a fallback.

---

## 9. Host integration (`@` mention + native selection)

> **The DSH-side "Blender viewport" panel, click-into-message, model-requested picking (`blender_rt_pick`) and the TUI sidebar panel have all been removed.**
> The selection entry point moved to the Blender side: native selection → send from the N panel (see §10); read-only viewport screenshots are still handled by the model tool `blender_rt_see`.
> The backend routes `/host/view/*`, `/host/pick*`, `/host/ready` are **removed at the same time**; the remaining host routes are only
> `/host/selection` (+ `/latest`, `/consume`), `/host/scene-items`, `/host/jobs` (+ `/log`).

Host integration is a **user-side** capability (you act → it goes into your own message), **not a model tool**: it goes through separate HTTP routes `/host/*`,
**does not enter** the op catalog and **does not add** model tools ⇒ the capability surface of 15 tools / 217 ops **is unchanged**.

### 9.1 What still exists: `@` mention

Type `@` in the input box to get object / material / collection candidates (references are prefixed `object:<name>` / `material:<name>` / `collection:<name>`);
after selection the `codec` strips the prefix and serializes it as `<blender-object>Cube</blender-object>`, so the model gets the exact name and does not have to guess.
Candidates come from `GET /host/scene-items?q=` (a read-only backend cache, **does not occupy** the Blender main thread).

### 9.2 Prerequisites and ports

| # | Condition | How to confirm |
|---|---|---|
| 1 | The backend is running (`127.0.0.1:9877`) | `curl -sS http://127.0.0.1:9877/health` |
| 2 | Blender is open and the addon is Connected (`127.0.0.1:9876`) | `curl -sS http://127.0.0.1:9877/doctor` → `kind=ok` |
| 3 | `lib/client.js` is built and **DSH has been restarted** | `npx vitest run tests/unit/js/contract/client-bundle.test.ts` |
| 4 | addon **v1.11+ / protocol 11** (native selection/collections/sub-elements/AI pause) | `blender_rt_cmd get_addon_info` → `addon_version [1,11]`, `protocol_version 11` |

Ports at a glance: addon `9876` · backend `9877` · DSH GUI `3080` (all listen on localhost only; do **not** expose them externally).

CORS for `/host/*` echoes the Origin only for **HTTP loopback** and the **exact `dsh-app://app`** (other origins get no `Access-Control-Allow-Origin`).
This is not request authentication, nor a server-side 403 rejection.

### 9.3 DSH must be restarted after changes/upgrades

The client half (`lib/client.js`) is a module loaded when DSH starts; only a backend-only change uses `blender_viewport(op="restart")`.
After upgrading this plugin you **must restart DSH**, otherwise neither the `@` mention nor the native selection bridge will update.

### 9.4 Self-check

```bash
npx vitest run tests/unit/js/contract/client-bundle.test.ts     # bundle shape + @ codec + selection text/insertion path
npx vitest run tests/integration/js/selection-store.test.ts   # backend selection store (sanitize/seq/consume)
```

## 10. Blender native selection → DSH (addon v1.11+)

### 10.1 What this is

"Selecting an object" no longer requires clicking a low-res screenshot in DSH's viewport panel: **select it in Blender's native selection**, press the button in the N panel,
and the selected object names go into **the input box of DSH's current session** (a draft; it is **not sent automatically**; whether to send is up to you).

At the same time the Blender side provides a unified **activity determination** (human / AI / idle / both), shown live in the panel and also queryable by the model --
so that AI does not treat an intermediate state as final while you are dragging, transforming, entering edit mode, or have just undone something.

### 10.2 Get going in three steps

1. **addon v1.11+ (zip package)**: use this repository's [`addon/dsh_blender_bridge.zip`](../addon/dsh_blender_bridge.zip) (or reinstall/re-enable it once),
   and **restart DSH** (the client half is loaded at startup).
2. Select objects in the Blender viewport: click selection / box selection / Shift to add all work; multiple selections send all names (cap 200).
   Entering **edit mode** and selecting vertices / edges / faces, or **pose mode** and selecting bones, also sends them (`selection.sub`).
3. In the 3D View press `N` → "DSH Blender Bridge" → **Selection → DSH**:
   - **Multi-select mode**: select several objects → click "object list (N) ▸" to expand (collapsed by default; has a scrollbar) → "send selection to DSH";
   - **Collection mode**: pick a collection in the "collection" dropdown (or click the ⟳ next to it to infer it from the selected objects) → click "member list (N) ▸" to expand and inspect
     → "send collection to DSH" (hundreds of parts need not be selected one by one).
   - After expanding, drag the "height (rows)" slider to adjust the visible height of the list (3-30 rows, default 8); the list has its own scrollbar when there is more content.
   - **Sub-elements**: when vertices/edges/faces are selected in edit mode, the expanded list gains rows like "vertices 12 / edges 3 / faces 7";
     the draft then reads "Blender edit mode (mesh) 'Cube': 12 vertices selected / … vertex indices: …",
     and the model uses the indices to make precise changes with `bmesh`; bones are selected in pose mode and the draft gives the bone names.
   - The backend address / overrides are in the collapsed "backend / advanced" section.

Then go back to DSH: a line appears in the current session's input box
`Blender selection: Cube, Camera. Active object: Cube. Mode: OBJECT. When the user says "this/these", they mean them; the object names can be used directly in bpy.data.objects.`

> On success the panel shows "last send: success (seq N)"; whether the insertion succeeded on the DSH side can be verified with
> the `last_consume` of `curl -sS http://127.0.0.1:9877/host/selection/latest` (`{ok:true, how:"actions"}` = it is in the draft).

### 10.3 The four activity states

| `state` | Meaning | Trigger |
|---|---|---|
| `idle` | Idle | Neither window has a signal |
| `human` | A human is operating | A modal operation (`window.modal_operators`: drag/transform/menu etc.) **or** a human operator / undo / selection change within 1.5 s |
| `agent` | AI is operating | An agent command is executing, or the last command ended ≤1.5 s ago |
| `both` | Both at once | Both signals are present |

- Look at the activity state directly at the **top** of the panel; in `agent` / `both` it shows a red warning "AI is operating Blender".
  The most recent human action is shown as `selection` / `undo` / `modal:transform.translate` and the like.
- **Pause AI operations**: a button at the top of the panel; once paused the socket only lets read-only queries through (`get_*` / `ping` etc.),
  while `execute_code`, asset download / model generation / import and other write operations return `AI_PAUSED`; resuming is only possible by clicking "resume AI operations" inside Blender.
- The model side queries the same state with `blender_rt_cmd get_activity_state` (**the query itself does not count as agent activity**);
  and the native selection with `blender_rt_cmd get_selection`.
- This determination is **independent of telemetry consent and uploads no data at all**; it is a different thing from `drain_human_activity` (which only has an event buffer after consent).

### 10.4 Troubleshooting

| Symptom | Cause / disposition |
|---|---|
| The button is greyed out | Nothing is selected right now (select something in Blender and click again) |
| `send failed: Connection refused` / timeout | The DSH plugin backend is not running (restart DSH first / check 9877); or Blender and DSH are not in the same network namespace. You can set the environment variable `DSH_BLENDER_BACKEND_URL` or fill a reachable address into the scene property `dshbb_backend_url` (empty defaults to `http://127.0.0.1:9877`) |
| The backend has a `seq` but the DSH input box is empty | ① DSH was **not restarted** after the upgrade (the old client half does not understand `/host/selection`); ② check `last_consume.reason` of `/host/selection/latest` (draft lock / fallback channel non-empty / TUI); ③ if the current session is not the one you want to write into, switch to the target session and click again |
| activity stays `agent` | Normal: within the 1.5 s window after an agent command just ended; wait a moment and query again. `get_activity_state` already excludes the query itself |
| A tool reports `AI_PAUSED` | "Pause AI operations" at the top of the panel has been pressed: have the AI stop, then click "resume AI operations" in the Blender panel |
| Cannot find the environment/model API panel | It is at the bottom of the N panel: "environment and role model API calls"; both the parent panel and the "environment generation / model generation" sub-panels are collapsed by default, expand them to configure |
| A human is clearly operating but it shows idle | The addon version is below v1.11; or the operation was input other than "pure view navigation" that did not trigger an operator/selection change (very rare) -- report the symptom together with `last_human_kind` |
| Not received in the TUI | The draft bridge only exists in the **Web client** (`conversation.input.dock`); the TUI's `sendToChat` is not authorized -- this is a pre-existing boundary |

### 10.5 Acceptance commands (re-runnable)

```bash
# 1) addon version and commands
blender_rt_cmd get_addon_info            # expect addon_version [1,11], capabilities include get_activity_state/get_selection/send_selection_to_dsh
blender_rt_cmd get_activity_state        # state=idle when idle
blender_rt_cmd get_selection             # names match the viewport selection

# 2) the three backend routes (pure memory, no need for Blender to be running)
curl -sS -X POST http://127.0.0.1:9877/host/selection -H 'content-type: application/json' \
  -d '{"v":1,"source":"curl","selection":{"count":1,"names":["Cube"],"active":"Cube","mode":"OBJECT"}}'
curl -sS http://127.0.0.1:9877/host/selection/latest

# 3) offline regression
npx vitest run tests/integration/js/selection-store.test.ts
npx vitest run tests/unit/js/contract/client-bundle.test.ts
npx vitest run tests/integration/js/host-selection.test.ts tests/integration/js/host-jobs.test.ts tests/integration/js/host-scene-items.test.ts      # criteria S1-S3 start a fake backend themselves, no Blender needed
```

> For the contract and criteria S1-S8 see [host-integration-contract-v2.3-addendum.md](host-integration-contract-v2.3-addendum.md).
