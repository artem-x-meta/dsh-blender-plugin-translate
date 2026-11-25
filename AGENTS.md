# AGENTS.md

Instructions for a coding agent that opens this repository. Read this file first, then act.

This repo is an **English localization of `dsh-blender-plugin`** (the Blender bridge for DeepSeek
Harness). Upstream ships its strings, comments and documentation in a Russian/Chinese hybrid; this
repo contains the same code with **only strings and comments translated**, plus the translated skill
documentation. Logic is unchanged — that was verified by AST / token comparison against the original
for every file.

---

## 1. If you were asked to install this

That is the main use case: the user cloned the repo and wants the English version inside their own
DeepSeek Harness installation. Do the following.

### 1.1 Find the installed package

First candidate that contains `package.json`:

- `%USERPROFILE%\.dsh\profiles\desktop\node_modules\dsh-blender-plugin` (Windows)
- `~/.dsh/profiles/*/node_modules/dsh-blender-plugin` (macOS / Linux)
- `$DSH_HOME/profiles/*/node_modules/dsh-blender-plugin`

Several profiles may carry the package. **Ask the user which one to patch**, or patch each with its
own backup. Do not change anything outside that package.

### 1.2 Install (backup is automatic)

```powershell
pwsh tools/install.ps1 -Package "<path to node_modules\dsh-blender-plugin>"
```

No PowerShell? Do the same by hand:

```bash
PKG="<path to node_modules/dsh-blender-plugin>"
cp -a "$PKG" "$PKG.orig-$(date +%Y%m%d-%H%M%S)"     # backup first, always
cp -a plugin/. "$PKG"/                              # overlay; files not in the repo stay untouched
find "$PKG" -name __pycache__ -type d -exec rm -rf {} +
```

### 1.3 Restart everything that cached the old strings

Nothing hot-reloads these:

1. **Plugin backend** (loads `lib/*.js` at start). With the DSH Blender tools available:
   `blender_viewport(op="restart")`, then `blender_viewport(op="status")` must be healthy.
   Without the tools: restart the DSH session / backend process.
2. **Blender** — the add-on is Python loaded at Blender start. Quit Blender, start it, reconnect:
   3D viewport → `N` → *DSH Blender Bridge* → **Connect** (port 9876).
3. **Headless workers**, if used: `blender_rt_worker(op="restart", name="<name>")`.

### 1.4 Verify — do not skip

```bash
python tools/verify_no_cjk.py "<package path>"     # expect: 0 line(s) with Chinese
```

`lib/runtime/core/errors.js` is allow-listed on purpose: it keeps Chinese alternatives in regexes
that match Blender's own localized error text.

Then smoke-test through the tooling (any scene):

1. `blender_rt_plan(op="catalog")` → family descriptions in English.
2. `blender_rt_commands()` → command list in English.
3. `blender_rt_plan(op="audit_mesh", args={"scope": "<collection>"})` → `note` / `hint` / `top_defects` in English.
4. `blender_rt_see()` → a frame comes back, so the channel survived the restart.

If Chinese still appears, report **file:line** and stop — no hand-waving.

### 1.5 Rollback

```powershell
pwsh tools/install.ps1 -Restore -Package "<package path>"   # newest backup, then restart again
```

The translation only touched string/comment payloads, so a real breakage almost always means some
*code* matches on a message that got reworded — report that file:line instead of patching blindly.

---

## 2. Known behaviour changes (intended, not bugs)

- Shape-draft role enum: `主体 / 配件 / 重复件` → `main / accessory / repeated`.
- Chinese unit words (`毫米`, `厘米`) in draft records are no longer parsed; use `mm` / `cm`.
- Error wording is English now (`parameter mismatch: %s`, `unknown parameters %s`, …). A personal
  script that matched the old Chinese messages must be updated.
- `plugin/skills/blender-modeling/SKILL.md` is English, so this skill is read in English.
- Upstream releases overwrite the translation: after a plugin update, re-run 1.2.

## 3. Repo layout

| Path | Meaning |
|---|---|
| `plugin/` | Drop-in replacement files for `<profile>/node_modules/dsh-blender-plugin/` (`addon/`, `lib/`, `runtime/`, `docs/`, `skills/`). |
| `skill/` | English translation of the modeling skill documentation (mirror of `plugin/skills/`). |
| `glossary.md` | Chinese → English term table, for any Chinese that still shows up in tool output. |
| `tools/install.ps1` | Backup + overlay + bytecode cleanup; `-Restore` rolls back; `-DryRun` previews. |
| `tools/verify_no_cjk.py` | Fails if any Chinese is left under a path. |
| `LICENSE`, `NOTICE.md` | Upstream BSD-3-Clause licence and attribution. Keep both. |

## 4. If you are editing this repo

- **Never hand-edit `plugin/` without re-running the gates**: `python tools/verify_no_cjk.py plugin`
  and a syntax pass (`python -m py_compile` for `.py`, `node --check` for `.js`).
- `plugin/` is a translation of a specific upstream version — record any rebase against a newer
  upstream in `NOTICE.md`, do not silently mix versions.
- Keep the translation surgical: strings, comments, docs. If a change would alter control flow,
  identifiers, JSON keys, placeholders (`%s`, `{0}`, `${x}`) or numbers, it does not belong here.
- Keep the licence and attribution intact; this is a derived work under BSD-3-Clause.
