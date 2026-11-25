# Make an AI assistant install the plugin correctly (a prompt you can copy as-is)

**Why this page exists**: pasting the repository URL straight at an AI commonly fails in these ways — skipping the §2 prerequisites and building anyway; inventing its own `blenderExe` / port / configuration items; treating "the command finished" as "it is installed"; declaring success without running `doctor`.
The prompt below turns "**read first → then install → accept against criteria**" into hard requirements; copy and paste it.

> **Current version facts (2026-11-05)**: plugin **v3.0.6** · **15 model tools** · plan catalog **34 family / 228 op** ·
> Blender-side addon **v1.11** (protocol **11**) · backend `127.0.0.1:9877` / addon `127.0.0.1:9876`.
> **Acceptance criteria**: GUI route = `doctor` returns `kind=ok`; pure headless route (no addon) = `rt_worker(start)` + `see` render an image as self-proof
> (doctor's bpy round trip being unreachable is expected). **The GUI is no longer required**: interactive headless (persistent worker + see/watch/reset) can model independently.

---

## ① General prompt (any AI assistant)

~~~text
Please install this DSH plugin for me from npm: dsh-blender-plugin@3.0.6

Requirements before you start (must be followed):
1. First read the repository's docs/zh/README.md in full: prerequisites, the npm install in Quick start, common failures, and AGENTS.md.
2. Check the 5 prerequisites one by one; if one is missing tell me first, do not skip it, and do not decide on my behalf.
   Current version: plugin v3.0.6 / 15 model tools / plan catalog 34 family 228 op / addon v1.11 (protocol 11).
   Note: a normal install needs no clone or build; the npm package ships lib/. Only source development needs npm ci --legacy-peer-deps && npm run build.
3. Follow the 5 steps in §3 exactly; take configuration items only from docs/configuration-reference.md, do not invent your own paths / ports / config names.
4. Acceptance criteria (pick the one for your route; when the other one does not apply, say why):
   · GUI route: curl -sS http://127.0.0.1:9877/doctor → kind=ok, and blender_rt_see(max_size=560) returns one frame;
   · Pure headless route (no addon): blender_rt_worker(op="start") + op="see" returns one frame
     (doctor's bpy round trip being unreachable is expected, not a bad install);
   Both routes require: blender_rt_plan(op="catalog") lists 34 family / 228 op.
   Do not say "install succeeded" before reaching the matching criteria; on failure work through the table in §8 item by item.
5. Paste the raw receipt of every step for me, do not give conclusions only.
6. After installing and passing acceptance, you must proactively tell me the capabilities of the current version (per §③.5, in your own words, do not omit):
   interactive headless (rt_worker see/watch/reset/preload/warmup, rt_do/rt_see accept session/auto,
   plan session="auto" synchronous headless routing, worker idle TTL), reference-image measurement tools img_digest/probe/measure/calib,
   assembly asm_scan/manifest/merge/repair/export/gate, blockout blockout base/batch/export/turntable/refsheet,
   same camera position QC visualreport_report, headless silhouette fitting shapesolve_solve, defect evaluation eval_run,
   mandatory gate gate_preflight/checkpoint/deliver + deliver_export(require_gate).
   And state explicitly that "landmark/faces (no cv2/MediaPipe), OCR, DXF, Open3D/manifold3d/glTF-Validator are not installed and are outside the supported scope".
~~~

## ② DSH users (the repository is already in the local workspace)

~~~text
Read §2 / §3 / §8 of dsh-blender-plugin/docs/zh/README.md and AGENTS.md,
and follow the five steps in §3 to install this plugin into my DSH profile (build (mandatory) → configure → install into the profile → start Blender → verify).
When done run blender_viewport(op="doctor"); only kind=ok counts as success; if it is not kind=ok, troubleshoot per §8 and paste the raw receipt for me.
(On the pure headless route without the addon, doctor's bpy round trip being unreachable is expected: switch to blender_rt_worker(op="start") + op="see" rendering an image as self-proof.)
After acceptance passes, proactively tell me the new capabilities of the current version (v3.0.6):
· interactive headless: rt_worker persistent worker (see/watch/reset/preload/warmup, idle TTL defaults to 15 min),
  rt_do/rt_see automatically go through session/auto when the GUI is unreachable, plan session="auto" synchronous headless routing;
· surface algorithms (new in v2.6.2): surface_loft/sweep/patch → tessellate → validate → export (M0–M2/M4; M3 fit and M5 blend/offset are not implemented);
· reference-image measurement tools / assembly / blockout and turntable/refsheet / visualreport / shapesolve / eval_run / mandatory gate (see the catalog for details);
· Blender native selection → N panel "Send selection to DSH" is still available (since v2.3; the addon needs v1.11+);
· from addon v1.11 the N panel has "Pause AI operations" (only a human can resume it by clicking in Blender);
· not covered: landmark/faces, OCR, DXF, Open3D/manifold3d/glTF-Validator (not installed).
And explain that after upgrading the plugin DSH must be restarted, and the Blender-side addon must be v1.11+ (the old MCP for Blender is no longer supported since v2.3).
~~~

## ③ After installing, have the AI self-check (both GUI / headless sets)

~~~text
blender_viewport(op="doctor")             # kind=ok? (actually runs one bpy round trip)
blender_rt_plan(op="catalog")             # can 34 family / 228 op be listed?
skill(name="blender-modeling")            # can the bundled skill load? (auto-registered since v2.2.0, no separate install)
blender_rt_cmd(name="get_addon_info")     # addon_version=[1,11] + protocol 11?
blender_rt_cmd(name="get_activity_state") # are the selection/activity commands there?
blender_rt_cmd(name="get_collections")    # is the collections-mode data source there?

# When the GUI is unavailable (interactive headless; no Blender window needs to be open)
blender_rt_worker(op="start")             # persistent blender -b (cold start ~2s)
blender_rt_worker(op="see", from="4,-4,3", look_at="0,0,1")  # image in ~50–100ms
blender_rt_do(code="print(K.out_dir)", session="auto")       # synchronous exec, does not occupy the GUI
~~~

## ③.5 After installing you must inform the owner (the "courtesy notice" requirement of v3.0.6)

> This section is a hard requirement for **the AI that installs the plugin**: after acceptance passes, tell the user the following points in your own words (Chinese preferred), do not omit them.
> Users who install a plugin usually only care about "what can it do" and will not go through the CHANGELOG —— so you pass it on.

1. **Version facts**: plugin v3.0.6, 15 model tools, plan catalog 34 family / 228 op, addon v1.11 (protocol 11);
   after installing/upgrading you must **restart DSH** (the plugin is a module loaded at startup).
2. **Interactive headless (the v2.6 focus)**: `blender_rt_worker` is a resident `blender -b` hot session (`start/exec/see/watch/reset/stop`,
   supports `preload`/`warmup`, idle TTL defaults to 15 min, the receipt carries `idleMs`); `blender_rt_do`/`blender_rt_see` go headless automatically when the GUI is unreachable
   or when `session` is given explicitly; `blender_rt_plan(..., session="auto")` starts a worker per family automatically and returns synchronously.
   **The GUI is no longer a prerequisite**, but when the GUI is available it is still the handiest way to look at images.
3. **Surface algorithms (new in v2.6.2)**: `surface_loft / surface_sweep / surface_patch → surface_tessellate →`
   `surface_validate → surface_export`; pure bpy+numpy, units in mm, reproducible for the same spec; three-state verdict (`fail` does not silently become pass,
   `degraded` does not mean pass). **M3 fit and M5 blend/offset are not implemented** (explicit `ok:false`, needs OCCT).
4. **New capability surface (P0–P2)**: reference-image measurement tools `img_digest/probe/measure/calib`; assembly `asm_scan/manifest/merge/repair/export/gate`;
   blockout `blockout_base/batch/export/turntable/refsheet`; same camera position QC `visualreport_report` (verdict-first);
   headless silhouette fitting `shapesolve_solve`; defect evaluation `eval_run`; mandatory gate `gate_preflight/checkpoint/deliver` +
   `deliver_export(require_gate=true)`; `blender_rt_watch` also supports headless.
5. **The selection entry point is still on the Blender side** (since v2.3): native selection → `N` → "DSH Blender Bridge" → **Selection → DSH**;
   multi-select / collection modes; edit-mode vertices/edges/faces, pose bones, and curve/lattice points are also sent along with the selection;
   the four activity states are queryable (`get_activity_state`); this entry point **supports only this repository's addon v1.11+**.
6. **Pause AI operations** (addon v1.11): a button at the top of the N panel; once paused, write operations are rejected and read-only operations still work; only a human can resume it by clicking in Blender.
7. **Not covered / missing dependencies (tell the user honestly)**: landmark/faces (no cv2/MediaPipe), OCR, DXF,
   Open3D / manifold3d / glTF-Validator are all not installed, and the related capabilities are outside this plugin's supported scope; the catalog's "not covered" statement also spells out
   that organic/biological modelling, film-grade lighting/volumetrics/compositing, and character animation rigging are not covered.
8. **Addon compatibility (important)**: since v3.0 only this repository's [`addon/dsh_blender_bridge.zip`](../addon/dsh_blender_bridge.zip) is supported (package form, v1.11+ / protocol 11).
   If the old single-file `dsh_blender_bridge.py` or the old `MCP for Blender` / `blender_mcp` is installed, disable it first (the old single file can be removed; bridge-type addons only need to be disabled, not uninstalled), then install the zip; otherwise "Selection → DSH" and the model tools may both fail to connect.
   Other ordinary addons are unaffected; do not uninstall or disable the user's other addons (only bridge-type addons need to be disabled).
   —— Tell the user this honestly, and give the migration steps ([MIGRATIONS.md](../MIGRATIONS.md)).

## ④ What counts as failure (do not declare success while holding these receipts)

| Receipt | Meaning | Handling |
|---|---|---|
| `blender-unreachable` | Blender is not running, or the addon is not Connected | `blender_viewport(op="launch")`; or manually press `N` → Connect in Blender; on pure headless switch to `blender_rt_worker` |
| `addon-unresponsive` (`addon.kind` of `/doctor`) | Port `9876` is reachable, but the addon did not return the bpy round trip of `execute_code` within budget (3s) (timeout) | Confirm Blender is running and "DSH Blender Bridge" is Connected; wait for the long command/render to finish, restart Blender if necessary; `op=start` only manages the 9877 backend and does not fix this channel |
| `addon-error` (`addon.kind` of `/doctor`) | The addon returned an explicit error (not a timeout, e.g. "AI operations are paused" / a script error / `BUSY_RENDER`) | Fix according to the error; if a render is running, wait for it to finish or use `render_wait`; this is not a busy main thread, so do not retry repeatedly |
| `main-thread-busy` | The main thread is held by a render / modal operation | Wait until it frees up, or switch to headless (`blender_rt_headless` / `blender_rt_worker`) |
| Backend unavailable | The backend process is not up | `blender_viewport(op="start")` |
| Tool count / op count does not match the docs (e.g. still the old catalog) | The plugin/lib and the host version disagree, or it was not restarted after upgrading | Reinstall v3.0.6 → **restart DSH** → re-check 34/228 with `blender_rt_plan(op="catalog")` |
| `value is not lossless JSON` | The receipt contract between host and plugin does not match (old version or not reloaded) | Upgrade to v3.0.6, **restart DSH**, then run the acceptance once more |
| Write operation 409 `leased` | Another session holds the write lease | `blender_viewport(op="who")`, do not force-take it |

## ⑤ For repository maintainers: four levers that make an AI "read the README first"

1. **`AGENTS.md` (repository root)** —— assistants such as DSH / Claude Code / Cursor / Codex **auto-load** it when working in the repository, which is the hardest line of the four.
2. **A paragraph in the README above the fold** —— people using an AI usually paste the repository URL straight into the assistant, and the first thing the assistant does is read the README's first screen.
3. **Failure receipts point at the docs** —— so that "someone who did not read the README" is told explicitly which section to read at the place where they are most likely to get stuck (the channel will not connect).
4. **The prompt template (this page)** —— pasted by the user, any assistant accepts it, and it does not depend on whether the assistant supports convention files.
