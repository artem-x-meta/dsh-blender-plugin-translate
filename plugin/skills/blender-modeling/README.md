# blender-modeling (bundled with the plugin)

> **This skill has already been merged into the plugin repository** (`dsh-blender-plugin`'s `skills/blender-modeling/`),
> and since **v2.2.0** the plugin **auto-registers it as a bundled skill** when DSH starts —— installing the plugin brings it along,
> with **no need** to separately clone / download / symlink it.

## How users use it

- After installing the plugin and **restarting DSH**, `blender-modeling` shows up directly in the session's skill catalog (the `skill` tool's available skills list);
  the model loads it automatically for tasks like "build / sculpt a 3D object", "reproduce a shape from a reference image", "have multiple agents divide the work of building a machine", "assembly inspection".
- To confirm manually: have the model load `blender-modeling` via `skill` in the session, or check whether the skill catalog contains this entry.
- **Precedence**: if you previously installed the standalone repository into `~/.dsh/skills/blender-modeling` (user level), it takes **precedence over** the bundled copy inside this package
  (DSH's rank rule: user 400 < bundled 600); the two are identical in content, so usage is unaffected. To force the in-package version, just delete the user-level directory/symlink.

## Without installing the plugin — giving the skill to another host (Claude Code / Codex / Cursor…)

The package install directory is itself a standard `skills/<name>/SKILL.md` directory, so just symlink or copy it:

```bash
# Locate this package's install path (example: the DSH profile's node_modules)
PLUGIN="$(dirname "$(node -e "console.log(require.resolve('dsh-blender-plugin/package.json'))")")"
mkdir -p ~/.dsh/skills
ln -s "$PLUGIN/skills/blender-modeling" ~/.dsh/skills/blender-modeling   # or cp -r
```

> ⚠ `SKILL.md` **must keep its YAML frontmatter** (`name` / `description` / `license`) —— the loader builds the skill catalog from it.

## Contents (v2.6 · architecture-first)

- `SKILL.md` —— **plugin-architecture-first modeling/assembly work instructions**: catalog first → plan op → worker session → receipt/verdict → gate/delivery; includes the standard state machine, tool selection matrix, reference-image measurement, assembly repair/gate/export, blockout and Seedance reference packages, same-camera QC, defect evaluation, headless watch, multi-agent protocol and anti-patterns. Generic Blender recipes are demoted to appendix A (deep-dive reference, not the preferred path).
- `references/modeling-overview.md` —— upstream English original text, included (deep-dive reference; does not replace the plugin architecture).
- `references/multiview-calibration.md` —— three-view joint calibration script (supports `--selftest`; pairs with img_calib/shapesolve).
- `references/reference-reconstruction-sop.md` —— reference-image reconstruction in nine steps (prefer img_digest/probe/measure/calib; no mm without calibration).
- `references/acceptance-checklist.md` —— for independent verification subagents only (prefer audit/asm_gate/gate_run/visualreport/eval; about 4.2k characters).
- `references/surface-algorithms.md` —— surface_* surface quick reference: loft/sweep/patch → tessellate → validate → export, the verdict three-state and the M3/M5 limitations.

> **Architecture-first**: wherever a plugin op exists, hand-writing equivalent geometry/acceptance is not allowed; write bpy only when the catalog has no matching capability, and it still must go back through the plugin gates for acceptance.

## Licensing and Sources

- Contents of this directory: **MIT** (see [LICENSE](LICENSE)), Copyright © 2026 sixtyseven67.
- Derived from two MIT projects (decision tree / recipes / pitfall table / six-step outline, etc.); tool calls have been rewritten for this plugin's `blender_rt_*` direct-connection chain:
  [RobLe3/cc-blender-skill](https://github.com/RobLe3/cc-blender-skill) ·
  [arjun988/blender-skills](https://github.com/arjun988/blender-skills).
- For full attribution and local changes see [NOTICE.md](NOTICE.md).
- Standalone distribution mirror (historical repository, contents synced with this directory): <https://github.com/sixtysevenlf/dsh-skill-blender-modeling>.

---

**Sync basis**: v2.6 (2026-10-21) rewrote SKILL.md around the plugin architecture and corrected the references; from then on it is maintained **with this repository as the source of truth**, and the standalone repository serves only as a mirror/history.
