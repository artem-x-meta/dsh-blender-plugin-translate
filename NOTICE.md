# Notice and attribution

This repository is an **unofficial English localization** of
[`dsh-blender-plugin`](https://github.com/sixtysevenlf/dsh-blender-plugin) (the Blender bridge for
DeepSeek Harness). It is a derived work, not the upstream project, and it is not affiliated with or
endorsed by the upstream author.

## Upstream components and their licences

| Component | Upstream | Licence |
|---|---|---|
| `dsh-blender-plugin` (plugin, add-on, docs) | © 2026 sixtyseven67 | BSD-3-Clause (see `LICENSE`) |
| `dsh_blender_bridge` add-on | derived from [ahujasid/blender-mcp](https://github.com/ahujasid/blender-mcp) (renamed) | MIT, copyright notices retained in `plugin/addon/README.md` |
| `blender-modeling` skill documentation | derived from [RobLe3/cc-blender-skill](https://github.com/RobLe3/cc-blender-skill) and [arjun988/blender-skills](https://github.com/arjun988/blender-skills) | MIT (see `skill/NOTICE.md`) |

All upstream copyright notices and licence texts are kept in place. Nothing here removes or alters
them; if a notice looks missing, treat that as a bug and open an issue.

## What was changed

- **Only strings and comments were translated** (Chinese/Russian hybrid → English), plus the
  documentation under `docs/`.
- **Code was not modified.** Every translated file was compared against the original by AST
  (Python) or a comment/string-stripped token stream (JavaScript/TypeScript): identifiers, control
  flow, numbers, JSON keys, format placeholders and API names are identical.
- **Documentation files with Chinese names were renamed** to ASCII slugs, and every reference to them
  was rewritten (`docs/操作教程.md` → `docs/operation-tutorial.md`, and so on).
- **The add-on zip was rebuilt** from the translated sources (`addon/dsh_blender_bridge.zip`,
  69 entries), because the shipped zip contained the original Chinese code.
- **Two upstream download URLs in `plugin/README.md` and `plugin/skills/blender-modeling/install.sh`
  were repointed at this repository**, since the files they fetch were renamed here.

## Intentionally kept Chinese

`plugin/lib/runtime/core/errors.js` keeps a few Chinese alternatives inside regexes
(`/已使用的库|in use|Cannot overwrite/i`, `…|无法读取/i`). These match error text produced by **Blender
itself**, which is localized — removing the Chinese alternatives would silently stop error
classification from working for Chinese-locale Blender installs. They are not user-facing strings.
Everything else in the tree is free of Chinese characters.

## Warranty

Provided **as is**, without warranty of any kind, as a translation aid. If the translation breaks
something, restore the backup taken by `tools/install.ps1 -Restore` and report the file and line.
