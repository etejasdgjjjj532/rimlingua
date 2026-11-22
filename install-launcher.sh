#!/usr/bin/env bash
# Create a user-only app-menu launcher for the RimWorld translation editor.
set -euo pipefail
project="$(cd -- "$(dirname -- "$0")" && pwd)"
target="$HOME/.local/share/applications/rimworld-translator.desktop"
mkdir -p -- "$(dirname -- "$target")"
if [[ -e "$target" ]] && ! grep -q '^# Managed-by: RimWorld Translation Editor$' "$target"; then
  echo "Another launcher already exists at $target; refusing to overwrite."
  exit 1
fi
cat >"$target" <<EOF
[Desktop Entry]
# Managed-by: RimWorld Translation Editor
Type=Application
Name=RimWorld Translation Editor
Name[ja]=RimWorld 多言語翻訳エディター
Name[en]=RimWorld Translation Editor
Comment=Translate RimWorld mods into multiple languages
Exec="$project/run.sh"
Path=$project
Terminal=false
Icon=accessories-text-editor
Categories=Utility;
Keywords=RimWorld;MOD;Translation;Japanese;
StartupNotify=true
EOF
chmod 644 "$target"
echo "Installed application launcher: $target"
