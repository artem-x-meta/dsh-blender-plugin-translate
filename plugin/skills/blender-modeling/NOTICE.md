# NOTICE — Sources and Licensing

This skill (`blender-modeling`) is a derivative work of MIT-licensed projects; tool calls have been rewritten for the local `blender_rt_*` direct-connection toolchain.

## Upstream Projects

1. **RobLe3/cc-blender-skill** — https://github.com/RobLe3/cc-blender-skill (MIT)
   Used: the decision tree, 8 recipes, three key pitfalls, modifier stack order and symptom table from `plugin/skills/blender-modeling/SKILL.md`; `references/overview.md` (this directory's `references/modeling-overview.md`, original text included).

2. **arjun988/blender-skills** — https://github.com/arjun988/blender-skills (MIT)
   Used: the six-step outline, collection structure, modifier stack philosophy and rules, cleanup checklist, MUST DO / MUST NOT DO from `.claude/skills/blender-modeler/SKILL.md`.

## Local Changes

- `mcp__blender__execute_blender_code` / `get_scene_info` / `get_object_info` → `blender_rt_do` / `blender_rt_headless` / `blender_rt_cmd` / `blender_rt_see` / `blender_rt_job` / `blender_rt_txn`.
- Added a "channel semantics" section (MCP's "re-import every time" assumption holds locally only for headless).
- Body text rewritten into Chinese; structure condensed and merged.

The MIT license requires retaining the copyright and license notices; for the full license text see the LICENSE in the corresponding upstream repository. This derivative work is likewise provided under MIT.
