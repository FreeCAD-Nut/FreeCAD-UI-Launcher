#!/usr/bin/env sh
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

if command -v python3 >/dev/null 2>&1; then
    exec python3 "UI_Launcher.py" --launch-as-creator
elif command -v python >/dev/null 2>&1; then
    exec python "UI_Launcher.py" --launch-as-creator
else
    echo "Python was not found in PATH." >&2
    exit 1
fi
