# FreeCAD UI Launcher

Cross-platform FreeCAD launcher for loading themes, packaging `.fctheme` files, and distributing custom FreeCAD experiences.

## Repository layout

- `Python_App/` — launcher source, bundled assets, and local Python run helpers
- `Executable/` — platform-specific build scripts and output locations for standalone binaries
- `.github/workflows/` — GitHub Actions workflows for building artifacts on GitHub-hosted runners

## Expected build artifacts

- `Executable/Windows/UI_Launcher.exe`
- `Executable/Linux/UI_Launcher.AppImage`
- `Executable/macOS/UI_Launcher.app`
- `Executable/macOS/UI_Launcher_Intel.app`

Generated build outputs are ignored by `.gitignore` and should be downloaded from GitHub Actions artifacts or attached to GitHub Releases instead of being committed into the repository.

## Notes

- `Python_App/run_UI_Launcher.bat` and `Python_App/run_UI_Launcher.sh` are kept for source-based local runs.
- The older `Launch_FreeCAD_as_User` / `Launch_FreeCAD_as_Creator` helper scripts are not used by the new shortcut-target logic anymore, but they are still kept in the repo for now as optional legacy helpers.

## License

This repository is licensed under the GNU Lesser General Public License v2.1 or later (LGPL-2.1-or-later). Theme packages and artwork distributed with the launcher can use their own separate license terms.
