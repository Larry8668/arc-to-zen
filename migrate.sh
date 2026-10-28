#!/bin/bash
# One-shot: snapshot Arc (read-only) -> build plan -> dry run -> confirm -> apply to Zen.
set -euo pipefail
cd "$(dirname "$0")"

[ "$(uname)" = Darwin ] || { echo "macOS only." >&2; exit 1; }
[ -d "$HOME/Library/Application Support/Arc" ] || { echo "Arc data not found." >&2; exit 1; }
[ -d "$HOME/Library/Application Support/zen/Profiles" ] || {
  echo "No Zen profile yet: install Zen, open it once, then quit it." >&2; exit 1; }

./scripts/01_snapshot_arc.sh
python3 -I scripts/02_build_plan.py
python3 -I scripts/03_apply_to_zen.py

echo
echo "Review out/preview.txt above. Edit out/plan.json to rename/drop things, then re-run step 3 if you do."
read -r -p "Quit Zen (Cmd+Q), then type 'apply' to write this into Zen: " ok
[ "$ok" = apply ] || { echo "Not applied."; exit 0; }
python3 -I scripts/03_apply_to_zen.py --apply
echo
echo "Next (optional): history via scripts/04_history_shim.py, passwords and extensions; see README."
