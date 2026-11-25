# Documentation archive

> This directory holds snapshots of **superseded** historical documents. They are evidence for traceability only and are **not the current baseline**.
> The outdated counts they contain (such as 27 families / 176 ops), removed paths (such as `runtime/audit.py`, `runtime/gate.py`),
> old version numbers and hashes are all preserved as-is; **do not judge the current state from them**.

## Archive inventory

| File | Period / nature | Replacement (current baseline) |
|---|---|---|
| [plugin-and-skill-optimization-acceptance.md](plugin-and-skill-optimization-acceptance.md) | v0.9.6 standalone acceptance snapshot (2026-09-26); counts and paths are all outdated | [AGENTS.md](../../AGENTS.md) §1–§7, [docs/architecture.md](../architecture.md), `blender_rt_plan(op="catalog")` |
| [headless-first-route-decision.md](headless-first-route-decision.md) | v0.9.3 historical route proposal (headless first), superseded by **GUI first** | [docs/operation-tutorial.md](../operation-tutorial.md) §7, [README.md](../../README.md) |
| [v2.6.0-release-notes.md](v2.6.0-release-notes.md) | v2.6.0 release notes (2026-10-21), superseded by later versions | [CHANGELOG.md](../../CHANGELOG.md), GitHub Releases |

## Archive policy

- Archive only documents that are **explicitly superseded by a new document or a new version** and still have traceability value; before archiving, add a "historical / outdated" banner at the original location.
- Archived files are **frozen snapshots**: they are no longer updated, and the body text, counts and links are kept as-is (internal links may be broken); archived content must not be treated as current instructions.
- Current documents must not cite files in this directory as the current baseline; when historical citation is genuinely needed, mark it as a "historical archive" and give the replacement.
- A new archive entry must be registered in the CHANGELOG or openspec change of the same change set, and the table above must be updated.
- Current sources of truth: [README.md](../../README.md), [AGENTS.md](../../AGENTS.md), [docs/architecture.md](../architecture.md),
  [CHANGELOG.md](../../CHANGELOG.md) and `blender_rt_plan(op="catalog")`.
