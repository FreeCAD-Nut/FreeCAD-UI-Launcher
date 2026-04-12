# Standalone executable builds

This folder contains the platform-specific build scripts used locally or from GitHub Actions.

## Outputs

- `Windows/UI_Launcher.exe`
- `Linux/UI_Launcher.AppImage`
- `macOS/UI_Launcher.app`
- `macOS/UI_Launcher_Intel.app`

## Notes

- Temporary build folders such as `build_work/`, `dist/`, `build/`, and `spec/` are ignored by the repository `.gitignore`.
- The Linux script can use `APPIMAGETOOL_PATH` when the workflow downloads `appimagetool` instead of relying on a globally installed copy.
