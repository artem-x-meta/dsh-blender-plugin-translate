# dsh-blender-plugin — English localization

An unofficial **English translation** of [`dsh-blender-plugin`](https://github.com/sixtysevenlf/dsh-blender-plugin),
the Blender bridge for DeepSeek Harness. Upstream ships its tool descriptions, receipts, comments and
documentation as a Russian/Chinese hybrid; this repo contains the same code with **only strings,
comments and docs translated**, so every receipt the agent reads comes back in English.

- **241 019** Chinese characters removed across **487** files → **13** left, all of them regex
  alternatives that match Blender's *own* localized error output (see `NOTICE.md`).
- **Logic unchanged**: Python verified by AST comparison, JS/TS by comment-and-string-stripped token
  comparison, per file, against the untouched original.
- **456 files** checked at the end: `0` with Chinese, `0` syntax errors.

## What you get

| Path | Meaning |
|---|---|
| `plugin/` | Drop-in replacement for `<profile>/node_modules/dsh-blender-plugin/` — `addon/`, `lib/`, `runtime/`, `docs/`, `skills/`, plus the package docs. |
| `skill/` | The modeling skill documentation (`SKILL.md`, `references/`), English. |
| `glossary.md` | Chinese → English term table: verdict, receipt, gate, criterion, floater, blockout, hidden overlap … |
| `tools/install.ps1` | Backup, overlay, clean bytecode. `-Restore` rolls back, `-DryRun` previews. |
| `tools/verify_no_cjk.py` | Reports any Chinese left under a path; exit code 0 = clean. |
| `AGENTS.md` | Instructions your coding agent can follow on its own (see below). |

## Install

**With an agent (recommended).** Clone the repo, open it with your coding agent and say:

> read AGENTS.md and install this

It finds the installed plugin, backs it up, copies the files, restarts the backend / Blender / workers
and runs the verification, then reports what it did.

**By hand, Windows:**

```powershell
git clone https://github.com/artem-x-meta/dsh-blender-plugin-translate
cd dsh-blender-plugin-translate
pwsh tools/install.ps1 -Package "$env:USERPROFILE\.dsh\profiles\desktop\node_modules\dsh-blender-plugin"
```

**By hand, macOS/Linux:**

```bash
git clone https://github.com/artem-x-meta/dsh-blender-plugin-translate
cd dsh-blender-plugin-translate
PKG="$HOME/.dsh/profiles/desktop/node_modules/dsh-blender-plugin"
cp -a "$PKG" "$PKG.orig-$(date +%Y%m%d-%H%M%S)"
cp -a plugin/. "$PKG"/
find "$PKG" -name __pycache__ -type d -exec rm -rf {} +
```

Then **restart what caches the strings**: the plugin backend (`blender_viewport(op="restart")` if you
have the tools, otherwise restart DSH), Blender itself (the add-on is Python loaded at startup —
reconnect it: `N` panel → *DSH Blender Bridge* → **Connect**), and any headless worker. Nothing
hot-reloads these; skipping the restart is the usual reason "it is still Chinese".

## Verify

```bash
python tools/verify_no_cjk.py "<path to the package>"     # expect: 0 line(s) with Chinese
```

Then check the tooling itself: `blender_rt_plan(op="catalog")`, `blender_rt_commands()`,
`blender_rt_plan(op="audit_mesh", …)` and `blender_rt_see()` should all answer in English.

Rollback at any time:

```powershell
pwsh tools/install.ps1 -Restore -Package "<path to the package>"
```

## Behaviour changes (intended, documented)

- Shape-draft role enum `主体 / 配件 / 重复件` → `main / accessory / repeated`.
- Chinese unit words (`毫米`, `厘米`) inside draft records are no longer parsed; `mm` / `cm` are.
- Error wording is English (`parameter mismatch: %s`, `unknown parameters %s`, …); personal scripts
  that matched the old Chinese messages need updating.
- Docs were renamed to ASCII slugs; references inside code and docs were rewritten accordingly.

## How it was built

1. Audited the original: 363 code files with Chinese, split into 16 balanced work units by character
   count; docs and `.d.ts` declaration files into separate units.
2. Each unit translated by a separate agent with the same rules: translate strings/comments/docs,
   never identifiers, keys, placeholders, numbers or paths; verify syntax afterwards.
3. Cross-file contracts were resolved explicitly — strings that one module *matches on* were kept
   consistent with their producer (e.g. a self-test comparing URDF warning text).
4. Gates: `py_compile` / `node --check` on every file, AST or token-stream equivalence against the
   original, and a zero-Chinese sweep. Final run: 456 files, 0 Chinese, 0 syntax errors.

## Limits

- Upstream releases overwrite the translation — re-run the install after updating the plugin.
- This is a translation of one specific upstream version; it is not a fork with its own features.
- The skill text is a faithful translation, not an editorial review: upstream contradictions were
  preserved, not "fixed".
- Blender's own localized messages can still be Chinese if *your* Blender UI language is Chinese —
  that is Blender, not the plugin.

## Licence

BSD-3-Clause, inherited from upstream — see `LICENSE`, and `NOTICE.md` for full attribution
(including the MIT-licensed add-on and skill sources). This is a derived work; keep the notices.
