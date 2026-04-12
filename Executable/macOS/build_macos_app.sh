#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
SOURCE_DIR="$ROOT_DIR/Python_App"
WORK_DIR="$SCRIPT_DIR/build_work"
VENV_DIR="$WORK_DIR/.venv"
DIST_DIR="$WORK_DIR/dist"
BUILD_DIR="$WORK_DIR/build"
SPEC_DIR="$WORK_DIR/spec"
OUTPUT_NAME="${OUTPUT_APP_NAME:-UI_Launcher.app}"
OUTPUT_APP="$SCRIPT_DIR/$OUTPUT_NAME"

mkdir -p "$WORK_DIR"
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install pyinstaller cryptography

rm -rf "$DIST_DIR" "$BUILD_DIR" "$SPEC_DIR" "$OUTPUT_APP"

pyinstaller   --noconfirm   --clean   --windowed   --name UI_Launcher   --distpath "$DIST_DIR"   --workpath "$BUILD_DIR"   --specpath "$SPEC_DIR"   --icon "$SOURCE_DIR/Default_Shortcut_Icons/Shortcut.icns"   --add-data "$SOURCE_DIR/Default_Shortcut_Icons:Default_Shortcut_Icons"   --add-data "$SOURCE_DIR/CC_Licenses:CC_Licenses"   "$SOURCE_DIR/UI_Launcher.py"

cp -a "$DIST_DIR/UI_Launcher.app" "$OUTPUT_APP"
echo "Built: $OUTPUT_APP"
