#!/bin/bash
# Restore the Zen profile from the newest (or given) backups/zen-profile-*.tar.gz.
# Only ever touches the Zen profile directory recorded next to the tarball.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
TAR="${1:-$(ls -t "$HERE"/backups/zen-profile-*.tar.gz | head -1)}"
PROFILE="$(cat "${TAR%.tar.gz}.txt")"

case "$PROFILE" in
  "$HOME/Library/Application Support/zen/Profiles/"*) ;;
  *) echo "refusing: unexpected profile path $PROFILE" >&2; exit 1;;
esac
if pgrep -f "/Applications/Zen.app/Contents/MacOS/" >/dev/null; then
  echo "Quit Zen first." >&2; exit 1
fi

echo "Restoring $PROFILE from $TAR"
read -r -p "Type yes to continue: " ok; [ "$ok" = yes ] || exit 1
mv "$PROFILE" "$PROFILE.replaced-$(date +%s)"
tar -xzf "$TAR" -C "$(dirname "$PROFILE")"
echo "Restored. (Previous state kept as $PROFILE.replaced-*)"
