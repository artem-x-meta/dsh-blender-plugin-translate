# Security policy

[English](../../SECURITY.md)

Security fixes are provided only for the **latest release** (see `version` in `package.json` for the current version). For older versions, please upgrade first.

## Reporting vulnerabilities

Please **do not** report security issues through a public issue; use GitHub's private channel:

1. <https://github.com/sixtysevenlf/dsh-blender-plugin/security/advisories/new>
   (repository -> **Security** -> **Advisories** -> *Report a vulnerability*).
2. If that channel is unavailable, you may open an issue that **only says** "I want to report a security issue, please provide a private contact",
   **without any details**.

A report should include: affected version, reproduction steps, impact surface (who can trigger it, what preconditions are needed) and, if available, a PoC.
We respond for the first time within 7 days; after a fix is released we credit you in the advisory (unless you ask to stay anonymous).

## This plugin's execution surface (consider it when assessing trust)

This plugin **by design** executes code and starts processes; it is not a read-only data plugin:

| Surface | Description |
|---|---|
| Blender-side Python | `blender_rt_do` / `blender_rt_headless` / `blender_rt_worker` / `blender_rt_plan` and others hand caller-supplied Python to Blender's `bpy` for execution; `K` is a persistent kernel retained across calls |
| Local processes | Spawns the backend `node lib/runtime/server.js` (after `npm run build`), headless `blender -b`, and the external validators under `runtime/ext/` (glTF-Validator / open3d); uses `SIGTERM` -> `SIGKILL` to clean up a leftover backend when necessary |
| Local network | The backend listens only on `127.0.0.1` (default 9877); it talks to the Blender addon over TCP on `127.0.0.1:9876`. The plugin itself has **no** outbound telemetry |
| File access | Default working directory `~/.dsh-blender-rt` (overridable with `DSH_BLENDER_*` environment variables or `dsh-blender.config.json` in the package root): render artifacts, logs, job ledger |
| gate expressions | `gate_run`'s `pass_if` / `degrade_if` are **restricted expressions**: they first pass the `_check_ast` syntax allowlist in `runtime/py/core/gate.py`, then are evaluated node by node by `_eval_node` (**no `eval` / `exec` call**); underscore attributes are disabled and functions are limited to `min` / `max` / `len` / `abs` / `round` / `all` / `any` / `sum` / `float` / `int` / `str` |
| Credentials | The host plugin **does not read, store or transmit** any API key / token / credential file. The bundled addon offers optional asset integration credentials (Hyper3D, Sketchfab, Poly Pizza, Hunyuan3D), kept as password fields in Blender's add-on preferences; they can also be supplied through `DSHBB_*` environment variables (the old `BLENDERMCP_*` names are still compatible), and are sent only to the corresponding third-party API you actively call |
| Telemetry | Off by default. Only after the addon's telemetry consent is checked does the addon collect manual edit events and hand them to the DSH host through `drain_human_activity`; the plugin itself sends no telemetry off the machine |

## Third-party dependencies / Blender-side addon

- The Blender side needs the addon shipped with this repository (`DSH Blender Bridge` v1.11 / protocol 11, distributed as `addon/dsh_blender_bridge.zip`,
  with sources in `addon/dsh_blender_bridge/`). The old `MCP for Blender` / category-action implementation is **not in this repository**
  and has not been supported since v2.3; do not install it or grant it trust.
- The release package is produced by `npm pack` and contains only the content of the `files` allowlist in `package.json`;
  build dependencies come from the DSH checkout, and runtime dependencies are injected by the host (`peerDependencies`).
- It is recommended to add this repository to Dependabot (see `.github/dependabot.yml`).
