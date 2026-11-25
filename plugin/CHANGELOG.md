# CHANGELOG — dsh-blender-plugin

## v3.0.6 (2026-11-05) — First-call failure fix and refactor end-state closure (governance + dev environment)

- Windows auto-detection now covers Steam libraries: it scans `%ProgramFiles%\Steam`, `%ProgramFiles(x86)%\Steam`, `%ProgramW6432%\Steam` and `{C,D,E,F}\{Program Files\Steam, Program Files (x86)\Steam, Steam, SteamLibrary}`, and parses other libraries from `steamapps/libraryfolders.vdf`; the matching source is recorded as `auto:steam`. This is the root cause of "Blender is installed in a Steam library, so the first call fails outright".
- `blender_rt_worker(op="start")` / `blender_rt_job(op="start")` pre-check blender.exe before spawn: when it is empty they immediately return a structured `blender_exe_missing` (including `DSH_BLENDER_EXE` / `dsh-blender.config.json` / Steam path examples) instead of throwing Node's `TypeError: The "file" argument must be of type string`.
- `blender_viewport(op="start")` no longer treats "the 9877 backend process is alive" as "the Blender/addon channel is usable": after /health passes it runs a bounded /status, distinguishing "backend alive + addon/bpy available" from "backend alive, addon/bpy not responding".
- `op="doctor"` and `GET /status` tell the truth: when 9876 TCP connects but the addon does not answer a bpy round-trip within budget, they return `kind: "addon-unresponsive"` (no longer collapsing to `blender-unreachable`); when the addon explicitly returns an error (not a timeout, e.g. "AI operations paused"), they attribute `kind: "addon-error"` instead of writing `main-thread-busy`; /status exposes `addonError`, and host timeouts report `backend_timeout` rather than `backend_unreachable`.
- Budgets are layered and keep their inverted relationship: after removing the startup-phase `get_addon_info` probe that was not awaited and occupied the head of the serial addon queue, /status responds within 5s and doctor within 4s (measured cold/warm calls differ by <2s; previously only 3.5s/3s were attainable); /commands gets FLAGS 15s + 3s per each of the 5 integrations (each failure additionally serializes a ~2.5s diagnostic, worst case ≈42.5s < client 45s < host static deadline 60s); the `blender_rt_commands` client budget is now 45s, closing before the host deadline; the `op="start"` /status probe budget rises to 12s (covering a first call right after the backend starts), so the host no longer aborts first and hides addonError from the model.
- `blender_rt_commands` returns `addon_unreachable` on socket-level failures, with next_action pointing at the N-panel Connect + a bounded `op=doctor`, no longer at the blocking `op=status`.
- Addon panel wording changed to "Bridge listening / Bridge server stopped" etc., no longer implying it connects to an MCP server.
- Failure classification for `blender_viewport(op="status")` fixed: connection-level failures (ETIMEDOUT / connect timeout / ECONNREFUSED etc.) uniformly report `backend_unreachable` instead of misreporting `backend_timeout`; while Blender is rendering, a separate `busy_render` is reported pointing at `render_wait`, no longer blamed on a broken addon. `errorText`'s cause chain gained depth/cycle protection.
- `/doctor` now shows `addon.kind/summary/fix` first when the addon explicitly returns an error (no longer reading a historical `metrics.lastDiagnosis`); the `BUSY_RENDER` fix points at waiting for the render.
- `/worker` exposes only one agreed code, `blender_exe_missing`; Node-internal error codes (`ERR_INVALID_ARG_TYPE` etc.) no longer become model-visible structured error codes.
- `blender_rt_headless` now genuinely surfaces the runtime `blender_exe_missing` (with configuration guidance), consistent with the docs; previously it was always swallowed into `backend_error`.
- Windows Steam detection now also covers the registry `SteamPath` (HKCU / HKLM WOW6432Node) and the usual G–H drive roots.
- Regression tests hardened: `doctor-bounded` warms up before timing (budget 12s, steady state 6–9s), macOS/Linux detection cases and the HKCU SteamPath case were added, and the worker source-order assertion became a regex.
- **Behavior change (the only one)**: `blender_rt_plan` calling `qc_render_*` in a headless worker session (`session=...`) now routes to `dsh_qc_render_api` and preloads `qc_render`; previously the worker path hit `dsh_qc_api`'s `render_views` relay function, and that relay depends on the GUI-side-only `K.dsh_qc_render_api`, so a worker that preloaded only `qc,imgtools` necessarily failed (GUI path behavior unchanged).
- No API / protocol / tool count changes (15 tools / 34 family / 228 op / addon 1.11 / protocol 11).

### Governance: refactor end-state closure

- Routing and contracts have a single source of truth: added `config/routing.json` and `scripts/gen-routes.mjs`, which generate `src/plan/routes.generated.ts` and `runtime/core/dispatcher/routes.generated.ts`; `npm run check:routes` verifies that generated artifacts match the source data; `config/contracts.json` aligns the catalog's 228 op with the Python dispatch literal table, and an AST parity test was added (`qc_compare_auto` / `qc_align_iou` are known catalog-only drift, registered for a separate fix).
- Exceptions and budgets are registered: added `config/exceptions.json` (path-level exceptions, including reviewBy expiry checks) and `config/function-budget-allowlist.json` (106 functions of 80–120 lines registered across 8 categories, reviewBy 2027-06-30); `check:exceptions` is wired into `npm run lint`; functions >120 lines remain at zero exceptions.
- Single source of truth for addon commands: handshake capabilities derive from `command_registry.COMMAND_NAMES` (no longer 16 hard-coded); host catalog and addon registry are in two-way parity; the count is unified as 38 registered + ping = 39 wire.
- public facade closure: `runtime/engine.ts` 88 → 22 exports (removed 38 py `*_PATH` and the rest of facade-dead), `config/facades.json` registers the two public facades and their consumers, and `check:no-shims` rejects unregistered exports; removed `src/host/backend/port-holders.ts`, the pure relay `engine-api/frame.ts`, and `qc_impl/api.py`'s `exec(compile(...))` second-stage load, and `runtime/recover.ts` merged into `execution/ledger/recover.ts`; addon credentials went to a single owner (add-on preferences + session override + `DSHBB_*`/`BLENDERMCP_*` env fallback), the Scene mirror properties were removed; the `detectBlenderExe` re-export was removed.
- Dead code and packaging: removed 5 unused exports, a duplicate `ReceiptContext`, the addon's `import_model_files` dead link, unused compat functions, the never-existing `runtime/ext/pkg.tgz` packaging entry, and cleaned 400+ stale `.pyc` files from the workspace.
- Documentation end state: 3 superseded documents archived to `docs/archive/`; SKILL headings renumbered; the surface algorithm collapsed to a single source; addon user-facing wording MCP/Claude → Bridge (keeping the upstream attribution and `BLENDERMCP_*` compatibility); added warn→enforce gates for `check:plan-ids` and `check:doc-paths`, cleaned refactor plan ids and fixed doc links/inbound links; `BEHAVIOR_MATRIX` row numbers became file + symbol and are verified by the gate; the SECURITY credential notes now describe it accurately.

### Development environment

- Added `npm run setup:dev`: auto-discovers Python (`PYTHON` → `python` → `python3` → Windows `py -3`, with a fallback for the broken Store alias), creates/reuses `.venv`, installs `requirements-dev.txt` + `requirements-typecheck.txt`, runs `npm ci --legacy-peer-deps` only when missing, supports `--check` / `--force`, and is idempotent; `.github/workflows/pr.yml` and `release.yml` reuse the same script instead of inlining their own venv steps.
- `CONTRIBUTING` / `README` (EN and ZH) and `scripts/README` converge on the same single dev-environment command.

## v3.0.5 (2026-11-04) — Fix missing __file__ in source injection

- Fix #73: Python modules injected as source now receive the real module path as `__file__`, so high-level operators such as `audit` / `qc` / `contract` no longer raise `NameError`.
- `preloadChunk` and `injectModule` both inject `__file__` uniformly; the `qc_render` asJob path now uses `preloadChunk`.
- Removed the `__file__` fallback left over from the refactor in `contract_impl/common.py`; the active fallback in `kit.py` is kept.
- No API / protocol / tool count changes (15 tools / 34 family / 228 op / addon 1.11 / protocol 11).

## v3.0.4 (2026-11-02) — Fix git-source install

- Fix #71: `prepack` builds only `lib/` and no longer runs `check-build` in the install path; `check:git-hygiene` is a standalone script run only by CI and by local clones.
- `scripts/check-build.mjs` dropped the `git ls-files lib` step, so it also passes in an unpacked directory without `.git`.
- Added `npm run check:git-hygiene`: fails closed when `.git` is missing or the checkout root does not match; run by both the PR gate and release verify.
- No API / protocol / tool count changes (15 tools / 34 family / 228 op / addon 1.11 / protocol 11).

## v3.0.3 (2026-11-02) — Node.js 24.9 baseline

- Minimum Node.js raised to 24.9, matching DSH's current requirement; CI/CD uses Node 24.
- Dev toolchain aligned with DSH: TypeScript 6.0.3, jsdom 29.1.1; `@types/node` aligned to 24.x.
- npm publishing switched to trusted publishing (OIDC), no longer depending on `NPM_TOKEN`.
- 3.0.2's first OIDC publish was parked by the npm registry as an invisible version and never went public; this release uses 3.0.3 instead.

## v3.0.1 (2026-11-02) — Python static checks and IDE wrap-up

> Adds no modeling capability; cleans up the Ruff allowlist, pyright noise and global injection in native E2E, and rebuilds the addon zip.

- Removed config/python-static-allowlist.json; `npm run check:python-static` runs Ruff directly and no longer maintains historical exceptions.
- native E2E's upstream modules now use explicit import + `support.bind(ctx)` instead of injecting PREFIX/api/chk/K through globals().
- The root pyrightconfig disables diagnostics only for legacy native E2E and runtime/py; the typed-core and pure-logic scopes stay strict.
- Fixed the addon's 2 pyright errors and triaged all 29 warnings one by one; no new baseline.
- Added the NumPy type-check dependency (dev/IDE only; Blender ships NumPy at runtime).
- Rebuilt addon/dsh_blender_bridge.zip; the install command is `dsh plugin --profile <profile> add dsh-blender-plugin@3.0.1`.

## v3.0.0 (2026-11-01) — Engineering health refactor (breaking: addon now a zip package)

> 15 model tools; plan catalog 34 family / 228 op; addon command 38, protocol 11;
> This release adds no modeling capability, only structure, tests, types, CI and release engineering; B1 scores are not combined with v2.6.1.

### Breaking changes

- **npm package name is now `dsh-blender-plugin`**: the `@dsh-external/dsh-blender-plugin` used inside the repo earlier was never published to npm; from v3.0.0 the npm package name is uniformly `dsh-blender-plugin`, and the install command is `dsh plugin --profile <profile> add dsh-blender-plugin@3.0.0`. The `@dsh-external/...` in older CHANGELOG entries is a historical name.
- **addon installation switched to a zip package**: the published artifact is addon/dsh_blender_bridge.zip (containing __init__.py, bl_info v1.11, protocol 11); the old single-file addon/dsh_blender_bridge.py is no longer published and is no longer an install entry point. When upgrading you must first disable and remove the old single file in Blender Preferences, then install the zip, enable it, and Connect from the N panel.
- **Premium / Tripo generation channel removed**: removed the Premium license, quota, Supabase client and Tripo toggle; Hyper3D and Hunyuan3D keep only their own API key channel. Tripo has no BYOK channel, so the whole command and its panel entry were removed too (addon command 39 → 38).
- **lib/ is no longer committed**: at source runtime, runtime/**/*.ts is compiled strictly into lib/runtime/**/*.js; to use it from git, run npm ci --legacy-peer-deps && npm run build first — prepack builds automatically. The npm package still ships lib/.
- **No more .mjs under runtime**: the old runtime/*.mjs require usage no longer holds; use the package entry point or the built lib/runtime/*.js.
- **Flat Python modules removed**: removed the 38 re-export shims of runtime/*.py, and generator.py / uv_tools.py moved into runtime/py/geometry/; modules now resolve only through runtime/py/modules.json, so the legacy import runtime.<name> (or loading runtime/<name>.py directly) no longer works. The public module names for preload / module are unchanged.

### Structure, types and tests

- src/index.ts is a 13-line entry-only file; all 15 tool handlers were split into src/tools/*; check:structure verifies 73/73 target files, 83 files / 330 import edges / 0 cycles.
- Production source line budget: 284/284 files ≤ 600 lines (runtime/catalog.ts data tables are an exception, architecture guide); runtime/py 167/167 files ≤ 1000 lines (architecture guide); the 13 runtime/py modules that were originally >1000 lines are split into a facade + same-domain impl package. Function budget: all 3,084 functions ≤120 lines, allowlist now empty (architecture guide).
- runtime: 133 TypeScript modules, 0 .mjs, 0 @ts-nocheck; explicit any across src + runtime = 0, enforced by both check:any and ESLint.
- addon: 69 modules, largest 558 lines; 69 entries in the zip (sha256 ff729426…); bl_info 1.11, protocol 11; 38 registered commands + ping = 39 wire.
- Tests: Vitest 80 files / 816 passed (2 skipped); among them unit 61 files/564 (2 skipped), integration 18/248, contract 29/324; pytest 337; addon-unit 108; real Blender native E2E 76 passed (10 deselected); GUI E2E 8 passed (2 skipped).
- Behavior matrix 346 rows (344 covered / 0 planned / 2 exempt), covering 15 tools / 38 commands / 34 families / 228 ops / 29 routes.
- C5 final tree (F6 amendment): JS 74.69 lines / 70.03 branches / 72.25 functions; changed lines 74.99%; Python pure 82.50 lines / 74.36 branches; critical and executionModules floors all pass.

### Fixes

- **A failed win32 backend child spawn no longer kills the host (#51)**: `spawnChild` explicitly passes `ELECTRON_RUN_AS_NODE=1` and `windowsHide:true`, and attaches an `error` listener before `unref()`; win32 residual backend cleanup goes through `runtime/win_proc.ts` (CIM → netstat/tasklist → taskkill /T /F), with `EADDRINUSE` self-healing recovery; the catalog probe got the same fix.

### runtime TypeScript migration

- The original 60 runtime/*.mjs files (7,307 lines) migrated to strict TypeScript, compiled to lib/runtime/*.js; T5b and finalization then split out headless, plan-dispatch, execution and other submodules, and runtime TS now counts 133 modules.
- SERVER_PATH points at lib/runtime/server.js; parsing functions were filled in at the JSON / subprocess / path / Python bridge boundaries; build order is runtime → host → client (architecture guide).
- The npm pack artifact contains lib/runtime/**/*.js and runtime/**/*.py but no .ts; both clean-clone and tarball-install smoke pass.

### CI, coverage and release engineering

- CI: .github/workflows/pr.yml (Node 22.17 + Python 3.11; typecheck/lint/format/build/structure/tests/matrix/pack + coverage). Real Blender E2E is currently a local release check and is not in CI yet.
- Manual CD: .github/workflows/release.yml (workflow_dispatch; dry_run defaults to true, publish_npm defaults to false; release environment requires human approval; draft Release; npm publish runs only after approval).
- The coverage gate passes locally; remote CI and canonical coverage calibration are still handled by T16a/T16c and are not declared verified before this release.

### Documentation and repository

- Added the architecture guide, tests/BEHAVIOR_MATRIX.md, tests/MIGRATION.md and four PR templates; the refactor spec, CI notes and evidence bundles live in the local refactor workspace and are not published with the repository.
- README / docs/zh/README / CONTRIBUTING / docs/zh/CONTRIBUTING / AGENTS / addon README all switched to zip installation; English AI docs stay English, Chinese user docs stay Chinese and both cross-link.

### Known limitations

- Remote CI has not run yet (T16a is still open); there is no v3.0.0 tag / GitHub Release / npm publish; release actions need human confirmation.
- The C5 global floor is still a conservative value, pending calibration with canonical CI data in T16c; runtime/py still has no pyright/coverage instrumentation; function-level large modules remain follow-up debt.
- Compatibility: Blender 4.2.10 is the only E2E-verified version, Blender 5.x is unverified; Node 22.17 is the test and CI baseline, Node 20 is unverified.

## v2.6.2 (2026-10-28) — Surface algorithms (surface_*) + docs/count consistency

> Model tools remain **15**; plan catalog grows to **34 family / 228 op** (+1 family / +11 op); addon remains **v1.10 / protocol 11**.
> This release **does not include** the experimental surface workbench (its panel/routes/modules were abandoned and never shipped).

### New: surface algorithm package (M0–M2 / M4)

- **`runtime/surface.py`** (pure bpy + numpy, no dependency on OCCT/geomdl/trimesh) adds 11 ops:
  `surface_loft / sweep / patch / tessellate / validate / export / blend / offset / fit / selftest / help`.
  - M0: SurfaceSpec validation and `spec_hash` (same spec + tessellation ⇒ same hash, same vertices);
  - M1: loft (interpolating B-spline through sections + Catmull-Rom in the hoop direction), sweep (parallel transport frames + twist + per-point scale),
    patch (tensor-product clamped B-spline), tessellate (spec→mesh / object→bake);
  - M2: G0/G1/G2 seam continuity, discrete curvature, BVH self-intersection, ray-cast approximate thickness, aspect ratio/flipped normals/watertight,
    `verdict = pass | fail | degraded`, **fail is never silently turned into pass**, degraded is not treated as a pass;
  - export: object → GLB; blend/offset explicitly return `ok:false` (M5 needs OCCT), fit keeps its interface (M3 not implemented).
- **Wiring**: `runtime/paths.mjs` SURFACE_PATH, engine `SURFACE_READY` + `surface_` prefix routing,
  a new catalog family, plan headless mapping (preload `surface,audit`), and `surface_help` added to the read-only allowlist.
- **On-device self-test** `tests/surface_selftest.py`: three benchmarks (bottle body/fender/helmet) + self-intersection/thin-wall/continuity negative cases +
  determinism + tessellate dual path + 7 classes of bad parameters; headless `preload="surface,audit"` all green (23 pieces of evidence).

### Documentation

- Added [docs/surface-algorithms.md](docs/surface-algorithms.md) (op table/SurfaceSpec/verdict/limits/integration chain);
- README (ZH and EN) each gained a "Parametric surfaces" feature and a docs entry point;
- The operating guide gained §3.5.6b Parametric surfaces;
- skill: SKILL.md §0.7 tool table + §0.7.1 surface algorithm loop (including hard rules), §9 family quick reference;
  added `skills/blender-modeling/references/surface-algorithms.md`, which install.sh fetches too; the skill README updates the references list.

### Fixes

- **Three silent misses in `scripts/sync_counts.mjs`**: the AGENTS regex only accepted "N <counter> family / N <counter> op" (after 2.6.1 dropped the counter word it could never match again, yet still reported "already consistent");
  it only refreshed the workspace AGENTS and not the in-repo AGENTS; a single replace only changed the first occurrence. Changed to both spellings + both AGENTS + `/g`,
  and added `docs/operating-guide.md` and `skills/blender-modeling/SKILL.md` as two more targets (this round measured both 33/217 sites refreshed to 34/228).
- Corrected the stale `33 family / 217 op` wording left in the skill / operating guide.

### Added (merged after v2.6.1)
- **headless: `opts.hardExit` (on by default)** — headless scripts explicitly flush stdout/stderr after the `done` marker,
  then call `os._exit(0)` to skip Blender's own exit teardown. Field case: Blender 5.2.3 (Steam), when a .blend loads a material with a
  Value→Material Output.Thickness link, the glTF export **succeeds, the artifact is complete, done has been printed**, and then
  during exit it hits an exporter AV (0xC0000005), so the result is pushed to "failure" by exitCode≠0.
  Callers that rely on normal teardown (`bpy.app.handlers` writes, delayed auto-save) pass `hardExit=false` for the old behavior.
  The job path and the sync path use one implementation (`runtime/hard_exit.mjs`);
  added `tests/headless_hard_exit_selftest.mjs` (ordering contract / toggle semantics / wiring assertions, already in the `npm test` main chain,
  `npm run test:hardexit`).
### Fixes
- **headless: a missing/empty/misspelled `file=` no longer silently succeeds** (old symptom: `file=""` or `blend=<path>` →
  `ok=true / exitCode=0 / inputFile=null / zero warnings`, and the script got the factory-empty scene):
  engine-side explicit `file=` validation (empty string→`file-empty`, non-string→`file-type`, the fallback for direct `/headless` calls);
  the tool side (`blender_rt_headless` / `blender_rt_job` op=start|run) intercepts misspelled parameter names (`blend=`/`path=` and four more)
  and empty strings — the tool side strips falsy values before assembling the body, so the engine guard never fires on the tool path, which is why ALIAS interception must live on the tool side.
  Behavior change note: `file=false` (boolean) used to be silently treated as "not passed"; it now fails explicitly as `file-type` — type discipline tightened,
  so anyone relying on the old semantics should omit the parameter instead.
- **headless: "succeeded but opened no file" is no longer silent** — the null branch of the `inputFile` receipt became a `{given, opened, reason}`
  semantic object (shape frozen: the truthy `fileFingerprint` return value is untouched); when no file was opened, `warnings` gains
  `no_input_file` (including the `.py` semantics-switch case); the ledger (headless/job running and terminal states) now also records
  `file`/`inputFile`, so after-the-fact forensics can tell "no file given" from "given but not opened".
- **headless: same-millisecond name collisions** — headless script names (`staging.mjs`, whose old `Date.now().toString(36)` overwrote each other within one millisecond)
  and stdout/stderr log names (`engine.mjs`, which appended to the same file within one millisecond and corrupted each other) both get a unique suffix (script name = ms + in-process
  sequence + random; log name = ms + runId).
- Added `runtime/file_guard.mjs` (engine / tool side / unit tests share one decision) and
  `tests/headless_file_guard_selftest.mjs` (41 checks, offline, already in the `npm test` main chain, `npm run test:fileguard`).

## v2.6.1 (2026-10-23) — Performance optimization (selection polling / audit / batch update) + platform and test fixes

> Changes merged after v2.6.0 are packaged as this release (including the dsh-TUI host half that an earlier PR labeled v2.7).
> Model tools remain **15**; plan catalog remains **33 family / 217 op**; addon remains **v1.10 / protocol 11**.

### Performance (measured on real production files)
- **Selection polling 1200 ms → 100 ms** (Web client + dsh-TUI host half): end-to-end p50 ~993 ms → ~156 ms
  (local loopback, 8 selection changes; CAS consume semantics unchanged).
- **`audit._tris` large-mesh fast path**: at ≥256 faces, batch `foreach_get("loop_total")`;
  137k faces 59.3 ms → 15.5 ms (3.8×), value-for-value equivalent.
- **Batch update steps 1/2**: added `K.dsh_kit.BatchUpdates`; `motion._restore_transforms` became
  "write all fields first → one update → verify together", restoring 300 objects on real production files 32× / 91×
  (planetary engine / space elevator), motion selftest 25/25.
- Measurement rejected "msgbus selection subscription": on Blender 5.2 `Object.select` is not an RNA property;
  selection changes keep using `depsgraph_update_post` (0.3–0.7 ms).

### Features (merged after v2.6.0)
- **#35 tool cards**: `presentCall` / `presentResult` for all 15 tools, so the host no longer renders a whole JSON blob.
- **#36 dsh-TUI host half**: selection context chip, footer status fields, `@` mentions, `/blender status|doctor|jobs`;
  enabled by seam capability detection, plus a new read-only `GET /host/state`.

### Fixes
- **#38 / #39 / #43 Windows console pop-ups**: three blender `spawn` sites + two `execFileSync` sites gained `windowsHide: true`,
  plus a static self-check `tests/windows_hide_selftest.mjs` (runs in `npm test`).
- **#40 / #41 capability lock**: the published tarball (no `src/`) no longer ENOENTs; it degrades the tool dimension and explicitly prints SKIP.
- **#42 capability lock families**: per-family reads now use the family name string + `full:true` detail, restoring the family-name / per-family op dimension;
  re-locked with `--update`.

## v2.6.0 (2026-10-21) — 33 family / 217 op · GUI first · headless fallback · docs and skill rewrite

> The four rounds of work after v2.5.0 (P0 / P1 / P2 + docs and skill rewrite) ship together in this release.
> Model tools remain **15**; plan catalog grows from 28 family / 186 op to **33 family / 217 op**.
> All new capabilities go through the plan catalog, **no new model tools**; GUI stays top priority; headless capabilities are filled in (including rt_see) as a fallback for no-GUI / batch / long-running work.
> **2026-10-21 wording correction**: this is not headless-first; by default open the GUI first, headless is only a fallback.

### Test and doc corrections (issue #32 / #33)

- **#32** `tests/linux_selftest.mjs`: a bare `import(path.join(...))` throws `ERR_UNSUPPORTED_ESM_URL_SCHEME` on Windows,
  which broke the `npm test` chain and silently skipped the 13 following cases → switched to `pathToFileURL(...).href`.
- **#33** `tests/workdir_shared_selftest.mjs`: C5 split POSIX-style paths with `path.sep`, which is always red on Windows
  → switched to `path.posix.basename(...)`.
- **Doc wording**: corrected the false statement that "the `/host/view/*`, `/host/pick*`, `/host/ready` routes are kept for compatibility" —
  those routes were already removed with the panel in v2.3; the host routes that exist are only `/host/selection` (+`/latest`, `/consume`),
  `/host/scene-items`, `/host/jobs` (+`/log`).

### Docs and skill rewrite (2026-10-21)

- **Full text pass**: README EN/ZH, the operating guide, the configuration reference, install/deploy/migration/AGENTS/CLAUDE all aligned to v2.6.0 (15 tools · 33 family / 217 op · addon v1.10 / protocol 11); removed the stale 28/186, v2.5/v0.9.x counts and the old "GUI is mandatory" promise.
- **Architecture-first skill rewrite**: SKILL.md now takes "the plugin is the modeling flow" as its main line (catalog → plan op → worker session → receipt/verdict → gate/delivery), and adds architecture iron rules, the standard state machine, a tool selection matrix, P0–P2 recipes, anti-patterns and the multi-Agent protocol; generic Blender knowledge is demoted to appendix A.
- **references corrected**: the acceptance checklist gains asm/visualreport/eval/mandatory gates; the reference-image SOP became img_digest/measure/calib + shapesolve + visualreport; multiview and the English overview now state their relationship to the current plugin.
- **Tool descriptions**: rt_do/rt_see/rt_watch/rt_worker/rt_headless/rt_plan now state GUI-first, session headless, worker see/watch/TTL, plan session=auto; package description synced to v2.6.0.
- Doc grep: user docs contain no stale 28/186/v2.5/v0.9.x counts; skill >50KB and skill_bundle_selftest 61/61; npm test all green.

### P2 third round (2026-10-20)

- **Assembly delivery export** `asm_export`: GLB/FBX/OBJ + manifest.json + append-only merge_ledger.jsonl; `merge=true` runs `asm_merge` first (gate+snapshot, no export unless the gate passes); 67 evidence items all green on device.
- **Low-risk repair policy** `asm_repair(policy=safe|manual|aggressive)`: safe only does translate/snap and hard-bans booleans; manual only plans and never executes; regression 88 evidence items all green.
- **Defect injection/baseline evaluation** `eval_run` (evalharness.py): assembly D1/D3/D4/D5/D7/D8 + reference 12 cases + calib core; missing modules are skipped/degraded, never faked as passing; assembly capture=1.0, reference 12/12, core degraded 0.875.
- **Seedance reference pack** `blockout_refsheet` (4 orthographic/perspective PNGs + 2x2 contact sheet + refsheet.json + optional turntable) + `blockout_turntable` (Blender built-in FFMPEG MP4/H264); 22 passed/0 failed; 256x256/12-frame MP4 9192B.
- **Headless watch** `rt_watch(session=...)` + worker `_watch`: per-frame Workbench offscreen + hash + up to 6 frame images; on device a 3-frame animation gave distinct=3/58ms.
- **Headless plan routing** extended to eval/blockout/asm and other families; on device `asm_export` 161ms, `blockout_refsheet` 331ms, `turntable` 334ms.
- catalog 33 family / 217 op; `npm test` all green; capability lock / read-only allowlist / counts synced.

### P1 second round (2026-10-20)

- **Assembly repair**: `asm_repair` + `fix_clash` (executor, dry_run by default) + `fix_interference` (read-only planner); a 2mm interpenetration dry run leaves the scene untouched → after execution clash=0/float=0/with snapshot; contained/boolean subtract/floating-block snap plans; 88 on-device assertions.
- **Mandatory gate/flow ops**: `gate_preflight / gate_checkpoint / gate_deliver`; `deliver_export(require_gate=true)` verified on device (writes only on pass, a bad gate is blocked; deliver+verify 18 checks).
- **Headless plan routing**: `blender_rt_plan(..., session="auto")` starts a persistent worker per family + preload + dispatch without depending on the GUI; first cold start ~2s, afterwards synchronously reused.
- **Session pool**: worker idle TTL (default 15 min, `DSH_WORKER_TTL_MS`) + `idleMs` in the receipt.
- **Same-viewpoint QC**: `visualreport_report` (verdict-first, three-level fallback qc→imgtools→numpy); 32/32; identical image passes, translation/missing corner fail, defect crop + mm localization, 72–96ms.
- **Headless contour fitting**: `shapesolve_solve` (orthographic analytic projection + numpy rasterization, no rendering); three-view inversion 40/20/30→error 0.98%/1.55%/0.35%, IoU [1,1,1], solve 793ms.
- catalog 32 family / 211 op; `npm test` all green; capability lock / read-only allowlist / counts synced.

### P0 first round (2026-10-20)

- **Interactive headless (key item)**: `rt_worker` supports `preload` startup preamble + `see` (temporary camera + Workbench offscreen) + `reset` + `warmup`; measured start 2.24s (including 1.1s first-frame initialization), afterwards exec 0–2ms and see round-trip 53–85ms (320×180), **not a job/async turn**.
- `rt_do` automatically falls back to a persistent headless worker when the GUI is unreachable or an explicit `session` is given (exec + see, images go straight back to the model); `rt_see` gained `session/auto`; `rt_loop` gained a `dsh_loop_sync` blocking inner loop via `target="session"` (20 iterations 56ms, no dependence on timers).
- `rt_headless` supports `attach_images` (true/"sheet"); `rt_plan` gained a single-line receipt.v2 envelope (verdict/top_defects/next) + `attach_images` (≤2 images), so the plan channel is no longer just 12KB of text.
- `imgtools.py` v2: added `img_digest` (native-resolution measurement/contour/Hough/holes/symmetry/readability/native crop/annotation + a confirmable number table), `img_probe`, `img_measure`, `img_calib`; 61/61 on-device assertions.
- Added `runtime/assembly.py`: `asm_scan` (all-pairs classification: clash/hidden_ok/contact/gap/float/contained/unresolved + extra testing for full containment), `asm_manifest` (md5/interface frames/allow validation), `asm_merge` (id-ordered append + normals + snapshot + automatic gate, dry-run by default), `asm_gate` (verdict-first, export_allowed only on pass); module self-check + test scripts all green.
- Added `runtime/blockout.py`: `blockout_base/batch/export` (declarative parts, mm/anchor, Workbench 3 views, GLB); 33/33 on device, 20 parts geom 9ms, 3 views at 512 about 1.1s (25ms/frame after the first), GLB 117KB.
- **Interactive headless on-device modeling test**: reference image→img_digest (2m×0.8m box: width 2000mm/height 800mm/px_per_mm 0.16)→12 white-box parts (GLB 70KB)→assembling two parts with 2mm interpenetration, scan detected depth=2mm/volume≈2.0e6mm³, and after moving 10mm apart clash=0.
- Catalog 30 family / 201 op; `npm test` all green; `capability.lock` / `plan_readonly.baseline` / provenance counts synced.

### Main line: seven field-measured feedback items — ledger reconciliation / 5.2 compositor / multi-light hygiene / progress channel / fifth state / non-coverage statement / two-dimensional write scope

**Source**: after one real 4-hour project with 3 subagents and 479 objects (a 120 m Godzilla + destroyed city + atomic breath),
the Lead and 3 subagents jointly retrospected 7 improvements; they landed in order, each with its own self-check.

1. **The ledger trusts the files (`runtime/recover.mjs`)**: after the backend restarts or is killed, the on-disk ledger may still say `status=running` with a dead pid,
   while **the child process actually finished long ago and the artifacts/logs are all there**. The old behavior always judged `stale`, so the model had to
   `Get-Process` + `ls` to crack the case itself (measured twice, each costing a round-trip). Now `reconcileLedger` first reconciles against the disk (`summary.json` → `resultPath` → stdout terminal states
   `DSH_STAGE done` / `HEADLESS` / `Traceback`), and on a match returns `status=done|failed` + `recovered:true` +
   `recoveredFrom/recoveredEvidence`; only a mismatch stays `stale`, with `evidence` / `evidenceChecked`.
   The ledger running records for run and job also gained `stdoutLog`/`stderrLog`/`dir`, so no directory scanning guesswork is needed after a backend restart.
2. **Blender 5.2 compositor migration (skill §6.5.6)**: added a 5-row pitfall table + a minimal runnable snippet —
   `scene.node_tree` is gone (use `compositing_node_group` + `NodeGroupOutput`; `CompositorNodeComposite` does not exist),
   Glare's Type/Quality became MENU sockets, `CompositorNodeMixRGB`/`CompositorNodeMath` were removed (use `ShaderNodeMix`/`ShaderNodeMath`),
   `mat.cycles.displacement_method` → `mat.displacement_method`, `surface_render_method` has only DITHERED/BLENDED.
3. **Multi-light hygiene**: detects `Shadow buffer full (N / M)` and produces a structured warning (`code=eevee_shadow_pool_full`, with count/usage/limit/a paste-ready fix);
   added a resident `K.light_hygiene(apply=True, max_shadow=4)` (keeps shadow casting only on the N highest-energy point/spot lights + sets the pool to 2048).
   Measured: 36 lights → the console spams an error every frame and `shadow_pool_size='4096'` is silently ineffective (the enum caps at 2048).
4. **Progress channel**: `dsh_progress(**fields)` / `DSH_PROGRESS {json}` is separate from stage (stage=stage transition, progress=high-frequency progress within a stage, keeping the latest 20);
   a 5 s heartbeat during the run (`heartbeat`: elapsedMs/logBytes/lines/stage/progressAgeMs, and jobs also append `heartbeat.jsonl`);
   `op=status/collect` and headless receipts all carry `progress/progressAt/heartbeat/progressHistory`.
5. **`audit_mesh` fifth state `pass_multi_shell`**: multi-shell parts are no longer uniformly `degraded`. The criterion became "each shell closes on its own + winding is consistent + volume sign is provable",
   so AABB intersections (debris clusters/fireball scales/set multi-shell pieces) no longer equal "cannot tell"; legitimate cavities are still exempted as `nested`.
   The object `state` stays `pass` (with new `multi_shell`/`state_detail`), and totals gained `normals_multi_shell`.
   Measured: two separate shells/nested cavity → `pass_multi_shell` + `clean=true`; a true interpenetration still fails as self-intersection.
6. **catalog non-coverage statement**: the `catalog` default page and `args={handoff:true}` both explicitly state that "creature/organic modeling, cinematic lighting/volumetrics/compositing, character animation rigging" are not covered,
   saving the exploration cost of "I cannot find a tool here" (handoff still respects the 3500-character cap).
7. **Two-dimensional write scope (collection + object prefix)**: `blender_viewport op="lease" scope="collection:COL_Lights,prefix:LGT-"`;
   it is visible in `/who`, `/lease` and the 409 receipt (`holderScope`); a bare token is inferred from its shape (`COL_*`→collection, containing `-`/`*`→prefix).
   Accompanied by a resident `K.route_collections(rules=None)`: routes lights/cameras/individual assets into COL_Lights / COL_Camera / COL_VFX / … by prefix
   — when a subagent has write permission only for a single collection, name by prefix and route in one line before assembly.

#### Self-checks (4 new cases)

- `tests/ledger_recover_selftest.mjs` (18 assertions, pure logic)
- `tests/ledger_recover_e2e_selftest.mjs` (10 assertions, independent backend + real headless: three-state reconciliation + progress + heartbeat)
- `tests/scene_hygiene_selftest.mjs` (8 assertions)
- `tests/lease_scope_selftest.mjs` (6 assertions, independent backend HTTP contract)

#### Compatibility

- Receipts only **add fields** (`recovered` / `progress` / `heartbeat` / `warnings` / `scope`), old field semantics unchanged;
- `stale` semantics kept: when no terminal evidence is found it is still judged `stale` (no false claim of completion);
- The host side `lib/index.js` is synced (recovered/progress wording, lease scope parameter), and **DSH must be restarted after upgrading**; backend-only changes can use `blender_viewport op=restart`.

## v2.5.0 (2026-10-20) — N-panel rearrangement (activity pinned on top / environment & model API sub-panels) + pause AI operations (addon v1.10)

**Source**: the user asked to move the activity status to the top, merge the asset library and AI Model Generation into an "Environment & Character Model API Calls" parent panel
(two sub-panels, environment generation / model generation, both collapsed by default), show a warning during AI operations, and add a "Pause AI operations" button; a few icons were dropped along the way.

- **Activity status pinned on top**: the first block of the N panel is the activity status; for `agent` / `both` it shows an `alert` red warning "AI is operating Blender".
- **Pause AI operations**: added the scene property `dshbb_ai_paused` + the button `dshbb.toggle_ai_pause`;
  once paused, the socket only lets read-only commands through (`ping` / `get_*` / `drain_human_activity` / `describe_node_type` / `bpy_api_lookup`),
  while write operations such as `execute_code`, asset download/generation/import return `AI_PAUSED`; `get_activity_state` carries a `paused` field.
  Only a human can resume, by clicking "Resume AI operations" in the Blender panel (the model cannot lift it itself).
- **New panel**: `Environment & Character Model API Calls` (parent, collapsed by default) → `Environment generation` (Poly Haven / Sketchfab / Poly Pizza) +
  `Model generation` (Hyper3D / Hunyuan3D / Tripo, including Premium status); the parent and both sub-panels are all `DEFAULT_CLOSED`.
- **Icons removed**: integration titles in the new panels, the environment-generation URL, model-generation buttons and so on no longer carry decorative icons; the activity status only has an icon when it is a warning.
- State changes are driven by a 0.5 s timer that triggers an N-panel redraw (no longer only refreshing on mouse movement).

## v2.4.0 (2026-10-19) — Sub-element selection + resizable N-panel lists (addon v1.9)

### New feature: edit-mode / pose-mode sub-elements enter the selection record

**Source**: the user asked "besides meshes, which of these types in the Add menu can be recorded?" → "include edit-mode sub-elements / bones in the selection record too".

- addon `build_selection_payload` gained `selection.sub`:
  - `MESH`: `counts` (vertices/edges/faces) + `indices` (three index arrays, each capped at 2000) + `select_mode` (current vertex/edge/face mode);
  - `ARMATURE`: selected bone names from edit mode `edit_bones` / pose mode `pose.bones` (cap 500);
  - `CURVE` / `LATTICE`: control points `(spline_index, point_index)` or point indices (cap 2000);
  - other edit modes (text/grease pencil) carry only `type:"OTHER"` + `note`, never faking element semantics;
  - `truncated` truthfully marks truncation.
- Backend `runtime/selectionstore.mjs` gained `sanitizeSubSelection`: allowlists types, filters non-integers/negatives, clamps caps again;
  unknown types fall to `OTHER`, and a missing object name is dropped outright.
- The Web client's `selectionMessageText` generates the sub-element draft text (meshes give counts + index samples, armatures give bone names,
  curves/lattices give control points); the full arrays can be queried with `blender_rt_cmd get_selection`.
- N panel: in edit/pose mode it shows "Sub-elements: edit mode (mesh) · Cube", and expanding the list adds rows such as "vertices 12 / edges 3 / faces 7 / Bone.001".
- Known boundary: sub-element changes **do not enter the activity fingerprint** (activity is still judged on the object-level selection); large meshes are not scanned every tick.

### Same-release UI: N-panel lists collapsible + scrollable + adjustable height

**Source**: user feedback "is this list resizable, collapse or hide as much as possible" → "the height should be adjustable, not fixed".

- The object list / collection member list became **Blender UIList**: built-in scrollbar, so a lot of content no longer spreads into one long column.
- **Adjustable height**: expanding reveals a "Height (rows)" slider (`dshbb_list_rows`, 3–30, default 8) + "− a bit shorter / + a bit taller" buttons;
  `template_list(..., maxrows=30)`.
- **Collapsible**: both lists start collapsed; clicking `Objects / sub-elements list (N) ▸` / `Member list (N) ▸` expands them; the properties
  `dshbb_show_selection_list` / `dshbb_show_collection_list` (default `False`).
- **Draw stability**: list data is now synced from timer / property update callbacks, no longer writing ID data inside `draw()`;
  panel draw exceptions are written to `dshbb_last_panel_error` (for diagnosis, normally empty).
- The backend address / overrides moved into a collapsible "Backend / Advanced" (`dshbb_show_advanced`, hidden by default).

## v2.3.0 (2026-10-19) — Blender native selection → DSH · unified human/agent activity determination (addon v1.8)

**Source**: user ruling — "add an 'operating' determination on the bl plugin side, and move the current DSH selection feature to the Blender plugin side".
Confirmed wording: **B. Blender N panel "send selection to DSH"** + **C. unify the two activities human / agent into one state**.
**Conclusion**: selecting objects no longer relies on clicking a low-res screenshot in the DSH panel — select in Blender's native selection and press the N-panel button to drop it into the current DSH session draft
(**no automatic send**); the Blender side also reports the four states `idle / human / agent / both`, shown live in the panel and queryable by the model.
**Removed in the same release** (explicit user request): the DSH-side viewport panel (Web sidebar + TUI sidebar), click-to-message, and model-requested picking `blender_rt_pick`
— model tools **16 → 15**; the backend `/host/view/*`, `/host/pick*`, `/host/ready` routes are kept but have no UI consumer in this repo.
**Two modes**: N panel `dshbb_selection_mode` switches between "**multi-select**" (send the currently selected objects) / "**collection**" (send the whole group, for large assemblies).

### New · addon v1.8 (protocol number still 11, backward compatible)

- **`ActivityTracker`** (main thread, local determination, **independent of telemetry consent, never uploaded**):
  - human signal = `bpy.context.window.modal_operators` non-empty (drag/transform/menu etc., continuously valid) + a human operator within the last 1.5 s
    (including view3d navigation, suppressed during agent commands) + undo/redo + native selection/active object/mode changes (1.5 s window);
  - agent signal = an agent command is executing (`agent_depth>0`) or the last command ended ≤1.5 s ago;
  - when an agent command ends, the selection fingerprint is invalidated ⇒ the tool's own changes are never misreported as "human operation".
- **5 resident commands** (into `capabilities`, resident 19 → **24**, total commands 34 → **39**):
  `get_activity_state` (four-state snapshot; **the query itself is not counted as agent**) · `get_selection` (native selection: name/type/active object/mode/scene) ·
  `send_selection_to_dsh` (POSTs the §S1.3 payload to the backend; the button and the command share one implementation) ·
  `get_collections` (scene collections + object count + selected count) · `send_collection_to_dsh` (send the whole group; no picking one by one for large assemblies).
- **New N-panel section "Selection → DSH"**: activity status row (human/agent/both/idle) + last human action + **mode switch (multi-select / collection)** +
  the selection summary and "Send selection to DSH" in multi-select mode / the collection dropdown (`dshbb_collection_target`) and "Send collection to DSH" in collection mode +
  the last send result + the backend address (overridable via the scene property `dshbb_backend_url` / env var `DSH_BLENDER_BACKEND_URL`).
- **Large-assembly convergence**: in object mode the draft text lists at most 24 names (beyond that it says "N items total"); in collection mode it only gives "collection name + item count + the first few members" —
  no more flushing 200 object names into the input box.
- **Both Blender-side modes completed (user request)**: multi-select mode shows a **scrollable object list** in the N panel (name + type, up to 30 rows);
  collection mode shows a **member list + item count + sub-collections + current selected count**; when switching to collection mode the `update` callback infers the most relevant collection automatically,
  plus a ⟳ button (`dshbb.use_selection_collection`) to re-infer at any time.
- On-device measurements: modal probe `human_active=true` + `modal_operators=[DSH_TMP_OT_modal_probe]`; after the modal ends it returns to `idle`;
  panel button → backend `seq` grows → the browser draft receives text (`last_consume {ok:true,how:"actions"}`);
  the collection commands `get_collections` / `send_collection_to_dsh` work on device; the other commands of the old v1.7 addon are unaffected.

### New · backend `/host/selection` (memory only, zero Blender round-trips)

- `runtime/selectionstore.mjs`: payload sanitization (names ≤200 / objects ≤50 / strings ≤200 chars) · `seq` / `consumed_seq` only increase ·
  `consume` idempotent + invalid seq 400 · `last_consume` records the client insertion result (answering "why is the draft empty after clicking the button").
- 3 routes: `POST /host/selection` (addon push, **does not validate the write lease**) · `GET /host/selection/latest` (carries a payload only when unconsumed) ·
  `POST /host/selection/consume` (may carry `{ok,how,reason}` diagnostics).
- `tests/selection_store_selftest.mjs` (wired into `npm test`): **53 assertions** covering sanitization / seq / consume / diagnostics / collection payload.

### New · Web-client half: headless bridge `conversation.input.dock`

- Registers id `blender-selection-bridge` (session scope, renders null, **still receives while the panel is collapsed**), polling latest every **1200 ms**.
- Inserts into the current session draft: prefers `inputActions.insertText` (appendable, keeps user content); falls back to `SessionInput.setDraft` only when the draft is empty;
  **no automatic send**. Only a successful insert triggers `consume {ok:true,how}`; on failure it does not consume, and after 3 retries it consumes and returns the reason.
- **Does not skip based on page visibility**: the user may click the Blender button and switch back to DSH immediately; polling costs zero Blender round-trips.
- `tests/client_bundle_selftest.mjs` rewritten as the v2.3 slim version: **46 assertions** (bundle shape / no leftover panel / @ codec / selection text (object/collection/large-list convergence) / three insert paths / dock registration).
- Removed `src/tui-panel.ts`, `tests/tui_panel_selftest.mjs`, `docs/tui-adaptation.md`; capability lock 16 → 15 tools.

### Docs / contracts

- Single source of truth for the new contract: [`docs/host-integration-interface-contract-v2.3-addendum.md`](docs/host-integration-interface-contract-v2.3-addendum.md) (§S0 background · §S1 addon commands and payload ·
  §S2 the three routes · §S3 client insertion · §S4 criteria S1–S8 · §S5 known boundaries).
- README (EN / zh-CN): added §4.3 "Blender native selection → DSH" + the four-state table + prerequisites (addon v1.8 + restart DSH) + a note that TUI is unsupported;
  command-surface counts 34→37 (resident 19→22); version v2.3.0.
- The operating guide gained §11 (steps / troubleshooting / acceptance); `AGENTS.md`, `llms.txt`, `addon/README.md`, the third-party install checklist and the configuration reference synced.
- Version synced in three places **2.3.0** (`package.json` / `PLUGIN_VERSION` in `src/index.ts` / the rebuilt `lib/`); **addon 1.8**.

### Acceptance (measured, 2026-10-19)

- `npm test` **exit 0** (selection_store + client_bundle newly added); `client_bundle_selftest` all pass; schema budget still ≤12,000.
- On device: after reloading addon v1.8, `get_addon_info` returns `[1,8]` and capabilities include the three new commands; `get_activity_state` reports `idle` when idle,
  `agent` after a command, and `human`/`both` when simulating human operation/modality (measured `last_human_kind=selection` / `modal:…`).
- End to end: select Cube+Camera in Blender → panel button → backend `seq` → **the current session draft receives text**;
  `/host/selection/latest.last_consume` returns `{ok:true, how:"actions"}` (a real Web client inserted successfully).
- Packaging: **1.3 MB / 142 files** (v2.2 was 1.5 MB/161; removed the TUI panel + viewport/pick routes + old addon adaptation/docs/tests; added selectionstore/contract/tests; the 8 files under `skills/blender-modeling/` are still in the package).
- **Cleanup (v2.3 slim-down)**: removed support for the old `MCP for Blender` / harveyxiacn category-action addon, the dual-name fallback and the `addonProtocol` setting;
  removed the `/host/view/*`, `/host/pick*`, `/host/ready` routes and `runtime/{viewstore,pickrequest,host_presence}.mjs`;
  removed the `blender_rt_pick` tool, the Web/TUI viewport panels, `tests/{tui_panel,protocol,pick_presence,host_cors,acceptance_v093}_selftest.mjs`;
  removed the historical contract documents (v1.2/v2.1/v2.2), the upstream integration/rename-plan/assessment documents, and the `tmp/` and `.bak` backups.

### Unverified / known boundaries

- **DSH must be restarted** (the client half is a module loaded at startup); during development HMR may hot-load it, but a formal upgrade is gauged by a restart.
- **The DSH viewport panel is gone**: old users' sidebar tab disappears (the code no longer registers it); routes such as `/host/view/*` still exist but have no UI.
- **The user must be told after install**: `docs/ai-installation-prompt.md` §3.5 already requires installation-type AIs to proactively introduce native selection / the two modes / activity / removed items.
- **addon compatibility matrix**: the upstream `MCP for Blender` (`blender_mcp`) can still use the model tools, but **has no** v2.3 selection/collection/activity;
  both addons occupy 9876 and cannot be enabled at the same time. Already written into README §2 / `addon/README.md` / the AI installation prompt.
- **TUI does not support draft insertion yet** (no composer dock; consistent with the existing boundary that `sendToChat` is not authorized).
- The bridge only writes to the **currently open session**; in the extreme multi-tab case the same selection may be inserted once per tab (the server's `last_consume` keeps the last one).
- The host panel cannot refresh per frame outside Blender's main thread (the panel display updates with Blender redraws).

---

## v2.2.0 (2026-10-19) — skill merged into the plugin repo: shipped in the package + auto-registered on load

**Source**: user question — "merge this blender-modeling skill into the blender plugin repo; many people don't look at the github homepage and don't download this skill".
**Conclusion**: the skill no longer requires users to download it from a separate repo / symlink it; once the plugin is installed and DSH restarted, `blender-modeling` appears automatically in the session skill catalog.

> **This release also includes (merged from upstream main, PR #23–#26)**: dsh-TUI adaptation — the `ctx.tuiPanels` sidebar "Blender viewport" panel +
> picking (automatic no-op on Web / headless; fails fast when no panel is polling), see README §4.2 and `docs/tui-adaptation.md`,
> `docs/host-integration-interface-contract-v2.2-addendum.md`. This skill commit was rebased on top of that TUI work and released.

### New · bundled skill (source of truth moved into this repo)

- Content merged into [`skills/blender-modeling/`](skills/blender-modeling/): `SKILL.md` + 4 `references/` + MIT `LICENSE` + `NOTICE.md` + bundled `README.md`
  (the standalone repo `dsh-skill-blender-modeling` is kept as a mirror for non-DSH hosts, with content synced to this directory).
- Host-side `apply()` registers the bundled provider **when the host has a `skills` service**: `ctx.inject(['skills'], cb)` mounts it lazily,
  and skips when the service is absent; **any registration failure only warns and does not affect the 16 tools** (skills are an add-on capability).
- provider wording: `source: "bundled"`, `rank = 600` (same value as `@deepseek-ai/dsh-skill`'s `BUNDLED_SKILL_RANK`);
  candidate / definition are built to the DSH skill registry contract, and `resourceBase` points at the in-package skill directory ⇒ relative paths to `references/*.md` can be read directly.
- **Priority**: in DSH rules a lower rank wins ⇒ a copy the user installed under `~/.dsh/skills` (user-level rank 400) overrides the bundled copy (600),
  so old users are not force-updated; uninstalling the plugin removes it automatically (no need to clean the user skill directory).
- No new runtime dependency: frontmatter uses ~20 lines of hand-written parsing (only `name` / `description`), no `yaml`, no import of the host's `@deepseek-ai/dsh-skill`.
- Packaging surface: `package.json.files` gains `skills`; tgz **1.5 MB / 161 files** (v2.1.0 was 1.3 MB / 144 files).

### New · regression gate

- Added `tests/skill_bundle_selftest.mjs` (wired into `npm test`):
  asset tree / frontmatter / no `.bak` / `files` packaging surface / provider shape in lib / frontmatter parsing boundaries /
  the three fake-ctx registration paths (`inject` / direct mount / no skills service) / **real `SkillRegistry` integration** (runs only when the host is found: `list`/`get` full chain + user-level rank 400 overriding bundled 600).
  Local machine **61/61 PASS**; an environment without the host package explicitly skips the real-registry integration section (57 assertions, including 4 thenable assertions carrying `AbortController.signal`).
- **P0 found on review (fixed the same day)**: the provider's `list` / `get` originally returned arrays / objects **synchronously**; the host's `waitWithAbort()` calls `.then(...)` on the return value when the caller passes a `signal`
  (every model-side lookup carries a signal) ⇒ `TypeError: promise.then is not a function`, the provider was **silently skipped**,
  and the skill could not actually load (tests without a signal happened to bypass it). After switching to `async`, assertions with `AbortController.signal` were added to the selftest (reproduce the failure first, then verify the fix:
  a `snapshot` with a signal hits, and `get()` returns the 103,925-character body).
- Implementation detail: the v2.2.0 code block sits **after** `apply()` (function declarations are hoisted, behavior unchanged) — if it were inserted after `registerSchemaDiagnostic`,
  it would disturb `discoverability_selftest`'s schema character-fragment splitting for `blender_viewport` (that check depends on relative position),
  misreporting the budget as 12,317. After the adjustment the schema budget stays **11,995 / 12,000**, and **this gate was not relaxed**.

### Docs

- README (EN / zh-CN): "Companion skill" became "Bundled skill (auto-registered on load)", §1 gained a bundling note, §3 installation gained "after restarting DSH the skill directory appears automatically";
  Releases tgz info updated to 2.2.0 (1.5 MB / 161 files).
- `AGENTS.md`: packaging health values updated; a new convention "bundled skill source of truth = `skills/blender-modeling/`".
- Version synced in three places **2.2.0** (`package.json` / `PLUGIN_VERSION` in `src/index.ts` / the rebuilt `lib/`).

### Acceptance (measured, 2026-10-19)

- `npm test` **exit 0** (including the new skill_bundle_selftest).
- Real host `SkillRegistry` integration: `ctx.skills.list()` hits `blender-modeling` (`source=bundled`) · `get()` loads the 103,925-character body ·
  `resourceBase` points at the in-package directory · a simulated user-level copy (rank 400) successfully overrides the bundled one (600).
- **With `AbortController.signal`**, the real registry's `snapshot` / `get` pass on device (before the fix: snapshot empty, get threw `TypeError`).
- `npm pack --dry-run`: **1.5 MB / 161 files**, all 8 files under `skills/blender-modeling/**` are in the package.

### Unverified (needs a DSH restart and user confirmation)

- Whether the skill directory shows up in the **first message**'s available-skills list in a real DSH session (this session supplies the same skill via a user-level symlink, so the bundled path cannot be verified without a restart).
- If a user keeps a user-level copy at the same time, the DSH log shows a "higher-priority skill already exists" note (expected behavior, not a fault).

---

## v2.1.0 (2026-10-16) — Panel zoom/pan · multi-select parts at once · headless job area

**Source**: user questions — ① parallel modeling by multiple subagents uses headless, "how do I watch it"; ② "can I select multiple parts at once"; ③ "can I zoom/pan the viewpoint inside the browser tab's blender viewport" → ruling "do all of them".
**Single source of truth**: `docs/host-integration-interface-contract-v2.1-addendum.md` (§8.1 zoom/pan · §8.2 multi-select · §8.3 job area · §8.4 criteria 18–26).

### New · panel zoom/pan (§8.1, client-side only)

- `{zoom∈[1,8], tx, ty}`: the **wheel** zooms anchored at the cursor, **press-and-drag** pans, **double-click or "⟲ N×"** resets
- **Implementation note**: the transform is applied to the **container wrapping the img**, while the click handler reads the img's own `getBoundingClientRect()` —
  **ancestor transforms count into that rect** ⇒ under pure scale+translate `(clientX-rect.left)/rect.width` **still equals the in-image ratio exactly**,
  **no hand-written inverse transform needed** (cheaper and less error-prone than the contract §8.1 formula)
- The selection marker sits in the same transform container as the img ⇒ **the marker does not drift** when zoomed; dragging past 3px suppresses the following click ⇒ "a little pan" does not accidentally pick an object
- `AUTO_CAPTURE_MAX_SIZE` **1000 → 1600**: this is the precondition for zoom to be **meaningful** (otherwise you only enlarge a low-res image and still cannot hit small parts)

### New · multi-select parts at once (§8.2)

- Backend: `request{multi:true}` → a hit on `answer` **accumulates deduplicated by name and stays pending** (returns `{ok:true,state:"pending",added,objects}`);
  an empty hit `{ok:false,state:"pending",error:"empty"}` **does not end it**; only `answer{done:true}` makes it `answered` (objects frozen);
  added `POST /host/pick/remove`; `GET /host/pick/result` returns `objects` in both modes; cap `PICK_MULTI_MAX=200`
- Panel: a "multi-select" toggle (repeated clicks accumulate, clicking an item again deselects it, an empty click **does not clear**), the selected list (each item has "✕" to remove),
  "**add to message**" inserts all names at once; a model-initiated multi-select request shows "**Done(N)**" — the **only** path that can end a multi-select request
- Tool: `blender_rt_pick` gained a `multi` parameter; in multi-select it returns an **array of object names** and lists them line by line
- **Single-select semantics unchanged word for word** (§7.2): an empty click still yields `answered` + `object:null`, regression verified

### New · headless job area (§8.3)

- **Why it is needed**: `blender_rt_headless` / `blender_rt_job` run an **independent `blender -b` process** (its own scene, never touching the GUI)
  ⇒ the viewport and panel **never have a picture** (architecturally inevitable, not a defect). The job registry lives in the **backend process**, so two **read-only** `/host` routes suffice
- `GET /host/jobs?limit=` → `{ok,jobs,running,total}` (running first, the rest by elapsed time descending); `GET /host/jobs/log?id=&tail=`
  → `{ok,id,stdout,stderr,job}` (unknown id → `ok:false,error:"unknown_job"`)
- The data source **reuses** `engine.job.list/status/collect` (no re-creation); `trimJob()` trims large fields, `resultJson` >8 KB is truncated and `resultTruncated` is set
- The panel's "Jobs" area: state (● running / ✓ done / ■ terminated), stage, elapsed time, **quiet time** (to tell "stuck" from "still running"), line count;
  clicking a row expands the log tail (max height 160px, scrollable); **polls every 2 s only while something is running, 10 s when fully idle**

### Acceptance (measured, 2026-10-16)

- `npm test` **exit 0**; `capability_lock` **PASS** (28 family / 186 op / **16 tools**); the client bundle self-check all green
- **The description budget gate held, not relaxed**: after adding the `multi` parameter it briefly hit **12 023 / 12 006 > 12 000** ⇒ **the wording was tightened instead** (final ≤ 12 000),
  rather than relaxing this gate (a rule set in v1.2)
- Backend state machine unit tests **19/19**: accumulation / dedup by name / `remove` / `done` freeze / cap 200 / superseded keeps the existing selection / **3 single-select regressions**
- On-device full chain: `request(multi)` → `answer` (empty click, still pending) → `remove` → `done` → `answered`; the single-select empty-click receipt is **word-for-word identical** to v1.2
- `/host/jobs` **zero Blender round-trips**: over 20 polls the `metrics.calls` delta is **0**; clamp `0/-5→1`, `99999→100`, invalid→default 20
- Version synced in three places **2.1.0** (`package.json` / `src/index.ts` / the rebuilt `lib/`)

### Unverified (needs a DSH restart and user confirmation)

- The **real feel** of in-panel zoom/drag, the **actual value** `getBoundingClientRect` returns in the right sidebar, and the **layout** of the job area in the real panel
- The client half and the new tool surface are only loaded **after a DSH restart**

---

## v2.0.0 (2026-10-16) — Rename: remove upstream brand traces (addon `MCP for Blender` → `DSH Blender Bridge`)

**Source**: user ruling — ① rename the Blender-side addon the plugin depends on as well (file name / display name / identifier prefix); ② remove the upstream project name from the protocol discriminator id (`ahujasid` → `flat`); ③ rewrite history + force-push.
**Single source of truth**: `docs/rename-plan-remove-upstream-traces.md` (word-for-word naming map).

### Rename surface

- **Blender-side addon**: `blender_mcp.py` → **`dsh_blender_bridge.py`**; `bl_info["name"]` `MCP for Blender` → **`DSH Blender Bridge`**; identifier prefix `blendermcp_` → **`dshbb_`** (34 deduplicated identifiers, including the registered class `bpy.types.dshbb_server` and 5 integration toggles). **The copyright notice and MIT license text are kept verbatim** (only the display name and identifiers changed).
- **Plugin-side protocol id**: `'ahujasid'` → **`'flat'`**; legal values of `addonProtocol` are `auto|flat|category-action`, with **`ahujasid` kept as a deprecated alias** (normalized to `flat`, so old configs do not blow up).
- **Protocol display labels neutralized**: `ahujasid / MCP for Blender (…)` → `direct addon · flat protocol (no framing)`; `harveyxiacn blender_mcp_addon (…)` → `direct addon · category-action (newline framing)`.
- **Compatibility (mandatory)**: the plugin does **dual-name probing** for addon identifiers (try `dshbb_*` first, fall back to `blendermcp_*`; same for `bpy.types`) ⇒ it connects both before and after the addon rename.

### Docs and migration

- Added the **v2.0.0 migration notes** (see [`MIGRATIONS.md`](MIGRATIONS.md)): rename essentials · you must **re-enable `DSH Blender Bridge`** in Blender preferences (the old `blender_mcp` record is a dead reference) · the old `ahujasid` config still works · upgrading the upstream addon later reverts to the original but **the plugin's dual-name fallback still works**.
- The install guide / configuration reference / README ×2 / `llms.txt` / `AGENTS.md` / `SECURITY.md` all use the new name; the install steps in `docs/operating-guide.md` §1.1 and `docs/deployment-sop.md` §3 are updated and still executable.
- **Kept (the user chose not to strip attribution; MIT compliance)**: the upstream provenance / comparison narrative in `docs/upstream-integration-assessment-mcp-for-blender-and-blend-ai.md` (file name included) and `docs/host-integration-layer-assessment-codex-plugin-and-dsh-port.md`, the source entries of this CHANGELOG, and the MIT provenance comment in `runtime/viewstore.mjs`.

### Acceptance (measured, 2026-10-16)

**addon side** (three copies: Windows live file / workspace v1.6 / plugin tmp v1.7)

- All three pass syntax checks; the Windows artifact is **byte-identical under `cmp`** to `tmp/dsh_blender_bridge.py` (md5 `d3197a75…` / v1.6 `6f0d36ef…`)
- **Brand residue zeroed**: `blendermcp` / `MCP for Blender` / `BlenderMCP` = **0**; the remaining hits are **v1.7 = 11 lines, v1.6 = 8 lines, 100% allowed positions** (the 9/6-entry env-var compatibility fallback tables + attribution lines)
- **Identifier conservation**: v1.7 **34 → 34**, v1.6 **25 → 25** (differing only by prefix one by one); changed-line count conserved (`modified` == lines containing key strings − allowed retained lines: 267 / 190, `deleted = 0`) ⇒ not a single unrelated line touched
- **Attribution identical line by line**: v1.7 7 lines / v1.6 5 lines (file-header copyright, `bl_info["author"]`, `terms_url` etc.)
- **Env-var fallback measured behaviorally** (not inferred from reading code): all 9 / 6 entries pass "unset → None · new name only → new value · old name only → falls back to the old value · both present → new name wins"

**plugin side**

- `npm test` **exit 0**; `protocol_selftest` **28 → 39 items** all green (new alias normalization / shared cache / dual-name fallback / new-name-wins assertions); `capability_lock` **PASS** (28 family / 186 op / 16 tools)
- On device (Blender running, the addon on disk already renamed while **the running session still has the old identifiers**): `/doctor` → `kind=ok`, `protocol=flat`, `protocol_label` a neutral string; `/host/ready` → `{"ok":true,"ready":true,"protocol":11,"backend":"2.0.0"}`
- **The dual-name fallback is the production path**: all `dshbb_use_*` missing, all `blendermcp_use_*` present ⇒ the fallback branch is genuinely executed; `/commands` gates already use `dshbb_use_*` as keys while **behavior is word-for-word unchanged** (19 available / 15 disabled)
- **Loosening the name heuristic was necessary**: the running module name is already `dsh_blender_bridge`, which the old `"mcp" in name` filter would **miss** (on-device counter-proof: `dsh_blender_bridge` is `false` under the old wording and `true` under the new one)

**History rewrite**

- main `1875b79…cc79b72` force-pushed (all 82 commits rewritten); **16 tags** (v0.4.0–v1.0.5) rewritten to the corresponding new commits and force-pushed (annotated tags keep their tagger and message)
- **Verified**: in `git rev-list --all` only **1 commit containing a brand string remains = HEAD**, and it falls entirely in §4's allowed positions (81 ancestor commits: `MCP for Blender` 0 / `blendermcp` 0; 16 tags: 0)
- HEAD content **tree `baa3d447…` unchanged byte for byte** (allowed positions intact)
- ⚠️ **Not cleaned**: GitHub-managed `refs/pull/*` (old PR #2/#5/#9/#13) still point at pre-rewrite commits — a push cannot delete them, so the PRs must be deleted on GitHub

---

## v1.2.0 (2026-10-16) — New: right-sidebar viewport panel (**appears only when the channel is available**) · model asks the user to pick (`blender_rt_pick`)

**Source**: user ruling — ① the panel should not be resident (do not take up space when not modeling), change it to "appears only once enabled"; ② the model should be able to proactively ask "which one is it? click it".

### New · the panel moves to the right sidebar and only appears when the Blender channel is available

- **Seat**: changed from `conversation.view` to a **right-sidebar tab** (`sidebar.right.pane.tab`, keyed/session slot)
- **Gating**: added a **cheap readiness endpoint** `GET /host/ready` (the client polls it every **2 s**). Only `ready:true` registers the tab type and body
  — both phases are wrapped in `ctx.effect` ⇒ **unregistering makes it disappear**; flipping to `false` disposes it and closes the tabs it opened
- **Auto-open**: on the `false→true` edge it auto-calls `openTab`, **bookkept per session** (repeated flips in one session open it once; after the user closes it manually it does not pop up again)
- **Degradation**: if the host has no `sidebarRight` (older version) → fall back to `conversation.view` and say so in the panel

### New · model asks the user to pick (the 16th tool `blender_rt_pick`)

- Five backend routes: `POST/GET /host/pick/request`, `POST /host/pick/answer`, `POST /host/pick/cancel`, `GET /host/pick/result`
- **At most one** pending globally; a new request marks the old one `cancelled`/`superseded`; `expired` is **evaluated lazily**; the last 8 terminal states are kept
- **`answer` and `/host/view/pick` share one implementation** (`hostPickCore()` was extracted so two copies cannot drift later)
- **A mismatch does not end the request**: `scene_mismatch` / `unknown_seq` → the request **stays pending** (the user refreshes and retries);
  a hit or an empty click → `answered` (**an empty spot = the user explicitly says "none"**)
- The tool **blocks** waiting: polls every 400 ms, returning the object name on a hit (`bpy.data.objects[...]` is directly usable);
  **responds to host cancellation** (abort → `cancel(reason:"aborted")` then exits quickly); `isConcurrencySafe:false` (one global request)

### Fixes · two real bugs

1. **The first `/host/ready` took 36.7 ms** (14× slower than `/health`) — the root cause was **not the route logic** but `engine.mjs`'s
   **trajectory wrapper**: it was not in `TRAJ_SKIP`, so **every poll did `fs.appendFileSync` to the drvfs mount** (~35 ms per synchronous write on this machine).
   After adding it to `TRAJ_SKIP`, **36.7 ms → 1.19 ms**. ⚠️ For an endpoint that "the panel polls every 2 s" this is fatal (slow and it floods the ledger);
   keep this in mind whenever adding high-frequency read-only endpoints later.
2. **`tests/discoverability_selftest.mjs` double-counted**: it collected tool names from an **array**, while `blender_viewport` is
   **declared once more** in the "degraded placeholder" branch (a placeholder tool reusing an existing name, not a new capability) ⇒ it was counted twice (~175 extra characters), pushing the 12000 description budget
   to the ceiling. `tests/capability_lock.mjs:26-29` had long deduplicated by set for the **same reason**, but this test missed it — it now deduplicates the same way.
   **The total gate stays 12000, not relaxed** (16 tools measured **11 949**); the per-tool <1600 hard gate was never touched.

### Capability surface

- Model-facing tools **15 → 16** (`blender_rt_pick`); `tests/capability.lock.json` **explicitly records** it via `--update`
  (28 family / 186 op unchanged)
- `MODEL_FACING_TOOLS` in `runtime/classes.mjs` was updated too — it is **name-by-name cross-checked** by `guidance_selftest` and the capability lock,
  and that list feeds the **handoff block** of `blender_rt_plan(op="catalog", args={handoff:true})`: a miss makes subagents **unaware the tool exists**;
  the hard-coded "15 model-facing tools" there is now generated from the array length (to prevent the same class of drift)

### Acceptance

- `npm test` **exit 0**
- The `/host` criteria 1–8 + 11–15 standalone self-check **99 passed / 0 failed / 0 skipped**; client bundle self-check **40 / 0**
- Client probe **218 / 0** (gating ①–⑦ + pick UI all green)
- Criterion 11: `/host/ready` median **1 ms** vs `/doctor` 198–410 ms (**162–400×**), and `metrics.calls` **delta 0** (never touches Blender)
- Description budget: 16 tools **11 949 / 12 000**

### Unverified items (registered honestly, see contract §7.8 and the operating guide §10.8)

① The right sidebar's **actual render shape** (whether `kind` really becomes a tab, whether `guide` really renders as a guide item); ② whether `useTabInfo()` really returns
`{sidebar,panel,tab}`; ③ whether `dispose()` really removes the window and whether `openTab` really throws when unregistered; ④ whether "do not poll while the panel is invisible"
really saves resources; ⑤ **known capability boundary (not a defect)**: the degraded seat (`conversation.view`) cannot get `tab.visible`, so on the degraded path
the §7.4 polling keeps running forever; ⑥ **a DSH restart is mandatory** — the final verification of "the panel appears only when the channel is available" can only be done by a human after restarting.

---

## v1.1.0 (2026-10-16) — New: host integration (viewport panel · click into context · `@` mentions); Fix: filepath semantics of file-level `restore`

### New · host integration: bring the Blender viewport into the DSH chat UI

**Source**: the **Codex plugin** of upstream `ahujasid/mcp-for-blender` (`integrations/codex/`, plugin 2.1.1) — it inlines the latest viewport frame next to the chat,
**clicking an object in the picture attaches that object to the next message**, and it offers `@` mentions plus a thumbnail picker. This release implements that **experience** with DSH-native facilities
(**not** by copying the MCP Apps protocol — DSH is not an MCP host; what is wanted is the same experience). The assessment and interface contract are in
`docs/host-integration-layer-assessment-codex-plugin-and-dsh-port.md` and `docs/host-integration-interface-contract.md`.

**Everything goes through dedicated `/host/*` routes, never enters the `/plan` op catalog and adds no model tools ⇒ zero change to the capability surface**

| Capability | Implementation |
|---|---|
| Viewport state machine | `runtime/viewstore.mjs` (new): `seq`/`source`/`captured_at`/`origin(file,scene)`/`stale`/`pickable`/`blender_quiet`; scene change counter; in-flight counter; `AUTO_CAPTURE_QUIET_S=0.8`; camera matrices for the last 50 frames |
| Five host routes | `GET /host/view/latest` · `GET /host/view.png` · `POST /host/view/capture` · `POST /host/view/pick` · `GET /host/scene-items` (`runtime/server.mjs`) |
| CORS | Echoes `Access-Control-Allow-Origin` only for **loopback** Origins; `OPTIONS` preflight 204 |
| Unprojection pick | `runtime/view.py::host_pick` — reuses the existing `make_view_matrix`/`make_proj_matrix` unprojection → `scene.ray_cast` → screen-distance fallback for lights/cameras/empties; **validates `.blend`/scene mismatch first and refuses** (`file_mismatch`/`scene_mismatch`), never casting a click into the current scene |
| Client half | `src/client/index.js` (new, hand-written bundle, zero bundler / zero new dependencies) + `scripts/build-client.mjs`; `package.json` gains `dsh.client` and `exports["./client"]` |
| Viewport panel | Registered into the `conversation.view` slot; polls at 1500ms (stale at 600ms); swaps the image only when `seq` changes |
| Click into context | Click → normalized coordinates → `/host/view/pick` → a hit gets a marker (click again to cancel); "Add to message" puts the whole frame into the draft as an **attachment** plus a one-line object description (**`ctx.conversation.createDrafts` + `inputActions.addAttachments/insertText`**) — **no automatic send** |
| Auto re-capture (upstream A8) | `stale && blender_quiet` → `POST /host/view/capture {auto:true}`; **1200ms throttle**, no repeat for the same `seq`, **stops after 3 consecutive attempts without progress** and says so in the status line, stops when `visibilityState==="hidden"`, never concurrent with an in-flight pick |
| `@` mentions | `ctx.inputTriggers.registerSource({trigger:'@'})`, data source `/host/scene-items`, grouped by object/material/collection via `section`; a failed candidate returns `[]` instead of throwing |

**Two design disciplines (rooted in the same source as upstream)**

- **Panel polling never touches Blender**: polling only reads the store. Measured over 60 polls, the `metrics.calls` delta was **0** (an open panel does not occupy Blender's main thread).
- **pick must not mark the frame it just captured as stale**: `execute_code` belongs to the "changes the scene" command set, and pick sends `execute_code` through `ensureView()` —
  so **the plugin's own python module loading** and the **three read-only host primitives** are excluded per call with `{noMark:true}` (**not** with a global suppression counter:
  that would swallow the mark of a write command from another session that happens to land inside the window, and **under-marking stale is the dangerous direction**).

**Acceptance**

- `/host` contract criteria 1–8: standalone self-check `tests/host_routes_selftest.mjs` **68 passed / 0 failed**; the Lead spot-checked CORS preflight / PNG magic / stale 409 and the reproductions matched.
- Client half: `tests/client_bundle_selftest.mjs` **29 passed / 0 failed** (loading `lib/client.js` through a fake `window.__ModuleLoader__`); all 6 deliberately violating fixtures exit 1.
- `npm test` **exit 0**; `tests/capability.lock.json` **unchanged** (28 family / 186 op / 15 tools).
- Site restored: every probe object created for acceptance was deleted (2256 objects / 10 materials / scene `Scene` / unsaved file).

**Boundaries and unverified items** (registered honestly, **do not treat as proven capabilities**)

1. The **actual render shape** of `conversation.view` was not observed in a real GUI: by type it is a **View tab in the chat area** (not a resident sidebar). A resident sidebar would require `main` or `sidebar.right`.
2. Whether the `label` thunk → `ViewTab.label`, whether `InputTriggerCandidate.section` really renders as a group heading, and whether `codec.serialize` really reaches the model text verbatim — all **not measured**.
3. HTTP-level `file_mismatch` was not measured (`bpy.data.filepath` is read-only, and creating a real mismatch requires saving / opening another `.blend`, which would disturb the user's **unsaved** 2256-object scene ⇒ refused to do it;
   it was verified at the **function level** with a control group, while `scene_mismatch` is measured at HTTP level).
4. The screen-distance fallback for lights/cameras/empties is **implemented but not triggered** (the current scene is all MESH).
5. The real behavior of `document.visibilityState` inside the DSH GUI was not measured (the failure direction errs conservative).
6. **A DSH restart is mandatory** (the client half is a module loaded at startup); final verification of the panel in a real GUI waits for a restart.

---

### Fix · filepath semantics of file-level `restore` (`blender_rt_txn`, TXN_VERSION 3 → 4)

**Source**: an external usage report (the "transactions / rollback" section). The exact words were "the original file was untouched (safe), but then any save went into the snapshot directory, which is unexpected semantics".

### Symptom and cause

`restore` uses `bpy.ops.wm.open_mainfile(<out_dir>/snapshots/<label>.blend)` to move **the whole session** onto the snapshot file,
so `bpy.data.filepath` becomes the snapshot path — the original file was indeed never touched, but **any later save (Ctrl+S / `save_mainfile`)
went into `snapshots/`**. The user "thought they were editing their own project" while it was actually writing to the plugin's temp directory.

### Fix (`runtime/txn.py`)

- **`restore(label, into="auto", backup=True)`**:
  - `into="auto"` (default): after loading the snapshot it **puts the session back on the file the snapshot came from** (preferring the `filepath` recorded in the snapshot,
    then the session's current file; if both are inside the snapshot directory it does not write). That is "restore into the original file" — a save goes back to your own project.
  - `into="snapshot"`: **non-destructive** mode, it only loads and writes not a single byte to the original file; the receipt's `next_save_goes_to` states exactly "where a save would land now".
  - `into="original"`: requires that it must be writable; if it cannot reach the target it returns `ok:false` (**no silent degradation**).
  - `backup=True` (default): before loading, save a `_pre_restore_<label>_<ts>` snapshot (restore loses the current unsaved state,
    so this undo point must be kept); when the session is dirty and the original file must be overwritten, also save a **disk copy of the original file** `_pre_restore_file_*`
    (memory state ≠ disk state, so both need a safety net before overwriting). Both enter the snapshot listing, so they can be `list`ed and `restore`d back.
- The `snapshot` record gained `filepath` / `unsaved` — after other files have been opened, `restore` still knows "where the original file is".
  (**Target order matters**: check the snapshot's origin first. The user may have opened **another** project before restoring, in which case writing "the current file"
  would destroy another project.)
- The receipt gained `filepath_before` / `filepath` / `wrote_to_original` / `target` / `target_source` /
  `next_save_goes_to` / `backup` / `on_disk_backup` / `warning`.
- `TXN_VERSION` 3 → 4; the `file_level.restore` wording in `t_help` synced.

### Tests

- Added **`tests/txn_restore_selftest.py`** (headless, self-built synthetic scene, `preload="txn"`) — **23 assertions**:
  after a default restore the session returns to the original file; with `into="snapshot"` the original file's md5 is unchanged byte for byte; when the session has already drifted to the snapshot directory,
  the `filepath` recorded in the snapshot still leads back to the original file; an unsaved scene is not written recklessly but only warns; the pre_restore backup really lands on disk and can be `list`ed.
  **Ran red first (old code 14 passed / 9 failed), then fixed**, 23/23 after the fix.
- Regression: `tests/txn_selftest.py` (including deliver cross-assertions) **55/55 all green** (the version assertion synced to 4).

### Tool surface

`blender_rt_txn` gained the parameters `into` / `backup` and forwards them to `/txn`; the old wording in the description
"restore loses the current unsaved state" became "returns to the original file by default + automatic backup before loading".
`src/index.ts` was changed, and **`lib/` must be rebuilt** (the worktree also has other unbuilt in-flight changes).

## Unreleased (v1.0.6 TBD) — S0 draft assessment: the first step of reference-image reconstruction becomes "produce a build table first, do not measure dimensions"

**Motivation (user wording)**: having the modeling **assessment** stage immediately measure exact dimensions and count meshes amounts to
treating invented numbers as a spec **before a reference image even exists**; that step should only be "sketching in your head" — recognize what it is / roughly how big / how many pieces / which is the body and which are accessories /
which part is hard-surface and which is curved / where the cutouts·bosses·recesses are, and refine later when images come back.

### Added `shape_draft` / `shape_draft_check` (shape family, read-only)

- **`shape_draft(object_class=?)`**: returns the **field contract and a fillable skeleton for the build table**, and **returns no measurement values at all**. Four tables:
  T1 identification and magnitude (what it is / which class / magnitude band A–F / symmetry / axis), T2 build units (each: role main body·accessory·repeat /
  parent / form_class / features / build_path / evidence / to_confirm), T3 form (faceted·smooth·organic·
  rotational·plate·repeats·sweep), T4 spatial features (cutouts·bosses·recesses·seams·thin walls·grilles).
  When `object_class` is given it also carries that class's **names of items to watch** (which proportions to check / which `section_path` to follow), **with no numbers**.
- **Three hard rules (machine-checked)**: R1 do not measure exact dimensions (a size may only be a magnitude band or a relative ratio such as `0.3×`; any mm/cm is rejected);
  R2 do not count meshes (it lists the ops forbidden at this stage: `audit_scene`/`audit_mesh`/`print_report`/`shape_sections`…);
  R3 do not pin values down (every field carries `confidence` + `source`, undecidable ones say `unknown`, and every unit must carry `to_confirm`).
- **`shape_draft_check(record=…)`**: mechanically validates the filled-in table (are fields complete / are enums valid / is the main body 0 or >1 /
  **did it secretly write absolute mm values**), returning `errors` / `warnings` / `stats`. `ok=true` only means "the table is valid and nothing was pinned down",
  **not that dimensions were verified** — numbers always wait for S2 calibration / S5 acceptance.
- The **iteration path** comes with the receipt: S0 draft (no image) → S1 `img_scan` (pixels ≠ millimeters) → S2 `img_rectify` calibration (the first time there are numbers)
  → S3 station table/sections → S4 render comparison → S5 acceptance (**only here** are faces counted and gaps measured).

### Guidance sync (`catalog` / `classes` / skill docs)

- `catalog`'s shape family: `when` became "**S0 draft first** → `shape_plan` → loft→feature lines→IoU", `not` gained
  "**at S0 do not write mm, do not call `audit_*` to count faces**"; ops gained `draft` / `draft_check` (the default-page length gate still passes).
- `classes.mjs`'s `recon` class: `entry` became `shape_draft` (the first step), the chain is prefixed with `shape_draft → shape_draft_check`,
  and the acceptance gate splits into S0 / S3 segments; `renderHandoff()` hard rule 1 synced.
- Skill side: `references/reference-image-reconstruction-sop.md` went from "eight steps" to "**nine steps**" (added ⓪ draft assessment + §1.1 the four tables +
  §5 the draft→numbers iteration discipline); `SKILL.md` gained §0.5.0 "draft before freezing the spec", and §0.7 decision tree plus hard rule 1 were changed.
- Counts: `28 family / 184 → 186 op` (`src/index.ts` description and the workspace `AGENTS.md` refreshed via `scripts/sync_counts.mjs`;
  `capability.lock.json` and `tests/plan_readonly.baseline.json` updated in sync).
- `SHAPE_VERSION` 1 → 2; `shape_selftest` gained S0 assertions (all four template tables present + a legal record passes + writing `450mm` must be rejected).
- Self-check: `npm test` all green (capability lock / single source of truth / discoverability / guidance completeness / route contract etc.).

## v1.0.5 (2026-10-07) — issue #14: overhang no longer counts "bottom faces touching the bed" as needing support by default (+ two old anisotropic-scaling debts + `npm test` not getting halfway on Windows)

### Fix 1 (P1 · issue #14): bed-contact-face wording in `print_overhang` / `print_report`

- **Symptom**: the vast majority of FDM parts have flat bottoms, yet the old wording counted every "face whose normal points down" as overhang ⇒ **a flat-bottomed part defaulted to `overhang_ok=false`**.
  The reporter's PLA bracket had `overhang_area_mm2=5351.57`, of which **97% (5198.49mm²) was the bed-contact flat bottom at z=0**;
  a 1-unit cube gave `overhang_ratio=0.1667` with ok=false.
- **Root cause**: the criterion looked only at the normal (`c >= cos_lim`) and never asked "is this face lying on the print platform"; yet the receipt note told the user
  "for a bottom face lying on the bed, use `min_area_mm2` to exclude it" — contradicting the implementation (that is an **area budget**; raising it lets real overhangs through as well).
- **Fix**: added `exclude_bed=True` (default), `bed_tol_mm=0.2`, `bed_mode=flat|min`, `bed_horiz_deg=1.0`, `bed_band_mm=1.0`.
  A bed-contact face = horizontal facing down (≤`bed_horiz_deg`) **and** its elevation within the platform plane ±`bed_tol_mm`; the platform plane in `flat` (default) takes
  the elevation of "the horizontal downward-facing layer with the largest area", while `min` takes the lowest point of the selected set. Receipt: `overhang_area_mm2` = **net overhang**,
  `bed_area_mm2` lists the bed-contact faces separately, `overhang_area_incl_bed_mm2` keeps the old wording, `bed_level_mm`/`lowest_mm` allow review;
  `exclude_bed=False` fully reverts to the v1.0.4 wording (net overhang/ratio/ok value-for-value equivalent).
- **Also closed a false green**: if `flat` unconditionally trusted "the largest-area horizontal downward face", a **mushroom part** (thin stem + wide cap) would treat the cap bottom
  as the platform plane ⇒ measured on a 200×200 cap bottom, **40000mm² of real overhang was swallowed whole and `ok=true`**. Added a `bed_band_mm` guard: when the candidate layer
  is more than 1mm above the lowest point it is judged "not a platform plane" → reverts to the `min` wording and writes `bed_warning`. After the fix the same geometry gives:
  `bed_mode=min-fallback`, the 40000mm² cap bottom still counts, `ok=false`.
- **Uncertainty must not read as green**: `print_report` gained a top-level `warnings[]` (self-justifying warnings about the platform-plane criterion, mirrored in `rows[].bed_warning`),
  and `gate.py`'s print preset feeds `len(warnings) > 0` into `degrade_if` ⇒ such receipts are **degraded** at the gate.
- **Known boundary (written into `print_help`'s limits)**: differences within `bed_band_mm` cannot be resolved — "a wide face ≤1mm above the bed" and
  "jagged bottom-edge faces" are the same shape, so `flat` always counts them as bed contact (FDM can bridge); also `flat/min` both infer geometrically and are **position-independent**,
  so a fully floating part's lowest point is itself; to judge against an absolute platform, place it on the platform first or use `exclude_bed=False`.
- **Field contract change**: `PRINT_VERSION` 1 → 2; `overhang_area_mm2` semantics flipped (no longer includes bed-contact faces by default).
- **Self-check**: `print_selftest` expanded from 1 shape to **8** (flat-bottom cube / cantilever / flat-bottom debris / mushroom cap / an inclined face must not count as bed contact /
  the ratio of a single T / true area and normals under non-uniform scaling); all expected values are closed-form rather than copied back from the implementation; also wired into the on-device A1–A5 suite.

### Fix 2 (old debt · present since v1.0.4): normals and areas are both wrong under anisotropic scaling

- **Normals**: `M.to_3x3() @ n` should be the **inverse transpose** `((M⁻¹)ᵀ @ n)`. Under scale(2,1,1) a true normal 16° off straight down (must be supported) was computed as
  49° ⇒ **the whole face dropped out of the overhang set** (measured: before the fix that inclined face had overhang 0.00mm², after the fix 0.34mm² counted).
- **Area**: `p.area × (_scale_avg × mmu)²` is off by **-11.1%** under scale(2,1,1) (1.777e6 vs the true 2e6 mm²);
  changed to accumulating triangle fans in world coordinates (equivalent to the old value under rotation/uniform scaling; only anisotropic scaling changes).

### Fix 3 (follow-up to issue #10): `npm test` does not get halfway on Windows

- A Windows drive-letter path (`C:\…`) obtained from `import(path.join(...))` is treated by ESM as the scheme `c:` ⇒
  `ERR_UNSUPPORTED_ESM_URL_SCHEME` (**reproducible on any platform**, not just Windows). **11 sites** were uniformly changed to
  `pathToFileURL(...).href`: `capability_lock` / `single_source` / `guidance` / `shape_search` / `backend_probe` /
  `route_contract` / `mac_selftest` / `sync_counts` / `dsh_api_compat_probe` (two inline scripts) /
  `schema_resolve_selftest` (parent passes a URL + child converts its own URL).
- `tests/schema_resolve_selftest.mjs` gained **group E**: Windows-style bare paths must no longer hit the scheme error — this one **runs on any platform**,
  so Windows's failure mode has regression protection on Linux CI.
- The "dead port" in `tests/protocol_selftest.mjs` was originally `flatPort + 4242`: OS dynamic ports live in 49152–65535, so above 61293 it overflows ⇒
  `Socket.connect()` throws `ERR_SOCKET_BAD_PORT` and that assertion never runs at all (about a **26%** chance of intermittent red). Changed to bind(:0) → close
  to obtain a genuinely dead port, and the originally **always-true** assertion became "the dead port ≠ any mock port".
- The preload example in `tests/README.md` was missing `pipeline` (measured 2 red: `t_pipeline` / `t_refs_single_op` — a missing item in the example,
  not a plugin defect); it is completed now, and the assertion counts were corrected to the measured values.

### Acceptance (all measured after the final changes)

| Gate | Result |
|---|---|
| `npm test` (16 steps) | **EXIT=0** |
| `print_selftest` (on-device Blender 5.2.2) | **ok=true** · 8 shapes |
| `gate_selftest` | **ok=true** (new on-device case: non-empty `warnings` ⇒ that gate is degraded) |
| A1–A5 integration self-check (on-device headless) | **128 / 0 failed** |
| gate review regression (on-device headless) | **52 / 0 failed** |
| issue #14 reproduction (default Cube) | before `4000000 / 0.1667 / ok=false` → after **`0 / 0 / ok=true`**; `exclude_bed=False` still reproduces the old numbers |
| mutation testing (deliberately breaking the implementation) | ignoring `bed_horiz_deg` → red; wrong `overhang_ratio` denominator → red; normals reverted to `M@n` → red; area reverted to `_scale_avg` → red; removing `bed_band_mm` → red |

## v1.0.4 (2026-10-05) — Native Linux becomes a first-class platform: fix `wslToWin()` treating "any host that is not Win/mac" as WSL (frame capture always reports `frame http 502`)

### Fix (issue #11, reported by @mlfc666, Manjaro native Linux)
- **Symptom**: on native Linux (Blender and the host on the same machine) `blender_rt_see` always reports `Error: frame http 502`, and `/frame.png` returns
  `ENOENT … /home/<u>/.dsh-blender-rt/dsh_live_viewport.png`; yet the frame PNG **really was written**, only into a
  **literal backslash directory** `/home/<u>/\wsl.localhost/Ubuntu/home/<u>/.dsh-blender-rt/`. Corroborating: `/doctor` on Manjaro reported `distro` as `Ubuntu`.
- **Root cause**: `wslToWin()` in `runtime/config.mjs` only distinguished `IS_MAC` / `IS_WIN`, **treating everything else as "a Linux host ⇒ WSL +
  Blender on Windows"**, mapping host absolute paths to `\\wsl.localhost\<distro>\…`. A same-machine Blender treats that string as a
  **relative path**, so the whole "Node writes, Blender reads" file handoff went out of alignment (frames / headless scripts / ledger / results / trajectory /
  launch's statusFile / staging all go through it). macOS hit the same pitfall years ago and fixed it (the comment in `blenderSidePath` is the original wording); native Linux was missed.
- **Fix**: added an `IS_WSL` criterion (env var first → fall back to `/proc/version`; inside a systemd service dsh **does not inherit** `WSL_DISTRO_NAME`,
  see #6, so looking only at env vars is not enough), and `wslToWin()` **returns identity** on non-WSL; the criterion was extracted into the pure function `detectWsl(platform, env, procVersion)`
  so it can be cross-checked on **any platform**. Two related issues fixed along the way: `/doctor`'s `distro` reads `/etc/os-release` on native Linux and reports the real distribution;
  `PATH_GUARD` (the check for "Windows Blender treats `/home/x` as a relative path under the current drive root") is disabled on native Linux — otherwise every normal script
  returned a false `render_filepath_posix` warning and steered people toward "convert it to Windows form".
- **Measured comparison** (inside WSL, using a **private mount namespace** to bind `/proc/version` to a Manjaro kernel string and clearing `WSL_DISTRO_NAME/WSL_INTEROP`,
  so it genuinely takes the "native Linux" branch; both pre-fix and post-fix code were run and cross-checked on the same machine):

  | Probe | Before | After |
  |---|---|---|
  | `wslToWin('/home/u/.dsh-blender-rt')` | `\\wsl.localhost\Ubuntu\home\u\.dsh-blender-rt` | `/home/u/.dsh-blender-rt` |
  | `CFG.workDirWin` | `\\wsl.localhost\Ubuntu\tmp\dsh-blender-rt` | `/tmp/dsh-blender-rt` (isomorphic to `workDirWsl`) |
  | `PATHS.livePngWin` | `\\wsl.localhost\Ubuntu\tmp\dsh-blender-rt/dsh_live_viewport.png` | `/tmp/dsh-blender-rt/dsh_live_viewport.png` |
  | `describeConfig().distro` | `Ubuntu` | `Ubuntu 24.04.4 LTS` (reads os-release) |
  | `PATH_GUARD` | non-empty (false warning) | `''` |

- **Regression gate**: added `tests/linux_selftest.mjs` (`npm run test:linux`, 25 assertions; already wired into `npm test`) — the `detectWsl()` criterion decision table
  (runs on any platform, including "a fake kernel string must not be misjudged as WSL" / "when /proc/version cannot be read, do not hard-guess") + platform-branch self-consistency + source regression protection (the UNC branch still exists)
  + native-Linux end-to-end identity. The same self-check run against the **pre-fix** code was **11 red / 16**, after the fix **25 all green**.
- **The three existing paths WSL / Windows / macOS are byte-identical**: `wslToWin('/home/x/f.png') === '\\wsl.localhost\Ubuntu\home\x\f.png'`,
  `/mnt/d/… → D:\…`; on device `lease_stale_selftest` (including launching the Windows `blender.exe` and getting back D2 with `resultJson.ok=true`) 20/0,
  `mac_selftest` 7/0, and `npm test` is **line-by-line identical** to before, with no new failures. (The only red, `shape_search_selftest`, is because on this machine the **Windows-side
  DSH main process occupies its default port 9895**, unrelated to this change: run separately on another port it is 24/24 all pass.)

### Known unfixed (consistent with the issue #11 reporter's footnote, left for later)
- `wslPathShared()` on native Linux still applies the WSL criterion (`/tmp` and independent mounts are always judged "not shared") ⇒ `/doctor`'s `workDir.shared=false`,
  and headless scripts take the "replace / degrade" branch with a `WORKDIR_NOT_SHARED` notice. Functionally it does not block anything (a same-machine Blender can read it), but the semantics need restating;
  the A1/A2/A3 cases of `workdir_shared_selftest` hard-code WSL semantics as assertions and must change along with it.
- Another note: the python side of `runtime/paths.mjs` uses a different "non-WSL native POSIX" criterion (`!IS_WIN && !fs.existsSync('/mnt/c')`).
  On native Linux both conclusions agree (this release did not touch it); they only diverge in the corner case of "WSL but no /mnt/c".

## v1.0.3 (2026-10-05) — Inner loop from "exists" to "actually usable": fix unbound `ns` (the inner loop could not finish a single iteration for 6 versions) + new op `shape_search` (declarative search) + descriptions switched to task-oriented trigger words

### Fix (P0 · this is the real reason "nobody uses rt_loop"): in `step`/`measure`, `ns[...]` throws NameError the moment it runs
- **Symptom**: `blender_rt_loop(op="start", …)` returns `start_ok: true`, but **it errors out at the very first tick** —
  `stop_reason="error"` / `i=0` / `best=null` / `board_n=0`, and the tail of `error` is
  `File "<dsh_loop.step>", line 1, in <module>\nNameError: name 'ns' is not defined. Did you mean: 'np'?`
- **Root cause**: `runner.py`'s `exec(step_code, ns)` uses `ns` as globals, but **never binds the name `ns` into the namespace**
  (`git log -S 'ns["ns"]'` finds no hits across the whole v0.4.0→v1.0.2 history ⇒ it has been like this since release). Yet the README / cookbook / tool descriptions /
  every recipe **invariably** writes `ns["params"]` / `ns["score"]` — whoever follows the docs blows up, hence "the inner loop exists but nobody can use it".
- **Fix**: inject `ns["ns"] = ns` and `ns["st"] = st` (the latter is also a name promised in the documented preloaded list).
- **Measured comparison** (real headless Blender, ticks driven by hand; timers do not fire headless):
  | | Before fix `run-muu3oj9hlcjh` | After fix `run-muu3ppkr6508` |
  |---|---|---|
  | `stop_reason` | `error` | `iterations` |
  | `i` | 0 | 5 |
  | `best` | `null` | `{score: 0.0687…}` |
  | `board_n` | 0 | 3 |
  | `ns_bound` | **false** | **true** |
- **Regression gate**: `dsh_loop_selftest` was upgraded from "only reads status/help, never really starts a loop" to **really starting a minimal loop and driving 4 ticks by hand**,
  hard-asserting `ns_bound / iters_done / best_present / no_error` (the old selftest's structural blind spot is exactly why this regression survived 6 versions).

### Change 1: `blender_rt_loop` description goes from "count threshold" to "task shape"
- Trigger words: align / fit / infer dimensions backwards / parameter sweep — the criterion can be written as a single number (silhouette IoU, bounding-box dimension error, profile difference, or a self-written score).
- Hard prerequisites stated outright: **only effective in a GUI session**; `op=board` shows candidates; `op=export` writes a reproducible script; after convergence verify through another route; when it finishes the scene stays on the **last iteration**, not on best.
- Long tail (spec fields / the three `K.dsh_measure` signatures / copyable skeletons / 4 disciplines) moved into the catalog detail: `blender_rt_plan(op="catalog", args={tool:"rt_loop"})` (1,834 characters, fetched on demand).
- Description budget gate still green: total **11,672 ≤ 12,000**, rt_loop **1,261 < 1,600**.
- The old `≥20 iterations before use` copy was self-vetoing: models read it and skipped — after switching to task-shaped trigger words, all three levels hit: the §0 routing table + description + catalog.

### New op: `blender_rt_plan(op="shape_search", args={…})` — declarative search
- **You give only the objective and the ranges, the machine searches**: `objective` (`silhouette_iou` / `profile_err` / `aabb_err`) + `params`
  (`{dy_mm:{min:-30,max:30,step:5}}` or `{values:[…]}`) + `apply` (code that lands `ns["params"]` into the scene each round;
  defining `apply(p)` in setup is recommended — consistent with the reproduction convention of `op=export`).
- Internally it **reuses the runner**: `start → poll → board → export` is fully managed ⇒ **only effective in a GUI session**;
  `dry_run:true` only validates and returns the spec (**no Blender connection needed**).
- Sampling `strategy:"auto"`: when the combination count ≤ iterations it uses an **exhaustive grid** (the iteration count converges automatically to the combination count), otherwise **random search**;
  `grid` / `random` can be forced explicitly; an explicit grid with >20000 combinations is rejected outright with a skeleton.
- Wrap-up: when the inner loop ends the scene sits on the last iteration's parameters, so by default this op runs `setup + apply(best)` once more to land the scene on best (`restore:"none"` disables it).
- Read-only-ness: it changes the scene through `apply` ⇒ classified as a **write op** (not in the `/plan` read-only whitelist, subject to the write lease).
- Receipt: `spec_echo` + `best` + `board` + `stop_reason` + `applied` + `exported` + `next_steps`; **any validation failure returns a `skeleton`**.
- Code-block indentation normalization (`normBody`): `apply`/`setup` accept the "first line flush left + continuation lines indented" style and nested blocks (`if/else`),
  so no `IndentationError` is produced — guarded by the test assertion "really compile three code snippets with python3".

### Companion skill (`dsh-skill-blender-modeling`, a separate repo, released in sync)
- §0 routing table gained an `rt_loop` row; §0.7 gained a **fourth hard rule** (quantifiable + dozens to thousands of groups to try ⇒ no hand-picked parameters);
  added **Recipe 24** (copyable spec + ready-made objective function table + 5 disciplines + 3 scenarios where it should not be used) + usage and division of labor for declarative `shape_search`;
  the front-matter description gained "parameter-search inner loop", recipe count 23 → 24.

### Tests
- Added `tests/shape_search_selftest.mjs` (**24 items**): catalog surface / spec generation (grid · random · aabb_err · multi-view averaging · pyLit booleans) /
  **real python3 compilation of three code snippets (including nested blocks)** / validation surface (missing param · illegal objective · combinatorial explosion must all return a skeleton) / real routing (isolated backend POST `/plan`).
- Capability lock updated to **28 family / 184 op** (+1 op, for the reason in this section); `npm test` **16 steps all green**.
## v1.0.2 (2026-09-30) — gate compliance (drop eval) + issue #10 fix + S10 self-healing all shipped together

> Trigger: when this plugin was submitted to [awesome-ai-plugins](https://github.com/hashgraph-online/awesome-ai-plugins) (PR #539), upstream's "required
> source scan" scored **73/100** (threshold ≥80 with no critical/high), and the only high was the dynamic evaluation in `runtime/gate.py`.
> This release ships three things together: **drop eval** · **issue #10 fix** · **S10 field patch backported**, plus repo hygiene for the gate's missing sub-items.

### 1. `runtime/gate.py`: dynamic evaluation → per-node whitelist AST evaluator (the gate's high item)
- The old implementation handed the compiled AST to the built-in dynamic-evaluation entry point. Semantically it was already pinned down by `_check_ast` (no underscore attributes, calls only to
  `ALLOWED_FUNCS`), but the "name + left paren" shape itself gets scored high by the scanner (`DANGEROUS_DYNAMIC_EXECUTION`).
- Now a new `_eval_node()` **evaluates node by node against the whitelist** (BoolOp / UnaryOp / Compare / BinOp / Name / Constant /
  Attribute(non-underscore) / Subscript / Tuple / List / Call), no longer calling any dynamic-execution entry point; `_check_ast` is still the only entry.
- Two places are **deliberately stricter**: a name not in env → immediate error; calls support no `*args` / `**kwargs` (`_check_ast` never allowed them anyway).
- Regression: added `tests/gate_eval_selftest.py` (**32 items**: source surface 3 · semantic equivalence 14 · short-circuit/operand semantics 4 · rejection surface 11),
  wired into `npm test`. It needs no Blender (stubs `bpy` and the shared kernel `dsh_rt_kernel`, testing only the pure evaluator).

### 2. issue #10 fix: schemastery resolution now ESM-first + no top-level throw
Details in the next section `v1.0.1+S11` (including the new `tests/schema_resolve_selftest.mjs`, 14 items).

### 3. S10 field patch **backported into `src/`**
It used to be applied only to `lib/index.js` and was lost on a single `npm run build`; this time the src side was filled in, details in `v1.0.1+S10`.

### 4. Repo hygiene (the gate's missing sub-items)
- Added `SECURITY.md` (private reporting policy + a statement of this plugin's execution surface / credential surface)
- Committed `package-lock.json` (fixes `DEPENDENCY_LOCKFILE_MISSING`)
- Added `.github/dependabot.yml` (weekly npm updates)
- `package.json`'s `files` gained exclusions: `!runtime/*.bak-*`, `!runtime/*.v1-*` — field backups no longer ship in the package

### Verification
- `npm test` green end to end (including the new `tests/schema_resolve_selftest.mjs` and `tests/gate_eval_selftest.py`)
- `python3 tests/gate_eval_selftest.py` → **32 items ALL PASS**
- Whole-repo text scan (comments included): the **dynamic-evaluation call shape** that was scored high appears **0 times**; the existing pattern of loading source with exec and then executing it
  is kept exactly as is — upstream's same scan run did not flag them (it only reported the one in gate.py)

## v1.0.1+S11 (2026-09-30) — fix issue #10: schemastery resolution now ESM-first + no top-level throw ("all 15 tools vanish")

> External report: <https://github.com/sixtysevenlf/dsh-blender-plugin/issues/10> (@qaz040619, evidence chain includes a file-by-file comparison of package contents,
> a bisect of `dsh.profile.bundles`, and divergence between `--dump-config-schema` and the boot path). **Confirmed, not fixed in 1.0.1**: `src/index.ts`
> really still has `createRequire()` dual-name resolution + a module top-level `throw`.

### Symptom
When `dshmarket` or `dsh-context` is installed in the profile at the same time (both pull the scoped name `@deepseek-ai/schemastery` through the ESM loader),
the plugin entry reports `failed to import`, **all 15 tools vanish at once**, and the backend does not start either; the host **returns only one line**, `failed to import`, and the real exception is swallowed.
Order-independent, the package itself is byte-identical, and in `--dump-config-schema` that entry is instead `schema` (import succeeded) — the symptom and the real cause are not on the same layer.

### Root cause
Resolution used only `createRequire()`, and **`throw` at module top level**: that require fails under the host's module-resolution interception when several plugins coexist ⇒
the module throws **at load time** ⇒ the entry's `fiber` stays `undefined` ⇒ it vanishes entirely. This repo's `docs/dsh-update-adaptation.md` called out this failure mode long ago.

### Fix (`src/index.ts`, 3 places)
1. **Order**: ESM `await import()` first (`@deepseek-ai/schemastery` → `schemastery`), falling back to `createRequire` on failure;
   the shape check requires actually obtaining `.object()` (if it cannot be obtained, treat it as unusable, no gambling).
2. **Failure semantics**: **no more top-level `throw`** ⇒ degraded load: `Config` is `undefined`, and `apply()` registers only one
   `blender_viewport` **diagnostic placeholder** (reporting the names it tried, the real error per channel, and the fix). The plugin no longer "vanishes entirely",
   and beyond the host's `failed to import` there is finally a readable scene. `apply()` also reads config defensively (no longer assuming the schema filled in the defaults).
3. **Diagnosable**: `__internals.schemaResolve` (`via` / `error` / `tried`), plus an extra line each in `blender_viewport op=status` and
   `op=doctor` ("which channel was taken / why it failed").

### Also fixed: S10 patch **backported into src** (otherwise one build loses it)
The S10 field patch used to be applied only to `lib/index.js` (absent from `src/index.ts`): `killBackendByCmd`'s `signal` parameter, argv token
exact matching (to prevent self-harm), the watchdog's "clear the corpse first, then respawn" (2 consecutive failed probes → SIGTERM → 1.2s → SIGKILL). A single `npm run build`
and this logic is wiped. This time the src side is filled in, **src and lib are in sync again**, and S10's `runtime/server.mjs` part was already in the tree.

### Regression selftest (new, needs no Blender): `tests/schema_resolve_selftest.mjs`
Wired into `npm test`, plus `npm run test:schema`. Each of the four fixture groups really `import()`s a copy of `lib/`, changing only the set of names present
in the `node_modules` above it:
| Group | Names the fixture provides | Assertion |
|---|---|---|
| A | only `@deepseek-ai/schemastery` | import succeeds, takes the `esm:` channel, `Config` builds normally |
| B | only `schemastery` | import succeeds, `Config` builds normally |
| C | neither | **does not throw**; `Config === undefined`; the diagnostic placeholder is registered and reports cause/fix |
| D | the real package itself (real node_modules) | importable, `__internals.schemaResolve.via` has a value |

Measured **14 items, all pass**; group C is exactly the path on which the old version "vanished entirely".

### Incidental
- **Capability lock**: `tools_count` changed from "array length" to **set dedup** (the degraded branch reuses the same tool name; this test's convention was always
  "look only at the set (tool names)"). The tool surface is still **15**, not 16.
- Item 3 in issue #10 (`tests/protocol_selftest.mjs`'s mock port randomly exceeding 65535, triggering `ERR_SOCKET_BAD_PORT`) **could not be reproduced**:
  in both 1.0.0 and 1.0.1, `tests/protocol_selftest.mjs:90` is `srv.listen(0, '127.0.0.1', …)` (OS-assigned port),
  and the only random port in the whole package is in `tests/launch_selftest.mjs:23` (`21000 + Math.random()*20000`, range 21000–40999). We already asked the reporter in the issue to add the line number/stack in that file.
- **Version**: this section's fix ships with **v1.0.2** (S10 field patch + this fix + gate hygiene files). `package.json`
  already has `!runtime/*.bak-*` / `!runtime/*.v1-*` in `files`, so field backups no longer ship.

## v1.0.1+S10 (2026-09-29) — self-healing for a dead backend (field patch, not shipped with the package)

> Scene: the 9877 backend's **event loop was hogged to death by a long synchronous operation** ⇒ `/health` does not answer (`ss` shows `Recv-Q` only growing,
> no one accepting), **the SIGTERM handler never gets its turn** (the signal is queued but the main thread never returns), and the watchdog respawns
> an instance every 15 s but hits `EADDRINUSE` and `exit(1)` outright ⇒ **infinite spinning, never self-heals, only a manual `kill -9`**.
> This time it was turned into self-healing, 2 files and 6 places changed; the measured red/green comparison is below.

### Fix 1: `runtime/server.mjs` — on EADDRINUSE "decide dead or alive first, take the port back if dead" (P0)
- Previously it only printed a conclusion inside `server.on('error')` and then `process.exit(1)`; now: probe the occupant (1200 ms),
  **if it answers, do not take it** (to avoid kicking out a backend that is merely busy), **if truly dead then `SIGTERM` → 600 ms → `SIGKILL` to clear the field, then retry `listen`** (at most 2 times).
- Why the escalation to SIGKILL is required: a process whose event loop is hogged to death **cannot receive or handle SIGTERM** in practice.
- Also fixed a pre-existing bug: that error branch used `fs` / `path` but **never imported them**,
  so that "actionable conclusion" was in fact always swallowed by `catch (e2)` and **never written to `backend-listen-error.txt`**; the imports are now added.

### Fix 2: `lib/index.js` — watchdog "clear the corpse first, then respawn" + SIGKILL escalation
- The watchdog used to call `startBackend()` as soon as a probe failed, **never calling the existing `killBackendByCmd()`** (it was only used by `op=stop/restart`)
  ⇒ while a dead process held the port, every respawn was doomed to EADDRINUSE.
- Now: **2** consecutive failed probes (≈30 s; `probe` times out at only 1500 ms, so a single probe is not enough) →
  `killBackendByCmd(port,'SIGTERM')` → 1.2 s → `killBackendByCmd(port,'SIGKILL')` → respawn again.
- `killBackendByCmd(port, signal='SIGTERM')` gained a signal parameter, with the default keeping existing call sites behaving as before.

### Fix 3: both "kill process" paths now use **exact argv token matching** (self-harm fix)
- The old criterion was **substring matching on the whole cmdline** (`cmd.includes('server.mjs') && cmd.includes('--port 9877')`).
  Measured self-harm: the caller's command line `bash -c "... node runtime/server.mjs --port 9899 ..."` contains both strings as well
  ⇒ when the new version grabs the port it **SIGKILLs the caller's own shell along with it** (hit on the very first version of this patch, caught on the spot by an A/B test).
- Now it requires: **some standalone argv ends with `/server.mjs`** (exact basename) and is immediately followed by `--port <port>`,
  and shell kinds like `bash/sh/zsh/dash/fish/bwrap` are excluded. Tightened on both sides, `lib/index.js` and `runtime/server.mjs`.
- Regression evidence: a bash call carrying the same literal **is no longer killed** (it was killed before the fix).

### Fix 4: `runtime/server.mjs` — forced-exit fallback in signal handling
- `SIGTERM/SIGINT` handling changed to `try{engine.stop()}catch{}` + `try{server.close()}catch{}` +
  `setTimeout(()=>process.exit(0),400)`: nothing throwing or hanging in any step can let the "zombie holding the port" survive any more.
- Measured: exits within **510 ms** of sending SIGTERM.

### Red/green comparison (measured locally, isolated ports 9898/9899, stand-in = holds the port + ignores SIGTERM + never answers)
| | Old version | New version |
|---|---|---|
| Startup result | `exit 1`, log `already in use (EADDRINUSE)…` | `dead backend holds 9899: SIGTERM=[37258] SIGKILL=[37258] → retry listen` + `[blender-rt] http://…:9899/` |
| `/health` | no answer ❌ | `{"ok":true,…}` ✅ |
| Stand-in process | still alive (manual kill required) | cleared by SIGKILL ✅ |

### Not shipped with the package / upgrade notes
- This is a **field patch**: upgrading the plugin package overwrites `lib/index.js` and `runtime/server.mjs`. The originals and a re-appliable diff are in
  `tmp/patch-backup-20260929/` (`index.js` / `server.mjs` originals + `S10-selfheal.diff`, re-apply with `patch -p0 < S10-selfheal.diff`).
- **Scope of effect**: the `runtime/server.mjs` part **takes effect as soon as the backend is restarted** (`blender_viewport op=restart`);
  the watchdog part of `lib/index.js` needs a **host/plugin reload** to take effect (the old watchdog is still active in this session, but the port-taking path in server.mjs alone already achieves self-healing).

## v1.0.1 (2026-09-28) — fix every op of blender_rt_perf / blender_rt_opt crashing (the perf API was never registered) + descriptions rewritten per platform

### Fix: every op of the perf / opt tools reports AttributeError (P0)
- **Symptom**: `blender_rt_perf` (status/analyze/apply/revert/help) and `blender_rt_opt` (analyze/opt_analyze/opt_join)
  every single op returns `AttributeError: module 'dsh_rt_kernel' has no attribute 'dsh_perf_api'` (the kernel only has
  `dsh_perf_api_fp`, which is a content fingerprint the engine writes and is easily misread as "registered").
- **Root cause**: the tail of `runtime/perf.py` had only one shim from the v0.9.1 era — it wrapped the **already existing** `K.dsh_perf_api`
  into `_DshApi`, while nothing in the whole package ever actually created that attribute; at the same time `engine.mjs`'s
  `MODULE_ATTR.PERF_READY='dsh_perf_api'` ready check was always false ⇒ the module was re-injected on every call.
- **Fix**: registered per `kit.py`'s unified convention (same shape as qc / clearance / pipeline):
  `_KIT.register("perf", PERF_VERSION, {status, analyze, apply, revert, help, opt_analyze, opt_join}, extra={selftest})`.
- **Contract alignment**: `engine.mjs`'s `perfCall` changed from per-op direct calls to `K.dsh_perf_api[op](dict)`
  (where parameters were misbound as the first positional argument, e.g. `samples={'samples':64}`) to
  `K.dsh_perf_api["dispatch"](op, json)` — the same contract as audit / txn / preset / plan, with parameters flattened as kwargs.
- **Selftest tightened**: `dsh_perf_selftest` promoted `api_registered_by_module` from "only annotate truthfully" to a **hard assertion**;
  from now on, regressions of the "module did not register its API" kind are caught by the tests directly.
- Verification: isolated headless run, status / help / opt_analyze / apply all pass (status returns `engine=BLENDER_EEVEE`); `npm test` all green.

### Change: `blender_rt_headless`'s path hint now branches per platform
- The old copy hardcoded `cwd is \\wsl.localhost\…\DSH, WSL absolute paths must carry a leading /`, which points at the wrong space on a Windows host.
- Now it branches on the new module-level `IS_WIN`: Windows hints "give a Windows path", WSL keeps the old hint.
- Description budget gate still green: rt_headless 1556 (< 1600), the 15 tools total 11944 (<= 12000).

### Includes
- This version uses `13a10bd` (ext install hint copy fix) after v1.0.0 as its baseline.


## v1.0.0 (2026-09-28) — first 1.0 release: the whole macOS GUI path works + outward capability freeze

> **1.0 = the capability freeze line**: the 15 model-facing tools + `blender_rt_plan` (28 families / 183 ops) are the stable outward surface;
> the package version (`package.json`), the tool description prefix (`[v1.0.0] …`) and the npm package name `@dsh-external/dsh-blender-plugin` all agree.
> **The only functional addition** relative to v0.9.6 is macOS support (see below); the rest is closing out existing capabilities + rewriting the README (Chinese and English) to "state only what 1.0 is",
> no longer listing history by version number — history stays in this file.
>
> **Two other actions in the same commit**:
> ① deleted the local and remote branch `backup/v0.9.6-local-0926-2005` (unique commit `0f99949`; after deletion no ref points at it any more;
>   look back locally with `git show 0f99949`, and if the remote has already been GCed it cannot be recovered) — from then on only `main` is kept and pushed;
> ② version number 0.9.6 → 1.0.0 (`PLUGIN_VERSION` in `package.json` / `src/index.ts` / `lib/index.js`), and `lib/` rebuilt.

On macOS the host and Blender are on the same machine and the same OS, so cross-OS path rewriting degenerates into identity.
Previously these rewrites glued `/Users/...` into `\\wsl.localhost\Ubuntu\Users\...` — Blender would silently fail to open it.
Windows / WSL behavior is unchanged (regression assertions guard it).

### Added

- `runtime/config.mjs`: `IS_MAC`; `winToWsl` / `wslToWin` return the original value early on mac;
  `detectBlenderExe()` additionally scans `.app` bundles (`/Applications`, `~/Applications`, `/Volumes/*/Applications`,
  supporting any version name `Blender*.app`); `resolveWorkDir()` now uses `~/.dsh-blender-rt`
  (**not into the system temp dir** — that gets cleaned out and frames and the ledger would be lost); `winLocalAppData()` no longer tries to call `cmd.exe`.
- `runtime/engine.mjs`: `blenderJoin()` absorbs the previously scattered `path.win32.join` (which produced `\Users\...` on mac);
  `withWslEnv()` returns immediately on the same OS (no more `WSLENV` stuffed into child processes); the python path helpers injected into Blender
  (`_dsh_slashes` / `_dsh_win_path` / `_dsh_wsl_path`) carry the `__DSH_NATIVE_POSIX__` render switch and are identity on mac;
  `PATH_GUARD` (the WSL-only `render.filepath` check) is turned off on mac, so a legitimate `/Users/...` is not misreported as a path problem.
- `src/index.ts`: `killBackendByCmd()` falls back to `ps -ax -o pid=,command=` when there is no `/proc`
  (macOS has no `/proc`; it previously returned `[]` silently, so a leftover backend could not be stopped after a hot reload).
- `tests/mac_selftest.mjs` (`npm run test:mac`): 45 assertions, pure Node + one real `python3` run that
  executes the injected path helpers; includes **regression protection** (asserting the WSL/Windows branches still exist, so mac support does not eat the original logic).

### Fixed

- `runtime/config.mjs`: `PATHS.livePngWin` / `PATHS.viewPngWin` hardcoded `path.win32.join` →
  produced `\Users\...` on mac, so taking a viewport screenshot failed silently (that path gets inlined into bpy scripts and is also handed straight to the addon).
- `runtime/qc.py`: the "is already an absolute path" criterion now also accepts a leading `/` (it used to accept only `X:` and `\\`).

### Real-machine verification (macOS arm64 + Blender 5.2.2 LTS + DSH Blender Bridge 1.7)

Path layer (`npm run test:mac`, 45 assertions, pure Node + one real `python3` run):

- headless run `status: finished` / exit code 0 / workdir·runId·env contracts correct;
- a real render produces a valid 160x120 RGBA PNG;
- `GPUOffScreen` custom-view self-check `gpu_init: ok`, `first_px == [25,153,51,255]`, projection error ≈1e-7
  (identical to the Windows reference values).

GUI channel (`npm run test:gui`, needs a real machine + addon) — **11/11 pass**:

- `blender_viewport op=doctor` / `op=status`: channel healthy, reads a real 3D viewport region;
- `blender_rt_see`: offscreen frame capture 148ms, valid RGBA PNG, written to `~/.dsh-blender-rt`;
- `blender_rt_see {from, look_at}`: custom view 178ms, coverage 26.8%, **the user viewport was not modified**;
- `blender_rt_do`: rewrites the scene + read-back verification passes; the persistent kernel `K` survives across calls;
- `blender_rt_cmd` / `blender_rt_commands` / `blender_rt_perf` / `blender_rt_opt` all normal;
- `blender_viewport op=launch` cold start: 2.5s from zero to a connected GUI Blender (previously a human had to click the panel).

`npm test`'s existing regressions (protocol / lease) are unaffected.


## v0.9.6 (2026-09-26) — upstream integration A1–A5 (sculpt/fix/UV/manufacture/sweep) + addon bumped to v1.7 + D1 tool discoverability

Source: `docs/upstream-integration-assessment-mcp-for-blender-and-blend-ai.md` (a measured inventory of ahujasid/mcp-for-blender and HoldMyBeer-gg/blend-ai).
In one line: **fill in the half both upstream projects lack** — neither upstream can do "procedural sculpting" (blend-ai's README admits it cannot simulate brush strokes),
so this plugin does it with a numpy displacement brush + topology preparation, turning it into a recomputable geometric operation; along the way it fills the uv/thin-wall/sweep gaps in the old runtime.

Added 5 runtime modules (21 ops, all through `blender_rt_plan`, no new tools):

| Module | op | Description |
|---|---|---|
| `sculpt.py` | scan / setup / apply / filter / mask / remesh / selftest / help | **numpy displacement brush** (draw·inflate·pinch·flatten·smooth·crease) + voxel/multires/subdiv/dyntopo + masking + GUI filters |
| `mesh_fix.py` | repair / decimate / selftest / help | audit only diagnoses, this one treats: merge duplicate verts / drop zero-area faces / delete loose verts / recompute normals / optional hole filling |
| `uv_tools.py` | stats / smart_project / unwrap / project / pack / selftest / help | the UV four-piece set; enumerations are read from the operator RNA, not hardcoded |
| `printcheck.py` | walls / overhang / report / selftest / help | BVH ray wall-thickness measurement + normal-cone overhang detection (no dependency on the 3D Print Toolbox add-on) |
| `sweep.py` | analyze / build / selftest / help | parallel-transport frame sweeping (no twist on bends) + bend radius computed before building |

### Measured numbers (local Blender 5.2.2 LTS)

- **Sculpt**: voxel remesh 1986 → 12148 vertices in **0.084 s**; a single stroke on 1986 vertices, 257 vertices affected, **6 ms**;
  `sculpt_selftest` runs apply+remesh+mask+scan on a temporary sphere, measured affected=65 / max_delta=0.223 / remesh 3120 vertices.
- **Fix**: `fix_selftest` synthesizes a defective mesh (7 boundary / 1 degenerate / 1 loose) → after the fix degenerate=0, loose=0, truly non-manifold=0.
- **Manufacturing check**: 200×200×5 mm thin plate (4 mm faces) @min_mm=10 → min=median=5 mm, thin=5000, **no warnings** (positive case);
  voxel sphere (47 mm faces) @min_mm=5 → min=1686 mm, thin=0, and it explicitly warns "min_mm is below the measurement resolution, the conclusion is untrustworthy" (no fake conclusions).
- **Sweep**: straight tube, 3 stations, 12-gon = 38 vertices / 48 faces; right-angle path min_radius=0.424 vs required 0.05 → passes;
  a too-tight path min_radius=0.014 < 0.2 → **rejected**, naming which point index it is.

### Key conclusions (written into the tool descriptions and the skill, so nobody has to step on this again)

- **`bpy.ops.sculpt.brush_stroke` does not work from Python on Blender 5.2**: the context is already solved
  (poll()=True after `temp_override`), but the `stroke` collection rejects dicts on the RNA side (all 6 formats fail),
  and `OperatorStrokeElement` cannot be instantiated either. So sculpting takes the "displacement brush" route; stop spending time constructing strokes.
- Symmetric mirroring must **each become an independent brush stroke** (caught in practice during development: stringing the mirrored points into the same polyline makes 1 point interpolate into 39 dabs and smears the surface).
- Wall-thickness measurement has a **resolution floor = the local face size**: a 60 mm face from voxel remeshing cannot measure a 5 mm wall — the receipt must give `resolution_mm`.

### Pre-existing defects fixed along the way

- `audit.py`: an empty mesh (0 edges) crashed the check with `me.edges[0]` IndexError → it now reports `empty` and counts
  `empty_objects` into `clean=false` ("built an object but never filled faces" no longer masquerades as healthy).

### Wiring and docs

- `engine.mjs`: 5 new prefix routes (sculpt_/fix_/uv_/print_/sweep_) + module injection (needFile fallback); `server.mjs`:
  11 read-only ops into the whitelist (scan/help/stats/walls/overhang/report/analyze…), write ops still go through the lease.
- `lib/index.js`: the `blender_rt_plan` tool description now covers the parameters and hard rules of the 5 capability surfaces (**takes effect on the next DSH start**).
- skill `blender-modeling`: added Recipe 11–14 (sculpt / fix+UV / manufacturing check / sweep), and corrected the old claim in the decision tree
  that "stroke-style sculpting is not suitable for text-driven workflows" (what it gives now is a measured conclusion at the API level).

### addon upgrade: v1.6 (protocol 5) → v1.7 (protocol 11)

- **Landing**: replace @@C:\Users\<user>\AppData\Roaming\Blender Foundation\Blender\5.2\scripts\addons\blender_mcp.py@@
  (the module name stays @@blender_mcp@@ so no duplicate entry appears in Blender preferences), the source file is taken from the PyPI sdist
  @@mcp-for-blender-2.1.0@@'s @@src/blender_mcp/bundled/addon.py@@ (sha verified identical).
- **Rollback points** (two copies, md5 already compared as @@50dfd58290e5eb34c2a2fd9fae3f6f23@@):
  @@blender_mcp.py.v16.bak@@ in the same directory and @@dsh-blender-plugin/tmp/backup/blender_mcp_v16.py@@.
- **Restart**: @@Stop-Process blender -Force@@ → @@blender_viewport(op="launch")@@ (5.7 s to listen on 9876, doctor healthy right after).
  ⚠ after the upgrade Blender **must be fully restarted** (a script reload leaves the old socket thread behind), consistent with the upstream notes.
- **New capabilities (measured)**: @@get_addon_info@@ returns @@addon_version":[1,7],"protocol_version":11@@, capabilities 9 → 11 entries;
  @@rt_commands@@ available commands 15 → **19** (new @@describe_node_type@@ / @@bpy_api_lookup@@ / @@export_scene@@ / @@get_tripo_status@@,
  already added to @@COMMAND_CATALOG@@). All three new commands ran for real on the spot:
  @@describe_node_type("ShaderNodeTexNoise")@@ returns a 3307-character property table; @@bpy_api_lookup("bpy.ops.mesh.primitive_uv_sphere_add")@@
  returns the operator signature; @@export_scene(filepath=..., format="glb")@@ exports 1936 B (Cube/Light/Camera).
- **Protocol layer**: the flat protocol is unchanged (@@{type, params} → {status, result}@@), the plugin's @@addonProtocol=auto@@ needs no change;
  the protocol label in @@addon-protocol.mjs@@ no longer hardcodes "v1.6" (it now says "measured working with both v1.6/protocol5 and v1.7/protocol11"),
  @@protocol_selftest@@ 28/28 still green.
- **Post-upgrade regression**: all five module selftests green, @@rt_do@@ works, @@audit_mesh(Cube)@@ clean, @@qc_render_views@@ renders normally, @@rt_see@@ 161 ms.

### D1 · Tool discoverability (forced out by measured data)

- **Evidence** (the plugin's own trajectory logs, 8,116 calls over 10 days): the plan channel is only **1.6%** (excluding selftests),
  the five families `sculpt_* / fix_* / uv_* / print_* / sweep_*` saw **0 real uses**; of the 111 failures **68% are timeouts**,
  and only 3 are genuine "wrong channel/parameters" ⇒ the bottleneck is "**not knowing it exists**", not "errors".
- **`op="catalog"`**: 16 family / 117 op of "when to use / when not to use / minimal args skeleton / key points",
  **served locally by the plugin** (no Blender round-trip, askable under any lease); `args={family:"sculpt"}` expands one family (about 600 characters),
  `args={full:true}` gives the structured detail. Default text 5.1k characters (≈1.3k tokens, fetched on demand, not resident).
- **Description compression**: `rt_plan`'s description **4,708 → 1,496 characters** (the schema of all 15 tools 24,028 → 20,816 ≈ **~800 tokens saved per turn**),
  the long tail moved into the catalog (progressive disclosure: description = index → catalog = criteria → `<family>_help` = operator detail).
- **Errors teach**: an unknown op returns `did_you_mean` (nearest neighbor + skeleton, measured `audti_mesh→audit_mesh`, `sculpt_appli→sculpt_apply`);
  sending a plan op to `rt_cmd` as if it were an addon command returns `CMD_HINT` and is stopped **locally** (measured: `qc_render_catalog` really did take the wrong channel once).
- **Trajectory gains fields** `family` / `args_keys` / `hint_shown`: used for "family coverage" and "intent→tool" weekly reports (parameter values are not recorded, only key names).
- **AGENTS.md (global + workspace) gained an "intent→call" table + three protocols**: ① run `doctor` first; ② when unsure, run `op="catalog"` first;
  ③ when you see `did_you_mean`/a correction hint, just do what it says. The table explicitly says "**heavy work >1 min goes through `rt_job`**" (aimed at that 68% timeout figure).
- **Regression**: `tests/discoverability_selftest.mjs` **26 items all green** (catalog size/one family/nearest neighbor/cross-channel correction/description budget/real HTTP routing),
  merged into `npm test`; `npm run test:discover` runs it on its own.

### D2 · Description budget (the schema of the 15 tools from 17,147 → 11,213 characters)

- **Same-convention measurement** (only what is really sent to the model: `description + parameters`): v0.9.1 13,671 (largest tool 2,829) →
  v0.9.4 17,147 (largest **4,020**, rt_headless) → now **11,213** (largest 1,437) ≈ **~1,480 tokens saved per turn**.
- **Approach**: heavy tools' descriptions keep only an "index" (purpose + 3 hard rules + pointers), each parameter gets one sentence; timeout semantics/path semantics/shots/
  preload/env/receipt fields/common pitfalls and other long tail moved into `blender_rt_plan(op="catalog", args={tool:"rt_headless"})`
  (served locally by the backend; 7 heavy tools: rt_headless / rt_job / rt_worker / rt_see / rt_loop / viewport / rt_plan).
  Three-level progressive disclosure: tool index → family → operator detail, all fetched on demand and never resident.
- **Anti-bloat gate**: `tests/discoverability_selftest.mjs` gained 4 budget assertions (single tool < 1600 characters, total <= 12000,
  rt_headless < 1600, every heavy tool has a detail entry), **35 items all green**, merged into `npm test`.
- ⚠ When it takes effect: descriptions live in `lib/index.js` and become visible to the model **on the next DSH start** (catalog/error-correction/detail live on the backend side and take effect as soon as the backend restarts).

### A6/A7 · Material node graphs + render state tracking (two pieces built against real usage)

**A6 materials (material_*, 6 ops)** — measured motivation: across the 7,182 scripts in the workspace, `nodes.new()/ShaderNode` hits
**2,732 times / 204 files**, and every build script hand-writes TexCoord→Mapping→Noise→ColorRamp→Principled again;
and OBJ/MTL delivery loses procedural nodes.
- `material_build`: 10 presets (metal_brushed / metal_paint / rust / plastic / glass / fabric / wood /
  concrete / emission / hologram / unlit), builds the graph and wires it in one call, parameters can be overridden (base_color / scale / bump / ior…)
- `material_scan` (read-only): node count/type distribution/texture dependencies/procedural/needs_uv/who uses it
- `material_apply`: apply by object or collection (replace / append semantics)
- `material_bake`: **bakes procedural materials into PNG** (Cycles: DIFFUSE/ROUGHNESS/NORMAL/AO/EMIT/COMBINED),
  restores the engine automatically when done — this is the bridge from "procedural material → deliverable texture"; hook up deliver_export and you deliver with materials
- Measured: `material_selftest` green (build 7 nodes/7 links → apply → scan recognizes procedural+needs_uv → AO 128px written, 473 B);
  real-machine E2E: rust preset @256px DIFFUSE bakes a **58,466 B** PNG

**A7 render state tracking (render_state / render_wait / render_reset / render_guard_install / render_guard_selftest)**
— measured motivation: of the 111 failures **76 are timeouts**, and a render hogging the main thread is one of the main causes; the workspace runs `render.render` 362 times / 334 files.
- **Design**: do not "ask Blender" (asking queues anyway while rendering); instead `bpy.app.handlers` (render_init / render_complete /
  render_cancel / load_post) **write a disk marker** when rendering starts and delete it when it ends; the backend (Node) reads the file and **judges busy in a second**
- **Behavior**: commands written from the main thread during a render **answer `BUSY_RENDER` in a second** plus a next step like "use render_wait or switch to rt_job"
  (ping is outside the interception range: it goes through the addon server thread and works while rendering → doctor can still judge main-thread-busy)
- Measured: a real 720×480/256 samples EEVEE render → busy was observed in **1.29 s** and cleared in **2.30 s**;
  **sending rt_do during a render ⇒ rejected in 71 ms** (it used to queue until timeout); the real wait path of `render_wait` waited **9,392 ms** for the render to finish
- Fallback: a stale marker is automatically judged stale and let through after 15 min (`DSH_RENDER_STALE_MS` adjustable); load_post clears markers; `render_reset` clears manually

**Wiring**: catalog 16 → **18 family / 117 → 128 op**; read-only whitelist +6 (material_scan/help, render_state/wait…);
the headless integration selftest **23 → 34 assertions** (new material chain and guard install/mark/clear).
⚠ When it takes effect: catalog and guard are in the backend (effective on restart); tool descriptions are in `lib/index.js` (next DSH start).

### D30 · Runtime-layer hardening (7 field reports, fixed in one pass, in order)

The field conclusion was "the methodology layer holds up, the runtime layer drags behind". Item by item:

| # | Field problem | This batch's change | Verification |
|---|---|---|---|
| ① | `/mnt/d` turned read-only ⇒ the backend cannot write status/ledger and will not start; the error only says "look at the backend log"; 9877 is held by a dead process (EADDRINUSE) | `config.mjs` adds a **workDir write probe + fallback** (original candidate → package-local `tmp` → OS tmpdir, **a fallback always leaves a trace** `CFG.workDirFallback{requested,why,used,errs}`); `server.mjs` adds explicit `EADDRINUSE` wording (stating "a dead backend holds the port" plus what to do) and writes `backend-listen-error.txt` to disk | Simulated unwritable: `DSH_BLENDER_WORKDIR=/etc/hostname/nope` ⇒ automatically falls back to `dsh-blender-plugin/tmp`, `writable=true`, `why=ENOTDIR…` ✅ |
| ② | once the backend dies, headless/job/do are all dead; there is no official offline channel (users hand-roll 15 lines to recover) | new **`runtime/offline_bootstrap.py`**: builds `dsh_rt_kernel` → injects the kit → loads modules by name, `kapi(name)` gets the API; supports `blender -b --python … -- vehicle audit` and in-script `ob.boot([...])` (same contract as the online path) | Real machine: `blender -b --factory-startup --python runtime/offline_bootstrap.py -- vehicle audit` ⇒ **`OFFLINE_BOOTSTRAP ok · loaded: audit, vehicle`** ✅ |
| ③ | `K` is not visible inside imported `lib/*.py` (the recommended usage conflicts with the implementation) | `kit.py` adds **`kapi(name)`** and **`install_kernel(ns=None)`**; the docs give the official one-liner `import sys; K = sys.modules["dsh_rt_kernel"]` | The offline path was really measured with `kapi("generator")` → `Api` ✅ |
| ④ | preload module names were guesswork | `kapi` errors list the loaded modules; the engine's `preload module not found` error **lists every available module name** and gives a `preload="vehicle,audit"` example plus a pointer to the offline escape hatch | syntax/unit tests pass ✅ |
| ⑤ | return types were inconsistent (`dsh_audit_api` returns a dict, the skill example wrote a JSON string) | the skill gains **§0.71 call conventions**: `api(op,args)`→dict; `api["dispatch"](op,json_str)`→str (you have to loads it yourself); naming rules for `kapi()`/`install_kernel()`/`preload` + the offline escape hatch | skill written ✅ |
| ⑥ | `audit_gate`'s assembly semantics were never spelled out (a 222-piece vehicle can never pass the connectivity gate) | the catalog's audit family `not` now says it plainly: **the connectivity gate uses the "single hull" convention (0.3 mm by default)**; for multi-part models adjust `micro_gap_mm`(1–2 mm) or go through `gate_plan(preset="assembly")`; skill §0.71 uses the same convention | discoverability 51/51 ✅ |
| ⑦ | Blender 5.2 compositor drift (`scene.node_tree` removed; Glare `mix`, Mix `blend_type` renamed) blew up AttributeError from deep inside the plugin helpers | `kit.comp_tree(scene)` **tolerates versions when getting the compositor tree** (5.2 `compositing_node_group` → old `node_tree`), and when it cannot get one it spells out the version convention and the rename list | registers and works on a real 5.2 (`material.py`/`qc_render.py` themselves use the material `node_tree`, unaffected) |

**Regression**: `npm test` **exit=0** (13 steps) · discoverability 51/51 · guidance passes · `py_compile` all pass · offline escape hatch passes on a real machine.

**Still not done** (next batch): full 5.2 property fallbacks for `remap`/mixed nodes (needs a real-machine version matrix); `workDir` fallback info is currently only in `describeConfig()`/`CFG`, and field exposure in `/status`+`/health` is not wired yet.

### D29 · Fix `blender_viewport(op="launch")`: the S3-c move left 4 dependencies behind (field report)

**Scene**: both `op=launch` and `dry_run` failed outright with `tcpProbe is not defined`, and users could only light up the GUI by writing their own boot script + PowerShell spawn.

**Root cause (my fault)**: when S3-c moved `launchBlender` from engine.mjs to `launch.mjs`, **only the function body was moved, not its dependencies**. What surfaced one by one was:

| Dependency | Defined in | Handling |
|---|---|---|
| `tcpProbe` | engine.mjs | reuse `probeTcp` from `runtime/backend_probe.mjs` (same semantics, single implementation) |
| `BLENDER_EXE` / `USER_CONFIG_WIN` / `USER_SCRIPTS_WIN` | paths.mjs | add the imports |
| `writeHeadlessScript` | engine.mjs | **extracted** into `runtime/staging.mjs`; engine imports it by name + re-exports (export surface unchanged) |
| `baseChildEnv` / `withWslEnv` / `readJsonSafe` / `workdirStagingWarning` | engine.mjs | **extracted** into `runtime/proc_env.mjs`; engine imports them (`readJsonSafe` stays engine-local and does not enter the export surface) |

**Anti-recurrence**: added `tmp/dep_scan.py` (mechanical scan: take the top-level names launch.mjs uses that are defined in engine/config/paths/staging/proc_env/backend_probe, subtract its imports and local declarations ⇒ list the missing dependencies).
This time it listed them all in one go instead of being found one by one by trial.

**Verification (real-machine END-TO-END)**:

```
dry_run   → LAUNCH ok · gives the blender.exe path + boot script path (no longer throws)
real launch → LAUNCH ok · spawned pid=2607071 · addon port 9876 listening (5689ms)
doctor    → ok
```
(incidentally, it brought back the Blender the user had already quit.)

Regression: `npm test` **exit=0** (13 steps) · Blender side **263 assertions** all green.

**Lesson**: a "move a function" like S3-c must **move the dependencies**, and right after moving you verify with a mechanical scan (not by calling it once and reading the error). This discipline is recorded in the CHANGELOG.

### D28 · Fix a batch of refactor leftovers (all hidden inside tests that "looked green")

While fixing `op=start` I also judged `npm test` by **exit code** (before that I judged by `grep failed|✗`, which missed three kinds of silent failure), and dug out 4 real problems:

| # | Problem | Root cause | Fix |
|---|---|---|---|
| 1 | `/plan op=catalog args={verify:true}` throws `ReferenceError: ENGINE_SOURCE_PATH is not defined` | when **S3-a** moved `probeDiskCatalog` into `catalog.mjs`, the three imports `ENGINE_SOURCE_PATH` / `pathToFileURL` / `execFileSync` did not come along | catalog.mjs got all three (`ENGINE_SOURCE_PATH` resolved from this module's location, same directory as engine.mjs) |
| 2 | importing `generator.py` in pure python gives `NameError: _KIT` outright | when **S1** unified the kernel, `_KIT` was only defined **inside the POSTLUDE string** (used for injected generator scripts), yet module top level used it — on the Blender side a preload namespace bleed masked it | module top level resolves it explicitly + errors clearly when missing; `tests/generator_dispatch_selftest.py` injects the kit first in a fake kernel (pure python path) |
| 3 | `catalog`'s default page was 10,410 characters (the guard limit is 9,600) | **S6**'s hard warnings + hint lines added for 13 families stretched the one-page index | the default page shows only the actionable warning and caps skeletons at 160 characters (full content is still in `args={family:…}` and the handoff block); now **9,442 characters** ✓ |
| 4 | `mac_selftest`'s `/mnt/` guard and `provenance_stale_selftest`'s C series failed | **S3-b** moved PATH_HELPERS into `paths.mjs` and **S3-a** moved the catalog into `catalog.mjs`, but these two guards were still modifying/reading `engine.mjs` | the guards now read engine + paths; provenance targets the **catalog copy**, family count 27 → 28 |

Also fixed the **classification convention** of the routing contract test: `parameter mismatch + did_you_mean` actually proves the **routing is connected** (only empty args are wrong), which used to be misjudged as "routing failed" ⇒ now parameter-kind errors are excluded first, and the real machine is back to **70/70**.

**Process lesson (writing it down)**: the several times I said "npm test all green" earlier were **inaccurate** — the criterion was `grep failed|✗`, while `mac_selftest` prints `FAILED`, `provenance` exits non-zero silently, and `pyrun` throws a traceback outright; all three slipped past grep. **From now on it is always judged by exit code**:

```
npm test > /tmp/nt.log 2>&1; echo "exit=$?"     # only exit=0 counts as green
```

**Verification**: `npm test` **exit=0** (13 steps all pass) · routing contract 4/4 (static 28/28 · real machine 70/70) · Blender side 263 assertions all green · `pyrun` generator 13/0 · provenance 16/0 · mac 7/0.

### D27 · Fix bug: `blender_viewport op=start` trusts a stale handle and answers "already running" even when the port is not listening

**Symptom (twice in the field)**:
- ① `op=start` answers "backend already started (already-spawned)" → right after, `doctor` fails and `curl /doctor` times out at 4 s: **9877 is not listening at all**;
- ② another time it really did start, but answered "startup failed: spawned pid=…" because the wait window was too short.

**Root cause**: `startBackend()` only looked at the child-process handle `childAlive()` (exitCode/signalCode/pid) and **never probed the port**; the wait was "sleep 20×300 ms, then probe once".

**Fix**:

1. new `runtime/backend_probe.mjs` (+ `backend_probe.d.mts`): `probeTcp` / `probeHttp` /
   `decideStart({portUp, childAlive})` (pure function, three states) / `waitHttp(url, timeout, interval)`;
2. `startBackend()` now **probes the port first**:
   - the port serves ⇒ `already-running` (one started by another session counts as running too, never start a duplicate);
   - the port is down but the handle is still there ⇒ **`stale-handle`**: SIGTERM clears the stale handle and then it starts over (this is the bug that got fixed);
   - otherwise `spawn`;
3. the wait in `op=start` / `op=restart` became `waitHttp(…, 15000, 300)` — **poll until it really serves** (no more fixed sleep window), and failures carry a hint about the fix (`op=restart` clears the leftovers);
4. the `startBackend` calls in the watchdog and the command path became `await` (the function turned async).

**Verification**:

- unit test `tests/backend_probe_selftest.mjs` (already on `npm test`) **10/10**: TCP+HTTP probe true/false with the service up and down, the three-state decision table, `waitHttp`'s "late success" and "pure timeout honestly returns false", and probing the real backend;
- **equivalent E2E (real environment)**: stop the backend → create the stale state "handle alive, port dead" → decision **`stale-handle`** (the old implementation answered `already-spawned` here) → clear the stale one → start over → poll until it serves ✅;
- `lib/index.js` mirrored in sync and passed `node --check`; `npm test` all green; `doctor` = ok.

**Effective conditions and honest boundaries**:

- the plugin is a module **loaded at DSH startup** ⇒ this fix **needs a DSH restart to take effect** (the backend side needs no restart);
- this machine **has no tsc** (this package does not install typescript, and neither does the DSH host) ⇒ `lib/index.js` is a **manual mirror**, semantically consistent with `src/index.ts`;
  running `bash scripts/build.sh` on a machine that can build should produce an equivalent result next time (the build output wins then).

### D26 · S6-b: subagent handoff block — solving "the main model can use the tools, subagents cannot"

**Field feedback**: "after enabling subagents, the main model read the catalog and could use the tools, but the subagents did not read the catalog."

**Why that happens**: subagents are **self-contained contexts** — they cannot see the catalog the main model read; and they tend to write Python directly (`rt_do` / `rt_headless`), bypassing the plan channel.
The consequence is one of the causes of that "soap car": subagents **invented geometry**, wrote their own criteria, and the plugin's `vehicle_*` / `shape_*` were all for nothing.

**Delivery**:

1. **One command gets a pasteable handoff block** (verified on a real machine):
   ```
   blender_rt_plan(op="catalog", args={handoff:true})
   ```
   ≈**2,545 characters** (fits in a subagent prompt): 15 tool names + 12 modeling classes (first step / forbidden to invent) + three hard rules + channel discipline;
2. the **catalog front page** gained a hint line pointing at it (visible when the main model looks at the catalog);
3. **the rule is written into both injected places** (subagents read them too): the workspace `AGENTS.md` "when dispatching subagents (mandatory · measured lesson)" + the start of skill `SKILL.md` §0.5;
4. **mechanical guard** (`tests/guidance_selftest.mjs` 6 → **11 items**): the handoff block exists · **≤3500 characters** (stays pasteable) · covers all 12 classes · contains "forbidden to invent/three hard rules" ·
   `MODEL_FACING_TOOLS` and the 15 tools in `capability.lock.json` **match name by name** (so the handoff block does not go wrong after a rename).

**Verification**: guidance selftest 11/11 · capability lock PASS (28/183/15) · routing contract 28/28 + 70/70 · `npm test` all green · real machine `args={handoff:true}` returns the handoff block ✓

**Boundary (honest)**: the handoff block still needs the **main model to paste it on its own** (the plugin's mechanism can guarantee "the command exists and its content will not rot", it cannot force a given model to use it);
writing the rule into AGENTS.md is to make **every** new context (subagents included) see this requirement. The real cure is still a mechanical gate (next step: a `vehicle_shell` gate preset + credentialized proportion gates).

### D25 · Acceptance no longer degrades with scale (the 7 face-count thresholds now default to "unlimited, run everything")

**Requirement**: cancel "acceptance degrades with scale" — every face count must get the full analysis and a real conclusion, not "skip above the threshold / degrade to bbox".

**Change**: the default of 7 threshold constants became `0 = no limit`, and every check got a `cap > 0` precondition (**only** when an env var / parameter is set explicitly is a limit enabled, and then behavior matches the old version):

| Constant | Old default | New default | Location |
|---|---|---|---|
| `SHELL_MAX_FACES` | 300,000 | **0 (unlimited)** | `audit.py:181` (per-shell orientation)|
| `CONN_MAX_TRIS` | 4,000,000 | **0** | `audit.py:792` (connectivity/floating parts)|
| `BVH_MAX_TRIS` | 500,000 | **0** | `audit.py:1799` (mesh-level recheck / interference BVH)|
| `PAIRS_BBOX_CAP` | 200,000 | **0** | `audit.py:2205` (overlap pair statistics)|
| `MATE_MAX_TRIS` | 2,000,000 | **0** | `contract.py:59` (mating gate)|
| `INSIDE_MAX_TRIS` | 200,000 | **0** | `contract.py:60` (ray inside test)|
| `VOL_MAX_TRIS` | 60,000 | **0** | `contract.py:62` (volume estimate)|

**Measured at scale (1.57M triangles: cube + subsurf 8 double layer)**:

```
connectivity   analyzed=true  gate=pass   28.1 s   ← old behavior: >500k faces skipped the mesh recheck → attached=null → gate degraded
audit_mesh     verdict=pass               9.9 s    ← old behavior: >300k faces made per-shell orientation unknown → state=degraded
interference   ok=true analyzed=true      runs     ← old behavior: this line in the gate took "0" as the limit and errored out (see below)
```

**Two-sided verification (default vs explicit)**: default `analyzed=true / gate=pass`; `DSH_CONN_MAX_TRIS=1000` → `analyzed=false / gate=degraded` + the reason spelled out; removing the env → `pass` again.

**How the fix went (recorded honestly)**: the first pass changed only 13 defaults and checks; running the regression, `gate_review` **5 failures** exposed 3 more comparisons without the precondition (`audit.py:2693`, `audit.py:2824`, `contract.py:1529`) — they treated `0` as "limit 0", so even a 12-face cube was judged "over the limit → do not analyze". After filling those in, **263 assertions all green**.
(One more note: the "all green" I posted the first time was a **false report** — I had truncated the output before checking and did not match the fail count; after that I switched to judging the full text.)

**Docs synced**: `docs/operation-tutorial.md` · `docs/evidence-grading-and-image-reading.md` · `docs/zh/README.md` · skill `SKILL.md` (2 places), **5 places** in total, changed the old convention ("face count above 500k skips the recheck → gate degrades") to "**unlimited by default, run everything**; only an explicit limit degrades".

**Cost (honest)**: running everything costs something — at 1.57M faces `connectivity` takes 28 s and `audit_mesh` 10 s; bigger models get slower (BVH construction is linear in face count and per-shell orientation is a Python loop). Three ways to go faster:
① per-part analysis (`objects:["A","B"]` narrows the scope) ② `fix_decimate` down under the threshold and then verify ③ chunked / vectorized optimization later (not done yet).

### D24 · S6: modeling-class guidance — telling the model "which tools to use for each class of modeling, and what it is forbidden to invent"

**Motivation (measured)**: another modeling AI had the `vehicle_*` recipes in hand and knew Recipe 17/18/19 and Recipe 22, and **still wrote its own parametric loft** ⇒
what it rendered was one continuous smooth surface: no crease lines, no panel gaps, 6 structural defects (pointed beak / floating flat plate / bulge / floating tail plate / isolated fin / no edges and no seams).
The root cause is **not missing docs** (SKILL.md has the car-shell recipe at lines 1030–1136, Recipe 22 at line 1141, `crease` appears 9 times), it is that all three of these were missing:
**an entry point** (which command to type first), **forbidden inventions** (nobody stopped them), **an acceptance gate with a numeric criterion** (nothing goes red for "ugly").

**This batch's delivery**:

1. **`runtime/classes.mjs`** — guidance for 12 modeling classes, four things each: first step / operator chain / forbidden to invent / acceptance gate:
   `recon · faceted · smooth · organic · repeats · boolean · human · sweep · rotational · plate · assembly · deliver`
2. **How the model queries it** (verified on a real machine): `op="catalog", args={classes:true}` gets all 12 classes · `args={class:"sweep"}` gets one class; the catalog front page gained a pointer hint line;
3. **hard warnings added to the 13 catalog families** — e.g. `vehicle.not` now states plainly "**do not write your own parametric loft** — inventing it only gives one continuous smooth surface (a soap with no edges and no seams); car shells always go `vehicle_sections → vehicle_loft → vehicle_panels`";
   same batch: `shape` (do not hand-compute a station table) · `sweep` (do not hand-join path segments) · `generator` (do not write a one-off loop) · `uv` (do not place UVs by hand) · `material` (do not hand-build node trees) ·
   `deliver` (do not hand-write the export) · `gate` (do not write your own criteria) · `motion` (do not hand-pose) · `human` (do not invent proportions) · `img` (do not estimate dimensions by eye) · `audit`/`qc` (do not eyeball instead of checking/accepting);
4. **mechanical guard `tests/guidance_selftest.mjs`** (already on `npm test`, 6 items):
   ① all 12 classes have every field and `forbid` must be hard wording; ② the ops / tool names mentioned in the guidance **must really exist** (so a rename does not turn it into wrong directions);
   ③ the `not` of all 13 families must carry a hard warning (so it does not get deleted).

**Companion skill** (`dsh-skill-blender-modeling`): `SKILL.md` gained **§0.7 modeling class → tool directions** (12-class table + three hard rules + query command),
and mentions of `shape_plan` in SKILL.md went **0 → 4** (before that, a model that only loaded the skill could not learn about this single entry point).

**Verification**: capability lock PASS (28 family / 183 op / 15 tools) · guidance selftest 6/6 · routing contract 28/28 + 70/70 · `npm test` all green · Blender side **263 assertions** all green · real-machine catalog query passes.

**Boundary (honest)**: the guidance is still "docs + queryable" and **has no enforcement** — what can really stop "inventing a loft" is a mechanical gate (next step: turn panel-gap/feature-line counts, connected components and floating parts into a `gate_run` `vehicle_shell` preset).

### D22 · Routing contract test (a precondition for splitting createEngine, and it already caught a real bug)

The existing 263 assertions lean toward "domain correctness" and do not cover "every op can be routed to" — which actually got hit twice in these rounds (the catalog omitted `vehicle_loft`, the `perf` module had no dispatch).
Added `tests/route_contract_selftest.mjs` (`npm run test:routes`), two layers:

1. **Static**: read `PLAN_CATALOG`, assert that the prefix of all 28 families has a route in `engine.mjs` (recognizing all three forms `p: 'x_'` / `indexOf('x_') === 0` / `startsWith('x_')`; families with an empty prefix fall through to the plan/contract fallback);
2. **Real machine**: call the `/plan` read-only whitelist (70 ops) **one by one with empty args** and judge only "is the route connected" — `ok:false` / parameter-validation errors all count as normal (what must be proven is "it is connected", not "empty args also run").

**It caught a real bug on the very first run**: `render_lock_status` (a read-only op in the whitelist) was split straight into `lock_status` and sent to `qc_render`, which the module does not recognize ⇒ `unknown qc_render op`.
Measured comparison: `render_status` passed instead (`qc_render`'s lock query op is simply called `status`) ⇒ aliased to `status` and normalized, the problem disappeared.

Now: **static 28/28 · real machine 70/70 routable** (normal receipts 47 · empty args rejected 22 · degraded 1).
**Skipped** when the backend/Blender is absent (exit 0), so it does not block offline `npm test`.


### D23 · On-demand kit execution: 7.45ms saved per call (measured)

`kit.py` (10.7KB) used to be embedded in `KERNEL_BOOTSTRAP` and **exec'd on every execute_code**. Measured directly inside Blender:

```
kit full exec      7.451 ms/call
conditional exec (already injected)  0.0006 ms/call     => saves 7.45 ms/call (~5% of the 163ms round trip)
```

The change (**zero risk**): the source is still sent as before (local socket transfer is negligible), but wrapped in a condition:

```python
if getattr(K, "dsh_kit", None) is None:
    <full kit.py, uniformly indented by 4 spaces>
```

So the persistent kernel (every plan/act path on the GUI side) really runs it only the **first** time, and rebuilds automatically after `K` is cleared (Blender restart); the headless/job path (`blender.exe -b`, where K is always new) is unchanged — no state flag or extra round trip needed.

Measured: `rt_do` round trip 163ms → **97ms** (including other changes in this session; the conservative figure is the "in-Blender exec 7.45ms") · Blender side 263 assertions all green · routing contract 4/4.

### D21 · S5-b: @references in single-shot ops (no longer limited to pipe_run)

Previously `@artifact` was only resolved inside `pipe_run` — a single `blender_rt_plan(op="vehicle_loft", args={"stations":"@sec.stations"})` would use the string as the parameter. This batch makes it **usable in single-step calls too**.

**Implementation path (one detour taken, recorded honestly)**: at first I wanted to wrap a resolution layer uniformly in the **engine routing layer** (patching around `_json.loads`), and every plan call then reported `JSONDecodeError`. A controlled test (everything normal after stashing the change) confirmed the routing change was the cause — **dropped it decisively** and switched to **module-level resolution** (a far smaller risk surface):

- `kit.resolve_refs(value, skip_keys=("out", "steps"))`: recursively resolves `"@name[.path]"`, throws KeyError when the reference does not exist (including the existing artifact names);
  `skip_keys` is **mandatory** — `pipe_run`'s `out="@h"` is an **output name**, and `steps` is resolved in order by pipe_run itself (otherwise "step 3 referencing step 2's output" would be resolved early and error out);
- `kit.dispatch_table` resolves after flattening ⇒ covers every module registered with `_KIT.register`;
- the hand-written dispatch in `vehicle.py` / `gate.py` / `imgtools.py` each got a pass inserted (these three are the most used consumers in the chain).

Measured (real machine): first `pipe_run` stores `@sec`, then a **single** `vehicle_loft(stations="@sec.stations")` ⇒ builds the shell directly (4289×597×708mm / 21 stations); when the reference does not exist it returns a readable error: `reference resolution failed: referenced a non-existent artifact @nope (existing: sec, n2)`.

**One more pitfall stepped on**: after changing `kit.py` I forgot to restart the backend ⇒ the test still ran the old kernel (`KIT_SRC` is read when the engine starts), which looked like "the change did not take effect".

Regression: Blender side **263 assertions** (integration 124 + audit 78 + gate 52 + module selftests 9) all green · capability lock PASS · npm test all green.

### D20 · S1-b wrap-up: selftests for the 10 "no selftest" modules (refactor blind spots cleared)

During the refactor I found that the 10 modules `contract / deliver / montage / perf / planner / presets / qc / runner / txn / worker`
**had no selftest** — breaking them went unnoticed (they were the blind spot when the earlier batches migrated them). This batch added 9 (worker is the entry script of the hot headless session,
not a K-API module, explained separately).

Every selftest is **self-contained**: create temporary objects/data → verify the core mechanism → clean up.

| Module | What it verifies (evidence excerpt) |
|---|---|
| contract | reset → register a real component → status count ≥1 → reset |
| deliver | build a temporary cube → export OBJ → the file really lands on disk → verify against md5 |
| montage | build two 8×8 PNGs → montage into 2 columns → the artifact lands on disk |
| perf | ops complete + status/apply/revert runnable (**this module is called directly by engine and registers no K API** — stated honestly) |
| planner | status / diag / graph all return structured receipts |
| presets | save → get → apply to a real object → **values really take effect** (location 1,2,3) → delete |
| qc | **IoU verified against a known answer** (50/50 masks, intersection 25, union 75 ⇒ 1/3) + resize + profile |
| runner | status readable when idle + help structured (no real loop started) |
| txn | mark → really change the transform → revert → **the transform is really restored** + the list is readable |

**New suite** `tests/modules_selftest.py` (9 items, independent regression): `HEADLESS {pass:9, fail:0}`.

**kit extension**: added `_KIT.wrap_dispatch(base, extra)` — attaches extra ops to an existing dispatch instead of rewriting each module's differently shaped hand-written op table
(this also incidentally exposed a real inconsistency: `perf.py` never registers its own API at all, its tail only holds a compatibility shim).

**Pitfalls recorded (all measured)**: ① an insert that passes `py_compile` can still be a syntax error (I inserted the selftest key **outside** the dict and compounded it into `},,`);
② helper functions appended to the **end** of a function ⇒ `UnboundLocalError` (Python treats the name as local, the call comes before the assignment);
③ a `kit.py` change needs a **backend restart** to take effect (`KIT_SRC` is read when the engine starts; the fingerprint only affects module re-injection);
④ `presets.apply`'s `targets` must be passed a **list** (a string gets split character by character).

Regression: Blender side **261 assertions** (integration 122 + audit 78 + gate 52 + module selftests 9) all green · capability lock PASS (28 family / 183 op / 15 tools) · npm test all green.

### D19 · S5: pipeline layer (artifact registry + @references) — making the 183 ops really cooperate

Pain point (measured before the refactor): ops could only hand data over by hand. `vehicle_sections` returns a **5,656-character** JSON,
`vehicle_loft` requires pasting the `stations` array back; every handover goes through the model context ⇒ expensive and easy to mistype.
Those 18 multi-step chains in the skill are all prose, and the model has to translate them into N tool calls itself.

**New family pip (7 ops)**: `pipe_run` / `pipe_put` / `pipe_get` / `pipe_list` / `pipe_clear` / `pipe_selftest` / `pipe_help`

- **Artifact registry**: the output of any step can be stored under a name (in the persistent kernel's `K.dsh_artifacts`, living for one Blender session);
- **@references**: later steps write `"@name"` or `"@name.a.b"` (dot paths/list indices) in their args, resolved to real values at runtime;
- **Step-by-step receipts**: each step gives `ok / ms / keys / stored`, and failure stops by default (`stop_on_fail=false` runs to the end to see the whole picture);
- referencing a non-existent artifact ⇒ **errors on the spot and lists the existing artifact names** (no silent failure).

**Real chain measurement** (synthetic reference image, @references throughout): `vehicle.sections` 144ms → `vehicle.loft` (`stations="@sec.stations"`) 97ms
→ `vehicle.panels` (`object_name="@shell.object"`) 353ms → `clearance.check` (`a/b` using `@panels.parts.0/1`) 61ms;
**one call finished in 657ms, 4 artifacts passed automatically**. The selftest's 9 items are all true (including dot paths, nested resolution, stop-on-fail).

Wired into the existing surface: engine route `pipe_` + catalog family (with when/not/minimal skeleton) + read-only whitelist +3 (`pipe_list/get/help`);
and S4's machine used it directly — one command refreshes the capability lock and the counts (**28 family / 183 op / 15 tools**).

Regression: Blender side **252 assertions** (integration 122 + audit 78 + gate 52) all green · capability lock PASS · single source of truth 5/5 · npm test all green.

Boundary: @references are resolved only inside `pipe_run` (a single plan op does not auto-dereference — that would touch the engine write path, left for later);
artifacts live in the current Blender session (cleared on restart); `pipe_run` is synchronous and serial, long tasks still go through `rt_job`/headless.

### D18 · P4.2: cross-section path written into the class protocol (no more reading the CHANGELOG to pick a route)

Each class protocol of `shape_plan` now directly carries **`section_path`** (which cross-section route that class uses), and returns **5 decision rules** along with the protocol:

1. axisymmetric (bottle/jar/hub/vase/nozzle) => `shape_revolve`, **not** lofting
2. left-right symmetric + a silhouette in the front view => `section_shape`
3. has camber / left-right asymmetric / cross-section must be controlled precisely (airfoils, gearbox housings, irregular parts) => `section_outline`
4. only one side silhouette and the cross-section barely changes along the length (plates/profiles) => superellipse `section_pts` + feature lines
5. multiple volumes => `shape_regions` / `shape_revolve(parts=[...])`, and `clear_check` verifies the clearances after assembly

Per-class emphasis: **aircraft explicitly gets section_outline (airfoil, mandatory)** (the mirror-symmetric route cannot express camber),
**rotational explicitly gets shape_revolve (not lofting)**, furniture points at `section_outline` + `sweep_build`, hull hints that stations above and below the waterline are given separately.

`shape_selftest` gained two hard checks: **every class must have a `section_path`** (so adding a class later cannot be left unconfigured) + decision rules >=4.
Catalog unchanged (27 family / 176 op); the headless integration selftest went 112 -> **116 assertions**.

### D17 · P4.1: generalized reconstruction extension (airfoils/asymmetric sections · multi-volume rotational bodies · G2 fillets) + ledger correction

**A. Fixing the workdir test premise (ledger correction)**: `tests/workdir_shared_selftest.mjs` used to hardcode "`/tmp` is not shared with Windows ⇒ it must be replaced",
but on this machine `/tmp` is on the WSL root filesystem (reachable via `\\wsl.localhost\Ubuntu\tmp\…`) ⇒ the plugin judging `shared=true` is **correct**, yet the test failed 4 items.
The fix (environment-independent): A1 now judges "**the decision is self-consistent**" (`shared=true ⇒ why=distro-root-fs`; `false ⇒ why names the separate mount);
section C **verifies the replacement contract by branch** according to `requestedShared`; the probe directory **dynamically picks a genuinely unshared mount** (here `/dev/shm`) ⇒ the replacement branch still really runs.
Measured **10/4 → 14/0**.

**B. Acceptance doc gained the "current convention"** (`docs/archive/plugin-and-skill-optimization-acceptance.md` §-1): the local convention = Blender side 237 assertions all green (107+78+52) + Node side all green (workdir 14/14);
and it notes that "npm test 197 passing" is a number under **another mount configuration**; U1/U2 (whether the new capabilities reach the model) were resolved by real-machine re-checks.

**C. Three capability extensions**:

- **custom/asymmetric sections `section_outline`**: `vehicle_loft`/`shape_loft` accept an explicit closed outline `[[y_mm, z_mm], …]`,
  normalized per station (y by half width, z by station height) ⇒ **airfoils (with camber) and side-mounted asymmetric parts** can both be expressed; `section_source: custom_outline`.
  Measured: a NACA-style 40-point outline → 4264×1304×551mm, `ymin −408.2 / ymax +895.9` (**genuinely left-right asymmetric**).
- **multi-volume rotational assembly `shape_revolve(parts=[…])`**: give several `{profile, at:[x,y,z]_mm, name}` at once ⇒ hub+tire, bottle body+cap, nozzle arrays.
  Measured: 2 parts each at its own position (`hub@[0,0,0]`, `tire@[200,0,0]mm` → `location.x=0.2`).
- **G2 fillet control**: `crease_lines` gained `profile` (0.5 a true circle / >0.5 squarer and closer to a smooth G2 / <0.5 more concave), and the receipt echoes `bevel.profile`. Measured profile 0.75.

Catalog unchanged (27 family / 176 op); the headless integration selftest went 107 → **112 assertions**, all green; `npm test` all green (including the fixed workdir 14/14).

### D16 · P4: generalizing the reconstruction method (`shape_*` family + SOP)

That vehicle stack "envelope → station table → cross-section → feature lines → IoU" is **itself class-independent** (the geometry mechanism does not rely on the "car" assumption),
so this round extracted it into an independent method layer: new module `runtime/shapegen.py` (`shape_*`, 9 ops), with **all geometry delegated** to `img_*`/`vehicle_*`,
leaving it responsible only for "**giving a protocol per object class**".

- **`shape_plan(object_class=…)`**: 10 class protocols — vehicle / humanoid / creature / headwear / furniture / hull /
  aircraft / rotational / weapon / generic, each giving "which views are needed · which proportions to watch · which operators to pair · acceptance gate · known pitfalls".
- **`shape_sections` / `shape_loft` / `shape_fit` / `shape_regions` / `shape_panels`**: general measuring/lofting/fitting/part-splitting (delegated implementations, receipt carries `layer`).
- **`shape_revolve`**: the **axisymmetric** route (bottles/jars/hubs/vases) — such objects **should not use lofting**, they need one generatrix revolved around the axis. Measured 60×60×100mm / 146 vertices.
- **SOP**: `dsh-skill-blender-modeling/references/reference-image-reconstruction-sop.md` — the eight-step process, ten-class protocol table, three decisive details, acceptance discipline.

**Measured**: `shape_selftest` ok (10 class protocols with nothing missing + the rotational route); catalog **26 → 27 family / 167 → 176 op**;
the headless integration selftest went 100 → **107 assertions**, all green; `npm test` all green.

### D15 · P3.6: filleted feature lines (true radius, G1/G2 transition)

Feature lines were extended from "hard polylines" to "**fillets with a radius**": entries of `crease_lines` gained `radius_mm` + `segments`,
going through the **Bevel weight attribute + Bevel modifier** (`limit_method=WEIGHT`, `affect=EDGES`, `profile=0.5` a true circle) —
**not** approximating a radius with crease weights, but generating genuine arc-transition geometry.

```python
crease_lines=[{"frac":0.55,"radius_mm":6.0,"segments":3},   # beltline: R6 fillet (3 arc segments)
               {"x_mm":1500,"radius_mm":4.0,"segments":2}]   # lateral seam: R4
```

**Measured**: hard-polyline version 762 vertices → R6 fillet version **1244 vertices** (the fillet geometry is really added); receipt `bevel={radius_mm:6.0, segments:3, edges:30}`;
all modifiers applied for real (nothing left on the object stack); same band width 868.45 (hard) → 883.64 (R6) — replacing sharp corners with fillets widens the outer silhouette slightly, as expected.

Implementation details: ① the crease-marking function was parameterized with `attr_name` (`crease_edge` / `bevel_weight_edge`) + `default_w`, so both paths share one ring-index logic;
② the Bevel modifier sits **before** Subsurf (fillet first, then subdivision = the standard hard-surface stack); ③ when subsurf is off, bevel must still be applied on its own, otherwise the fillet only hangs on the stack and the geometry does not change.

Catalog unchanged (26 family / 167 op); the headless integration selftest went 96 → **100 assertions**, all green.

### D14 · P3.5: feature-line layer (parametric surface feel)

`vehicle_loft` gained `crease_lines` (SubD creases = hard polylines) and `inset_lines` (geometric folds/grooves), both specified by **height or position + range**:

```python
crease_lines=[{"frac":0.55,"weight":0.8},                    # by each ring's height ratio (beltline, recommended)
               {"z_mm":560,"x_mm":[400,3900],"weight":0.85}, # longitudinal line at an absolute height
               {"x_mm":1500,"weight":1.0}]                   # lateral seam (stations inserted automatically)
inset_lines=[{"z_mm":470,"band_mm":60,"inset_mm":12,"x_mm":[500,3800]}]   # door-line groove/fold
```

**Measured**: shoulder-line creases 10 ring edges · lateral seam 20 edges (full loop) · recess A/B same band width **868.9 → 850.2mm (−18.7mm)**.

**Two pitfalls that must be written down**: ① **you cannot match edges by z band** — ring vertices are discrete and at the target height there are often no edges at all (measured: `frac=0.55` marked **0 edges**);
switching to **ring-index** marking (longitudinal line = connecting the nearest point of each ring) hits reliably; ② a lateral feature line requires that x to **have a station**, otherwise likewise 0 edges —
now `vehicle_loft` **inserts a station automatically** at lateral lines (measured `stations_inserted: 1`, edge count 0 → 24).

Honest convention: `z_mm` only marks where the geometry really has that height (a low count is normal); for a continuous beltline use `frac`.
Catalog unchanged (26 family / 167 op); the headless integration selftest went 92 → **95 assertions**.

### D13 · P3.4: stronger shape family (polyline closed profile) + photo perspective correction

- **① polyline family `profile_pts`**: `vehicle_spec` accepts explicit control points `[[x,z_top,z_bottom]…]` (three points = a **closed profile**, both the upper and lower contour come from the reference image) ⇒
  `_profile_points` uses them to build the polygon directly, which can express shapes the cargen family **cannot** (box van / pickup / armored / sci-fi).
  The fitter gained `family="polyline"` + a `control_points` **K sweep** (fewer K, simpler spec):
  measured on the same silhouette — cargen family 0.637 → 0.667 (240 iterations); polyline family K=6 **0.754**, K=10 **0.781**, K=16 **0.821** (200 each).
  That is, **the ceiling was raised from 0.67 to 0.82**, with a K↔IoU trade-off curve (pick the number of control points that is "good enough").
- **② `img_rectify` (photo perspective correction)**: four corner points → rectangle **homography correction** (4-point DLT solving 8 parameters + bilinear sampling),
  **pure numpy, no OpenCV dependency**; given `known_w_mm` it returns `mm_per_px` directly, and only the corrected image is accurate enough to feed `vehicle_sections`/`img_scan`.

**Pitfalls recorded (both of the "the change silently zeroes the result" kind)**: ① when splitting `_profile_points` into the cargen/polyline paths,
the three lines `L/H/ride` stayed in the head that got cut away ⇒ `_profile_cargen` threw NameError ⇒ **the cargen fit IoU dropped to zero**;
② `_load` returned `(arr, path)` instead of a bare array ⇒ `img_rectify` reported a tuple has no shape. Both are fixed and guarded by assertions.

Catalog 26 family / **166 → 167 op**; the headless integration selftest went 89 → **92 assertions**, all green; `npm test` all green.

### D12 · P3.3: shell reconstruction trio (cross-section outline / multiple regions / IoU loop)

- **③ front-view cross-section outline**: `vehicle_sections` extracts a normalized shape `section_shape[{z_frac, hw_frac}]` from the **per-row width of the front view** (20 points);
  `vehicle_loft(section_shape=…)` uses it to build the rings (`section_source: front_view_shape`) — the cross-section character is no longer guessed from a superellipse formula.
  **Also fixed a distortion**: with only side+front views, a missing `half_w_mm` narrowed the body to 460mm ⇒ added a backfill from "max front-view width × flat taper assumption"
  (`half_width_source: front_view_taper_assumed`), measured width restored to **1850.0mm**.
- **② `vehicle_regions`**: cuts the reference image into several blocks along x, **each block its own volume** (truck cab+bed, armored hull+turret, sci-fi body+pods).
  Measured: 3 regions → `DBG_R_nose/cabin/tail` three parts, each with dimensions.
- **① `vehicle_fit`: station table → IoU fitting loop** (pure 2D trapezoid integration, **no rendering needed**, an order of magnitude faster than going through `rt_loop`).
  target outline = the measured station table; candidate = the 15-parameter profile formula; objective = two-region IoU; search = **analytically derived initial value + multiple starts + coordinate descent**.
  Measured: default initial value IoU 0.456 → **analytically derived initial value 0.637** → refined **0.667** (240 iterations).
  Pitfall recorded: after the analytic initial value changed `height_mm` to the measured value, the default wheel diameter of 340mm tripped the "wheel diameter > 0.65×body height" check ⇒ every candidate was discarded and **IoU dropped to zero**;
  adding a **parameter self-consistency guard** (wheel diameter/wheelbase/track shrink proportionally with the measured values) restored it.

**Honest boundary (written into the docs)**: `vehicle_fit` fits the **cargen 15-parameter shape family** —
if the reference outline is not in this family (a box shape, say), IoU stops at ~0.67 and will not go higher; **for an exact replica use the direct station-table loft path** (by construction it equals the outline).
Division of labor: `vehicle_fit` gives "a reusable spec with editable parameters", `vehicle_loft(stations=…)` gives "a shell hugging the reference image".

Catalog 26 family / **164 → 166 op**; the headless integration selftest went 83 → **89 assertions**, all green; `npm test` all green.

### D11 · P3.2: shell reconstruction (three views → station table → parametric loft → seams → IoU)

Following on from D10: `vehicle_base`'s 15 parameters could only express a "single-volume car", not complex/sports-car shapes ⇒ upgraded to **station-table driven**.

- **`img_scan` gained `col_top/col_bottom/col_fill`** (per-column upper/lower bounds) — the raw material for the station table (previously only per-row width).
- **`vehicle_sections`**: side view (required) + top/front views (optional) → station table + cross-section parameters + envelope numbers:
  the side view gives z_top(x)/z_bottom(x) per column; the top view gives half_w(x); the front view gives beltline height / tumblehome / sill tuck.
  The wheel-axle x is located automatically by **clustering the low dips at the bottom of the outline** (wheels and body merge into one blob in the filled outline, so "a few pixels above the ground" cannot be used — measured: only 1 segment was detected that way);
  the threshold is adaptive (z_min + 0.35×(median bottom edge − z_min)). Measured: synthetic sports-car side view (1px=10mm) ⇒ body length **4300** exactly,
  wheelbase **2687.5** (true value 2600, 3.4% error), front axle 860 (true value 900).
- **`vehicle_loft`**: station table → superellipse ring per station → loft; the cross-section character is controlled by `n_top/n_bot/tumblehome/beltline_frac/
  shoulder_inset/sill_tuck`; `flare_mm` does the fender flare (by default landing on stations where the **bottom edge is lifted** = wheel arches);
  `crease_shoulder` adds SubD creases to the beltline ring edges (the source of surface feel). **Creases go through Blender 4+'s `crease_edge` attribute**
  (`e.crease_weight` no longer exists — measured: crease_edges=0 the first time). Measured: 41 stations → 4295×611×723mm, 3242 vertices, **134 creases**.
- **`vehicle_panels`**: **subtracts a thin slab** at a given x (the gap width = real geometry) and can `separate(type=LOOSE)` into several parts.
  Measured: two cuts ⇒ 3 parts, gap width measured at **3.9999mm**, zero interpenetration.

**Known boundaries** (written into Recipe 18): without a top view ⇒ `half_w_mm` is missing and the body comes out narrow (measured 611 vs the expected 1850mm);
the wheel diameter cannot be inferred from the filled outline (needs `wheel_r_px` or a known spec); a photo reference must be perspective-corrected first;
the last 20% of surface feel comes from fine-tuning crease positions and surface tension.

Catalog 26 family / **161 → 164 op**; the headless integration selftest went 78 → **83 assertions**, all green; the real-machine four-piece set (sections/loft/panels/clear_check) runs end to end.
The skill gained **Recipe 18** (and states clearly: this "envelope→station table→cross-section→feature lines" stack is universal for **any object with a clear outer outline**; it does not apply to cloth/fluids or parts defined by internal structure).

### D10 · P3: vehicle shell (reference image → profile numbers → loft) + paired clearance gate

The problem (the user's own words): vehicle modeling looks nothing like the reference image, and there is interpenetration everywhere. Diagnosis: **a car shell must be lofted from profile parameters, not sculpted as a surface**.

Reference implementation (GitHub): **fpagerie/cargen** (a Blender add-on that generates a car shell from parameters: length/width/height / wheelbase / front axle to nose / wheel+tire radius /
tire width / wheel sink into the floor ratio / grille height / hood angle·length / windshield angle / roof length·angle / rear window angle·height / trunk angle; meters + degrees, angles measured from horizontal);
and the **vehicle-design skill**'s Proportion-First protocol (the human eye is extremely sensitive to car proportions; surface detail cannot rescue wrong proportions).

**New family vehicle (5 ops)**:

- `vehicle_package`: the proportion gate — WBR (wheel diameter/body height), wheelbase/length, height/length, track/width, front and rear overhang, ground clearance, each with its range and verdict.
  The WBR ranges are **calibrated against real cars** (911(992) 1300/680 ⇒ 52% · Corolla 1435/632 ⇒ 44% · Range Rover 1870/781 ⇒ 42%);
  the vehicle-design skill's 35-45% is a different convention (relative to the body, not total height), and the code states the basis so it is not mistaken.
- `vehicle_base`: longitudinal profile → superellipse cross-section per station → lofted into a shell; **stations densified at the wheel rims** (46 stations = 28 uniform + 18 densified);
  **exact wheel arches booleaned out** (cylinder of radius r + arch_clear); four wheels (axis along Y) + axle/nose/tail markers.
  Measured: 4300×1850×1140mm, 1101 vertices, 4 wheels at x=900/3500, z=289, r=340.
- `vehicle_spec` / `vehicle_selftest` / `vehicle_help`.

**New family clearance (3 ops)**: `clear_check`, rule-table-driven paired clearance/interpenetration checks (`min_mm` governs clearance, `allow_overlap` governs panel interpenetration).
Measured: 10mm clearance passes · 2mm fails · interpenetration fails · allowed interpenetration passes; **wheel and shell have zero interpenetration (clearance 10.51mm)**.

**Three real problems caught along the way (all measured first, then fixed)**: ① the wheel rotation axis was wrong (rotated around Y ⇒ the axis pointed toward the nose and the wheels grew sideways into the shell, 78 face pairs intersecting);
② the analytic wheel-arch formula had a cliff at the rim plus too-coarse stations ⇒ the chord cut into the wheel (58 → 20 face pairs intersecting) ⇒ switched to a boolean cut;
③ `vehicle_spec` returned a dict while the API layer expected a JSON string (`KeyError/TypeError`) ⇒ fixed, and defensive handling was added to the API layer of 6 modules.

Catalog 24 → **26 family / 153 → 161 op**; the headless integration selftest went 71 → **78 assertions**, all green.

### D9 · Integration plan P2: zero-asset humanoid (human family)

The asset route (MPFB2) does not work on Blender 5.2 (the source tree only has fake_bl_info; after a restart the loader still does not scan directory-style legacy add-ons,
reporting "The package does not name an extension"), and the user does not want to download a GB-scale asset pack ⇒ switched to a **zero-asset** parametric route.

**New family human (5 ops)**:

- `human_base`: fill in numbers only (height mm / head-to-body ratio / shoulder width / pose) → skeleton lines + Skin + Subsurf → base body;
  returns `heads_measured` (**measured from geometry**, not restated from the spec) / `head_mm` / `shoulder_over_head` / 19 joint empties.
  Measured (1750mm / 7.5 heads): height **1750.00mm, error 0**, head-to-body ratio **7.546**, shoulder width 350mm, shoulder/head **1.51**, 58,181 vertices.
- `human_measure`: prefers the object properties written at modeling time (head_mm/heads), falling back to joint-marker geometry.
- `human_spec`: reference-image outline → pixel ratios (height/head_w/shoulder/waist + a per-row foreground width profile).
- `human_head`: 9 landmark points → parametric head shape (cranial ellipsoid + jaw wedge) + facial feature markers;
  measured head_mm=233 → dimensions 171.7×206.0×238.4mm, landmark_fracs eye line 0.50 / nose base 0.725 / mouth line 0.825.
- `human_selftest` / `human_help`.

**Three real pitfalls hit and fixed (all measured)**:

1. **the Skin modifier must have `use_root` set** — without it the geometry comes out **zero-width** (measured: all three test dimensions were [0,0,0.6]);
2. **Skin's terminal big sphere does not work** — the head center gets computed above the top of the mesh (head height measured 26mm instead of 233mm) ⇒ the head became an **exact ellipsoid** merged into the same mesh;
3. the convergence direction was once written backwards (it should multiply by measured/target), and the depsgraph was not updated before measuring (a newly created empty read as 0).

**Wired into the existing flow**: the gate's OP_MAP gained 4 humanoid ops, and the `ensureGate` chain now carries human ⇒ the gate can judge "humanoid proportions" directly;
measured `gate_run` on a three-gate package → **verdict=pass** (body height error 0 · props head-to-body ratio 7.546 / shoulder-to-head ratio 1.51 · head height 233mm).
Skill gained **Recipe 15 (humanoid base body) / Recipe 16 (human face head shape + occlusion strategy)**.
Catalog 23 → **24 family / 147 → 153 op**; headless integration self-test 63 → **71 assertions**, all green.

### D8 · Integration plan P1-③: asset gate + second self-check pathway (landed)

- gltf_validate (Khronos glTF-Validator 2.0.0-dev.3.10): bypasses an npm failure (pull the registry tarball directly → runtime/ext/node_modules).
  Measured on a real GLB: ok=true / errors=0 / warnings=0; the receipt gives messages[].code, and rule codes can go straight into the gate spec's pass_if.
- ext_mesh_check (open3d 0.20.0): own venv (bypassing PEP 668) + libusb-1.0-0 from apt, installed under the plugin's own runtime/ext/.
  A/B measured: intact piece watertight=true / edge_manifold=true / 12 faces; after deleting one face watertight=false / 10 faces
  — consistent with the plugin's internal audit conclusion; that is exactly the point of a second independent pathway.
- Both ops spawn locally (no Blender round trip); candidate commands are ordered by platform (measured: the backend runs under WSL); the receipt carries used / tried,
  and on failure gives the exact install command.
- Measured pitfall: export PLY/STL for open3d, not OBJ — Blender 5.2's OBJ is judged a non-triangle primitive and read as 0 faces.
- Catalog 22 → 23 family / 145 → 147 op (ext family); read-only allowlist gained gltf_validate.

### D7 · Integration plan P0: gate calibration suite + reference-image instruments (and the gate's 4 real bugs dug out)

Two tools landed against the conclusion "the flash ceiling = coverage of the external pathways":

**① Gate calibration suite `calib_run` (8 defect classes + healthy-baseline control)** — answers "what can your gate actually catch":
injects 8 known defect classes (deleted face / flipped normals / isolated vertex / self-intersection / translation detachment / floater / thin wall / same-name forked resources),
judges each class caught, and runs a **healthy baseline** once (all 4 gates must pass, otherwise the calibration is void — the false-positive control).
**Final: baseline_pass=true, capture_rate=1.0 (8/8), missed=[]**.
But its first run produced **7/8**, and chasing the `thin_wall` escape turned up **4 real bugs**:

| # | bug | symptom | fix |
|---|---|---|---|
| 1 | `print_walls` ray-origin offset `0.25×face size` | a 40×30×**0.3mm** plate samples as 0, reports 30mm, thin=0 (a thin plate is simply not measurable) | the origin only avoids the face's own polygon (`1e-3×face size`) |
| 2 | same-surface-sheet test used a "distance threshold" | the voxel-reconstructed sphere shows 26% false thin walls (previously held down by the face-size threshold; reproduces as soon as that changes) | distinguish same sheet (same direction) / opposite wall (opposite direction) by the **hit-face normal**, 8 retries |
| 3 | `_scale_avg(ob)` used for anisotropic scaling | base plate z scaled 0.1 (3mm→0.3mm) computed as 2.1mm ⇒ thin wall missed | transform both hit point and face center with `matrix_world` and measure the **world distance** |
| 4 | gate's `pass_if` precedence | a sub-op `ok=false` (e.g. print_report's "some piece's overhang fails") overrides the explicit criterion, so a criterion that is true still judges fail | **when `pass_if` is written, it is authoritative**; only degraded is the exception (a downgrade must not be read as pass) |

— also: `print_report` gained gate-friendly top-level fields (`walls_ok / overhang_ok / thin_samples_total / worst_min_mm /
**worst_p05_mm**`); the gate criterion switched to the **robust percentile p05** (measured: the voxel sphere has 0.05% near-zero outlier samples, and judging by min falsely reports thin walls).

**② Reference-image instruments `img_scan / img_crop / img_annotate / img_diff`** — turn "can't see clearly" into "don't need to look":
- `img_scan`: silhouette bbox / aspect ratio / fill rate / principal-axis angle / major line angles / ROI foreground rate / color sampling at a given point (Otsu self-segmentation,
  plus `mask_warning`: if foreground >95% it states outright "no background separated, the numbers are unreliable")
- `img_crop`: ROI crop + nearest-neighbor upsample to disk (**fovea-style viewing**: one patch at a time, filling the visual input as much as possible)
- `img_annotate`: draw lines/boxes/crosses/grids back onto the image (colors on the image, numbers in the legend)
- `img_diff`: silhouette diff of two images → **IoU + a_only/b_only + per-axis profile diff + red/blue overlay** (far more sensitive to "where is there extra/missing" than to "does it look alike")
- Self-test (synthetic known geometry): bbox exactly `[20,30,80,60]`, aspect ratio 1.3333, 2× upscale → 160×120, aligned IoU=1.0, unaligned 0.6 ⇒ **all green**
  (during the self-test an Otsu plateau bug was fixed: on a bimodal image `argmax` lands on 0 ⇒ threshold 0 ⇒ mask entirely empty)

**Wiring**: catalog 19 → **21 family / 132 → 141 op**; read-only allowlist +3; both are callable directly as plan ops
(`img_selftest` / `calib_run` / `calib_selftest` verified on the real machine).

### D6 · Touching-contact false positive closed out + light-rig discoverability

- **Fix · "exactly touching" misreported as a floater** (the one marked "pending decision" in D5): the root cause is that `_components()` **welds vertices with
  coincident coordinates** per precision — two shells that exactly touch therefore merge into **1 connected component**, and the classification logic then asks "is this component attached to another component",
  with no other component ⇒ judged a visible floater. **The criterion is fixed at the semantic level**: when the whole range has only 1 connected component, the criterion `"not attached to other components"`
  cannot hold ⇒ `attached=True`, `evidence="single-body"`, and `confirm_note` points to
  `audit_mesh(island_split=true)` to check internal shell contact.
- **Three adjacency relations, regression** (two 1-unit cubes each, same mesh):
  | relation | before fix | after fix |
  |---|---|---|
  | interpenetration 0.1 (process requirement) | pass (micro tolerance 2) | **pass** (unchanged) |
  | **exactly touching gap=0.00 mm** | **fail (1 visible floater misreported)** | **pass** (visible floaters 0) |
  | 5 units apart (genuinely isolated block) | fail | **fail** (unchanged) |
- **② Light-rig discoverability**: `qc_render_views` had `lights={key,fill,rim}` / `lights=false` /
  `lights_mode="add"|"only"` all along, but the qc family catalog never mentioned it (people in the field added a backlight themselves for this). Now added to the family entry.
- Regression: headless integration self-test **61 → 63 assertions** (new "touching ⇒ pass and visible floaters=0", "isolated block still fail"); `npm test` all green.

### D5 · First batch of field feedback ③①② (spec-driven gate package / self-intersection island split / per-object tri-state)

Three real gaps from the same 95-object assembly feedback, all closed in one pass (headless integration self-test 51 → **61 assertions**, all green).

**③ Spec-driven gate package (`gate_plan / gate_run / gate_selftest / gate_help`)** — in the field, ~600
lines were hand-written for these three gates (interference / redcheck / selfint_diag); the plugin now executes and gathers the evidence:
- Three spec forms: .json / .py module (`SPEC` or `NAME/UNITS/TOLERANCE_MM/GATES`) / inline dict, plus 3 presets
  (assembly / print / delivery)
- **Explicit tri-state**: each gate pass/fail/degraded/error; package `verdict` = any fail → fail, else any degraded → degraded,
  else pass; `ok` is true only on pass — the field complaint that "degraded looks too much like green" is closed off at the field level
- `pass_if` is a **restricted expression** (ast allowlist: comparison/boolean/arithmetic/attribute + min·max·len·abs·round·all·any·sum),
  **the receipt returns only the fields pass_if uses** (slimmed by design); referencing a nonexistent field ⇒ that gate judges error and lists the available fields
- Measured: `gate_plan(preset="assembly")` lists 3 gates and their reads in 955 characters; `gate_selftest` green;
  a real-machine package run: 738 characters; when a sub-op errors it **surfaces its own words** (previously misreported as "pass_if evaluation failed")
- Side note: real-machine verification also found your current scene has **103 objects / 0 mesh** (audit_scene refuses honestly: "0 meshes in the scene")

**① `audit_mesh` self-intersection island split (`island_split` / `min_island_verts`)** — the attribution experiment the field once did by hand is now built in:
- edge-connectivity union-find → connected islands; self-intersection pairs split into **same island / cross island**; `min_island_verts=N` filters out intersections where either side belongs to an island with <N vertices
- New fields: `islands{count, small_islands}` / `self_intersections_same_island` / `_cross_island` /
  `_filtered_small_island` / `_kept`, added to the `summary_only` allowlist
- Self-test: host (subdivided cube) + rivet (small cube) ⇒ detects 2 islands, cross-island >0, same-island=0; with `min_island_verts` on ⇒ all filtered out, kept=0;
  one edge connects the two shells ⇒ detects 1 island and records a same-island self-intersection (**true interpenetration vs benign press-in** now read separately)

**② Per-object connectivity + verdict (`per_object=true`)** — the pitfall where a 3 M-face whole can only be bbox-only now has a proper answer:
- `audit_connectivity(per_object=true)` runs per piece, each piece usually stays within limits ⇒ gets back a mesh(BVH)-level conclusion,
  returns `objects[{object,state,verdict,tris,mesh_mode,real_floaters,reason}]` + `"failed_objects"/"degraded_objects"`
- `_gate_from` and `audit_gate` both gained `verdict`; degraded always carries `warn: "DEGRADED ≠ pass…"`
- Measured three adjacency relations (two 1-unit cubes each): **interpenetration 0.1 ⇒ pass** (micro tolerance 2); **exactly touching gap=0.00 mm ⇒ fail**
  (reported as 1 visible floater); **1.2 units apart ⇒ fail, 2 real floaters**.
  ⚠ **Pending decision**: the second one is a **false positive** — when the gap is exactly 0, the triangle-level recheck does not count it as "touching but not coincident". Under default units 1 unit = 1 m,
  and the 0.3 mm basis = 0.0003 unit, so the third case is not a bug (a 200 mm gap should indeed flag); only the "exactly touching" case needs fixing.

**Also fixed**: one escaping level was missing from `C:\home` in `PATH_GUARD`'s hint ⇒ every headless run spams
`SyntaxWarning: invalid escape sequence '\h'` (fixed; confirmed gone after restarting the backend).

### D4 · First batch of field feedback (MK1 large-part measurement · fixed + verified)

From one real assembly-modeling session of 95 objects / 3.05 M faces, the conclusions after checking each item against the code:

- **✅ Fix · script_file context (feedback #4)**: script_file is executed **inline** (copied to `D:\DSH\blender\tmp\dsh_headless_*.py`),
  previously `__file__` pointed at that temporary wrapper file and the script directory was not on sys.path ⇒ the first line `import spec` in a multi-file project raised
  `ModuleNotFoundError`. Now `DSH_SCRIPT_FILE` is injected + `__file__` points back to the original script + the script directory is inserted into `sys.path[0]`.
  Reproduction check: `tmp/sfprobe/{spec.py,main.py}` runs directly without workdir (it always failed before).
- **✅ Fix · WSL path "double prefix"**: `"home/…/DSH/test/x.py"` (missing the leading `/`) was treated as a relative path and appended to cwd →
  `…\DSH\home\sixtyseven67\DSH\test\x.py`. Now `slipFixPath()` treats "adding `/` really exists" as the fix and corrects it, writing to backend stderr;
  covers the five entry points script_file / file / outdir / out_json / workdir. Reproduction check: the same call with the `/` missing runs directly.
- **✅ Note · path semantics into the first line of the description**: a warning at the head of the schema description; the long tail of the 19 parameters (including timeout/path/receipt semantics) is in
  `blender_rt_plan(op="catalog", args={tool:"rt_headless"})`. **Note**: the first version's longer description was **blocked by the budget gate**
  (rt_headless 1,690 > 1,600 characters); after compressing the text 38/38 passed — the gate works as designed.
- **🔎 Feedback #5 "custom light rig" was in fact already supported**: `qc_render_views(lights={key,fill,rim}, lights_mode="add"|"only")`
  — the field's "the back side renders all black" was because they did not use it (a **discoverability** issue, not a missing feature; TODO: add the hint to the qc family entry).
- **⏳ Pending decision**: feedback #1 (`audit_mesh` self-intersections **split by connected island** + small-island filtering), #2 (connectivity/gate supporting **per-object or per-chunk**
  and `degraded` must not look like green), #3 (**spec-driven one-shot gate package**: the field hand-wrote interference / redcheck / selfint_diag, ~600 lines)
  — all three are real gaps, awaiting scheduling (cost low to high: #2 < #1 < #3, value high to low: #3 > #1 > #2).

### D3 · Verifier cost: checklist externalized + receipt slimming (tier B, low risk, reversible)

**Attribution (measure first, then change)**: the fixed cost of starting a "clean verifier subagent" ≈ tool schema 2.8k + **full SKILL.md ≈16–22k** +
AGENTS 3.7k ≈ **23–29k tokens**, and it is **repaid every round**; the actual gate calls (21 audit_gate, 17 audit_mesh in 10 days of logs…)
are cheaper instead. ⇒ what must be saved is the **loading periphery**, not the criterion.

- **① Checklist externalized**: `dsh-skill-blender-modeling/references/acceptance-checklist.md` (**2,249 characters ≈ 0.8–1.2k tokens**):
  verifier task template (fixed input + fixed 4-line output) + numeric gate criteria table (one command and threshold each for audit / print / deliver / uv) +
  **a criterion against the Goodhart "switch to another computation pathway"** (built with `Object.dimensions` ⇒ verification must use `matrix_world @ v.co`…) +
  drift self-check. **Fixed per-verification overhead ≈23–29k → ≈7.3–7.7k** (saves ≈16–21k/run × rounds).
- **② Receipt slimming** (default **all off**, takes effect only with explicit args, fully reversible): `audit_scene(summary_only, top_k)`,
  `audit_mesh(summary_only)`, `audit_duplicates(top_k)`. Measured on a 40-object scene (1/4 with defects):
  **9,176 → 1,148 characters (−87%)**, `top_k=2` → **773 (−92%)**, while `clean` and `totals` **judge identically**
  (verification strength unchanged); `audit_mesh` slimming drops `self_intersection_pairs` and other details but keeps every criterion field.
- **③ One silent failure fixed in passing**: `audit_duplicates(limit=30)` accepted the parameter and never used it — now it really takes effect,
  and on truncation returns `materials_total` / `meshes_total` and `slim` ("it ran" no longer disguises itself as "it checked everything").
- **④ Regression**: headless integration self-test **34 → 42 assertions** (verdicts unchanged, top_k takes effect, ≥70% character reduction, mesh details dropped, duplicates has slim).
- **⑤ Pointers**: SKILL.md first screen + both AGENTS.md files each gained a line "the verifier subagent reads only the checklist"; the audit family entry of `op="catalog"`
  gained the `summary_only / top_k` hint (`audit_mesh` automatically adds a `hint` when the receipt is >6k characters).

### License

The interface shape and criteria reference upstream, **the code is this plugin's own implementation** (blend-ai is AGPL-3.0, its code is not copied; mcp-for-blender is MIT).

## v0.9.5 (2026-09-26) — measurement-driven three performance fixes + multi-instance hot sessions + health distribution metrics

Source: measured on this machine (the plan and all raw numbers are in `DSH/blender/measured-driven-channel-and-skill-optimization-plan-2026-09-26.md`).
In one line: **move the effort from "new mechanisms that look smarter" to the three big items that measurement surfaced** — diagnostic probes, duplicate frames, fixed overhead of small jobs.

### P0-1 · `rt_see` diagnostics made lazy (custom-view path −39~40%)

- **Measured** (403 objects / 128k tris): the three diagnostics in `capture()` (coverage / scene_bbox / objects_in_frame)
  cost 63 ms (560px), 137 ms (1120px), 488 ms (2240px) every single time; while the actual `draw_view3d` + VRAM readback is only ~22 ms.
- **Change**: `_spec()` gained `diagnostics` (default **false**); a normal frame returns only image/hash/ms/matrix.
  **Near-empty frames rerun automatically** (PNG < `EMPTY_PNG_BYTES`=8000 bytes) ⇒ the `frame_looks_empty` warning stays as before;
  an explicit `diagnostics=true` forces a run every time. Also fixed the waste of **calling `_scene_bbox()` twice in a row** in the render fallback branch.
- **Measured gain**: 560×315 from **146.3 → 88.6 ms**; 1120×630 from **301.3 → 179.4 ms**; the forced-diagnostics path unchanged (161 ms, semantics identical to v0.9.1).
- **Regression**: `tests/view_diag_selftest.py` gained 5 assertions (invariant = "diagnostics ran ⟺ explicitly requested or byte count < threshold"),
  21/21 all green; `npm run test:diag` turns "how to run it" into a fixed command (needs backend 9877; finds the holder via `DSH_LEASE_HOLDER`/ `GET /who`, **does not force-take the lease**). `VIEW_VERSION` 2 → 3.

### P0-2 · Frame dedupe: the same image is not re-attached (the saving is model-side tokens)

- **Measured**: the same image sent 5 times in a row hashes identically (`038c7439`), a single frame is 116,870 B — re-attaching only burns visual tokens.
- **Change**: the hash was already computed (first 8 chars of the PNG md5 in `fetchFrame`/`fetchView`); added `frameDedupe(key,hash,force)`:
  same key, same hash ⇒ the receipt states "identical to the previous image (occurrence N) ⇒ image not re-attached; pass force:true to resend";
  keys are isolated per channel (`viewport:<size>` / `area:<n>` / `view:<view signature>` / `do-see:<size>`); **an empty hash is never deduped** (better one extra image than silently dropping one).
  `blender_rt_see` and `blender_rt_do` each gained a `force` parameter.
- **Regression**: `tests/frame_dedupe_selftest.mjs` 15/15 (merged into `npm test`).
- ⚠ **Effective scope**: this part is host-side (`lib/index.js`), **effective after restarting DSH** (as noted for v0.9.4).

### P0-3 · `rt_loop` plateau early stop (off by default)

- **Measured**: idle spin 176 tps (5.7 ms/tick = timer floor, there is no "useless idling" to save); with a heavy measure (~72 ms each) 12.4 tps (measure takes ~90%);
  same measure + `measure_every=20` ⇒ 96.8 tps ⇒ **the frequency knob already exists**, so this release **does not** do "dynamic frequency tuning".
- **Change**: spec gained `patience` (0 = off, off by default): patience consecutive measures without refreshing best ⇒ `stop_reason="plateau"`,
  status/receipt carries `patience` / `last_improve_i`. Only judged when "a best already exists", so a loop whose measure never returns a score is not killed by mistake.
- **Measured**: patience=0 runs the full 200 iterations (byte-identical to old behavior); patience=10 + 30 rounds with no further improvement ⇒ **stops at i=41** (`last_improve_i=31`);
  a loop that keeps improving is not stopped early. `RUNNER_VERSION` 2 → 3.

### P1-1 · Multi-instance hot sessions (small-job fixed overhead 2.7 s → ~0)

- **Measured**: empty-script cold start **1000–1257 ms** (opening a 2.5 MB project 1287 ms / 11 MB 1386 ms); a small render job (512²/16spp/2 frames)
  totals 3098 ms of which **first-frame shader compilation alone takes 1640 ms** ⇒ fixed overhead ≈2.7 s = 85%; while 2 concurrent runs are only ~10% slower (the GPU has headroom).
- **Change**: `blender_rt_worker` goes from "singleton" to **multi-instance by name** (`op=start name=w1` / `exec name=w1` / `status` / `stop` / `restart` / **new list**),
  ports allocate sequentially by name (starting at the configured port); the default name `default` ⇒ old calls byte-identical; the `/worker` route and `/health`'s `rtt.worker` stay in sync.
- **Measured gain**: the same script line, **hot session 40–60 ms** vs **cold start 1257 ms** (≈20–30×); batch small jobs no longer spawn every time.
- ⚠ **The tradeoff is written into the description**: reuse = deliberately giving up "headless process isolation" (the same instance shares scene and K) ⇒ use `restart` when dirty, keep `headless` when you need a clean scene.

### P2-1 · `/health` gains distribution metrics (**observation only, no automatic restart**)

- Added `rtt` (frame/act/view/headless/plan/worker/job each keeping `last/p50/p95/n` over the last 20 samples) and
  `backend{pid,rssMB,uptimeMs}`. **Does not include blender.exe's RSS** (Windows side, one read requires spawning tasklist, hundreds of ms, so it is not put on the hot path).
- Why no "predictive restart": killing one 20-minute render by mistake costs far more than the restart time saved; automatic relaunch still only happens in the deterministic state "port/PID clearly dead".

### P2-2 · `rt_job op=list` occasional abort (logged, not reproduced)

- Symptom: in this session `op=list` returned `This operation was aborted` twice in a row, while at the same moment `/health` was normal at 2.7 ms with no leftover processes.
- Reproduction attempts: **after restarting the backend the same call returns normally in 116 ms** (60 ledger entries + in-memory handles all present). ⇒ judged a **transient state**, no reproducible defect found;
  the `/job` route got `rtt.job` instrumentation (P2-1), so when it recurs, look at the distribution and `inflight` first, then talk about fixing.

### Verification

- `npm test`: protocol / lossless / lease / **frame-dedupe 15/15** all green.
- `npm run test:acceptance`: **62 passed / 0 failed** (44 s).
- `npm run test:diag`: **21/21** (including P0-1's 5 new assertions).
- Real-machine numbers: see the entries above (same script, before/after A/B).
- ⚠ **Effective scope**: `runtime/*.py` (view / runner) takes effect as soon as it is changed (injection re-injects automatically by size+mtime fingerprint);
  `runtime/server.mjs` + `engine.mjs` need a **backend restart** (`blender_viewport op=restart`);
  `lib/index.js` (tool layer: force / patience docs / worker name / list) needs a **DSH restart**.

## v0.9.4 (2026-09-25) — response-channel fix (P0) + one-click launcher (P1) + skill v2

Source: another session's hands-on list from "M1A1 part-by-part modeling" (500 objects / 7 agents / headless throughout / the main battleground being a hand-written `tools/bl.sh`).
Report: `docs/feedback/improvement-landing-record-2026-09-25.md`.

### P0 · Root cause of `value is not lossless JSON` (headless/job unusable across the board)

- **Symptom**: `blender_rt_headless` failed **every time** (even the simplest script), `blender_rt_job(op=start)` could submit but
  `status/collect/wait` all failed — "the task can be handed out but not collected back". The guess at feedback time was "the harness rejects non-finite numbers".
- **Real cause**: in v0.9.3 `receiptEnvelope()` had `promoted: ctx.mode === 'promoted' ? true : undefined`.
  The host's `dsh-util-values` lossless-JSON gate (`walkJsonValue`) **rejects own enumerable keys whose value is undefined**,
  while `JSON.stringify` **drops** that key → the receipt looks completely normal in logs/unit tests, but the host directly judges
  `tool "…" returned invalid output: value is not lossless JSON`.
  That function is the **common exit** of headless(sync) / headless(job completion) / rt_job status·collect·wait → exactly matches the symptom.
- **Second instance of the same class** (caught by the regression test): `gpu: { fell_back_to_cpu: r.gpu.fell_back_to_cpu }` (undefined when the backend omits that field).
- **Fix**: ① the envelope changed to "only provide the key when there is a value"; ② `!!r.gpu.fell_back_to_cpu`;
  ③ **the central sanitizer `losslessSanitize()` closes up at the `vTool` exit** (the single exit for all tools):
  undefined→drop key (array element→null) · NaN/±Infinity→null · -0→0 · bigint→number/string · Date→ISO ·
  Map/Set→array · class instance→own enumerable keys · binary→`{bytes:N}` · cycle→`[Circular]`;
  **changes are not silent**: each is recorded in `fixes` and appended to the receipt text (`⚠️ receipt sanitized N places…`) + `console.warn`.
- **Regression gate**: `tests/lossless_guard.mjs` (`npm run test:lossless`) — uses the **host's real validator**
  (`dsh-util-values`' `snapshotJsonValue`, auto-detecting the install location) to assert "any receipt from this plugin passes the gate";
  includes the control group (§3 proves the validator really is strict), the sanitizer, and four receipt constructors; `--live` adds three real-machine
  cases (really run headless + `rt_job(op="status")`). **Offline 40 / real machine 47 assertions all green**.
- ⚠ **Effective scope**: the plugin loads when DSH starts → **the session that is already running still runs the old module** (measured: same error still reported),
  **effective after restarting DSH**; new sessions / the `dsh` CLI take effect immediately.

### P1 · Launcher: the agent lights up the GUI itself (the suggested `blender_rt_launch(autoconnect=true)`)

- Implemented as **`blender_viewport(op="launch")`** (no 16th tool surface: the `doctor` / `blender-unreachable` fixes point straight at it).
- Semantics: write a boot script (`addon_utils.enable` on the module whose name contains mcp in the GUI; if that fails, `importlib` loads
  `$BLENDER_USER_SCRIPTS/addons/*mcp*.py` directly + `register()`) → detached `spawn blender.exe` →
  **poll 9876** (the only trustworthy criterion) → once the port is open, run doctor in passing.
- **Idempotent** (already listening returns `already:true`, no second Blender stacked) · `dry_run` · `exe` / `addon_module` / `addon_file` overridable ·
  boot conclusion written to `launch-status.json` (the GUI process's stdout is unavailable) · the receipt gives `bootScript` for manual re-running.
- **A real bug the self-test caught**: `spawn` on a nonexistent exe does **not throw**, it emits `'error'` asynchronously → without a handler it takes down
  **the whole backend process** (the first self-test version died exactly this way); fixed + a path-existence precheck.
- **Regression**: `tests/launch_selftest.mjs` (24 assertions) — uses a **fake blender** + a separate backend/port/working directory,
  **never touches the Blender the user has open**; covers spawn → port criterion → idempotence → dryRun → readable failures.

### P1+ · **Automatic reclaim of write leases from dead sessions** (hit by measurement on this machine, not a feedback item)

- Field case: after a DSH session crashed or was closed, its write lease stayed in backend memory and **kept taking effect until TTL (default 1 h)**,
  blocking other sessions' write channel entirely — even though that session had long ceased to exist (measured on this machine: holder=@@plugin-pid-816309@@
  had no such process, 57 min still left, headless got a 409 straight back).
- Fix: the holder convention is @@plugin-pid-<pid>@@ (generated by the plugin frontend, on the same machine as the backend) → the backend does a liveness probe
  with @@process.kill(pid, 0)@@ **when a write request arrives** and on @@op=lease@@; **reclaims as soon as it is judged dead** and records @@stats.staleLeasesReclaimed@@ +
  @@lastLeaseNote@@ (not silently). @@/who@@ / @@/health@@'s @@lease.holderAlive@@ gives a tri-state:
  @@true@@ / @@false@@ / **@@null@@ = undeterminable (non-conventional name → conservatively keep blocking, never steal by mistake)**.
- Regression: @@tests/lease_stale_selftest.mjs@@ (16 assertions) — separate backend; covers "a live holder still blocks / a dead holder is reclaimed automatically /
  when liveness cannot be determined, conservatively block / a real write route no longer gets 409".
- Live verification (real backend): plant a dead lease → @@holderAlive:false@@ → one headless from this session **passes without force** →
  @@staleReclaimed:1@@ + a readable note.

### Docs / skill

- `docs/feedback/improvement-landing-record-2026-09-25.md` (report: root cause, fix, acceptance, what was not done).
- `docs/operation-tutorial.md`: the `blender-unreachable` line now prefers "one-click `op=launch`" + a new section 8 on the launcher.
- **skill `blender-modeling` v2** (`~/.dsh/skills/blender-modeling/SKILL.md`, v1 backed up):
  new §0.5 multi-agent division-of-labor pattern, §0.6 reference-image-driven form reconstruction, pitfall four (be careful with bpy.ops in headless),
  pitfall five (normals are the premise of every clipping criterion), pitfall six (the preview fixture can see panel seams by default); recipe 2 split into 2a faceted / 2b smooth;
  new 3b (bmesh), 6b (parametric exact pitch), 9 (assembly audit gate), 10 (dual-evidence acceptance); §6's cleanup checklist upgraded to a numeric gate checklist.
  ⚠ editing the skill must keep the YAML frontmatter, otherwise the skill disappears from the catalog (hit before).
- `npm test` is now = `protocol_selftest` + `lossless_guard`; new `test:lossless` / `test:lossless:live`.

### Not done (next-round suggestions)

1. **Normal check becomes a code gate**: `audit_mesh` gains `normal_consistency` / `signed_volume`,
   and `audit_interference` / `audit_overlap` run it automatically before their criteria and write "premise: normals point outward (verified/unverified)" into the receipt.
2. `qc_render_views` gains `mode="inspection"` (neutral gray + one-sided hard shadow + dual camera positions), turning pitfall six from discipline into a default fixture.
3. The image-measurement primitives (D7 last round) are still not implemented.

## v0.9.3 (2026-09-24) — external feedback "Plugin improvement handoff 2026-09-24" landed: timeouts no longer drop results + structured receipts + observability + path space

Source: `docs/feedback/plugin-improvement-handoff-2026-09-24.md` (7 collaborators / about 120 tool calls / all done in headless).
This release lands both P0s from §2, D2/D3 (one refactor), D4/D5/D6 from §3, F1/F2/F3/F4/F5/F6 from §4, and the route decision from §5,
and adds the §8 acceptance tests item by item (`tests/acceptance_v093.mjs`, 62 assertions / real machine Blender 5.2.2).

### Route decision (§5): **headless batch processing = the first path**, direct GUI = interactive gain
- Evidence: 7/7 collaborators were headless throughout, the 9876 addon was never Connected, `rt_do/rt_see/rt_watch/rt_cmd` 0 calls;
  while `audit_*/qc_*/deliver_*` could already be called directly in headless (the `preload=` channel), the description simply did not say so.
- Landing: see `docs/headless-first-route-decision.md` (includes a 17-line op→preload reference table + 5 copy-paste blocks + task templates);
  tool descriptions rewritten (`blender_rt_headless` explicitly says "first path", `preload` explicitly says audit/qc/deliver are directly callable).
- **No tool is deleted**: the GUI tools remain the "change one step, look once" gain, just no longer the default entry.

### P0-1 · D1/F3: timeouts no longer swallow results (promoted semantics)
- **Client wait window** (`DSH_HEADLESS_WAIT_MS`, default 100 s): on expiry or host cancellation → returns
  `{kind:"promoted", jobId:"run-…"}`, the server-side child process keeps running, `blender_rt_job(op="collect"|"wait", id=…)` collects the result.
- **runId is generated by the client** and sent with the request → when the window expires there is **immediately** a usable handle (the old version could only guess the latest entry in /status).
- **Key fix**: `withTimeout` used to cover only "waiting for response headers" — for streaming routes (`/headless` sends headers immediately + a heartbeat every 15 s)
  the subsequent `await r.text()` was unbounded, so the wait window was nominal and the outer deadline dropped the whole result.
  Now the timer lives until the body is fully read (same AbortController).
- Added `as_job` / `wait_s` (F3): `as_job=true` goes to background immediately, `wait_s=N` waits at most N more seconds and returns the jobId if unfinished;
  plus `DSH_HEADLESS_AUTO_JOB_MS` (default 0=off) sends calls whose "expected budget ≥ threshold" straight to background.

### P0-2 · D5: long tasks observable (PYTHONUNBUFFERED + stage heartbeat)
- All three spawn sites (headless / job / worker) go through `baseChildEnv()` → injecting **`PYTHONUNBUFFERED=1`**;
  measured: the job's `stdout.log` grows **while running** (the old version stayed at 0 bytes throughout and only wrote on exit).
- New stage heartbeat contract: in the script `dsh_stage("building")` / `K.progress("building", i=3)` →
  prints `DSH_STAGE {single-line JSON}`; the engine automatically prints `boot / engine-prelude / preload-done / script-start / script-end / done`.
- `op=status` gained `stage / stageName / stageAt / stageAgoMs / lastOutputAt / idleMs / lines / logBytes / pidAlive`.

### D2/D3 · Structured receipts (one refactor)
- Tools return **two text blocks**: block 0 = single-line JSON envelope (directly `JSON.parse`-able), block 1 = human-readable summary.
  Envelope fields: `kind/status/ok/runId/jobId/resultJson/resultTruncated/resultPath/resultPathWsl/resultBytes/`
  `resultParseError/stdoutTail/stderrTail/logs/artifacts/shots/inputFile/pathWarnings/stage/...`.
  (The host only passes through ContentBlock[]; there is no json block; and each text block is an independent part on the provider side → the first pure-JSON block is parseable.)
- **A non-JSON last line no longer overrides the real output**: parse failure degrades to `resultParseError`, `stdoutTail`/logs keep the original text (the old version returned `{_parse_error, raw}`).
- Large results: >4 KB are written to disk automatically with `resultPath` + `resultPathWsl` (`resultTruncated=true`); `out_json=` can also be given explicitly.

### D6 · Job-layer interface completed
- `op=start` takes the same parameters as headless: `script_file` / `args` / `env` / `factory_startup` / `bootstrap` / `workdir` / `include_noise` / `out_json`.
- Added **`op=wait`** (blocks until completion or timeout, default 120 s per call, max 600 s, server side uses streaming heartbeats) —
  no need to fire `op=status` repeatedly (it collides with the outer harness's duplicate-call detection).
- **run and job share one id space**: `status/collect/wait/kill` all accept `run-…`; `collect` can also tail logs for a run.
- State reconciliation: after a backend restart, a `running` entry in the on-disk ledger whose pid does not exist → converges to **`stale`** with `staleReason` (no more lying "running");
  `op=kill` on an unknown id **does not throw** (returns "finished/nonexistent" + `alreadyFinished`).
- Lease gating: `wait` / `kill` are no longer blocked by the **write lease** (they read/terminate their own jobs and do not touch the live scene).

### D4/F4/F6 · Path space and fingerprints
- `outdir` / `out_json` / `file` accept WSL paths (`/home/…` → `\\wsl.localhost\<distro>\home\…`), and the receipt gives both the Windows and the WSL real path.
- **`winToWsl()` gained a UNC branch** (`\\wsl.localhost\…` → `/…`): the old version returned it as-is → when workDir used a WSL path, ledger/results/trajectory all landed on a string Node could not open (measured).
- Path checkup (`pathWarnings`): when a script hands a POSIX absolute path to a Windows API (`scene.render.filepath` / `Saved: 'C:home…'` in logs) it is caught and given a `K.win_path()` fix.
  *Basis note*: D4.3's original text suggested "fail explicitly"; here it lands as an **auditable warning + hint** (does not interrupt the script) — because a hard mid-script failure would throw away "the images already rendered" along with it.
- `inputFile` (F6): a `file=` receipt carries `{path,size,mtimeMs,mtime,md5}` (>512 MB hashes only the first 64 MB and marks `md5Partial`).

### F1/F2 · Multi-view rendering integrated + framing self-diagnosis
- `blender_rt_headless(shots=[{name, from, look_at, lens, res, samples, ortho, ortho_scale, margin}], outdir=…)`:
  goes through `qc_render.py`'s `qc_render_views` (automatic three-point light / render lock / per-image md5 / device readback), receipt `res.shots =
  [{name, path, ms, bytes, md5, coverage_estimate, warning?}]`; subject under 5% of the frame → `warning.code="subject_too_small"`.
- `shots` also supports the object form `{views:[…], res, samples, tag, warmup, margin}`; can be given together with `script` (run the script first, then render); `as_job=true` works as well.

### Silent failures fixed in passing (found by measurement during acceptance)
- **`blender_viewport(op=status)` also works when the addon is not connected**: the old version threw on the first `addon.send` → local information
  (version self-report / ledger / workDir writability) was all invisible, exactly when it is needed most.
- **workDir writability self-report**: `status.ledger` gained `writable / workDir{wsl,win} / lastError / hint`, and `doctor` prints "working directory: … (⚠️ not writable …)" + the fix;
  `op=status` top level gained `workDir / workDirWritable / workDirWarning`.
- `jobStart`'s engine prelude is aligned with headless (`engine="none"` is no longer stuffed into the EEVEE prelude).

### Acceptance
- Added `tests/acceptance_v093.mjs` (`npm run test:acceptance`): **62 assertions all green** (real machine Blender 5.2.2 / EEVEE),
  mapping item by item to §8: D1/D2/D3/D4/D5/D6/D6-stale/F1/F6/F5-doc.
- Regression: `npm test` (protocol self-test 28 items) all green.
## v0.9.2 (2026-09-23) — DSH update adaptation: cancel/timeout contract + host API self-report + silent image failure + bundle declaration

Source: a package-by-package diff + measured check of "will this plugin break after a DSH update" (host 0.1.6-alpha.1 ↔ npm latest
0.1.7-alpha.2). The conclusion is **zero drift in the tool-definition contract** (all 15 tools registered successfully under the five dsh-tools versions
0.1.5-rc.2 / 0.1.6-a1 / 0.1.6-a2 / 0.1.7-a1 / 0.1.7-a2, with byte-identical parameter schemas),
so what this release fixes is **four surfaces outside the contract**:

### R3 Host cancel/deadline signal propagation (used to "hang")
- Added `EXEC_CTX` (AsyncLocalStorage) + `execSignal()`: `vTool()` uniformly puts the host's `exec` into
  an async context, and `withTimeout()` merges `exec.signal` via `AbortSignal.any` — **15 tool bodies, not a line changed**.
- The wording on cancellation is fixed to `ABORT_HINT` (it only says "the wait was cancelled", never falsely claims the task failed; it hints that long tasks are collected by `runId`).
  Measured: with an already-aborted signal `blender_viewport(op=status)` returns a readable error in **20 ms** (the old version waited until the internal timeout).
- **Every tool gained a static `timeoutMs`** (constant `T`): always "internal maximum timeout + margin", guaranteeing the internal timeout fires first.
  Background: the host's `@deepseek-ai/dsh-tool-call-timeout-policy` **only sets a deadline when the tool declares timeoutMs itself**;
  without a declaration = once upstream supplies a default, you get the silent mismatch "Blender is still running, the tool has already been judged timed out".

### R2 Host API self-report (the resolution chain is live, not a copy)
- Resolution chain on this machine: plugin `node_modules/@deepseek-ai/dsh-tools` → `~/dsh-harness` (fake checkout symlink) →
  the **global install** in `/usr/lib/node_modules`. The benefit is being the same version as the host (no stale copy); the cost is that any change to the global install location
  causes `ERR_MODULE_NOT_FOUND` at load time (all 15 tools vanish, with no visible reason).
- Added a `HOST_API` self-report: `blender_viewport op=doctor` prints `Host API: dsh-tools@<version> @ <path>`;
  the `op=status` JSON gained `hostApi` / `toolVersion` fields.

### R8 Image return is no longer silent (`toAttachment`)
- Old behavior: attachment service unavailable/over limit was always `catch → undefined`, the model saw plain text only, with no warning at all.
- New behavior: returns `{ref}` or `{why}`; `rt_see` (viewport/custom view), `rt_do`, `rt_watch` write
  `⚠ image not returned: <reason>` into the tool text when the image is not returned.

### R5/R1 Declare the bundle per the `dsh.bundle` convention and **actually switch to bundle-style assembly** (2026-09-23)
- `package.json` gained `dsh.bundle.patch = ./cordis.patch.yml`; added `cordis.patch.yml` (its own insert lines).
  `@deepseek-ai/dsh-plugin-manager` uses that field to decide "can this be managed/assembled as a profile layer"; without it the only option is
  super-injector runtime injection (once the injector breaks, the whole plugin disappears).
- The switch is already done on this machine: the plugin is listed in the profile's `dsh.profile.bundles`, and **`dsh-super-injector` is uninstalled and deleted**
  (source / state directory / junction / distribution artifacts / .gitmodules entry all cleaned). In the same batch the other two plugins that only lived via injection
  (`dsh-coc-dice`, `dsh-session-list-cache`) were migrated to bundle style too — otherwise tearing out the injector would lose them as well.
- Assembly change record, migration table, rollback and new self-check commands: see `docs/dsh-update-adaptation.md §4`.

### Re-runnable regression
- Added `tests/dsh_api_compat_probe.mjs` (`npm run test:dsh-api`): runs a registration pass with the host's or a **specified version** of dsh-tools,
  asserting 15 tools / 15 timeoutMs / 0 errors, and can output baseline JSON for cross-version diff; `--smoke` also
  really calls `blender_viewport` once with an already-aborted signal, verifying the cancellation path.
- `tests/README.md` gained "run these three first after a DSH update" at the top.

## v0.9.1 (2026-09-18) — fixing rifle-build's "93 feedback": silent failures (P0) ×4 + API consistency + file-level operators + GUI primitives + render queue

Source: 14 measured feedback items from the whole rifle-build (QBZ47-5.8 film-grade modeling) team (lead + 5 subagents, each with symptom/reproduction/evidence path).
**Every item was checked back against the code + empirically reproduced**: A1/A2/A3/B3 all **reproduced**; D2 (custom view returns an empty frame) **could not be reproduced** — that was aiming at nothing
(from/look_at not where the geometry is: with correct coordinates the model is dead center), but that is exactly why it should not "silently return an empty image";
this release added self-diagnosis to it (see D2).

### P0-A1 Unknown view names are no longer silently substituted (qc_render v3)
- `views` non-empty and **not a single one resolved** → `ok:false` + `unknown_views` + `available_views` (22-name catalog) + `hint`;
  **not one image is rendered** (old behavior: silently fell back to rendering 4 views with `ok:true` → "right filename, wrong angle" images slipped into the evidence chain).
- `views` omitted/empty → the default **3 views** consistent with v0.8.11 (iso/front/right). For Procedura's 4-view set, pass those four names explicitly
  — a patch release does not silently change the default output set.
- Response gained `requested_count / rendered_count / unknown_count` (team members hit "12 names rendered only 8 images with no error").
- Added **spelling** aliases: `side_left/left_side/left_view → left`, `side_right/right_side/right_view → right`, `front_view → front`,
  `back_view → back`, `top_view/topdown/top_down → top`, `bottom_view → bottom`, `iso_left → iso_l`,
  `iso_right/isoright/iso_back_right → iso_br`; **anything semantically ambiguous is never guessed** (`muzzle_end`/`breech_end`/`*_end` still go into `unknown_views`).
  Measured: `["front","totally_bogus","side_left"]` → 3/2/1, actually renders `front`+`left`.

### P0-A2 Headless QC defaults to `view_transform="Standard"` (qc_render v3)
- Default = `"Standard"` (removes the AgX/Filmic washout so threshold reading is reliable); passing `"scene"` = follow the scene (old behavior, for beauty images); passing a specific name = use that one.
- The response and **every jsonl line** carry the `view_transform` actually used; after rendering the scene is **restored item by item** (measured: default returns Standard while the scene stays AgX).
- ⚠ Behavior change: old calls that relied on "follow the scene color transform" should now pass `view_transform="scene"` explicitly.

### P0-A3 Structured results no longer have to be sliced out of stdout
- `blender_rt_headless` gained `out_json=<path>`; **results >4KB are automatically written to the working directory `results/<runId>.json`** (response `resultPath`/`resultBytes`).
- The `result` display limit in tool text 2 KB → **6 KB**; when a structured result already exists, the stdout block keeps only head and tail (no more duplicate amplification).
- plan-channel result limit **4 KB → 12 KB** (measurement tables/probe output no longer truncated).

### P0/P1-A4 Fake-failure classification + collection by runId
- Response gained `status` (`finished / script_error / blender_error / timeout / gpu_required_missing / blender_exe_missing`) + `failure_hint`.
  **Measured pitfall**: on a script `raise ValueError("boom")` Blender's **exit code is still 0**, and the old criterion looking only at exit misses it → now judged `script_error` by "missing receipt + stderr exception marker".
- `runId` + `how_to_recover` go into the response: a client disconnect **does not mean failure**, collect with `blender_rt_job(op="status"/"collect", id=runId)`.

### P1-B1/B2 API consistency
- `K.dsh_*_api` changed from a plain dict to a **callable dict subclass**: `api("op", {…})` / `api({…})` → **the resolved dict**; `api.call(...)` is synonymous;
  `api["dispatch"](op, json_str)` **still returns str** (the engine contract is unchanged). Covers audit / contract / txn / deliver / generator / motion / planner / presets / perf / runner + qc_render + view.
- One pitfall noted in passing: `dict` is a static type, and `instance.__class__ = subclass` raises `TypeError` (measured) → the implementation became "swap in a new instance".

### P1-B3 headless accepts a script file
- Added `script_file=<.py>` (accepts both Windows `D:\…` and WSL `/home/…`); when `file=` is given a `.py` it is **automatically recognized as a script** and marked `auto_from_file:true`
  (the old version said `File format is not supported in file "…py"` — reproduced by measurement).

### P1-B4 Parameter/environment contract
- Added an `env={…}` input; the plugin automatically injects `DSH_RUN_ID / DSH_OUTDIR / DSH_ARGS / DSH_SESSION / DSH_PLUGIN_VERSION`,
  readable in the script as `K.args / K.run_id / K.session / K.outdir_env / K.env`.
- **Measured pitfall**: when spawning Windows blender.exe from the WSL side, **env does not cross the boundary automatically** (Node passed 6 DSH_* variables, the child's `os.environ` saw none)
  → automatically declare `WSLENV` **and** inject once more inside the script (double safety). Measured `K.args == ["delta","echo"]` with `DSH_*` visible inside the script.

### P2-C1 File-level interference/overlap operators (audit v3: AUDIT_VERSION 2→3)
- `audit_overlap(file_a, obj_a, file_b, obj_b)`: BVH triangle-pair intersections + **true intersection segment length** + overlap bbox (both scene units and mm);
  either end can be "an object in the current session" or "another .blend file", with no need to `register_component` first.
- `audit_interference(...)`: **intersection volume estimate (mm³) + 95% confidence interval + tri-state** (supported / refuted / unresolved);
  the basis is spelled out: Monte Carlo ray parity check, sampling only in the overlap region, **not an exact boolean**; open meshes/non-manifold → `unresolved` (no plausible-looking fake number).
  Measured (1×1×1 cube vs the same cube shifted 0.5 along X, analytic intersection volume 5×10⁸ mm³): `audit_overlap` pair_count=8 / overlap bbox exactly matching the analytic box / true intersection segment 500 mm / 18 ms;
  `audit_interference` **496,620,000 mm³ vs analytic 500,000,000 → relative error 0.676%** (95% CI 0.623%) → `supported`; not intersecting → `refuted` (upper bound 1 mm³); open mesh → `unresolved` with `volume=null`.
  Self-test `tests/audit_file_selftest.py` → **50/50**. The R2 self-test also caught and fixed three real bugs: the ray-advance eps must be > the float32 geometry resolution (otherwise a 0.92% systematic bias → volume short by 10%),
  `_ray_limit` failed to divide by the direction component (oblique rays truncated 1.73× too early), and when loading two files the cleanups on both sides deleted each other's objects.
  ⚠ Error-basis correction: the "about ±0.4% at n=200k, 10% occupancy" line in my brief was optimistic; the correct value is **±1.31%** (the formula is already in the response's `error_caliber`).

### P2-C2 audit-class ops support `file=`
- `audit_connectivity / audit_gate / audit_measure` all accept `file=<.blend>`: temporary load → the same analysis chain → **cleanup no matter what the outcome**;
  the response carries `source: "file:<path>"` and `cleanup` details (measured: `file=` results equal the session-side objects/tris/bbox item by item, and object names keep the file's original names).

### P3-D1 GUI primitives (view v2)
- `gui_frame(object=…)` / `gui_shading(mode=…)` / `gui_open(path=…)` / `gui_help()` — executed plugin-side in a **real UI context**
  (inside `rt_do`, `bpy.context.screen` is None). Measured `gui_frame(object="Cube")` → `framed:"Cube", mode:"selected"`.

### P3-D2 Custom-view self-diagnosis (view v2)
- The response carries `coverage_estimate` (background taken as the **mode**, so `background=true` does not misjudge) and `objects_in_frame` (projecting object bboxes into the frame and counting) + `scene_bbox`;
  when no geometry is counted it gives `warning{code:"frame_looks_empty", scene_bbox, suggest:{from,look_at,lens}}`.
  Measured: aiming at nothing → coverage 0.00% + warning + suggest; rendering again per suggest → **coverage 68.11%** (no need to press Home yourself).
- Also fixed: the `x-dsh-view` header used to carry only 5 fields and was truncated at 500 characters; **non-ASCII (Chinese warnings) directly produced 502 "Invalid character in header content"** → header values are now URL-encoded.

### P2-E1 Render queue/lock (qc_render v3) — replaces the `render_lock.py` team members built themselves
- Cross-process file lock `<working directory>/locks/render.lock` (TTL + holder + waited ms): `blender_rt_plan(op="render_lock", args={action:"acquire"|"release"|"status"})`;
  `qc_render_views` **automatically** acquires/releases before and after rendering (`lock=false` turns it off), and `waited_ms` / holder / stale go into the response and every jsonl line (the **timing basis is auditable**).
- holder defaults to `DSH_SESSION#<pid>` (unique even among concurrent processes in the same session); breaking a lock **only honors the `acquired_at` timestamp + TTL**, not process liveness.
- Measured: a second holder with `wait_s=1` → refused, reporting `waited_ms=1001` + the current holder; a wrong holder's release is refused; **an expired lock is broken** (forge a lock from 2 hours ago + TTL 60s → `stale_broken:true`);
  a live production case: a killed process left a lock behind → broken by the next acquire once the 600s TTL expired.

### P3-E2 Default artifact paths carry the session
- Session name `DSH_SESSION` (default `plugin-pid-<pid>`): evidence default path → `dsh_evidence_<session>.png` (measured); `status` gives `session` / `resultsDir`.

### Real bugs in the tool layer fixed in passing (found by measurement this round)
- **The plan tool's `args` was silently dropped**: the harness's `type:"json"` sometimes delivers the object as a **string**, and the old code's `typeof x === 'object'` check came up empty →
  **every plan op's arguments were silently ignored while still returning `ok:true`** (hit by `gui_frame` / `gui_shading` this round; passing a `bogus_key` did not report "parameter mismatch" either).
  Now `jsonPayload()` parses tolerantly (accepts both objects and JSON strings), and invalid JSON errors explicitly.
- Passing an array as `args` was turned into `"[delta]"` by `String()` → arrays are passed straight through.
- A no-argument `perf`/`opt` op that was given `{}` → the python side received an extra positional argument (measured `_dsh_perf_status_cycles() takes 0 positional arguments but 1 was given`) → empty args fall back to `undefined`.

### Self-tests and regression
- Added `tests/engine_probe.sh` (**16 items**, backend HTTP probes) → **16/16**; added `tests/view_diag_selftest.py` (**16 items**) → **16/16**;
  `qc_render` self-test → **29/29** (v3); `tests/audit_file_selftest.py` → see below; all 9 existing self-tests re-run.

---


## v0.9.0 (2026-09-17) — Procedura fusion: assembly-level criteria + quantified change metrics + judgments invalidated as geometry changes

Source: a porting assessment after reading every file of [SpatiaOS/Procedura](https://github.com/SpatiaOS/Procedura) (MIT, Agentic 3D Modeling with Procedural Control)
(analysis table: `docs/procedura-fusion-analysis.md`). **Only criteria and algorithms are ported, not the tech stack** (no OpenSCAD / Isaac / its TS runtime).
Full regression: 9 self-tests all green, each in its own process (measured numbers item by item below).

- **★ First, a real bug: `audit_*` was never wired up**. The `blender_rt_plan(op="audit_mesh" / "audit_scene" / "audit_duplicates")` documented in `docs/` all along
  actually fell into the contract layer reporting `unknown contract op` (measured: `audit_help` returns `"unknown contract op"`) — audit.py was reachable only via the preload channel.
  This release wires `audit_*` and `montage` into the engine routes for real (`engine.mjs` + `server.mjs` read-only list), and adds the three new routes `motion_* / deliver_* / generator_*`.

- **Assembly-level connectivity gate `audit_connectivity` / `audit_gate`**: connected components + floater attribution + micro-gap grading.
  Criterion: visible floater = longest bbox edge ≥ **1%** of the whole model's longest edge; the contact basis is `micro_gap_mm` (default 0.3).
  **Two deliberate divergences from upstream** (both written into the response, not hidden):
  ① No longer "largest-volume component = body, everything else is a floater" — with two equally large parts that rule picks one as the floater at random (the self-test caught it, A/C volumes both 1.0);
     instead **each component is asked "are you attached to another component"** (`attached` three classes: floaters / tolerated / unconfirmed).
  ② Upstream judges micro by bbox gap (fine for a single mesh; **in multi-object assemblies bboxes generally overlap → gap is always 0 → everything passes**); this release adds a **mesh-level recheck**:
     BVH `find_nearest_range` + **surface sampling** (≤400 points; using vertices misses — vertices across a 0.2mm gap between large planes can be meters apart).
     Self-test case F (bbox overlapping A, face-to-face 1.32 mm) is judged a floater; case C (0.2 mm gap) is judged genuinely micro.
  Large meshes (>500k triangles) skip the mesh recheck → `attached=None` → the gate **degrades to ok=null**, and unconfirmed must never be read as passed.
  The basis and distribution travel with the response (`gate_caliber` / `gap_histogram` / `floater_gap_range_mm`).
  **Real-machine measurement (COCKPIT_DELIVERY, 14 objects / 97,438 faces)**: 0.3 mm basis → 178 visible floaters (0.33–1.14 mm from their nearest neighbor) + 970 confirmed contacts;
  2.0 mm basis → 63 floaters. That says the model is an assembly of "close but not touching" parts, not a single solid — what basis to use depends on what you want.

- **Mesh drift metric `audit_drift`**: symmetric Chamfer distance = **shape drift** (not bevel!). Upstream's basis is "normalize each → point to nearest sample point";
  this release switches to **BVHTree point-to-surface**: 20k samples **21,397 ms → 46 ms (460×)**, and the same mesh reads **0.000000** (upstream's basis has a sampling noise floor of 0.017).
  ⚠ Semantics: normalization removes translation and uniform scaling → it answers "how far did the shape change", not "how far did it move"; displacement is reported separately by `bbox_delta.moved_mm` (the self-test pins both).
  bands: ≤0.01 essentially unchanged / 0.01–0.05 slight (≤2.5% of the longest edge) / >0.05 obvious; the grid fallback basis is systematically high, and the response marks `metric`.

- **Measurement pack `audit_measure` / floater snapping `audit_snap_floaters`**: world bbox + per-axis gap/overlap (mm and %) + neighbors (contract graph + spatial nearest K);
  snap only reports by default, and **only translates objects that belong entirely to that floater** (never tears a welded body apart — the failure point of upstream v3 snap),
  and when the bbox reads 0 it automatically falls back to **mesh-level nearest point pairs**.

- **Evidence invalidated by edits + verdict auto-downgrade on drift (contract layer)**: added `fingerprint` (objects/faces/verts/world bbox + a 12-digit digest);
  evidence and verdicts are both bound to the fingerprint, and `ledger` marks each one `stale` when it does not match; `verify` records a bbox snapshot, and later geometry drift > 10% of the diagonal (or size > 20%)
  → `supported` **auto-downgrades to unresolved** when read via status/ledger (objects with animation data are skipped). Contract self-test 24 → **33 items**.

- **Three render-harness items (qc_render v2)**: `mode="parts_color"` (12-color per-part coloring + `parts_color_meta.txt` legend + item-by-item restore after rendering;
  shared meshes are copied first for isolation, otherwise the colors bleed), jsonl carries the **measured `device`** per line (guards against Cycles silently falling back to CPU ≈7×; if unavailable it is `null` + named, never guessed),
  and `qc_render_catalog` (22 views / 4 groups / alias normalization: `iso-FR-top`/`isometric`/`isoright` → `iso`; **unknown names are no longer silently rendered as iso**).
  Two existing issues fixed in passing: `op="qc_render_help"` used to fall into unknown (engine strips a 3-character prefix; the `render_*` alias was added);
  `_set_engine` changed the engine and did not restore it when framing failed and returned early. Self-test 14 items + 15 boundary items all green.

- **Mate gate + assembly feature library + interference upgrade (contract layer v3)**: `mate_check` measures contact-area ratio / one-sided median gap / penetration depth on **the actual mesh**
  (contact distance = 1.5% merged diagonal; sampling ≤4000; two-way area ratio takes max; fit's four grades clearance 0.25 / location 0.15 / press −0.05 / snap 0.20);
  `fit_help` reads `runtime/assembly_features.json` (9 features + four grades + lead-in chamfer + ISO 273 + shared-nominal discipline);
  `interference_report` reports depth/volume ratio/severity pair by pair, marking both ends of already-registered connections `declared` (planned contacts are exempt by default, still reported when over `depth_eps` default 0.2 mm);
  `check_interface` makes an **additive upgrade** (old bbox fields unchanged word for word + a new `mesh` block).
  Measured: a normal fit has a one-sided median gap of **0.1498 mm** (design 0.1500) → supported; moving 5 mm away → refuted, naming "not touching at all";
  deep clipping depth_max **3.000 mm** > 0.2 → refuted; `samples=2` → unresolved; the interference-fit grade measured 0.0499 (design 0.05) → supported.
  Self-test 33 → **57 items**.

- **Pending-edit transactions + delivery export (txn v3 + new module deliver.py)**: `edit_begin / edit_check / edit_accept(verified) / edit_revert(why) / edit_status`
  — one pending at a time; accepting requires "a review + one verified sentence (empty string refused)"; revert is budget-free but capped at `max(2, cumulative steps)` and debounced (consecutive reverts with the same label are refused);
  `deliver_export / deliver_verify`: unit-box normalization + multiple OBJ/MTL sets + manifest (md5/bytes/unit conversion/normalization trio),
  changing one byte or adding one face must FAIL. txn self-test **55 items**, deliver self-test **53 items**.

- **Trajectory JSONL**: every top-level call writes `<working directory>/trajectory/blender_rt-<date>.jsonl` (route/op/ms/ok/argument summary/summary hash),
  rotating past 16 MB; `DSH_TRAJ=0` turns it off, `DSH_TRAJ_FULL=1` records more arguments; `engine.status()` gives the path.

- **Articulation/mechanism `motion_*` (new module motion.py)**: joint axes/anchors **measured** (rotational symmetry + contact band, two independent pieces of evidence; on conflict it reports unresolved instead of picking one),
  **sweep verification** (replacing Isaac: multi-phase driving + BVH interference; zero interference with real displacement → supported; a collision → refuted and named, measured naming `MS_Blocker`, deepest 0.019 m),
  URDF/USDA export (single-tree composition, degenerate joints downgraded to fixed with a warning, structural self-check: XML parseable / names unique / endpoints exist / no cycles / mesh files present).
  After the sweep **all objects' matrix_world are compared item by item and restored** (max_delta 0.0). Self-test 25/25 (the other evidence pathway: hinge along Y + axis fixed by a pinless contact band + a prismatic slider).
  **Three real pitfalls fixed along the way**: ① `%.9f` silently wrote an mm-scale mass of 8.6e-11 as `0` (changed to `%.9g` plus an assertion);
  ② the `meters_per_unit` default of 0.001 gives absurd magnitudes in metric scenes → added `meters_per_unit="scene"` (reads scale_length) + a suspicious-unit warning;
  ③ the same object claimed by two joint groups counted geometry and mass twice in URDF/USDA → now `ok:false` with the conflicts listed.
  Boundaries (written in `motion_help`): it is kinematics + BVH sweeping, not physics validation; zero interference needs at least one bystander object, otherwise unresolved;
  axis inference is only valid for identifiable geometry (a thin flat plate → unresolved); USDA is minimal usable ASCII, not the full UsdPhysics schema; this machine has no URDF/USD consumer for end-to-end load validation, only the structural self-check.

- **Generator `generator_*` (new module generator.py) — a lightweight Blender-native take on the #18 code-as-modeling channel**.
  Neither side of this machine has OpenSCAD installed (really wiring it up needs the Manifold backend: the same `hull()` takes CGAL 1774 s vs Manifold 1.77 s), so those four things are obtained the Blender-native way:
  **program as shape** (register a python generator) + **compile gate** (reproduce from scratch in a brand-new headless process) + **module-level cache** (do not rerun when neither the source hash nor the argument hash changed)
  + **receipt expires when the source changes**. Self-test measured: 3 cubes supported (805 ms) → running again hits the cache (ms=0) → expect mismatch refuted → no expect given unresolved →
  after editing the source diff.changed=true/verdict=refuted → a broken script refuted.

**Two infrastructure problems fixed in passing (both from this release's measurements)**:
- **preload modules overwriting each other's helpers**: the engine splices several modules' source into **the same globals**, while every runtime module defines `_j/_kernel/_store/_now` →
  measured `preload="txn,deliver"` crashed txn outright (`KeyError: 'marks'`). Now each module execs into **its own namespace**
  (private names do not leak; public names and common imports are still copied back to globals → backward compatible), and both paths (headless / job layer) are changed.
- **Two channel semantic pitfalls** (now written into their respective scope/help): ① headless `ok:true / exit=0` **does not equal** script success — Blender's `--python`
  keeps exit code 0 when an exception is thrown (the generator self-test caught it), so the verdict must read the receipt/exception marker; ② the source-injection channel has **no `__file__`** (reading a data file from the same directory needs `K.runtime_dir` as a fallback,
  see `contract._features_path()`).

---


## v0.8.9 (2026-09-16) — fixing ">15 s calls fail silently" and 5 other items (external session feedback, batch 1)

Source: a retrospective from another session using the plugin (5 channel pain points). After checking each item back against the code, **1 is a real bug and 4 are small gaps**, and this release fixes them all.

- **★ Real bug: headless / worker / txn / preset calls longer than 15 s "fail silently"**. Root cause: these four routes go through
  `streamJson(res, producer, hbMs=15000)` — **a heartbeat line is written first every 15 s** `{"heartbeat":true,...}`, and only the last line is the result;
  while the client's `backendPost` does `await r.text()` + **`JSON.parse` on the whole thing** → with several lines it throws `Extra data: line 2 column 1` →
  degrades to `{ok:false, raw:...}` → the tool layer printed only `HEADLESS failed · exit=undefined · undefinedms` (no result, no logs, no hint),
  **while the server-side child process had in fact finished with exitCode=0**.
  Fix: on parse failure, take **the last non-heartbeat JSON** by scanning lines from the end, and record the heartbeat count into `__heartbeats`; beyond 15 s the tool layer explicitly notes "this run went through the streaming receipt with N heartbeats".
  Measured: a 20 s script before the fix `HEADLESS failed · exit=undefined · undefinedms` (21477 ms) → after `HEADLESS ok · exit=0 · 21406 ms` + `result: {"slept":20}` + log path;
  `blender_rt_worker exec` (sleep 20) after the fix `WORKER exec ok · 20000ms` + `result: {"worker_slept":20}`.
- **Job layer supports preload** (previously only headless had it): `blender_rt_job(op=start, preload="qc,qc_render")` splices the runtime module source into the job script.
  Measured: inside the job `K.dsh_qc_render_api.version = 1`, API surface `["dispatch","help","render_views","selftest","version"]` (job-mu45mi7xip4, done/exit=0/8019 ms).
- **headless `args` supports quotes**: the old implementation's `split(/\s+/)` cut `--flag="a b"` into two tokens; now a matched pair of quotes is not a separator.
  Measured: `args='--alpha "a b" --x=1 plain'` → `["--alpha","a b","--x=1","plain"]`.
- **Zero-size image-read guard** (qc.py, QC_VERSION=4): Blender **silently** returns 0×0 for unsupported formats (like GIF) without throwing → now it reports directly
  `image read failed or format unsupported: <path> (Blender can decode PNG/JPEG/WebP/BMP/TGA/TIFF/EXR; GIF is silently read as 0×0) → convert to PNG with an external tool first`.
  Measured: loading a 2×2 GIF → before `size=[0,0], has_data=false` (silent) → after, the explicit error above.
- **Error hints gained two Blender semantic pitfalls**: `StructRNA of type ... has been removed` (→ every Object/Collection reference grabbed before switching files is invalid; re-fetch after open)
  and `context is incorrect` (→ reset active/select, or `temp_override`, or split into two calls). Both were triggered and echoed by measurement.
- **Long-task boundaries written into tool output**: for a headless call >60 s it hints "next time use `as_job:true` directly / go through blender_rt_job".

## v0.8.8 (2026-09-15) — built-in multi-view render harness (P2-1, last item of external feedback #4)

The shape external feedback asked for: input {file, views[], res, samples, thr, outdir} → automatic exact framing by bbox + fixed three-point light
+ per-image jsonl timing + a within-budget verdict ("this is the thing every modeling task has to rewrite"). This round consolidated it into a general capability.

- **New module `runtime/qc_render.py`** (hangs off `K.dsh_qc_render_api`), entry point `blender_rt_plan(op="qc_render_views", args={...})`;
  also supports `args.asJob=true` to go straight to the job layer (a headless process isolates the scene by nature). qc.py also registers a `render_views` adapter (works even if only qc.py is injected).
- **Automatic framing**: merge the AABB of all visible meshes (`targets` can narrow it) → solve camera distance per corner + `margin` padding; named views
  front/back/left/right/top/bottom/iso/iso_l/iso_back/front_high/right_high, also supporting `az=35,el=20`, explicit `from/look_at`, and orthographic.
- **Fixed three-point light**: SUN lamps key 3.2 / fill 1.0 / rim 2.4 (fixed angles, camera-relative azimuths: +35°/45°, -50°/8°, +165°/30°),
  **built temporarily in this process only**, deleted after rendering with all scene render settings restored (measured in GUI: 95 objects, 1 camera, 4 lamps, no leftovers, viewport frame hash unchanged).
- **Per-image rendering + jsonl**: each PNG records `{view, ms, bytes, hash, path, res, engine, samples, camera, frame{bbox,margin_px,coverage,pred_bbox_px,proj_err_px}}`,
  written to `<outdir>/render_views.jsonl` (one line per image; lines already completed are kept even if the budget stops it midway).
- **Budget verdict**: `budget_s` (alias `thr`) stops immediately when cumulative render ms exceed it → `within_budget=false` + `stopped_early` + `skipped_views`, images already produced are kept.
- **Optional reference comparison**: `ref_path`/ref_box (a per-view dict is allowed) calls qc.py's `compare` per image (fixed alignment by default), with IoU/Dice/boundary distance/profile diff written into the jsonl.
- **Engine semantics**: default `engine="keep"` follows the process (headless/job guarantees EEVEE+RT via the engine prelude); `samples` writes both EEVEE taa_render_samples and Cycles samples; `view_transform` optional.
- In passing: path constants injected as `K.runtime_dir` (qc.py uses it to load same-directory modules on the spot); `bpy.types.Camera.calc_matrix_camera` was removed in Blender 5.2,
  so `bpy_extras.object_utils.world_to_camera_view` is used as projection ground truth for comparison.

**Measured (`D:/DSH/blender/out/preserve_scene_before_orca.blend` / 350 visible meshes / 512×512 / 64 samples / EEVEE+RT)**:

| view | render ms | bytes | output alpha bbox | frame margin (px) |
|---|---|---|---|---|
| iso (−45°,25°) | 2124 (first image includes shader compilation) | 154604 | [83,96,428,458] | L83 T96 R83 B53 |
| front (−90°,0°) | 798 | 162515 | [36,36,475,475] | 36 / 36 / 36 / 36 |
| right (0°,0°) | 565 | 192160 | [36,36,475,475] | 36 / 36 / 36 / 36 |

Total 3 images **3487 ms** (in-process 3571 ms) · jsonl 3 lines · `within_budget=true` (budget 120 s);
the 1.0 s-budget control run: stops after 1 image, `within_budget=false`, `skipped_views=["front","right"]`, images already produced are kept;
framing comparison `proj_err_px` 0.000009–0.000081 pixels (self-computed matrix vs world_to_camera_view); all 11 named views in the selftest land inside the frame;
comparison against the hand-written flow at the same camera position: the alpha channel is pixel-identical (same geometry/camera), RGB differs by ≤5/255 and only on 0.046% of pixels (EEVEE+RT random sampling noise;
the same fixture rendering twice in a row already differs by 1/255 as a control).

## v0.8.7 (2026-09-15) — P0-2 / P1-1 / P1-2 / P2-2 / P2-3 / P3 of external feedback #4

- **P0-2 Long tasks can reconnect to a handle**: `blender_rt_headless(as_job=true)` (or `auto_job_ms`) converts to the job layer automatically — returns `mode=job` + jobId + log path, so a client timeout no longer drops the result.
- **P1-1 Scene generation number**: the `/act` receipt carries `sceneEpoch` (objects/meshes/materials/nameHash), used to notice "someone else's rebuild wiped my assembly"; the `/act` route passes it through.
- **P1-2 Path constants into the script namespace**: `DSH_OUT` / `DSH_WIN(path)` / `DSH_WSL(path)` (works for standalone modules + `exec(open())` style too).
- **P2-2 rt_loop modeling measure templates**: the cookbook gained an input/return table for three measures + spec templates + coordination discipline.
- **P2-3 Error enhancement**: library occupancy (`libraries.remove` / `copy=True`), no camera (set `scene.camera` first), UNC form normalization or a `K.stage` fallback.
- **P3 Two Blender semantic pitfalls**: `libraries.write` can write a file with no scene; `transform_apply` does not scale Bevel width.

## v0.8.6 (2026-09-15) — fixing blender_rt_perf's dsh_perf_status NameError (P0, external feedback #4)

Root cause: when v0.8.3 added engine awareness to perf, it renamed dsh_perf_status to _dsh_perf_status_cycles and **appended the wrapper function to the end of the file**, while the registration dictionary (line 323) referenced it before the wrapper (line 338) → NameError on module import → the whole perf module failed to inject ('PERF status failed · name dsh_perf_status is not defined').
Fix: the registration dictionary became a lazily evaluated lambda, resolving the name only when called. Verification: status returns engine/engine_mode/eevee details; apply returns preset=eevee-rt (rt false → true).


## v0.8.5 (2026-09-14) — job layer + module hot reload + QC mask interval (implemented and verified; tooling and docs pending)

- **Job layer (engine + routes implemented, verified)**: job start/status/collect/kill/list. Measured: start returns a job id in 0.08 s; status=running immediately; 15 s later collect → done + result={"slept":12} + 40 artifacts + log path; kill → killed; list normal. Logs and artifacts land in outdir/jobs/<id>/.
- **Module hot reload (implemented, verified)**: kernel K.reload_modules(prefixes, root); rt_worker exec supports purge_prefix (passed through the /worker route). Measured: after editing the file, no purge reads the old value 1, with purge 2, purged=["pe_mod_test"].
- **QC mask interval (implemented, verified)**: qc_mask_sweep computes IoU per (sat,v) group with fixed alignment → iou_min/median/max + spread + recommended basis. Measured on a poster: 0.5914 / 0.6319 / 0.9324, spread=0.341.

**Pending (first thing next round)**: ① the blender_rt_job tool (the 15th tool, exposing op=start/status/collect/kill/list); ② four doc items (UNC writing changed to what measurement proves writable, `//` semantics, WSL env not crossing exe, applicability and the silhouette-fit recipe).

## v0.8.4 (2026-09-14) — worker exception visibility + path normalization + K.stage

Source: the third piece of external feedback (design-driven line). Two ★★★ items done:

- **worker exceptions returned (aligned with /act)**: the /worker route lifts error/traceback to the envelope level; the blender_rt_worker tool reads r.result.{error,traceback,stderr,stdout} on failure. Measured raise RuntimeError → envelope error + traceback complete (previously it returned only unknown).
- **Path form normalization**: `//wsl.localhost/...` was previously treated by Blender as "relative to the .blend" (resolved to <blend dir>\wsl.localhost\...) → now K.win_path() normalizes it to a backslash UNC path.
- **Added K.stage(path)**: copies to a local path as a fallback, returns {ok,src,staged,bytes,was_unc}; qc_load auto-stages and retries when reading fails. Measured a UNC path holding a Chinese-named image → D:\DSH\blender\tmp\stage\qc_front.png (437KB) → images.load 640×640.

> Ops note: engine.mjs loads when the backend starts (only Python modules are hot-reinjected by content fingerprint) — changing runtime JS requires blender_viewport(op="restart").

**TODO (not in this release)**: blender_rt_job job layer (★★★) · module hot reload K.reload_modules (★★) · QC mask interval mask_sweep (★★) · four doc fixes (★) · applicability and the silhouette-fit recipe (★).

## v0.8.3 (2026-09-14) — honest QC basis + auto mask guard + absolute-basis criterion

Source: a measured recheck of the planetary engine's "two versions" (old 09-12 / new 09-14 film-grade rebuild). The new build's ratio deviation is only 0.03%–0.29%, but the total-height basis differs by 11% (9,900 vs 11,000 m) plus the final render washed out by fog/AgX (saturation 0.2222→0.1181, fog feel 0.28→0.74) → "it doesn't feel faithful enough". Three fixes followed:

- **`iou` changed to fixed alignment (the honest value)**: search alignment moved to `iou_search`; the `scale_drift` warning threshold 12%→**5%**; new `iou_search_gain >0.05` warning (measured: a pure 11% scale difference was once absorbed by the search as **0.13 IoU**).
- **auto mask guard**: when the reference image's foreground share is >80% or <2% it automatically falls back to the threshold basis, and the receipt states `satv-fallback` + the reason (measured: a full-frame poster had auto foreground 95.9% → untrustworthy).
- **`ref_box` became optional** (omitted = the whole image; previously required, which made the first call fail outright).
- **New absolute-basis criterion** (cookbook layer 3): every absolute-size item must list a separate "absolute size comparison table" and state which basis it used — **ratios/IoU structurally cannot see an absolute-basis difference**.

In sync: `tests/qc_selftest.py` assertions updated; the operations guide/configuration reference basis notes updated.

## v0.8.2 (2026-09-14) — preset library (blender_rt_preset) + deployment SOP + integrating community strengths

- **Added the 14th tool blender_rt_preset (preset library)**: save/list/get/apply/delete/export/import; dot-path data; targets support MAT:/OBJ:/SCENE; with no targets it only previews; export/import goes through a single bundle for easy sharing. Measured: scene render.resolution_x 720 → 640 really takes effect. Inspired by the "recipe-ization" strength of lurenjia-l/dsh-blender-stylized-shading (generalized into a domain-agnostic mechanism).
- **Added docs/deployment-sop.md**: goals and completion criteria → environment probing → installation → connecting the addon → self-check (doctor/qc_self_check/engine) → reporting → troubleshooting quick reference (format borrowed from its AI_DEPLOY.md).
- **cookbook restructured into a three-layer skill structure** (domain methodology / platform primitives / delivery and acceptance SOP, with frontmatter trigger conditions); the configuration reference gained an engine index section.
- README (bilingual) gained "Acknowledgements / Credits", naming @lurenjia-l for the measured EEVEE pitfalls and the skill-layering method.
- Both trees consistent: 14 tools, presets.py, deployment SOP, cookbook, configuration reference, EEVEE work notes.


## v0.8.1 (2026-09-14) — fixing the /act route regression since v0.7.0 (Issue #4, thanks @yihefeikong-rgb)

engine.act was changed in v0.7.0 to return a structured object (stdout/stderr/error/traceback/mainThreadMs), but server.mjs's /act route still read the old out.result, causing: rt_do never having stdout, rt_do(file=...) silently running empty, and exceptions treated as success. Affects the repository edition/share package of v0.7.0 and v0.8.0. Fix: the /act route forwards the structured fields and passes file through to engine.act. Measured on this machine: print(123) gives stdout=123, a thrown exception gives ok=false + error + traceback, and a file= script really executes.


## v0.8.0 (2026-09-14) — default render engine switched to EEVEE + ray tracing (Cycles optional)

- Added the engine parameter (default eevee): sets BLENDER_EEVEE + use_raytracing=True + ray_tracing_method=SCREEN + shadow quality + taa_render_samples; the receipt gained engine / engineMode and an engine line.
- cycles keeps the original OptiX device prelude; keep leaves the settings untouched (backward compatible with gpu:"false").
- Why switch: EEVEE goes through the graphics backend and does not depend on preferences like compute_device_type → headless does not silently fall back to CPU the way Cycles does (measured 15.4×). Measured (360 objects / 512×512 / 64 samples): EEVEE+RT warm frame 1.35 s vs Cycles GPU 3.13 s = 2.3×.
- Cost: first-frame shader compilation (cold ~16 s, warm cache ~2.4 s) → for iteration use a blender_rt_worker hot session.
- rt_perf engine awareness: under EEVEE it applies the EEVEE preset and explicitly lists the skipped Cycles-only items; status returns engine / engine_mode / eevee details.
- QC records the engine: comparison results gained engine_at_qc (e.g. BLENDER_EEVEE+RT) — criteria are only comparable within the same engine.
- Doc slimming: deleted docs/author-private-edition-README.md, docs/ai-realtime-interactive-blender-channel-notes.md, docs/ai-modeling-two-level-loop-plan.md (their useful content merged into docs/operation-tutorial.md / docs/configuration-reference.md); the private and repository doc sets are now consistent.


> Other sessions/agents: read this first, then `MIGRATIONS.md` (path changes) and `README.md` (usage).

## v0.7.0 (2026-09-14) — transactions/rollback + built-in QC (with algorithm optimization) + exception observability + path bridging

> Source: usage feedback from the plush-build session (rebuilding a plush toy from scratch); item-by-item verification in `feedback-analysis-plush-line-plush-build.md`, algorithm details in `qc-algorithm-optimization-notes.md`. **Tool count 12 → 13** (added `blender_rt_txn`).

**① Exception observability (the #1 pain point in the feedback)**
- `rt_do` / `/act` wrapped with `DSH_ACT_OK`/`DSH_ACT_ERR`: **partial stdout / stderr / traceback are returned even on exceptions**. Measured `print(DIAG-1) … raise` → `stdout="DIAG-1 …"` + the traceback tail line (previously only one error line survived).
- Fixed misleading diagnosis: `diagnosis` is attached only to **transport/timeout-class** errors, while execution-class errors get `errorKind:"execution"` (previously a throw was misreported as `main-thread-busy`).

**② Path bridging (usable from the GUI channel too)**: the kernel gained `K.win_path / K.wsl_path / K.blend_path / K.out_dir / K.workdir` (`/mnt/d/x ↔ D:\x`, WSL internal `↔ \\wsl.localhost\...`, `//rel → relative to .blend`).

**③ Running files as a first-class citizen**: `blender_rt_do(file=...)` executes a workspace script directly; the kernel gained `K.run(path, reload_modules=True)`.

**④ Transactions / rollback**: added `runtime/txn.py` + the tool **`blender_rt_txn`** — file-level `snapshot/restore` (`copy=True` leaves the current filepath alone; measured on a 300-object project **96.7MB / 824ms**), object-level `mark/revert` (measured: moved to (5,0,0) → revert → **back to (0,0,0)**). Object-level **does not include topology/UV/vertex changes** (stated in the tool description).

**⑤ Built-in QC + algorithm optimization** (`runtime/qc.py`, prototyped from plush-build's 539-line script)
- Four optimizations: **adaptive mask** (smart alpha decision / background estimated from the borders + Otsu, no more manual thresholds), **centroid alignment + scale and translation search**, **actionable metrics** (Dice / missing area / extra area / boundary distance / profile diff), **anti-gaming** (`iou` and `iou_fixed` both reported + scale-drift warning + fixed alignment enforced in the inner loop + out-of-bounds pixels explicitly counted in the union).
- Verification: synthetic self-test self-compare **1.0000**, still **1.0000** when translated 12px; a perturbed real image directly compared **0.534** → after search **0.866**; five views **0.776–0.890** (against their 0.688–0.790; why their numbers were not fully reproduced is in the notes doc).
- Entry points: `blender_rt_plan(op="qc_compare" / "qc_compare_basic" / "qc_self_check" / "qc_robustness_check" / "qc_help")`; artifacts = overlay image + three-panel comparison image.

**⑥ Inner-loop measure presets**: `K.dsh_measure = {aabb_err, silhouette_iou, profile_err}`.
**⑦ Main-thread occupancy hint**: when `rt_do`'s ms > 1 s it hints to switch to `blender_rt_headless` / `blender_rt_worker`.
**⑧ Incidental fix**: module injection switched to a **content fingerprint** (previously it only checked `hasattr` → editing a module file had no effect in the same session).

## v0.6.0 (2026-09-14) — hardening from external usage feedback: GPU semantics / hot headless sessions / long-task streaming / structured failures / artifact filtering

> Source: feedback from another AI that ran 22 rounds of modeling with this plugin (45 pipeline runs + ~40 diagnostics); item-by-item verification and measurement in `feedback-analysis-other-ai-usage-experience.md`.
> Tool count 11 → 12 (added `blender_rt_worker`).

**① GPU semantics (★★★, the most expensive item)**
- Headless processes cannot read the user's preferences by default → Cycles **silently falls back to CPU**. Measured on this machine (1821-object project, 480×270/32spp):
  CPU 2.78 s vs GPU first frame 1.43 s / warm **0.18 s = 15.4×** (external feedback reported 5×; the real gap is wider).
- Added the `gpu` parameter (`auto` default / `true` force / `false` off): `auto` configures `prefs.compute_device_type` in the order OPTIX→CUDA→HIP→ONEAPI→METAL
  plus ticking the GPU devices and setting `scene.cycles.device="GPU"`, and **returns the `gpu` field** (before/after/configured/fell_back_to_cpu) — the "silent" property is killed off entirely;
  with `gpu:"true"` and genuinely no GPU backend → `ok=false` (not silent).
- Added the `use_user_config` parameter: passes through `BLENDER_USER_CONFIG` / `BLENDER_USER_SCRIPTS` (only meaningful together with `factory_startup:false`).

**② Hot headless sessions `runtime/worker.py` + tool `blender_rt_worker` (★★★)**
- A resident `blender -b` process: **the blocking accept runs on the main thread** (in headless `bpy.app.timers` fired 0 times when measured; only main-thread bpy execution is safe),
  reusing the **persistent kernel K** (the same `sys.modules["dsh_rt_kernel"]` semantics), ops: `start / exec / status / stop / restart`.
- Ships with the GPU prelude from the start; serial semantics (one request at a time; long code occupies the worker — that is the price of "hot" and also the source of safety); does not interfere with the GUI channel.
- Measured: `start` → pid/port/GPU ready; `exec ×2` → `K.n` 1→2 (**state preserved across calls**); `status` gives uptime/calls/objects/kernel modules; `stop` exits cleanly.

**③ Long-task streaming (★★)**
- Root cause measured: the client `fetch` response-header timeout is **300 s** (separate experiment: a service that delays sending headers by 330 s → `fetch failed after 300.9s, cause=UND_ERR_HEADERS_TIMEOUT`).
- `/headless` and `/worker` became **ndjson streaming**: headers return immediately + a heartbeat every 15 s + only the last line is the result → any duration (heartbeats < 300 s) is no longer cut off by the client timeout.
- Another measured conclusion: a client disconnect **does not mean the task failed** — the server-side child keeps running to completion and the artifacts still land in outdir (stated in both the docs and the tool descriptions).

**④ Structured failures (★★)**
- Full stdout/stderr **written to disk** with paths returned (`logs.stdout` / `logs.stderr`, by default in outdir);
- Extracts `lastException` (the last exception line in stderr) and the `traceback` section; `reason` gives the killed/GPU-unavailable/exit-code cause;
- Friendly escaping-pitfall hint: when a **literal \n** in the script (should be \\n) causes `SyntaxError: unexpected character after line continuation character`, it says so outright.

**⑤ Artifact-list filtering (★)**
- `outdir` artifacts filter out `__pycache__ / *.pyc / *.blend1|2 / tmp*` by default and return a `noiseFiltered` count; `include_noise:true` turns filtering off.

**⑥ Docs (★)**
- Tool descriptions now spell out the respective applicability of `blender_rt_cmd` (30 fixed commands, good for status/asset integration) and `blender_rt_do`/headless/worker (arbitrary Python, good for heavy geometry generation);
- Added three sections "GPU semantics", "Long tasks", "Hot headless sessions", and wrote "client timeout ≠ failure" into the tool descriptions and the tutorial.

## v0.5.0 (2026-09-14) — contract layer (S1/S2) + planner (S3)

> Source: landing issue #3 (@wujinz's "white-boxing + planner" suggestion). Methodology and criteria in `docs/assumption-driven-modeling-cookbook.md`,
> reproducible experiment in `docs/examples/chair-backrest/`, self-tests in `tests/contract_selftest.py` and `tests/plan_selftest.py`.
> Tool count 10 → 11 (added `blender_rt_plan`).

**① Hypothesis-driven modeling cookbook (S0, zero code)**
- `docs/assumption-driven-modeling-cookbook.md`: templates for hypotheses/ranges/prohibitions/refutation conditions, two ways to run a range search (GUI inner loop / headless blocking),
  the **identifiability** criterion, tri-state verdicts (supported / refuted / unresolved), probe design and a provenance table, 7 measured pitfalls.
- `docs/examples/chair-backrest/run.py`: a purely headless reproducible experiment (~3 s). Measured conclusion: under external evidence the attach and insert residuals are **exactly identical (184 / 184)**
  → must report unresolved; `dy` is identifiable (range 790), `dz`/`tenon_len` are not (range 2 / 0); the dismantling probe (depth gauge) reads 0.000 m vs 0.065 m (true value 0.060 m)
  → attach refuted, insert supported. Results and evidence images archived in `docs/examples/chair-backrest/` (including results.md/json and 5 evidence images).

**② Contract layer `runtime/contract.py` (S1+S2, API at `K.dsh_contract_api`)**
- S1: `register_component` / `register_connection` (candidates/parameter ranges/prohibitions/confidence/required evidence) / `register_envelope`,
  `check_envelope` (out-of-bounds list), `check_interference` (AABB sweep pruning along x + BVH exact check, with a timing breakdown), `check_interface` (gap/penetration between two components),
  `destructive_guard` (**boolean_union / weld / merge / apply_transform on an undecided connection is blocked outright**, reporting `Unsupported Destructive Merge`),
  `evidence` (image + md5 + size accounting), `ledger` / `status` / `report` (Markdown report: hypotheses/verdicts/evidence/reproduction commands).
- S2: `verify` (tri-state verdict: external error + identifiability + probe reading), `flip` (flip a hypothesis and keep history), `advance` (proposed → testing → supported/refuted).
- Measured (headless, `tests/contract_selftest.py`): **24/24 passed** (including "undecided connection → Boolean blocked", "tenon_len not identifiable → unresolved", "probe on target → supported").

**③ Planner `runtime/planner.py` (S3, API at `K.dsh_plan_api`)**
- Object graph: Component (box / cylinder / sphere / mesh_copy) + Connection (candidates/state/prohibitions/offset) + Feature (array / grid / mirror).
- Diagnostic codes (IDE style): `MissingComponent` / `MissingObject` / `UnresolvedConnection` / `UnsupportedDestructiveMerge` /
  `Cycle` / `ParamOutOfRange` / `UnknownKind` / `PlanInvalid` (hard errors refuse compilation outright).
- `order` (topology: components → connections → features), `build` (`dry_run` produces the plan first; compiled artifact prefix `PLAN_`; `hidden_when` decides existence by connection candidates;
  automatically creates and checks envelopes in the contract layer per `plan.envelope`), `graph` (mermaid / dot).
- Measured (headless, `tests/plan_selftest.py`): **18/18 passed** (including dry_run leaving the scene untouched, feature expansion, connection offsets, both `hidden_when` states,
  `ParamOutOfRange`, `Cycle` detection, hard errors blocking compilation, and the envelope check wired to the contract layer).

**④ Tools and routes**
- New tool **`blender_rt_plan`** (11 tools): contract ops called directly; planner ops use the `plan_` prefix; `report` supports writing to disk via `path`.
- Backend gained `POST /plan` (the write route is lease-gated; read-only op allowlist: status/help/ledger/check_*/plan_status/plan_validate/plan_order/plan_graph),
  `stats.plan` counter.

## v0.4.1 (2026-09-14) — addon protocol adaptation: supporting both the ahujasid and harveyxiacn addons

> ⚠️ **`ahujasid` in this section is the historical name from before the rename**: since v2.0.0 the protocol discriminator id is called **`flat`**, with `ahujasid` kept as a **deprecated alias** (old configs are still accepted, `resolveProtocol` normalizes it to `flat`). This section's text is kept as it was before the rename.

> Source: external contribution [PR #2](https://github.com/sixtysevenlf/dsh-blender-plugin/pull/2) ([@yihefeikong-rgb](https://github.com/yihefeikong-rgb), corresponding to issue #1), **merged** (merge commit `b0a04b3`).
> Status: the author measured on Windows 11 + Blender 5.2.1 LTS + harveyxiacn `blender_mcp_addon`; the maintainer side did an independent review before merging: `node tests/protocol_selftest.mjs` → **28/28 passed**, plus a real-machine check with the official addon for no regression (`/doctor` → `protocol=ahujasid from=auto`, `execute_code` and custom-view framing normal).
> Added the `addonProtocol` config item, default `auto`. **Does not change existing behavior**: the flat protocol still comes first, and machines with the official addon need zero configuration.

- **Added `runtime/addon-protocol.mjs`**: collapses the differences between the two addons (frame splitting / command vocabulary / reply envelope) into protocol descriptors, with `AddonClient` and `freshPing` sharing the same `plan / encode / decode`.
- **Added config `addonProtocol`** (`auto` / `ahujasid` / `category-action`, equivalent env var `DSH_BLENDER_ADDON_PROTOCOL`): `auto` probes once on first use and caches it — it first sends a flat ping **without a newline** (only flat addons reply), and if there is no reply sends a category/action ping with a newline, correcting itself by the reply envelope's shape (so an addon being busy for a moment does not misjudge the protocol).
- **Diagnostics upgraded**: `/doctor` outputs `protocol` / `protocol_label` / `protocol_from`; the old "port reachable but ping does not reply" was always classed `addon-thread-stuck`, now it probes the protocol once more and, when it really is a protocol mismatch, gives `detected_protocol` and the fix "change `addonProtocol` to X"; `diagnose()`'s panel hints also follow the protocol.
- **category-action-side adaptation**: `execute_code → utility.execute_python` (the reply is re-wrapped as `{executed,result}`, otherwise `/act`'s stdout and `LOOP` marker parsing are all empty), `get_viewport_screenshot` / `get_world_state_snapshot` generated plugin-side in python (the same-named handler on the other side is incompatible in both its parameters and the Blender 4 legacy API), telemetry commands go to local stubs, and the 5 asset integrations report an explicit error.
- **Added self-test `tests/protocol_selftest.mjs`** (`npm test`): two mock addons cover probing / parsing / calls under both protocols / error propagation / not faking success when a capability is missing, 28 assertions in total, **needs no Blender**.
- Docs: `docs/configuration-reference.md` §6 gained a "two addon protocols" subsection; the prerequisites and troubleshooting table in `README.md` and `docs/zh/README.md` each gained a line; `dsh-blender.config.example.json` gained `addonProtocol`.

## v0.4.0 (2026-09-13, this session) — three batches of enhancements: diagnostics / custom views / leases / headless processes

> Status: **implemented and measured item by item** (every entry below carries measured values, not a plan). Tool count 9 → 10.

**① Observability (diagnostics)**
- Tool errors are no longer just `connect timeout`: on timeout/unreachable it automatically runs a three-level determination and gives a human reason (`kind` + `summary` + `fix`):
  - TCP unreachable → `blender-unreachable` (Blender not running / addon not listening on 9876)
  - TCP reachable + `ping` replies → `main-thread-busy` (main thread occupied: rendering/modal operation)
  - TCP reachable + `ping` does not reply → `addon-thread-stuck` (the addon's client thread is stuck)
- Added `GET /doctor` + `blender_viewport {op:"doctor"}`: **really runs one bpy round trip** (`status`), reporting `ok` only if it succeeds (measured round trip 97 ms / ping 50 ms); only on failure does it fall back to the three-level determination above.
- Added `GET /who` + `{op:"who"}`: lease holder + TTL + channel metrics (calls/errors/timeouts/inflight/lastCmd/lastCmdAgeMs/views/headlessRuns).
- `/status` carries `metrics`, and carries `diagnosis` **only when there is a lastError** (cleared on success, so no stale conclusion shows); the error bodies of all write/read routes uniformly carry `diagnosis`.

**② Custom-view frames (new `runtime/view.py`)**
- `blender_rt_see` gained `from / look_at / lens / ortho / ortho_scale / view_size / shading / overlays / view_mode`; giving `from+look_at` uses a custom view **without creating a camera object, touching `scene.camera`, or touching the user's viewport**; `shading/overlays` are changed temporarily and restored as soon as the image is drawn.
- The matrix is built in-house and compared against `calc_matrix_camera`: landscape / portrait / ortho, three cases, **max deviation 1.2e-7** (forward/orthographic/shift parameters consistent with camera semantics).
- PNG written by hand (zlib+CRC): the framebuffer read back is already sRGB 8bit, and writing the bytes directly avoids a second gamma (the `bpy.data.images` path would re-encode); reading out `memoryview(tex.read())` and flattening 1920×1080 takes only **1 ms**.
- Measured: live 900×506 **276 ms**, 640×360 170–261 ms, headless 320×180 **85 ms**; rendering repeatedly with the same parameters gives **identical md5** (hash `3a7bee2a`, deterministic).
- `view_mode:"render"` fallback: temporary camera + `render.opengl` (640×360 → 1157 ms), the camera is deleted afterwards and everything restored item by item; a viewport failure degrades automatically and carries `fallback_from` in the response.
- Blender 5.2's `gpu.init()` lets a `-b` headless process draw offscreen too → batch multi-angle image production can be done fully offline.

**③ Write-channel leases (`/lease` `/release` `/who` + `{op:"lease|release|who"}`)**
- Semantics: **zero friction when there is no lease**; with a lease, another session's write routes (`/act /cmd /loop /perf /opt /headless`) return `409 {error:"leased", holder, expiresInMs, hint}`; `force:true` preempts; `renewOnly:true` only renews without preempting.
- **Read-only ops are exempt**: `perf status/help`, `loop status/board/help`, `opt analyze` (looking at the current state should not be blocked).
- The plugin automatically carries `holder` (`plugin-pid-<pid>`, overridable with `DSH_BLENDER_HOLDER`); the 15 s watchdog only renews the heartbeat when it **already holds** the lease.
- Measured 9 paths: someone else holds → 409 · no holder → 409 · force preempts and the write succeeds · who shows holder/TTL/renewal · own heartbeat renews · another's heartbeat does not preempt · writable after release.

**④ Independent render process (new tool `blender_rt_headless`)**
- The WSL side `spawn`s Windows `blender.exe -b` (binfmt interop), with stdout/stderr returned live; `file` accepts WSL paths (`/mnt/d/...` auto-mapped to `D:\\...`) or Windows paths (internally converted to UNC).
- Defaults to `--factory-startup` (fast, **does not take port 9876**); `file / outdir / args / timeout_ms / factory_startup / bootstrap` are controllable; `print("HEADLESS {json}")` is parsed into `result`; new `outdir` files are listed by time; timeout → SIGKILL.
- `preload:"view,perf"` splices `runtime/*.py` source to the top of the script → a headless process can use `K.dsh_view_api` / `K.dsh_perf_api` too.
- Measured: building a 3-cube scene + view.py self-test + rendering 2 custom-view images = **2.66 s**; opening the 1821-object `FISTONE_v3.9_S5_master_delivery.blend` and reading settings = **1.24 s**.

**Docs**
- `README.md` gained §4 three batches of enhancements (with all measured values and the 9 lease cases), the tool table 9 → 10, 3 more known limitations, and env vars in the porting notes.
- The old text's "advisory lease / `require_lease` / `{op:"render"}` / `resolution` parameter name" did not match the implementation; this release rewrote it to match (see §①③④).
- `MIGRATIONS.md` gained the v0.4.0 API change entries.

## v0.3.0 (2026-09-13) — standalone package

- Package name `@dsh-external/dsh-blender-viewport` → **`@dsh-external/dsh-blender-plugin`**; directory `plugins/dsh-blender-viewport/` → **`dsh-blender-plugin/`** (ships its own `runtime/`, all paths relative).
- Added `blender_rt_perf` (render performance diagnosis/presets/restore) and `blender_rt_opt` (object slimming: merge candidates/safe merge).
- Backend 15 s watchdog (auto-relaunch on disconnect); `blender_viewport op=restart`.

## v0.2.0 / v0.1.0

- Direct addon socket connection (bypassing MCP/CLI): `blender_rt_see / rt_do / rt_watch / rt_cmd / rt_commands` + persistent kernel `K`.
- `blender_rt_loop` inner loop (timers-driven, 160 tick/s, penalties/annealing/candidate table/export).
