# Deployment and self-check SOP (standard operating procedure for an AI to execute)

> Format borrowed from lurenjia-l/dsh-blender-stylized-shading's AI_DEPLOY.md: **goal and completion criteria → environment probe → install → connect → self-check → report → troubleshooting**.
> Principle: **probe first, do not guess**; every step needs a verifiable criterion; a failure gives a clear next step instead of a vague error.

> **Current version facts (2026-11-05)**: plugin **v3.0.6** · **15 model tools** · plan catalog **34 family / 228 op** ·
> addon **v1.11** (protocol **11**) · backend `127.0.0.1:9877` / addon `127.0.0.1:9876`.
> Acceptance criterion: **GUI route = `doctor` returns `kind=ok`**; **pure headless route** (addon not installed) = `rt_worker(start)` + `see` produces an image as self-proof
> (doctor's bpy round trip being unreachable is expected). **The default is to open the GUI first**; without a GUI, interactive headless (persistent worker + see/watch/reset) can also model independently, but it is the fallback path.

## 0. Goal and completion criteria

Goal: get the DSH-side **15 model tools** working on this machine; use the GUI when there is one, and when there is no GUI use **interactive headless** (`blender_rt_worker`), which can equally model and view images.
The plan catalog should list **34 family / 228 op**.

Completion criteria (only when **the common items plus the route you chose** are all satisfied is the install considered done):
- **Common**: `blender_rt_plan(op="catalog")` lists **34 family / 228 op**;
- **Common**: `blender_rt_commands` lists addon **38 commands** (22 resident + 16 integration-gated);
- **Common**: `blender_rt_perf(op="status")` returns the `engine` field (default `BLENDER_EEVEE`; QC/blockout rendering uses Workbench);
- **Common**: `blender_rt_plan(op="qc_self_check")` returns `iou_self = 1.0`; the PNG produced by any render-type call **is not a black image** (you can look at the `qc_compare` comparison image);
- **GUI route**: `blender_viewport(op="doctor")` returns `kind=ok` (TCP + ping + bpy round trip, all three levels pass);
- **Pure headless route** (addon not installed): `blender_rt_worker(op="start")` → `op="see"` returning one frame is taken as the channel being usable
  (doctor's bpy round trip being unreachable is expected, not a broken install).

## 1. Environment probe (do this first, do not guess)

| Probe item | Command | Expected |
|---|---|---|
| Blender process | `blender.exe` present in Task Manager / `tasklist` | A GUI is most convenient; **not required** (the headless worker runs independently) |
| addon socket | `blender_viewport(op="status")` | `9876` reachable (addon v1.11 / protocol 11) |
| plugin backend | `blender_viewport(op="doctor")` | `kind=ok`; on `blender-unreachable` start Blender first or switch to headless |
| write-channel lease | `blender_viewport(op="who")` | if another session holds it, writes get 409 (read-only ops are exempt, `force=true` can take over) |
| engine | `blender_rt_perf(op="status")` | default `engine=BLENDER_EEVEE`; QC/blockout uses Workbench |

## 2. Install the plugin

Regular users install from npm (no clone or build needed):

~~~bash
dsh plugin --profile <profile> add dsh-blender-plugin@3.0.6
dsh --profile <profile> --dump-config | grep -A3 dsh-blender-plugin
# then restart DSH
~~~

Only when modifying plugin source do you need clone + `npm ci --legacy-peer-deps` + `npm run build`, and then install the checkout into the profile via `link:`.

## 3. Connect the Blender addon (one manual step)

1. In Blender install and enable this repository's **DSH Blender Bridge** addon (`addon/dsh_blender_bridge.zip`, **v1.11+** / protocol 11). The old single-file `dsh_blender_bridge.py` and the old `MCP for Blender` are no longer supported; if they are installed, disable and remove them first (see [../MIGRATIONS.md](../MIGRATIONS.md));
2. In the 3D viewport press `N` → **DSH Blender Bridge** panel → **Connect** (socket defaults to `127.0.0.1:9876`);
3. Back in DSH run `blender_viewport(op="doctor")` to re-check;
4. Or instead run `blender_viewport(op="launch")` to start GUI Blender and Connect automatically in one step (idempotent).

## 4. Self-check (mandatory after deployment)

~~~text
blender_viewport(op="doctor")                     # three-level channel check (kind=ok)
blender_rt_plan(op="catalog")                     # 34 family / 228 op
blender_rt_commands()                             # 38 commands + 5 integration states
blender_rt_perf(op="status")                      # engine/samples/ray-tracing state
blender_rt_plan(op="qc_self_check")               # QC algorithm self-check (self-compare IoU should be 1.0)
blender_rt_see()                                  # return one viewport frame (when a GUI is available)
blender_rt_headless(script="print('HEADLESS {ok:1}')")  # headless process + engine preamble
blender_rt_worker(op="start")                     # interactive headless hot session (fallback; default is GUI first)
blender_rt_worker(op="see", from="4,-4,3", look_at="0,0,1")  # headless image
~~~

## 5. Format for reporting to the user

1. Conclusion (works / does not work, and whether it is the GUI or the headless path); 2. Criteria (doctor's kind, catalog's 34/228, engine, qc_self_check's iou_self);
3. Open items and next steps (if a step fails, give the concrete fix).

## 6. Troubleshooting quick reference

| Symptom | Check first | Common cause |
|---|---|---|
| A tool reports "backend unavailable" | whether `blender.exe` is running / whether backend 9877 is up | Blender not started; or the addon not Connected; or the backend not up (`blender_viewport(op="start")`) |
| `doctor` reports `main-thread-busy` | whether heavy work just ran | Main thread occupied; route heavy work through `blender_rt_headless` / `blender_rt_worker` |
| Tool count is not 15, catalog is not 34/228 | plugin version / whether it was restarted | **Restart DSH** after installing v3.0.6; use `--dump-config` to confirm the profile bundle is loaded |
| `rt_do`/`rt_see` cannot connect but headless works | whether a GUI is available | Fallback when the GUI is unavailable: use `session="auto"` / `rt_worker` for interactive headless |
| Rendered shadows are pure black | `docs/eevee-essentials.md` §2 | `Shader to RGB` contains direct light only; use two Backgrounds + Is Camera Ray or add an environment light |
| Rendering is very slow | whether it is a cold start | EEVEE first-frame shader compilation takes about 16 s → use a `blender_rt_worker` hot session |
| QC scores are not comparable with history | `engine_at_qc` | The engine changed (EEVEE ↔ Cycles); criteria are comparable only within the same engine |

> Related documents: `docs/operation-tutorial.md` (tool-by-tool walkthrough) · `docs/configuration-reference.md` (configuration items + engine index) · `docs/eevee-essentials.md` (engine and material pitfalls) ·
> `docs/ai-install-prompt.md` (an installation prompt you can paste into any AI).
