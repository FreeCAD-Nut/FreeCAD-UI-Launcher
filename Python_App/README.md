# UI Launcher

Cross-platform Python launcher for FreeCAD on Windows, macOS, and Linux.

## What it does

- lets you select the FreeCAD executable
- lets you select a single **Theme Folder**
- if the Theme Folder contains a `.cfg` file, the launcher treats it as `user.cfg`
- if the Theme Folder contains a `.qss` file, the launcher treats it as the stylesheet to apply
- if the Theme Folder contains `freecadsplash.png`, the launcher treats it as the custom splash image
- if the Theme Folder contains icon files directly, or inside `icons/`, `Icons/`, `images/`, or `Images/`, the launcher can expose that location as FreeCAD's external icon theme
- creates a runtime copy of the detected `.cfg`
- writes the detected `.qss` path into `Preferences/MainWindow/StyleSheet` in that runtime copy
- launches FreeCAD with `--user-cfg` pointing to the runtime copy
- uses a runtime `FREECAD_USER_HOME` when needed so the splash override works without modifying your default FreeCAD files
- writes a helper macro named `ReloadExternalIconTheme.FCMacro` into the runtime Macro folder when a runtime user-home is used
- creates shortcuts that point directly to the current launcher entry point with `--launch-as-user` or `--launch-as-creator`

Your default FreeCAD configuration is not overwritten.

## Platform-specific FreeCAD selection

- **Windows:** browse to `FreeCAD.exe`
- **macOS:** browse to `FreeCAD.app`; the launcher resolves the real executable inside the app bundle
- **Linux:** browse to `FreeCAD.AppImage`; the launcher uses the selected AppImage as the launch target and makes it executable when needed

## Theme Folder layout

Minimum:

```text
MyTheme/
  user.cfg
```

Optional stylesheet, splash image, and icons:

```text
MyTheme/
  user.cfg
  theme.qss
  freecadsplash.png
  icons/
    Std_Save.svg
    Tree_Part.svg
```

You can also place icon files directly in the Theme Folder itself.

The launcher does not require the files to be named exactly `user.cfg` or `theme.qss`.
If it finds any `.cfg` file in the Theme Folder, it will use it as `user.cfg`.
If it finds any `.qss` file in the Theme Folder, it will use it as the stylesheet.

If there are multiple `.cfg` or `.qss` files, the launcher will pick one automatically and show that in the Status panel.

## External icon theme integration

When **Enable external icon theme from the selected Theme Folder** is checked, the launcher sets these environment variables before launching FreeCAD:

- `FREECAD_EXTERNAL_ICON_THEME`
- `FREECAD_EXTERNAL_ICON_THEME_ENABLED`
- `FREECAD_EXTERNAL_ICON_THEME_PREFER_EXTERNAL`

That is meant for a patched FreeCAD build where `BitmapFactory` supports external icon themes.

After you edit icon files while FreeCAD is already running, reload them from the Python console with:

```python
import FreeCADGui as Gui
Gui.reloadExternalIconTheme()
```

If the launcher used a runtime `FREECAD_USER_HOME`, it also writes this helper macro:

```text
<Theme Folder>/.UI_Launcher_runtime/user_home/Macro/ReloadExternalIconTheme.FCMacro
```

## Run

### Windows

Double-click:

```text
run_UI_Launcher.bat
```

### macOS / Linux

Run:

```bash
python3 UI_Launcher.py
```

or:

```bash
./run_UI_Launcher.sh
```

## Notes

- This launcher is Python-based and requires Python 3 with Tkinter available.
- `cryptography` is required for Author Key, Export Theme, and Launch from Theme features.
- The launcher does not modify your default FreeCAD config unless you deliberately point it at that same folder.
- The runtime helper files are written under `<Theme Folder>/.UI_Launcher_runtime/`.
- `Gui.reloadExternalIconTheme()` is only available in a FreeCAD build that includes your new Python binding patch.
- In a frozen executable build, the launcher stores settings in the per-user application config location instead of next to the bundled executable.

## Splash image behavior

If `freecadsplash.png` is present in the Theme Folder, the launcher copies it to a runtime `Gui/Images/splash_image.png` location before launch. That matches the FreeCAD user-home override pattern for custom splash images.
