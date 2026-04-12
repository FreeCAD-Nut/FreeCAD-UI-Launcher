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
APPDIR="$WORK_DIR/AppDir"
OUTPUT="$SCRIPT_DIR/UI_Launcher.AppImage"
APPIMAGETOOL_BIN="${APPIMAGETOOL_PATH:-}"

mkdir -p "$WORK_DIR"
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install pyinstaller cryptography

rm -rf "$DIST_DIR" "$BUILD_DIR" "$SPEC_DIR" "$APPDIR" "$OUTPUT"

pyinstaller   --noconfirm   --clean   --onedir   --windowed   --name UI_Launcher   --distpath "$DIST_DIR"   --workpath "$BUILD_DIR"   --specpath "$SPEC_DIR"   --add-data "$SOURCE_DIR/Default_Shortcut_Icons:Default_Shortcut_Icons"   --add-data "$SOURCE_DIR/CC_Licenses:CC_Licenses"   "$SOURCE_DIR/UI_Launcher.py"

mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -a "$DIST_DIR/UI_Launcher/." "$APPDIR/usr/bin/"
cp "$SOURCE_DIR/Default_Shortcut_Icons/Shortcut.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/UI_Launcher.png"

cat > "$APPDIR/AppRun" <<'APP_RUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/UI_Launcher" "$@"
APP_RUN
chmod +x "$APPDIR/AppRun"

cat > "$APPDIR/UI_Launcher.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=UI Launcher
Exec=UI_Launcher
Icon=UI_Launcher
Terminal=false
Categories=Graphics;Engineering;
DESKTOP

if [[ -z "$APPIMAGETOOL_BIN" ]] && command -v appimagetool >/dev/null 2>&1; then
  APPIMAGETOOL_BIN="$(command -v appimagetool)"
fi

if [[ -n "$APPIMAGETOOL_BIN" ]] && [[ -x "$APPIMAGETOOL_BIN" ]]; then
  ARCH=x86_64 "$APPIMAGETOOL_BIN" "$APPDIR" "$OUTPUT"
  echo "Built: $OUTPUT"
else
  echo "appimagetool was not found."
  echo "The AppDir is ready here: $APPDIR"
  echo "Provide APPIMAGETOOL_PATH or install appimagetool, then run:"
  echo "  ARCH=x86_64 appimagetool "$APPDIR" "$OUTPUT""
fi
