# Configuration reference

> All machine-specific settings live in `runtime/config.ts` (compiled output `lib/runtime/config.js`):
> **environment variables → config file → auto-detection → built-in defaults**. There is only this one implementation; to move to another machine you change configuration, not source.
>
> **Current version**: plugin **v3.0.6** · **15 model tools** · plan catalog **34 families / 228 ops** · Blender-side addon **v1.11 / protocol 11** ·
> backend `127.0.0.1:9877` / addon `127.0.0.1:9876`. **The only acceptance criterion**: `doctor` returns `kind=ok`.

---

## 1. Priority chain (high → low)

```text
┌ 1. Environment variables  DSH_BLENDER_* (see §3)
├ 2. Config file            $DSH_BLENDER_CONFIG
│                           → <package root>/dsh-blender.config.json
│                           → ~/.dsh/dsh-blender.config.json
├ 3. Auto-detection         work dir (Windows %LOCALAPPDATA%\dsh-blender-rt; macOS ~/.dsh-blender-rt; if unobtainable then os.tmpdir())
│                           blender.exe (macOS /Applications/Blender*.app; Windows Program Files / Steam; WSL /mnt/<drive>/...; then PATH)
└ 4. Built-in defaults      addon 127.0.0.1:9876 · backend 127.0.0.1:9877 · lease TTL 600000 ms · holder=plugin-pid-<pid>
```

**How to confirm what is actually in effect**:

```bash
curl -sS http://127.0.0.1:9877/who | python3 -m json.tool | sed -n '/"config"/,/}/p'
# or have the model call: blender_viewport(op="doctor")   → the config section in the response
```

The `config` section states `configFile` (which config file was used; `null` if none), `workDir.from`, `blenderFrom` (`config` / `auto:install` / `auto:steam` / `auto:path` / `not-found`).

---

## 2. Config file

Copy the example and rename it, and it takes effect:

```bash
cp dsh-blender.config.example.json dsh-blender.config.json
```

| Key | Type | Default | Description |
|---|---|---|---|
| `workDir` | string | auto | Directory for frame PNGs / headless scripts / temporary artifacts. **Windows form** (`D:\\work\\dsh-blender-rt`); under WSL it is mapped to `/mnt/d/...`. Must be "readable and writable from both ends" |
| `blenderExe` | string | auto | The blender executable. Under WSL give `/mnt/d/.../blender.exe` (a Windows process); on native Windows give `D:\\...\\blender.exe` |
| `addonHost` | string | `127.0.0.1` | addon listen address (generally no need to change) |
| `addonPort` | number | `9876` | addon port (changeable in the addon panel; it must match here) |
| `httpPort` | number | `9877` | This plugin's backend port (change it on one of two coexisting Blender instances) |
| `holder` | string | `plugin-pid-<pid>` | Write-lane lease identity (makes it easy to tell who is writing with multiple sessions) |
| `leaseTtlMs` | number | `600000` | Lease validity period; the holder renews it every time, and it expires automatically on timeout |
| `blenderUserConfig` | string | `null` | User Blender config directory (where the GPU preference lives). **A headless process cannot read it by default** → to inherit it, set this and use `factory_startup=false` (env: `DSH_BLENDER_USER_CONFIG`) |
| `blenderUserScripts` | string | `null` | User Blender scripts directory (where the addon lives), as above (env: `DSH_BLENDER_USER_SCRIPTS`) |
| `workerPort` | number | `9879` | Local port of the hot headless worker (distinct from addon 9876 / backend 9877; env: `DSH_BLENDER_WORKER_PORT`) |

---

## 3. Environment variables

| Variable | Equivalent to | Note |
|---|---|---|
| `DSH_BLENDER_CONFIG` | Specify the config file path | Highest priority; suits "one config per environment" |
| `DSH_BLENDER_WORKDIR` | `workDir` | Give a Windows-form path; auto-mapped under WSL |
| `DSH_BLENDER_EXE` | `blenderExe` | The blender used by headless tools |
| `DSH_BLENDER_ADDON_HOST` / `DSH_BLENDER_ADDON_PORT` | `addonHost` / `addonPort` | |
| `DSH_BLENDER_HTTP_PORT` | `httpPort` | Backend port (plugin and backend share the same set of sources) |
| `DSH_BLENDER_HOLDER` | `holder` | With multiple sessions, giving it explicitly is recommended (for example `session-A`) |
| `DSH_BLENDER_LEASE_TTL_MS` | `leaseTtlMs` | |
| `DSH_BLENDER_SERVER` | — | Specify the backend script path directly (generally not needed) |
| `DSH_HEADLESS_WAIT_MS` | — | headless client **wait window** (default 100000 = 100 s). If it has not finished by then → return `{kind:"promoted", jobId:"run-…"}` (the result is not lost; collect it with `blender_rt_job(op="wait"/"collect")`). See §11.1 |
| `DSH_HEADLESS_AUTO_JOB_MS` | — | **Automatic job-layer conversion threshold** (default 0 = off): a headless call whose estimated budget is ≥ this does not wait for the window and is backgrounded directly. See §11.1 |
| `DSH_WORKER_TTL_MS` | — | **Idle reclamation TTL of the hot headless worker** (default **900000 = 15 min**; `0` = reclamation off). Only reclaims sessions that are `ready` with no request in flight, checked every 30 s. `blender_rt_worker(op="status")` returns `idleMs`; see §5.6 |

---

## 4. How blender.exe is found

Detection order (`runtime/blender-detect.ts:detectBlenderExe`; `runtime/config.ts` calls it only once at module load and no longer re-exports the function):

1. The `DSH_BLENDER_EXE` environment variable;
2. The config file's `blenderExe`;
3. **Automatic scan**:
   - Windows official install: `%ProgramFiles%\\Blender Foundation\\Blender*\\blender.exe` (iterate `Blender*` in directory-listing order, unsorted; if none, fall back to the fixed candidate `Blender\\blender.exe`), source recorded as `auto:install`;
   - Windows Steam: first read the registry `HKCU\\Software\\Valve\\Steam` (and for 32-bit installs also try `HKLM\\SOFTWARE\\WOW6432Node\\Valve\\Steam`) for `SteamPath` (covers G:/H: and non-default directories; skip if unreadable), then add `%ProgramFiles%\\Steam`, `%ProgramFiles(x86)%\\Steam`, `%ProgramW6432%\\Steam`, and `{C,D,E,F,G,H}:\\{Program Files\\Steam, Program Files (x86)\\Steam, Steam, SteamLibrary}` (taking the first existing root in that order), then read the other libraries listed in each root's `steamapps\\libraryfolders.vdf`, matching `<library>\\steamapps\\common\\Blender\\blender.exe`, source recorded as `auto:steam` (if the vdf is missing/corrupt, only the root itself is tried, without an error);
   - WSL: `/mnt/{c,d,e,f}/Program Files/Blender Foundation/Blender*/blender.exe`, plus `SteamLibrary/steamapps/common/Blender/blender.exe`, `Steam/steamapps/common/Blender/blender.exe`;
   - **macOS**: `/Applications/Blender*.app/Contents/MacOS/Blender` and `~/Applications/Blender*.app/Contents/MacOS/Blender` (any version name, such as `Blender.app`, `Blender 4.2.app`), plus mounted volumes `/Volumes/*/Applications/…`;
4. `PATH` (Windows `where blender`; Linux `which blender`);
5. None of the above → `config.blenderExe = null` (`blenderFrom: not-found`): `blender_rt_headless` / `blender_rt_worker(op="start")` / `blender_rt_job(op="start")` immediately return `blender_exe_missing` (with configuration guidance, no longer throwing `TypeError`), suggesting the three configuration methods.

**The three configuration methods (pick one)**:

```bash
# ① Environment variable
export DSH_BLENDER_EXE=/mnt/d/SteamLibrary/steamapps/common/Blender/blender.exe     # WSL
#   Windows: set DSH_BLENDER_EXE=D:\Program Files\Blender Foundation\Blender 5.2\blender.exe

# ② Package-root config
echo '{"blenderExe":"/mnt/d/.../blender.exe"}' > dsh-blender.config.json

# ③ User-level config (shared by several projects)
mkdir -p ~/.dsh && echo '{"blenderExe":"/mnt/d/.../blender.exe"}' > ~/.dsh/dsh-blender.config.json
```

---

## 5. Work directory (why it must be "paired")

Blender (a Windows process) **writes** frame PNGs and headless scripts; the host (Node inside WSL) **reads** them. So one physical directory needs two spellings:

| | Example |
|---|---|
| Blender side (Windows path) | `C:\Users\\<you>\\AppData\\Local\\dsh-blender-rt` |
| Host side (WSL path) | `/mnt/c/Users/<you>/AppData/Local/dsh-blender-rt` |

- By default it takes Windows' `%LOCALAPPDATA%\\dsh-blender-rt` (inside WSL it asks once via `cmd.exe /c echo %LOCALAPPDATA%`; the result is cached);
- If unobtainable (no WSL interop / **native Linux**, the latter supported since v1.0.4) → fall back to `os.tmpdir()/dsh-blender-rt` (this requires Blender and the host on the same machine; on native Linux **no cross-OS mapping is done**, the host path is handed to Blender as-is, and `workDirWin` and `workDirWsl` are isomorphic);
- **In the WSL scenario do not** configure a path inside WSL (such as `/home/me/x`): Windows Blender can only reach it over UNC, and **UNC writes fail silently**; on native Linux, `/home/me/x` is instead the correct spelling;
- Do not configure a read-only mount (inside WSL, `/mnt/c` is usually read-only unless you enabled the corresponding permission on the Windows side).

---

## 5.5 GPU semantics (the most expensive pitfall in headless rendering)

**Problem**: a headless process (`blender -b`) **cannot read user preferences by default** → `prefs.compute_device_type = NONE`, the device list is empty → even if the project file says `scene.cycles.device = "GPU"`, **Cycles silently runs on CPU**.
Measured on this machine (1821-object project, 480×270/32spp): **CPU 2.78 s vs GPU with warm-up 0.18 s = 15.4×**.

**Three-layer solution** (in recommended order):

1. **The default `gpu:"auto"` preamble** (zero configuration): set `compute_device_type` in the order `OPTIX→CUDA→HIP→ONEAPI→METAL` + enable GPU devices + `scene.cycles.device="GPU"`, and report back the `gpu` field (`before/after/configured/fell_back_to_cpu`);
2. **`use_user_config: true`**: pass through `BLENDER_USER_CONFIG` / `BLENDER_USER_SCRIPTS` (together with `factory_startup=false`, so the headless process inherits your preferences and addons);
3. **`gpu: "true"`**: require a GPU; without one `ok=false` (use this when you do not want to be bitten by a silent downgrade again).

> In one sentence: **do not trust `device=GPU` in the file; look at `gpu.after.gpu_enabled` in the receipt.**

## 5.6 Hot headless sessions, plan headless routing and long tasks

| Scenario | What to use | Description |
|---|---|---|
| One-off heavy work (render/batch geometry/validation) | `blender_rt_headless` | Cold start 0.9-1.2 s, clean, reproducible; `engine="none"` skips the preamble (pure numpy/image tasks) |
| **Repeated iteration / no-GUI interaction** | **`blender_rt_worker`** | A persistent `blender -b`; `start` → `exec` / `see` / `reset` → `status` → `stop` (`list` shows all); serial execution; the same `name` reuses the same process and the persistent kernel `K` |
| **Headless execution of a plan op** | `blender_rt_plan(..., session="auto")` | Automatically starts a persistent worker + injects the preload by family (such as `asm_*` → assembly/audit/contract/clearance/gate/mesh_fix/geo/txn), returning synchronously; the first cold start is ~2 s, then it is reused |
| A single run > 5 minutes | Job layer / hot session | The client `fetch` response-header timeout is **300 s**; `/headless` and `/worker` have been changed to **streaming** (response headers return immediately + 15 s heartbeat) → so runs can exceed 5 minutes, and `as_job` can also hand over to `blender_rt_job` |

**worker session pool**:

- `blender_rt_worker(op="start", name="s1", preload="audit,qc,assembly", warmup=true)`: `preload` injects modules into `K.dsh_*_api` before start-up (on failure start errors out directly rather than silently missing modules); `warmup` warms up the renderer (default true).
- **Idle TTL**: by default reclaimed automatically after **15 min** without requests (`DSH_WORKER_TTL_MS` is adjustable, `0` = off; see §3; the value is read once when the engine starts, so restarting DSH after changing it is safest); reclamation only targets sessions that are ready with no request in flight.
- `rt_do` / `rt_see` / `rt_watch`'s `session`, `rt_plan`'s `session="auto"`, and `rt_loop target="session"` all reuse it; `session="auto"` only takes effect within the plan's headless-mapped families (`asm_/blockout_/img_/gate_/eval_/visualreport_/shapesolve_/audit_/qc_/…`).

**Semantics of timeout/disconnect**: a client disconnect **does not equal task failure** -- the server-side child process keeps running to completion, the artifacts remain in `outdir`, and the full log path is in the `logs` field. On `fetch failed`, look in the directory first.

## 6. Ports and multiple instances

| Scenario | How |
|---|---|
| One Blender, one session | The default is enough (9876 + 9877) |
| **Two Blender instances in parallel** | Second instance: change the port in the addon panel (say 9896); plugin side `httpPort=9898, addonPort=9896` (config file or environment variables) |
| Temporary debugging | First `npm run build`, then `node lib/runtime/server.js --port 9888` (the command-line `--port` takes precedence over configuration) |

### addon protocol (there is only one)

Only this repository's `DSH Blender Bridge` (**v1.11+ / protocol 11**) **flat protocol** is supported (no framing; request `{"type":…,"params":{…}}`,
response `{"status":"success","result":{…}}`). Upstream `MCP for Blender`, harveyxiacn's `blender_mcp_addon`
and the old `addonProtocol` config/environment variables **have all been removed**; installing an old addon shows up as `blender-unreachable` or
`addon-thread-stuck`, so switch to this repository's addon per [MIGRATIONS.md](../MIGRATIONS.md) (`blender_rt_cmd get_addon_info` can verify `addon_version/protocol_version`).

---

## 7. Lease (concurrent-write protection)

| Item | Description |
|---|---|
| What is protected | Write routes: `/act /cmd /loop /perf(write ops) /opt(join) /headless`; **read-only ops are exempt** (`perf status/help`, `loop status/board/help`, `opt analyze`) |
| When there is no lease | No friction at all (day-to-day single agent) |
| When someone else holds it | Returns `409 {ok:false, error:"leased", holder, expiresInMs, hint}` |
| Preemption | `blender_viewport {op:"lease", force:true}` or `force:true` in the HTTP body |
| Renewal | The plugin heartbeats every 15 s; it renews **only when it already holds the lease** (no grabbing while idle) |
| Release | `blender_viewport {op:"release"}` |
| Inspect | `blender_viewport {op:"who"}` or `curl /who` |

---

## 8. Two deployment shapes

### A. DSH in WSL, Blender on Windows (recommended)

- Requires: WSL interop (`cmd.exe` / `blender.exe` can be executed directly);
- Headless tools start `blender.exe` directly through binfmt (stdout/stderr passed straight back);
- Path mapping is automatic: `/mnt/d/x` ↔ `D:\x`.

### B. DSH and Blender both on Windows

- When `runtime/config.ts` detects `process.platform === 'win32'`, path mapping automatically degrades to "return as-is";
- Just give `blenderExe` a Windows path;
- Headless tools `spawn` that exe directly.

---

## 9. History: comparison with the old hard-coded version (for traceability only)

An early distribution shipped an "author's own build" that hard-coded machine-specific settings in the source; now there is only one implementation (`runtime/config.ts`),
and the table below only serves to trace differences in old documents; it is no longer an optional branch.

| Config item | Old hard-coded build | Current implementation |
|---|---|---|
| workDir | `D:\DSH\blender\tmp` ↔ `/mnt/d/DSH/blender/tmp` hard-coded | automatic / configurable |
| blender.exe | Steam path hard-coded | auto-scanned / configurable |
| Ports | 9876 / 9877 hard-coded | configurable |
| Denoiser | fixed OPTIX | automatic by `compute_device_type` (OptiX ↔ OIDN) |

> Change only configuration, not code, to move machines -- the current implementation is already unified, and no migration between an "own build / shared build" is needed.

## 10. Engine-related index (EEVEE default) and pitfalls

Configuration items themselves do not distinguish engines, but **the default engine is EEVEE + ray tracing**; engine-specific hard limits and countermeasures are written up separately:

| What you want to look up | Where to look |
|---|---|
| Engine facts (pure GPU / graphics backend / no dependency on device preferences / no silent downgrade when headless) and measured numbers (1.35 s vs 3.13 s, cold first frame 16 s) | [docs/eevee-essentials.md](eevee-essentials.md) section 1 |
| EEVEE hard limits: Shader to RGB contains direct light only, dark areas are pure black, environment light 300~500 W | same document, section 2 |
| NPR material pipeline division of labor (main node vs light-source extension BSDF, Lightgroup ID = -1, diffuse extension light dimmed 214→44) | same document, section 3 |
| The three gradient-group pitfalls + the "move the camera to verify first, then return to the user's camera position" diagnostic routine | same document, section 4 |
| Coordination with this plugin's toolchain (rt_do / rt_worker / rt_headless / qc_compare / txn) | same document, section 5 |
| Values of the tool parameter engine= (eevee / cycles / keep) | [docs/operation-tutorial.md](operation-tutorial.md) appendix "Render engines" |

> In one sentence: **for engine-related questions read eevee-essentials.md first**; use engine="cycles" only when real GI / caustics / maximum fidelity is required.


---

## 11. Headless path space, wait window and session pool

### 11.1 Wait window and automatic job conversion

| Variable | Default | Effect |
|---|---|---|
| `DSH_HEADLESS_WAIT_MS` | **100000** (100 s) | Client **wait window**: how long `blender_rt_headless` waits synchronously. If it has not finished by then → return `{kind:"promoted", jobId:"run-…"}`; **the result is not lost**, collect it with `blender_rt_job(op="wait"/"collect", id=…)` |
| `DSH_HEADLESS_AUTO_JOB_MS` | **0 (off)** | **Automatic job-layer conversion threshold**: when the estimated budget of `timeout_ms + 60 s` is ≥ it, the headless call **does not wait for the window** and is backgrounded directly with `as_job=true` semantics (returning a jobId on the spot). Setting `120000` means "anything estimated at >2 min is always backgrounded" |

When they are read: both variables are **read once at plugin module load** (not per call) → **restarting DSH after changing them is safest**.
**Explicit parameters take precedence over environment variables**: if `as_job` / `wait_s` is given, that is used (`wait_s` itself is also clamped by the wait window, as `min(wait_s, window)`).

> Semantics: the client only waits for its own budget; on expiry it returns a `promoted` envelope (**not a failure**) -- the server-side child process keeps running and artifacts keep landing on disk; just collect them with `blender_rt_job` by `run-…` / `job-…` id.

```bash
# WSL (DSH in WSL)
export DSH_HEADLESS_WAIT_MS=30000        # wait only 30 s; anything longer, take the jobId and go
export DSH_HEADLESS_AUTO_JOB_MS=120000   # background anything expected to take >2 min

# Windows (DSH and Blender both on Windows)
set DSH_HEADLESS_WAIT_MS=30000
set DSH_HEADLESS_AUTO_JOB_MS=120000
```

**Confirming the effective values**: the `config` section of `blender_viewport(op="doctor")` (or `curl -sS http://127.0.0.1:9877/who`) reflects the backend-side effective configuration;
the two `DSH_HEADLESS_*` are **client** variables, so just look at them in the same environment with `node -e "console.log(process.env.DSH_HEADLESS_WAIT_MS)"`.

**Acceptance (copy and run)**:

```python
# ① Wait-window semantics: a script that sleeps 200 should return a promoted envelope at the window deadline, not a deadline error
r = blender_rt_headless(script="import time; time.sleep(200); print('HEADLESS {}')", timeout_ms=900000)
blender_rt_job(op="collect", id=r.jobId)      # the jobId in the envelope (of the form run-…)

# ② Explicit parameters override environment variables: if wait_s is given, wait per wait_s
blender_rt_headless(script="import time; time.sleep(5); print('HEADLESS {}')", as_job=True, wait_s=15)
```

> Relation to §5.6 "client timeout ≠ task failure": this now **has a handle to collect** -- the receipt gives the `jobId` directly, so you no longer have to guess from `ls` PNG timestamps.

### 11.2 `outdir` / `out_json` accept WSL paths

| Parameter | Current behavior |
|---|---|
| `blender_rt_headless(outdir=…)` | **Accepts WSL paths** (`/home/…`, `/mnt/…`), mapped internally with `K.win_path`; the receipt gives the real write path (both Windows and WSL forms) |
| `blender_rt_headless(out_json=…)` | Same as above; large-result overflow also lands in the real artifact directory |
| A script handing `/home/…` to a Windows-side API | Detected and **reported explicitly**, no more silent drift |

```python
blender_rt_headless(outdir="/home/sixtyseven67/DSH/.tmp/hull_aft",     # ✅ give a WSL path directly
  script="import os, json; open(os.path.join(K.out_dir, 'probe.txt'), 'w').write('ok'); "
         "print('HEADLESS ' + json.dumps({'out': K.out_dir}))")
```

```bash
# After it runs, check on the WSL side (the receipt also gives both the Windows form and the WSL-visible form of the real path)
ls -la /home/sixtyseven67/DSH/.tmp/hull_aft/probe.txt
```

**Red lines (unchanged)**:

- `/mnt/c|d|e|f` are **read-only mounts** -- you cannot write into them;
- Artifacts landing on a read-only mount → `read_image` cannot open them, so every round needs an extra `cp` before you can look at the image;
- **Do not** write to UNC (`\\wsl.localhost\…`): it may "return success but no file exists";
- Temporary files go in the **workspace** (the bash sandbox's `/tmp` is not shared with the fs tools; see [operation-tutorial.md](operation-tutorial.md) §7.5).

### 11.3 Relation to §5 "the work directory must be paired"

Two separate things, no conflict:

| | Whose requirement | How to write it |
|---|---|---|
| **§5 plugin `workDir`** | The plugin itself (the landing point for frame PNGs / headless scripts; the Blender side must be able to write there directly) | Still recommended to configure the **Windows form** (`D:\…`); the plugin maps out the WSL form automatically |
| **§11.2 call-level `outdir` / `out_json`** | The artifact directory of each call | **A WSL path can be given directly**; the plugin does the mapping |
