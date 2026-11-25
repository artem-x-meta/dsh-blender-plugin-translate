# The `dsh_blender_bridge` package — the Blender-side addon (shipped with this repository, the only supported version)

The in-Blender addon that goes with [`dsh-blender-plugin`](../docs/zh/README.md).

> **As of v3.0 the addon is installed as a package + zip; the single-file `dsh_blender_bridge.py` is no longer an installation entry point and has been removed from this repository.**
> If you installed the old single file, disable and remove it in Blender first, then install `dsh_blender_bridge.zip` (see
> [`../MIGRATIONS.md`](../MIGRATIONS.md)). The upstream `MCP for Blender` (module `blender_mcp`) and
> harveyxiacn's `blender_mcp_addon` are likewise no longer supported.

## What this package is

| Item | Value |
|---|---|
| Installation package / module name | `dsh_blender_bridge.zip` (package root `dsh_blender_bridge/`) / `dsh_blender_bridge` |
| Source directory | `addon/dsh_blender_bridge/` (`__init__.py` is the entry point; sub-packages `commands/`, `recorders/`, `assets/`, `integrations/`, `ui/`) |
| Display name (in the Blender add-on list) | **DSH Blender Bridge** |
| Version / protocol | addon **v1.11 / protocol 11** |
| Identifier prefix | `dshbb_` (registered class `bpy.types.dshbb_server`, 5 integration switches `dshbb_use_*`) |
| TCP port | `127.0.0.1:9876` (listens on the local machine only) |
| Command surface | 38 commands (22 resident + 16 integration-gated; command names, parameters, return structures and pause semantics match v1.10) |

## Origin and licence (MIT)

This package is a **derived, renamed version** of [ahujasid/blender-mcp](https://github.com/ahujasid/blender-mcp) (MIT).
The rename touched only the **display name, module name and identifier prefix**; the **copyright and licence text are kept verbatim**:

```
# Code created by Siddharth Ahuja: www.github.com/ahujasid © 2025
    "author": "Siddharth Ahuja",
```

The upstream MIT licence requires keeping the copyright notice above — **do not delete it**.

## Building the zip

The repository already commits `addon/dsh_blender_bridge.zip`; rebuild it after changing the sources:

```bash
node scripts/build-addon.mjs          # writes addon/dsh_blender_bridge.zip
node scripts/build-addon.mjs --check  # only validates the manifest and version of the existing zip
```

The zip contains a single package root `dsh_blender_bridge/`, no `__pycache__` / `.pyc`, and uses fixed timestamps so the build is reproducible.

## Installation

1. Blender → `Edit ▸ Preferences ▸ Add-ons`:
   - If the list still contains the old single-file addon (the `.py` version of module `dsh_blender_bridge`), the old `MCP for Blender` /
     `blender_mcp` / `blender_mcp_addon`: **untick it and uninstall/remove it first** (the same module name cannot be installed twice, and the two addons would also fight over 9876).
   - `Install...` → select the `dsh_blender_bridge.zip` in this directory (not the directory, not a single `.py`).
2. Tick to enable **DSH Blender Bridge**.
3. In the 3D view press `N` → find the "DSH Blender Bridge" panel → click **Connect** (port 9876).

> You can also let the plugin **launch everything in one step**: `blender_viewport(op="launch")` — it launches GUI Blender, **automatically finds and enables**
> this addon (the `dsh_blender_bridge` / `dshbb_*` directory or zip form) and verifies addon v1.11+ / protocol 11.

## Verification

```bash
blender_rt_cmd get_addon_info     # addon_version should be [1, 11], protocol_version should be 11
blender_rt_cmd get_activity_state # state may be idle / human / agent / both
```

Once installed, select an object in Blender → `N` → "Selection → DSH" → send; the selection goes into the **draft of the current DSH session** (it is not sent automatically).
Selecting vertices/edges/faces in edit mode, bones in pose mode, and curve/lattice control points in edit mode are sent as well (`selection.sub` in the payload);
the object / member lists in the N panel are collapsed by default, and when expanded they have a scrollbar and an adjustable height.

Panel structure: activity state pinned at the top (a red warning is shown while the AI is operating) + a "Pause AI operations" button;
"Environment and character model API" is the parent panel and contains the "Environment generation" (Poly Haven / Sketchfab / Poly Pizza) and
"Model generation" (Hyper3D / Hunyuan3D) sub-panels, all collapsed by default. While paused, the socket only lets read-only commands through.

## Environment variables (old names still work)

The new name wins and the old name is the fallback: `DSHBB_HYPER3D_API_KEY` → falls back to `BLENDERMCP_HYPER3D_API_KEY`, and likewise for the rest
(`SKETCHFAB` / `POLYPIZZA` / `HUNYUAN3D_*`). **Old variables you already set do not stop working** (this is only key-name compatibility, it does not mean the old addon is supported).
