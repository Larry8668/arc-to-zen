#!/bin/bash
# Copy the Arc data we need into ./snapshot/<timestamp>/ so every later step
# works on copies. This script ONLY READS from Arc's directory: the sole
# operations against Arc paths are `cp` (source side) and `ls`.
#
# Deliberately NOT copied: Cookies, Login Data, Web Data (cards/autofill) —
# they're encrypted with Arc's keychain key; passwords go via Arc's own CSV
# export instead (see README).
set -euo pipefail

ARC="$HOME/Library/Application Support/Arc"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$HERE/snapshot/$(date +%Y%m%d-%H%M%S)"

# Refuse to ever write inside Arc's tree.
case "$OUT" in "$ARC"*) echo "refusing: output inside Arc dir" >&2; exit 1;; esac

mkdir -p "$OUT/user-data"
umask 077

# Top-level Arc JSON state (spaces, pinned tabs, folders, favourites, windows)
for f in StorableSidebar.json StorableWindows.json StorableSessionRestorationData.json StorableArchiveItems.json; do
  [ -f "$ARC/$f" ] && cp -p "$ARC/$f" "$OUT/"
done
cp -p "$ARC/User Data/Local State" "$OUT/user-data/"

# Per-profile: history (+favicons) and prefs. Copy each db with its journal so
# the copy is transactionally consistent; any rollback then happens on the copy.
for P in "$ARC/User Data"/Default "$ARC/User Data"/Profile\ *; do
  [ -d "$P" ] || continue
  name="$(basename "$P")"
  mkdir -p "$OUT/user-data/$name"
  for f in History History-journal Favicons Favicons-journal Top\ Sites Preferences; do
    [ -f "$P/$f" ] && cp -p "$P/$f" "$OUT/user-data/$name/"
  done
  # Extension manifests only (to list what to reinstall), not extension code/data
  if [ -d "$P/Extensions" ]; then
    for m in "$P/Extensions"/*/*/manifest.json; do
      [ -f "$m" ] || continue
      id="$(basename "$(dirname "$(dirname "$m")")")"
      mkdir -p "$OUT/user-data/$name/ext-manifests"
      cp -p "$m" "$OUT/user-data/$name/ext-manifests/$id.json"
    done
  fi
done

chmod -R go-rwx "$OUT"
ln -sfn "$(basename "$OUT")" "$HERE/snapshot/latest"  # relative: survives moving the folder
echo "Snapshot written to: $OUT"
du -sh "$OUT"
