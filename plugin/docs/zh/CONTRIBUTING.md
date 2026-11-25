# Contributing to DSH × Blender

[English](../../CONTRIBUTING.md)

Thank you for taking the time to contribute. This project lets an AI assistant operate a real Blender session directly and verifiably. Issues and pull
requests are welcome in both Chinese and English.

Before you start, read the [Chinese README](./README.md) (or the [English README](../../README.md)) and [AGENTS.md](../../AGENTS.md).
AGENTS.md explains how the layers fit together, what counts as "installed correctly", and where the single source of truth for commands lives.

## How you can contribute

- **Bug reports**: include reproduction steps, the exact version from `package.json`, and the response from the `doctor` endpoint.
- **Documentation**: the two READMEs, `docs/`, the architecture notes, and the bundled skill under `skills/blender-modeling/`. User-facing
  Chinese guides stay in Chinese; AI-facing documents stay in English.
- **Tests**: a failing test that reproduces a real bug is worth more than a fix without one.
- **Code**: `src/` (TypeScript host side), `runtime/` (backend), `addon/` (Blender side).

## Before opening an issue

1. Search existing issues and the common-failures section of the README first.
2. Reproduce on the latest version, not on an old tag.
3. **Security issues go through [SECURITY.md](SECURITY.md)**; do not open a public issue.

For changes larger than a bug fix — new tools, protocol changes, new dependencies — open an issue to agree on the direction first, then invest in the implementation.

## Development environment

Prerequisites:

- Node.js **24.9** or newer for development and testing; CI uses Node 24.
- Blender **4.2 LTS** (verified); Blender 5.x is not yet verified (GUI mode needs the bundled addon; headless mode needs only the executable).
- Python **3.11+**; `npm run setup:dev` creates `.venv` and installs the Python test dependencies. Tests auto-detect
  `.venv`; point `PYTHON` elsewhere only when you need a different interpreter (on Windows also set
  `PYTHONIOENCODING=utf-8` and `PYTHONUTF8=1`).
- Optional: only a DSH source checkout is needed if you have to rebuild `lib/`.

After cloning, set up the dev environment with one command:

    git clone https://github.com/sixtysevenlf/dsh-blender-plugin.git
    cd dsh-blender-plugin
    npm run setup:dev

`npm run setup:dev` looks for a Python 3.11+ interpreter in the order `PYTHON` → `python` → `python3` → (Windows) `py -3`,
creates or reuses `.venv`, installs `requirements-dev.txt`, `requirements-typecheck.txt`, and the npm
dependencies (running `npm ci --legacy-peer-deps` only when `node_modules` is missing). The script is idempotent:
`npm run setup:dev -- --check` only verifies without writing, `npm run setup:dev -- --force` rebuilds `.venv`. When the script
finishes it prints the venv's `PYTHON` path. Neither `.venv` nor `node_modules` is checked in.

Build, typecheck, test, lint, and packaging commands are defined once, only in [AGENTS.md §1](../../AGENTS.md#1-commands-single-source). Use the commands there; do not copy variants from older documents. A normal clone no longer carries `lib/`, so you
need to build before running the backend locally.

Blender side: install the addon from the release zip, enable it, and click **Connect**. Only when `doctor` returns `kind=ok`
(GUI route), or a worker plus `see` returns one frame (pure headless route), is the install considered done.

## Repository structure

| Path | What it is |
|---|---|
| `src/` | The plugin's host-side TypeScript source, split into tools, host, plan, and contracts |
| `lib/` | Build output — generated, not checked in since 3.0.0, do not edit by hand |
| `runtime/` | Backend: engine, server, catalog, worker, headless runner, Python domain packages |
| `addon/` | The Blender addon package — the only supported addon |
| `skills/` | The bundled `blender-modeling` skill, registered automatically |
| `tests/` | Unit, integration, and end-to-end layers; see [tests/README.md](../../tests/README.md) |
| `docs/` | User guides (Chinese), architecture notes, refactor specs, and evidence packs |

## Testing

Layers and per-layer commands are in [tests/README.md](../../tests/README.md). While iterating, run the layer that matches your change; before opening a PR, run the full
PR gate. Most tests need neither Blender nor a GUI; the end-to-end layer needs both and runs only on tags and release candidates, not on
every PR.

A failing test is information. Do not make it green with skips, retries, or loosened assertions; fix the cause, or report. A flaky test needs an issue, an owner,
and a due date.

## Changing the catalog

The catalog in `runtime/` is the single source of truth for families, ops, and counts. After changing it, refresh the counts and the
capability lock with the commands in AGENTS.md §1, then run the contract tests. In the PR, explain why the lock changed; do not hand-edit the lock file.

## Pull Request

- One logical change per task; do not mix unrelated formatting into the diff.
- Use conventional commit titles: `feat:`, `fix:`, `docs:`, `test:`, `perf:`, `chore:`.
- Use the matching template from [.github/PULL_REQUEST_TEMPLATE/](../../.github/PULL_REQUEST_TEMPLATE/) (`bug_fix`, `feature`, `docs_update`, `refactor`): scope, behavior-matrix row, test
  evidence, risk, rollback, disclosure, checklist.
- When a PR fully fixes an issue, write `Fixes #123` in the description (one keyword per issue); GitHub closes it automatically once the PR merges into the default branch (`main`). Use `Refs #123` when it fixes only part of it or merely relates to it. Put the keyword in the PR description body, not in a comment or code block.
- [README.md](../../README.md) and the [Chinese README](./README.md) must stay in sync, and
  [CONTRIBUTING.md](../../CONTRIBUTING.md) likewise with the [Chinese CONTRIBUTING](./CONTRIBUTING.md); they are two versions of the same
  document, not independent pages.
- Update [CHANGELOG.md](../../CHANGELOG.md) under the next version heading; for breaking changes also update
  [MIGRATIONS.md](../../MIGRATIONS.md).
- Before changing a boundary or a contract, read [docs/architecture.md](../../docs/architecture.md), and keep the architecture document in sync with the code.
- Disclose AI assistance both in the commit trailer and in the PR; see AGENTS.md §6.
- Do not commit `node_modules`, virtual environments, `__pycache__`, `.tgz` artifacts, or dependency symlinks. Keep review size down: a single PR
  targets no more than 400 changed lines.

## Release process

The release process is owned by the release checklist and [docs/architecture.md](../../docs/architecture.md). In short: verify the release gates first, update
`package.json` and `PLUGIN_VERSION` in `src/constants.ts` in the same change, let `prepack` build `lib/`, attach the addon zip and
the npm tarball to the release, and rehearse the rollback before tagging. The detailed checklist is kept in the local refactor workspace and is not published with the repository.

### Manual CD

[.github/workflows/release.yml](../../.github/workflows/release.yml) is the manual release pipeline and supports only
`workflow_dispatch`: **Actions → Manual CD → Run workflow**. Inputs:

- `version` must match `package.json` and `PLUGIN_VERSION` in `src/constants.ts`;
- `dry_run` defaults to `true` and only verifies and packages;
- `dry_run=false` creates a **draft** GitHub Release and tag after approval in the `release` environment;
- `publish_npm` defaults to `false`; when enabled it publishes the packaged tarball to npm with provenance.

The pipeline does not push `main` or tags on its own; `workflow_dispatch` is visible only after that file is on the default branch, so run it after merging into `main` (the dry-run stage can also run on a branch that contains the workflow). Real-Blender E2E and the final publication of the GitHub Release remain manual steps. Configure required reviewers for the `release`
environment and protect `v*` tags. npm publishing uses trusted publishing (OIDC), so no `NPM_TOKEN` needs to be stored in the environment.

## License

The project uses [BSD-3-Clause](../../LICENSE). By submitting a contribution you agree to license it under the same terms. Be respectful and assume good faith; design
disagreements are fine, personal attacks are not.
