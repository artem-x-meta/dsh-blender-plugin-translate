# DSH × Blender direct live plugin

[English](../../README.md)

DSH × Blender connects DeepSeek Harness to Blender, so an AI can model, inspect, accept and export inside a real Blender session. The default path is the GUI: open Blender, connect the addon, and the AI works against the scene you are looking at with "take a look → change one step → confirm again". Without a GUI, a persistent headless session provides the same interactive loop and can also produce images.

## Table of contents

- [Features](#features)
- [Quick start](#quick-start)
- [Tools](#tools)
- [Documentation](#documentation)
- [FAQ](#faq)
- [Development](#development)
- [Support](#support)
- [License](#license)

## Features

- **GUI-first interactive modeling.** The AI operates the Blender session in front of you directly: inspect the scene, run Python in the persistent kernel, capture the viewport or a custom angle, change and confirm step by step.
- **Headless fallback, but still with visual feedback.** Without a GUI a persistent worker is started, and the AI can still execute code and get Workbench frames. It is the fallback path, not the default path; the point is that the AI is not blind when there is no window.
- **Reference image measurement.** Before modeling, measure contours, holes, symmetry, readable features and proportions; without calibration it returns pixel units and does not guess millimeters.
- **Parametric surfaces.** Generate reproducible surface meshes with cross-section loft / sweep along a path / four-sided patch, run continuity, curvature, self-intersection and thickness checks, then export GLB; the same spec yields the same `spec_hash` and the same set of vertices, without hand-sculpting.
- **Assembly audit and repair.** Validate the assembly manifest, classify interpenetration, allowed hidden overlap, contact, gap, floater and full containment, do safe repairs, and after passing the gate export GLB / FBX / OBJ with a manifest and a merge ledger.
- **Blockout and video reference pack.** Build a low-poly model from declarative parts, render orthographic/perspective reference views, and output a turntable MP4 for video models such as Seedance.
- **Visual acceptance and delivery gate.** Compare renders against reference images at the same camera position, output a defect report with crops and measurements, and run defect injection evaluation; if the gate is not pass, delivery is blocked.
- **Automation and long jobs.** One-shot headless scripts, background long jobs, parameter search and batch validation do not occupy the GUI.
- **Native selection.** Select objects or collections in Blender and send them into the current DSH draft with one click.
- **Available in dsh-TUI too.** In dsh-TUI, a Blender selection is attached to the next message as a context chip; the footer shows the Blender channel status (connected / AI paused / rendering / jobs); `@` mentions objects, materials and collections in the scene; `/blender status|doctor|jobs` queries status directly without going through the model. All of this requires dsh-TUI to provide the corresponding seams, and is not enabled automatically when they are absent.

## Quick start

**Do this step first: install the bundled addon.** Use the **addon/dsh_blender_bridge.zip** provided by this repository; it must be your only Blender-side agent bridge: do not install or enable `MCP for Blender`, `blender_mcp`, or any similar addon that brings its own socket service (it will fight with this repository's addon over 127.0.0.1:9876). Unrelated ordinary addons (modeling, materials, rendering, asset libraries) are unaffected. Install and enable it in Blender first, then do the later steps. If it still does not work after installing as described below, come back and check whether this is the addon being used, whether it is enabled, and whether **Connect** has been pressed.

### Prerequisites

- An installed and working DSH (DeepSeek Harness).
- Installing from npm does not require a separate Node.js installation; only building from source requires Node.js **24.9** or higher. Node.js **24.9** is the minimum supported version; CI uses Node 24.
- Blender **4.2 LTS** is the verified version; 4.x may work, 5.x is not yet verified. GUI mode requires the bundled addon installed first; headless mode only needs the Blender executable to be findable.
- addon compatibility: the bundled addon is the only agent bridge needed and the only one supported. Other addons do not conflict with it; the old `MCP for Blender` / `blender_mcp` do conflict (both take 127.0.0.1:9876), so just disable them, there is no need to uninstall.
- Optional: if you want to rebuild the plugin you need a DSH source checkout.

### Option A: install from npm

This is the supported installation method and does not need `git clone`, `npm ci` or `npm run build`.

1. **Install the bundled addon first.** Download `dsh_blender_bridge.zip` from the [latest GitHub Release](https://github.com/sixtysevenlf/dsh-blender-plugin/releases/latest); in Blender open `Edit > Preferences > Add-ons > Install`, choose the zip, enable **DSH Blender Bridge**, press `N` in the 3D view to open the panel, and click **Connect**.

2. **Install the DSH plugin from npm.** Choose according to the DSH host you use:

   - **DSH Web / DSH TUI:** use the profile you actually run:

         dsh plugin --profile <profile> add dsh-blender-plugin@3.0.6

     After installing, restart DSH as described in step 3.

   - **DSH Desktop:** open the Plugins page and install the bundle `dsh-blender-plugin@3.0.6`. After installing through the Plugins page, DSH Desktop does not need a DSH restart.

3. **Restart DSH (DSH Web / DSH TUI only).** Users who installed from the DSH Desktop Plugins page skip this step.

4. **Verify the installation.** The only acceptance criterion for the GUI route is that `doctor` returns `kind` equal to `ok`:

        curl -sS http://127.0.0.1:9877/doctor

   GUI route: `curl -sS http://127.0.0.1:9877/health` and `/doctor`; `doctor.kind` must be `ok`.

   Pure headless route (without the addon): `blender_rt_worker(op="start")` followed by `op="see"`, which must return one frame.

The addon remains the only supported Blender-side agent bridge. Other bridging addons occupying port 9876 must be disabled; ordinary modeling, material, rendering and asset addons are unaffected.

### Option B: let the AI install it for you

Give the following prompt to an AI that can execute commands:

    First install and enable the addon provided by the latest GitHub Release: dsh_blender_bridge.zip.
    If a bridging addon is already installed (MCP for Blender / blender_mcp, or any addon
    serving on port 9876), disable it first; do not uninstall the user's other addons, and do not ask the user to do so.
    Then install the DSH × Blender plugin from npm into my DSH profile:
    dsh plugin --profile <profile> add dsh-blender-plugin@3.0.6
    Read docs/ai-install-prompt.md first and follow it strictly;
    in the end you must verify: the GUI route returns kind=ok from doctor,
    and the pure headless route returns one frame with worker start + see.
    Do not skip the verification, and do not claim the installation succeeded without verifying it.

Pull the full installation prompt locally:

    curl -fsSL https://raw.githubusercontent.com/sixtysevenlf/dsh-blender-plugin/main/docs/ai-install-prompt.md -o ai-install-prompt.md

Install the standalone modeling skill (only for hosts that do not load this plugin; DSH registers it automatically along with the plugin, so this step is not needed):

    curl -fsSL https://raw.githubusercontent.com/sixtysevenlf/dsh-blender-plugin/main/skills/blender-modeling/install.sh | bash

### Option C: build from source (developers)

1. **Install the bundled addon first.**

   Download **addon/dsh_blender_bridge.zip** from the addon/ directory of this repository. Open Blender, go to Edit > Preferences > Add-ons > Install, choose that zip, and enable DSH Blender Bridge; press N in the 3D view to open the panel and click Connect. The addon listens on 127.0.0.1:9876. If you previously installed the single-file `dsh_blender_bridge.py`, disable and remove it first: v3.0 installs only the package-form zip.

   Only this addon may be used as the agent bridge. If `MCP for Blender` / `blender_mcp` is enabled (or another addon with its own 9876 service), just disable it, there is no need to uninstall; other addons can stay. If the later installation does not work, come back and check this step.

2. **Developer path:** clone the repository and build. lib/ is a build artifact and is no longer committed, so a fresh clone must be built once first. `npm run setup:dev` installs the npm and Python development dependencies (and creates `.venv`); unless you are developing this plugin, use the npm installation above.

        git clone https://github.com/sixtysevenlf/dsh-blender-plugin.git
        cd dsh-blender-plugin
        npm run setup:dev
        npm run build

3. Add the plugin to the DSH profile. First symlink the checkout into the profile, then add the dependency and bundle entry to the profile's package.json.

        ln -s /absolute/path/to/dsh-blender-plugin <profile>/node_modules/dsh-blender-plugin

    The profile's package.json:

        {
          "dependencies": {
            "dsh-blender-plugin": "link:/absolute/path/to/dsh-blender-plugin"
          },
          "dsh": {
            "profile": {
              "bundles": ["dsh-blender-plugin"]
            }
          }
        }

    Validate the profile, then restart DSH:

        dsh --profile <profile> --dump-config

4. Acceptance.

    GUI route:

        curl -sS http://127.0.0.1:9877/health
        curl -sS http://127.0.0.1:9877/doctor

    The only acceptance criterion for the GUI route: doctor returns kind=ok. If it is not there, it is not installed properly.

    Alternatively, after DSH restarts you can call the launch operation of blender_viewport: it brings Blender up automatically, enables the addon and connects it.

    Pure headless route (without the addon):

        blender_rt_worker(op="start", name="smoke")
        blender_rt_worker(op="see", name="smoke")

    Returning one frame means the headless fallback path works. At that point, doctor's bpy round-trip being unreachable is expected.

## Tools

The plugin provides 15 model tools. Operations such as plan, audit, assembly, export and evaluation are all collected inside blender_rt_plan, so the tool list does not balloon.

### Interaction and control

| Tool | What it gives you |
|---|---|
| blender_rt_see | One frame of the current GUI viewport, or one frame from a specified camera angle. |
| blender_rt_do | Execute Python in Blender, with the kernel retained across calls; it can return a frame along the way. |
| blender_rt_watch | Sample a time window or frame range to tell whether the picture changed. |
| blender_rt_worker | Persistent headless interactive session used when there is no GUI. |

### Planning and operations

| Tool | What it gives you |
|---|---|
| blender_rt_plan | Capability catalog + execution entry point, covering modeling, audit, assembly, delivery and evaluation operations. Check it first when you do not know what to use. |
| blender_viewport | Channel health, doctor, launching Blender, writing leases, used to coordinate several sessions. |

### Automation and long jobs

| Tool | What it gives you |
|---|---|
| blender_rt_headless | Standalone Blender background process, for batch work, validation or rendering. |
| blender_rt_job | Background long jobs, collecting results by job id; a timeout does not lose the result. |
| blender_rt_loop | Run a parameter search inside Blender and return the best candidate. |

### Scene tools

| Tool | What it gives you |
|---|---|
| blender_rt_txn | File-level snapshots and object-level marks, for rollback. |
| blender_rt_preset | Save, list, apply and export reusable parameter presets. |
| blender_rt_perf | Diagnose and apply rendering performance settings. |
| blender_rt_opt | Find safely mergeable objects to lower scene cost. |

### addon access

| Tool | What it gives you |
|---|---|
| blender_rt_cmd | Call any addon command directly. |
| blender_rt_commands | Inspect the available addon commands and integration status. |

## Documentation

- Surface algorithms: [skills/blender-modeling/references/surface-algorithms.md](../../skills/blender-modeling/references/surface-algorithms.md)
- Operations tutorial: [docs/operation-tutorial.md](../operation-tutorial.md)
- Configuration reference: [docs/configuration-reference.md](../configuration-reference.md)
- AI installation prompt: [docs/ai-install-prompt.md](../ai-install-prompt.md)
- Deployment SOP: [docs/deployment-sop.md](../deployment-sop.md)
- Third-party installation checklist: [docs/third-party-install-checklist.md](../third-party-install-checklist.md)
- DSH upgrade adaptation: [docs/dsh-update-adaptation.md](../dsh-update-adaptation.md)
- Architecture notes: [docs/architecture.md](../architecture.md)
- Modeling skill: [skills/blender-modeling/](../../skills/blender-modeling/)
- Release notes: [GitHub Releases](https://github.com/sixtysevenlf/dsh-blender-plugin/releases) and [CHANGELOG.md](../../CHANGELOG.md)

## FAQ

| Symptom | Handling |
|---|---|
| doctor does not return kind=ok | Check whether Blender is running and whether the addon is connected. The GUI route accepts only this. |
| No GUI | Use the persistent worker fallback path: start the worker, then execute code and request one frame. |
| Another session is writing to the same scene | Take a write lease with blender_viewport; for parallel modeling use a separate headless worker. |
| The old MCP for Blender / blender_mcp is still enabled | Disable it (no need to uninstall) and switch to the bundled DSH Blender Bridge addon; the two fight over 127.0.0.1:9876. |
| The image was generated but not attached | Upgrade to the latest build (it includes the Windows path fix); if it still fails, open the returned path directly. |
| It still does not work after installing by the steps below | Check the addon first: only addon/dsh_blender_bridge.zip is supported, and it must be enabled and must be connected. |

## Development

- Node.js **24.9** is the minimum supported version; CI uses Node 24.
- Development setup: after cloning, run `npm run setup:dev`; it probes Python 3.11+, creates or reuses `.venv`, and installs
  `requirements-dev.txt`, `requirements-typecheck.txt` and the npm dependencies (running
  `npm ci --legacy-peer-deps` only when `node_modules` is missing). `npm run setup:dev -- --check` only verifies without writing;
  `npm run setup:dev -- --force` rebuilds `.venv`. Neither `.venv` nor `node_modules` is committed.
- Python tests need a virtual environment (virtualenv, created by `npm run setup:dev`) with `pytest` installed. Tests probe
  `.venv` automatically; to use another interpreter, point `PYTHON` elsewhere (on Windows also set `PYTHONIOENCODING=utf-8`
  and `PYTHONUTF8=1`); tests import the TypeScript sources directly.
- The single source of truth for commands (build, typecheck, test, lint, packaging) is
  [`AGENTS.md` §1](../../AGENTS.md#1-commands-single-source); `lib/` is rebuilt from `src/`, do not edit it by hand.
- Test layering, fixtures and per-layer commands: [`tests/README.md`](../../tests/README.md).
- Contribution process: [English CONTRIBUTING](../../CONTRIBUTING.md) · [Chinese CONTRIBUTING](./CONTRIBUTING.md).
- Source of truth for the bundled skill: `skills/blender-modeling/`.

## Support

If this project helps you, you are welcome to support development on Afdian: <https://afdian.com/a/sixtysevenlf>

## License

The plugin itself is BSD-3-Clause. The bundled modeling skill is MIT; see skills/blender-modeling/LICENSE and NOTICE.md. Blender is a trademark of the Blender Foundation.
