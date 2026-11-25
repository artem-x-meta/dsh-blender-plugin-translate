#!/usr/bin/env bash
# Install the standalone blender-modeling skill (English edition) for non-DSH hosts.
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/artem-x-meta/dsh-blender-plugin-translate/main/skill/install.sh | bash
# Installs into ~/.dsh/skills/blender-modeling.
set -euo pipefail

REPO_RAW="https://raw.githubusercontent.com/artem-x-meta/dsh-blender-plugin-translate/main"
ROOT="$HOME/.dsh/skills"
DEST="$ROOT/blender-modeling"

mkdir -p "$DEST/references"

fetch() {
  local src="$1"
  local dst="$2"
  curl -fsSL "$REPO_RAW/skill/$src" -o "$dst"
}

fetch "SKILL.md" "$DEST/SKILL.md"
fetch "README.md" "$DEST/README.md"
fetch "NOTICE.md" "$DEST/NOTICE.md"
fetch "LICENSE" "$DEST/LICENSE"
for f in modeling-overview.md multiview-calibration.md reference-image-reconstruction-sop.md acceptance-checklist.md surface-algorithms.md; do
  fetch "references/$f" "$DEST/references/$f"
done

printf 'Installed blender-modeling skill to %s\n' "$DEST"
printf 'Restart your agent or reload skills, then invoke "blender-modeling".\n'
