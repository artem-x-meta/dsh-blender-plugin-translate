# DSH update adaptation (current plugin v3.0.6)

> Trigger scenario: after DSH is upgraded (`npm i -g @deepseek-ai/dsh@<version>`), whether this plugin's 15 tools are still there and whether the behavior changed.
> Basis for the conclusion: a per-package diff of host 0.1.6-alpha.1 ↔ 0.1.7-alpha.2 on 2026-09-23 + a version-matrix, measured in practice (**historical snapshot**).
>
> **Current baseline (2026-11-05)**: plugin **v3.0.6** · **15 model tools** · plan catalog **34 families / 228 ops** ·
> addon **v1.11 / protocol 11**; acceptance is still gated on `doctor` returning `kind=ok`. The DSH upgrade adaptation conclusions (§0–§4) are unchanged;
> for the concrete tool count / catalog count, the current repository and `blender_rt_plan(op="catalog")` are authoritative.

## 0. In one sentence

**The tool-definition contract is safe** (all 15 tools registered successfully under all five versions `dsh-tools` 0.1.5-rc.2 / 0.1.6-alpha.1 / 0.1.6-alpha.2 /
0.1.7-alpha.1 / 0.1.7-alpha.2, 0 errors, parameter schema byte-for-byte identical).
What really needs watching is **the four things unrelated to tool definitions**: the load chain, the resolution chain, cancellation/timeout, and the output budget baseline.

> 2026-10-28 review: the tool count is still **15**, the plan catalog is **34 families / 228 ops** (v3.0.1); the conclusions on the four risk points above are unchanged.

## 1. The three chains of this plugin inside DSH (understand the structure first, then look at the risks)

| Chain | Current state | Symptom when broken |
|---|---|---|
| **Load chain** | **bundle style (since 2026-09-23)**: the plugin is listed in the profile's `dsh.profile.bundles`, the patch layer is provided by this package's `cordis.patch.yml` (the adjacent coc-dice / session-list-cache moved in the same batch). `dsh-super-injector` has been uninstalled and deleted | all 15 tools disappear as a whole, but neither Blender nor the plugin package is broken; first use `--dump-config` to see whether this package's layer is there (§2) |
| **Resolution chain** | `<plugin>/node_modules/@deepseek-ai/dsh-tools` → `~/dsh-harness` (fake-checkout symlink) → `/usr/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/dsh-tools` (**global install**); same for `cordis`/`schemastery`/`cosmokit`/`dsh-llm` | `ERR_MODULE_NOT_FOUND` at load time (not a degradation, a complete disappearance); changing npm prefix / nvm / pnpm global triggers it |
| **Build chain** | `npm run build` (`scripts/build.mjs`) is the only default entry point; the old `scripts/build.sh` is kept only as an optional `DSH_CHECKOUT` dependency-link compatibility entry and is marked deprecated | build failure / `tsc not found`; the old wrapper is only needed when using `DSH_CHECKOUT` |

Benefit: the resolution chain points at **the global install itself**, so the plugin's `defineTool` and the host are **always the same version** (there is no "compiling against an old copy").
Cost: there is no frozen baseline — whatever the host changes, the plugin eats it on the next load; hence the regression below must be run.

## 2. Post-update acceptance (three steps, about 30 seconds)

```bash
cd ~/DSH/dsh-blender-plugin
npm run test:dsh-api                    # ② tool contract: 15 tools + 15 timeoutMs + 0 errors + prefix [v3.0.6]
npm run test:dsh-api -- --version 0.1.7-alpha.2   # ③ pre-upgrade rehearsal: pull down the dsh-tools of the version to be upgraded and test first
```

Then click `blender_viewport(op="doctor")` once more in the session:

```
Diagnosis: …
Host API: dsh-tools@<current version> @ /usr/lib/node_modules/.../dsh-tools/lib/index.js   <- self-evidence (the version is whatever this machine has)
Plugin: v3.0.6 @ /home/sixtyseven67/DSH/dsh-blender-plugin/lib/index.js
```

The `Host API` line is **the first thing to look at after an upgrade**: it proves "which host API the plugin is attached to".
If the tools disappear as a whole, first run the assembly rehearsal:

```bash
dsh --profile web --dump-config | grep -A3 dsh-blender-plugin
```

Having this package's layer = the load chain is not broken (go check the resolution chain / host API); not having it = the profile's `dsh.profile.bundles` was modified.
(`dev_plugin_status` / `dev_injected_list` belong to the deleted super-injector and are no longer available.)

## 3. Known risks and status

| ID | Risk | Status |
|---|---|---|
| R1 | could once only be injected via super-injector: the third-party hook consumed host internals (`loader.internal.loadCache`/`entry._dispose`), so a single loader refactor could make it disappear as a whole | **Resolved**: switched to official bundle assembly on 2026-09-23 and deleted super-injector (see §4) |
| R2 | the resolution chain depends on the absolute path of the global install; no frozen baseline | **Self-evidence added** (`HOST_API` + doctor/status); switching install locations still needs manual confirmation |
| R3 | host `exec.signal` not wired, `timeoutMs` not declared → when upstream sets a default deadline, "Blender is still running, the tool already judged it timed out" | **Fixed** (still holds in v3.0.6: `EXEC_CTX` threaded through + 15 static `timeoutMs`) |
| R4 | 0.1.7 changed the spill baseline from `maxInlineBytes: 50000` to `maxInlineTokens: 12500`, and images count toward omission → large text may become an on-disk spill, and images in long sessions may be omitted | **Watch item**: after upgrading, recalibrate this plugin's own 12KB truncation threshold in tokens |
| R5 | the new `plugin-manager` decides bundles by `dsh.bundle` | **Declared** (`package.json` + `cordis.patch.yml`), can switch to §4 |
| R6 | 0.1.7 replaced the official HMR line `cordis-plugin-hmr` with `@deepseek-ai/dsh-hmr`, and `dsh-settings-file` → `dsh-settings` | this plugin does not depend on these ids; the injector is deleted — the cost is no more third-party "runtime hot injection", config changes need a restart (the official HMR line only became active in 0.1.7) |
| R7 | `peerDependencies` names the bare names `cordis`/`schemastery` (a different lineage on npm), while the host uses `@deepseek-ai/*` | currently **link assembly** (profile node_modules → this directory → global install) → no impact; **must be resolved before switching to registry install** (`pnpm add`), otherwise a second implementation gets pulled in |
| R8 | image round-trip failures were swallowed by `catch`, text-only results had no warning | **Fixed** (still holds in v3.0.6: `{ref}`/`{why}` + `⚠ image not returned: <reason>`) |
| R9 | all 15 tools + very long Chinese descriptions go into the prompt; the new dsh-tools already has `deferLoading` | **Optimization item**: if upstream defaults to deferred loading, the "description is the documentation" strategy needs evaluating |

## 4. Assembly style: bundle (switched on 2026-09-23 + migration record)

Current state of this machine: the plugin is listed in `~/.dsh/profiles/web/package.json`'s `dsh.profile.bundles`, the patch layer is provided by this package's
`cordis.patch.yml`; `dsh-super-injector` has been deleted entirely from bundles / dependencies / state directory / source / distribution artifacts.

Two plugins that **previously stayed alive only through injection** migrated in the same batch — not migrating them would have lost them together with the injector:

| Plugin | Before migration | After migration |
|---|---|---|
| `dsh-blender-plugin` | injector injection (`ctx.loader.create` mounted on root) | profile bundle (this package's `cordis.patch.yml`) |
| `@dsh-external/dsh-coc-dice` | same as above | profile bundle (that package's `cordis.patch.yml`) — still **host level**, the dice tool is visible to all sessions |
| `@dsh-external/dsh-session-list-cache` | same as above | profile bundle (that package's `cordis.patch.yml`) |

**DSH must be restarted for this to take effect** (before the restart the old process still holds the injector entry and the injected fiber; after the restart only bundles are used for assembly).
Note: before the restart, that live injector fiber **rebuilds** the stats/log files in `~/.dsh/super-injector/` by itself (its periodic write),
so "deleted and it comes back" is normal — just delete it once more after the restart:

```bash
rm -rf ~/.dsh/super-injector   # run after the restart; it will not be rebuilt afterwards
```
Self-check after the restart:

```bash
dsh --profile web --dump-config | grep -A3 "dsh-blender-plugin\|dsh-coc-dice\|dsh-session-list-cache"
# expected: one insert line per layer, three in total; also grep super-injector should print nothing
```

**Rollback**: restore `~/.dsh/profiles/web/package.json` from `package.json.bak-injector-removal-<timestamp>`,
reinstall super-injector, restart.

⚠ Do not use two assembly styles at once: the two fibers **register tools with the same names twice** (you will see two copies of `blender_rt_*` in the session).

## 5. Fixed actions for every DSH upgrade (copy this paragraph)

1. Before upgrading: `npm run test:dsh-api -- --version <target version>` → PASS, then upgrade.
2. When upgrading: **do not use a bare `npm i -g @deepseek-ai/dsh`** — `latest` may be **older** than the installed version (this happened in the 2026-09-23 historical snapshot).
   Before upgrading, check with `npm view @deepseek-ai/dsh dist-tags` (or the version recommended in the project docs), then install an explicit version / `@alpha`.
3. After upgrading: the three steps of §2 + `dsh --profile web --dump-config | grep -c super-injector` (should be 0)
   + `blender_viewport(op="doctor")` to check the `Host API` line.
4. If R4 takes effect (results become on-disk spill): adjust the truncation threshold recorded in `docs/configuration-reference.md`, and re-run one large
   `blender_rt_plan audit_*` to see the output shape.
