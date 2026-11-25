# MIGRATIONS — migrating from older versions to v3.0

> **Current release (2026-11-01)**: plugin **v3.0.0** · **15 model tools** · plan catalog **34 family / 228 op** ·
> addon command **38** · addon **v1.11** (protocol **11**) · backend `127.0.0.1:9877` / addon `127.0.0.1:9876`.
> **The old `MCP for Blender` has not been supported since v2.3**; v3.0 is an engineering refactor plus a breaking change to how the addon is installed, so migrate following §0/§1 below.

## 0. Shortest path (any older version → v3.0.0)

1. Update the DSH plugin package to **v3.0.0**: `dsh plugin --profile <profile> add dsh-blender-plugin@3.0.0` → **restart DSH**; the old "Blender viewport" tab / click-to-message were removed in v2.3, and that is expected.
2. In Blender, disable and remove the old addon (including the old single-file `dsh_blender_bridge.py`) → install this repository's `addon/dsh_blender_bridge.zip` (**v1.11**) → enable → N → Connect.
3. `blender_rt_cmd get_addon_info` → `addon_version=[1,11]`, `protocol=11`;
   GUI route `curl http://127.0.0.1:9877/doctor` → `kind=ok` (for the pure headless route, use `rt_worker(start)` + `see` to prove it yourself with a returned frame);
   `blender_rt_plan(op="catalog")` → **34 family / 228 op**.
4. Selection entry point: Blender native selection → `N` → "Selection → DSH" → send (multi-select / collections); points or faces selected in edit mode and bones selected in pose mode are sent as well.
5. For the new capabilities (interactive headless, `img_*`, `asm_*`, `blockout`, `visualreport`, `shapesolve`, `eval_run`, delivery gates and so on) look up the skeleton with
   `blender_rt_plan(op="catalog")`; apart from the Premium/Tripo channels explicitly removed in v3.0, old ops are not deleted, only added and never changed.

## 0.1 Capabilities explicitly removed in v3.0.0 (breaking)

- **Premium channel**: the Premium licence / quota / Supabase client / default quality and the activation UI are all removed; there is no premium generation entry point any more.
- **Tripo channel**: Tripo has no BYOK path, so get_tripo_status, create_tripo_job, poll_tripo_job_status, import_generated_asset_tripo and the N-panel switch are removed together with it; addon commands 39 → 38.
- **Flat Python module paths removed**: the 38 re-export shims in runtime/*.py are deleted, and generator.py / uv_tools.py moved to runtime/py/geometry/; the public module names of preload / module are unchanged, but the old-style `import runtime.<name>`, or loading directly as `runtime/<name>.py`, no longer works — use `runtime.py.<domain>.<name>` or locate the module through `runtime/py/modules.json`.
- **Replacement path**: Hyper3D and Hunyuan3D keep supporting their own API keys; when you need Tripo, generate the asset in an external service and then import it into Blender.
- Apart from the declared removals above, existing ops / parameters / return structures stay compatible; do not rewrite existing calls because of this release's refactor.

## 1. Blender-side addon: you must switch to `DSH Blender Bridge` v1.11 (zip package)

v2.3's native selection / collections / activity depend on the 5 commands and the N-panel entry point of this repository's addon, which the old addon does not have.
Both addons listen on `127.0.0.1:9876` by default and **cannot be enabled at the same time**.

1. `Edit ▸ Preferences ▸ Add-ons` → disable the old entries (`MCP for Blender` / `blender_mcp` / `blender_mcp_addon`).
2. `Install...` → select this repository's [`addon/dsh_blender_bridge.zip`](addon/dsh_blender_bridge.zip) → tick to enable **DSH Blender Bridge** (v1.11 / protocol 11). Single-file installation is no longer supported as of v3.0.
3. In the 3D view press `N` → "DSH Blender Bridge" → **Connect** (port 9876); or just run `blender_viewport(op="launch")`.
4. `blender_rt_cmd get_addon_info` → `addon_version` should be `[1,11]` and `protocol=11`, and capabilities include
   `get_activity_state` / `get_selection` / `get_collections` / `send_*_to_dsh`.

> The "enabled" record under the old name `blender_mcp` is a dead reference and can be removed; the plugin **no longer falls back to the double name**.

## 2. DSH side: DSH must be restarted after upgrading the plugin

- The client half (`@` mentions + native selection bridge) is loaded at startup; without a restart it keeps running the old bundle (which still contains the deleted panel).
- The old "Blender viewport" tab, click-to-message and `blender_rt_pick` all disappear in v2.3; this is **expected behaviour**.
- The selection entry point becomes: Blender native selection → `N` → "Selection → DSH" → send (multi-select / collections modes).
- After a v2.6 upgrade **restarting DSH** is likewise required; when only the backend changed you can use `blender_viewport(op="restart")`.

## 3. Configuration file cleanup (optional)

- The `addonProtocol` configuration item and the `DSH_BLENDER_ADDON_PROTOCOL` environment variable are **deleted** (only this repository's flat protocol remains).
  Leaving them in an old configuration does not affect startup, but removing them is recommended so you do not think the protocol can still be switched.
- The other `DSH_BLENDER_*` configuration items are unchanged, see [`docs/configuration-reference.md`](docs/configuration-reference.md).

## 4. How to use the repository (as of v3.0.0 / T15)

- **npm package name**: as of v3.0.0 it is `dsh-blender-plugin`, not `@dsh-external/dsh-blender-plugin`. Install/upgrade command:
  `dsh plugin --profile <profile> add dsh-blender-plugin@3.0.0`. The published package ships its own `lib/` build output, so it works as soon as it is installed.
- **Using it from Git** requires building once first: `lib/` is no longer committed, so after `git clone` run `npm ci --legacy-peer-deps` and then
  `npm run build` (`DSH_CHECKOUT` is optional and only needed when linking DSH host packages). `prepack` builds automatically,
  so `npm pack`/publishing needs no extra step.
- The backend TypeScript sources live in `runtime/` and the compiled output in `lib/runtime/`; never hand-edit `lib/`.

## 5. Historical interface contracts

`docs/host-integration-contract.md`, `host-integration-contract-v2.1-addendum.md`, `v2.2-addendum.md` and the TUI adaptation document have been deleted;
the only current source of truth is [`docs/host-integration-contract-v2.3-addendum.md`](docs/host-integration-contract-v2.3-addendum.md) — that file opens with a **v2.6 compatibility statement**
(the v2.3 contract still applies; addon v1.10 / protocol 11; the new P0–P2 ops are listed in the catalog).

## 6. addon v1.10 / v1.11 / v2.6 additions (no migration action needed)

- **addon v1.11**: split into a package and switched to zip installation; command names, parameters, return structures and the pause semantics are unchanged (protocol 11).
- **addon v1.10**: activity state pinned to the top of the N panel, environment and character model API sub-panels, **pause AI operations** (after pausing only read-only commands pass,
  and only a human clicking in Blender can resume). Just upgrade the addon, there is no configuration migration.
- **v2.6**: receipts **only gain fields** (`recovered / progress / heartbeat / warnings / scope` etc., old field semantics unchanged);
  `audit_mesh` gains a fifth state `pass_multi_shell`; the catalog gains "non-coverage statements"; the write scope supports two dimensions, collection and object prefix.
  **Restart DSH** after upgrading the plugin; old call parameters stay compatible.
- New capabilities (P0–P2): interactive headless (`rt_worker` see/watch/reset/preload/warmup, `rt_do/rt_see` can take `session/auto`,
  `plan session="auto"`, worker idle TTL), `img_digest/probe/measure/calib`, `asm_scan/manifest/merge/repair/export/gate`,
  `blockout_base/batch/export/turntable/refsheet`, `visualreport_report`, `shapesolve_solve`, `eval_run`,
  `gate_preflight/checkpoint/deliver` + `deliver_export(require_gate)` — all **new ops**, look them up in the catalog; they do not replace older usage.

> **Not covered / dependencies not installed** (do not promise them after migrating either): landmark/face (no cv2/MediaPipe), OCR, DXF,
> Open3D / manifold3d / glTF-Validator are not installed and are out of scope.

## 7. Uninstall and rollback (v3.0.0)

### 7.1 Uninstalling v3.0.0

1. Blender: `Edit ▸ Preferences ▸ Add-ons` → disable **DSH Blender Bridge** → remove; if a package directory is left behind, delete `scripts/addons/dsh_blender_bridge/` (or the same-named directory under your Blender user addons path).
2. DSH: uninstall the plugin package from the profile's `node_modules/dsh-blender-plugin` (or remove it from the profile bundle list) → **restart DSH**; the blender-modeling skill registered with the package is removed together with the plugin, so there is no need to hand-delete the user skill directory.
3. The old single-file `dsh_blender_bridge.py` (v2.6.1 and earlier) had to be disabled and removed at upgrade time; v3.0.0 will not load it again.

### 7.2 Rolling back to v2.6.2

1. Install the v2.6.2 plugin package (tag `refactor-base-v2.6.2` / the corresponding tarball); do not overwrite it with the v3.0.0 directory;
2. In Blender, disable the v1.11 zip addon and reinstall the single-file `dsh_blender_bridge.py` shipped with v2.6.2 (or v2.6.2's addon artifact), then enable it and use N → Connect;
3. **Restart DSH**; `blender_rt_cmd get_addon_info` should be back at v1.10 / protocol 11, and `blender_rt_plan(op="catalog")` should be back at 34 family / 228 op.
4. The v2.6.2 tag ships its own `lib/` and the old `runtime/*.mjs`, so no build is needed; do not mix v3.0.0's `lib/runtime` with `.ts` files.
5. The rollback drill record is kept in the local refactor workspace and is not published with the repository.

