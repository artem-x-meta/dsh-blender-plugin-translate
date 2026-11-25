# Installation checklist for third parties (just follow it)

> Goal: install `dsh-blender-plugin` on your own machine **from scratch** and complete acceptance. The whole thing takes about 10–15 minutes.
> Acceptance criterion: **GUI route = `curl -sS http://127.0.0.1:9877/doctor` returns `kind=ok`**;
> **pure headless route** (no addon installed) = `blender_rt_worker(op="start")` + `op="see"` returns one frame (doctor's bpy round-trip being unreachable is expected).
> Every step has a **self-check command**: if you get stuck, run the self-check first, then move on.

> **Current version baseline (2026-11-05)**: plugin **v3.0.6** · **15 model tools** · plan catalog **34 families / 228 ops** ·
> Blender-side addon **v1.11** (protocol **11**) · backend `127.0.0.1:9877` / addon `127.0.0.1:9876`.
> **GUI preferred**: with a GUI it is the most convenient; without a GUI, interactive headless (`blender_rt_worker`: start/exec/see/watch/reset) can model and view images just the same.

## 0. Prerequisites (5 items, all required)

| # | What you need | How to confirm |
|---|---|---|
| 1 | **DSH** (this plugin is a DSH plugin, installed in DSH's profile) | `dsh --version` prints something |
| 2 | **Blender 4.2 LTS** (verified; 4.x probably works, 5.x unverified) (the GUI version is most convenient; without a GUI, interactive headless also works) | you can open a Blender window, or you can run `blender -b` |
| 3 | **Blender-side addon** — only this repo's [`dsh_blender_bridge.zip`](https://github.com/sixtysevenlf/dsh-blender-plugin/releases/latest) is supported (**v1.11+ / protocol 11**) | see §2 (the old single-file and the old `MCP for Blender` are both no longer supported) |
| 4 | **Node (only needed for a source build)** | an npm install does not need a separate Node; `node -v` is only checked when building from source |
| 5 | ports **9877** (backend) / **9876** (addon) free | see §5 troubleshooting |

## 1. Get the plugin

Ordinary users install from npm; no clone or build needed:

~~~bash
dsh plugin --profile <profile> add dsh-blender-plugin@3.0.6
~~~

> **Only source development** needs clone + `npm ci --legacy-peer-deps` + `npm run build`.
> The npm package ships the built `lib/`, so it works right after installation.

## 2. Install the Blender-side addon (pick one)

**A. The version shipped in this repo (the only supported one)**

1. Download `dsh_blender_bridge.zip` from the [latest GitHub Release](https://github.com/sixtysevenlf/dsh-blender-plugin/releases/latest), Blender → `Edit ▸ Preferences ▸ Add-ons ▸ Install...` → pick this zip
2. Tick to enable **DSH Blender Bridge** (addon **v1.11** / protocol 11)
3. In the 3D viewport press `N` → the "DSH Blender Bridge" panel → **Connect** (port 9876)

> **Self-check**: `blender_rt_cmd(name="get_addon_info")` → `addon_version=[1,11]`, `protocol=11`, capabilities include
> `get_activity_state / get_selection / get_collections / send_*_to_dsh`.

## 3. Install into DSH

1. Install from npm into the target profile:
   ~~~bash
   dsh plugin --profile <profile> add dsh-blender-plugin@3.0.6
   ~~~
2. Rehearse the config: `dsh --profile <profile> --dump-config` (seeing `dsh-blender-plugin` means success)
3. **Restart DSH** (the plugin is a module loaded at startup)
4. After the restart the **session skill catalog automatically gains `blender-modeling`** (since v2.2.0 it is registered as a bundled skill with the package, no download / symlink needed); have the model load it with `skill` to confirm
5. **(since v2.3, recommended) Blender native selection → DSH**: confirm the addon is **v1.11+** (check `addon_version` with `blender_rt_cmd get_addon_info`),
   select an object in the viewport → `N` › "DSH Blender Bridge" › **Selection → DSH** › "Send selection to DSH" → the object names should appear in the current DSH session draft.
   For troubleshooting from the receipt, look at `last_consume` in `curl -sS http://127.0.0.1:9877/host/selection/latest`.
6. **(since addon v1.11) Pause AI operations**: the button at the top of the N panel; while paused write operations are rejected and read-only still works, and resuming can only be clicked inside Blender.

## 4. Start Blender and verify (**acceptance criterion**)

> **GUI route**: `doctor` → `kind=ok` is the only criterion; **pure headless route** (no addon installed): `rt_worker(start)` + `see` produces an image, that is enough.

~~~bash
# recommended: one-click launch of GUI Blender + automatic addon enable (idempotent)
blender_viewport(op="launch")

# acceptance (all green means it is installed properly):
curl -sS http://127.0.0.1:9877/health      # backend is alive
curl -sS http://127.0.0.1:9877/doctor      # ⭐ GUI route criterion: kind=ok
blender_rt_plan(op="catalog")              # 34 family / 228 op
blender_rt_commands()                      # addon's 38 commands + 5 integration states
~~~

> **You can also do acceptance without a GUI** (interactive headless; does not depend on a Blender window; doctor's bpy round-trip being unreachable is expected here):
> ~~~text
> blender_rt_worker(op="start")            # persistent blender -b (cold start ~2s)
> blender_rt_worker(op="see", from="4,-4,3", look_at="0,0,1")   # image in ~50–100ms
> ~~~
> Since v2.3 the DSH-side **viewport panel has been deleted** (use Blender native selection + N panel sending instead; see §3 step 6).

## 5. If you get stuck, look at this table first

| Receipt / symptom | Meaning | What to do |
|---|---|---|
| `blender-unreachable` | Blender is not running, or the addon is not Connected | `blender_viewport(op="launch")`; or manually press `N` → Connect; for pure headless switch to `blender_rt_worker` |
| `blender-unreachable`, and `/doctor`'s `addon.kind` is not `ok` | the addon is not this repo's v1.11+ (the old `MCP for Blender` / category-action is unsupported since v2.3). **Since v2.3 there is no protocol probing**, so there is no `handshake-stale`-style state "cached into a fallback" | disable the old addon → enable the addon shipped in this repo (v1.11+); if needed `blender_viewport(op="restart")` |
| `main-thread-busy` | the main thread is occupied by a render / modal operation | wait for it to free up, or switch to headless |
| `addon-unresponsive` (`/doctor`'s `addon.kind`) | port `9876` is reachable, but the addon did not return the `execute_code` bpy round-trip within the budget (3s) (timeout) | confirm Blender is running and "DSH Blender Bridge" is Connected; wait for the long command/render to finish, restart Blender if necessary; `op=start` only fixes the 9877 backend process |
| `addon-error` (`/doctor`'s `addon.kind`) | the addon returned an explicit error (not a timeout, e.g. "AI operations are paused" / a script error / `BUSY_RENDER`) | fix it per the error; if rendering, wait for the render to finish or use `render_wait`; it is not a busy main thread, no need to retry repeatedly |
| backend unavailable (9877 unreachable) | the backend process is not up | `blender_viewport(op="start")` |
| write operation 409 `leased` | another session holds the write lease | `blender_viewport(op="who")`, do not force-take it |
| tool count is not 15 / catalog is not 34-228 | the plugin version is old, or it was not restarted after upgrading | install **v3.0.6** → **restart DSH** → re-check |
| `value is not lossless JSON` | the host and the plugin receipt contract do not match (old version / not reloaded) | upgrade to v3.0.6, then **restart DSH** |
| the N panel has no "Selection → DSH" | the addon is not this repo's v1.11+ | disable the old addon → reinstall/enable the addon shipped in this repo (v1.11) → restart DSH |

## 6. Post-install self-check (optional, no Blender needed)

~~~bash
npm test                              # offline self-check all green
npx vitest run tests/integration/js/host-selection.test.ts tests/integration/js/host-jobs.test.ts tests/integration/js/host-scene-items.test.ts   # /host routes + selection contract (v2.3 supplement; the tests start a fake backend themselves, no Blender needed)
~~~

## 7. Out of support scope (please pass this on as it is)

- **landmark / face**: needs cv2 / MediaPipe, **not installed**, no face/landmark capability;
- **OCR, DXF**: not provided;
- **Open3D / manifold3d / glTF-Validator**: dependencies not installed, the related validation/reconstruction capabilities are unavailable;
- the catalog's "non-coverage statement" also states: creature/organic modeling, cinematic-grade lighting/volumetrics/compositing, and character animation rigging are outside this plugin's coverage.
