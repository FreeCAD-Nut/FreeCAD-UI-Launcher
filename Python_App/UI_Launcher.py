#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UI Launcher
Cross-platform (Windows / macOS / Linux)

What it does:
- Lets the user choose a FreeCAD executable.
- Lets the user choose a Theme Folder.
- If the Theme Folder contains a .cfg file, it is treated as user.cfg.
- If the Theme Folder contains a .qss file, it is treated as the stylesheet to apply.
- If the Theme Folder contains freecadsplash.png, it is treated as the splash image override.
- If the Theme Folder contains icon files, or icons/ / Icons/ / images/ / Images/ folders,
  it can be used as FreeCAD's external icon theme source.
- Launches FreeCAD with --user-cfg pointing to a runtime copy of that .cfg file.
- Redirects FREECAD_USER_HOME to a runtime user-home when needed for splash support and helper macro support.
- Saves launcher settings in a local JSON file next to this script.

This avoids overwriting the user's default FreeCAD configuration.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import platform
import re
import secrets
import shlex
import shutil
import subprocess
import tempfile
import textwrap
import sys
import time
import tkinter as tk
from datetime import datetime, timezone
from dataclasses import asdict, dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import zipfile
import xml.etree.ElementTree as ET
from typing import Callable

APP_NAME = "UI Launcher"
APP_VERSION = "1.50.7"
SETTINGS_FILE = "UI_Launcher_settings.json"
RUNTIME_DIR_NAME = ".UI_Launcher_runtime"
DEFAULT_SHORTCUT_ICONS_DIR_NAME = "Default_Shortcut_Icons"
CC_LICENSES_DIR_NAME = "CC_Licenses"
LICENSE_FILE_NAME = "License.lic"
CUSTOM_LICENSE_OPTION = "Custom License"
DEFAULT_LICENSE_NOTICE_BRIEF = 'Unless otherwise stated, the original icons, splash screens, images, and other artwork included in this *.fctheme package are subject to the terms of the included license'
DEFAULT_LICENSE_NOTICE = """License Notice

This package may contain materials under different licenses.

Unless otherwise stated, the original icons, splash screens, images, and other artwork included in this *.fctheme package are subject to the terms of the included license.

Stylesheets, FreeCAD configuration files, scripts, and other code-like files are not covered by the included license unless explicitly stated in the relevant file, folder, or accompanying notice.

Any third-party materials included in this package remain subject to their own respective license terms."""
LICENSE_PRESET_DETAILS = {
    "CC BY-ND 4.0": {
        "filename": "CC BY-ND 4.0.lic",
        "brief": "Credit must be given to the creator. No derivatives or adaptations of the licensed work are permitted.",
    },
    "CC BY-SA 4.0": {
        "filename": "CC BY-SA 4.0.lic",
        "brief": "Credit must be given to the creator. Adaptations must be shared under the same license terms.",
    },
    "CC_BY_4.0": {
        "filename": "CC_BY_4.0.lic",
        "brief": "Credit must be given to the creator.",
    },
    "CC_BY-NC_4.0": {
        "filename": "CC_BY-NC_4.0.lic",
        "brief": "Credit must be given to the creator. Only noncommercial use of the licensed work is permitted.",
    },
    "CC_BY-NC-ND_4.0": {
        "filename": "CC_BY-NC-ND_4.0.lic",
        "brief": "Credit must be given to the creator. Only noncommercial use of the licensed work is permitted. No derivatives or adaptations of the licensed work are permitted.",
    },
    "CC_BY-NC-SA_4.0": {
        "filename": "CC_BY-NC-SA_4.0.lic",
        "brief": "Credit must be given to the creator. Only noncommercial use of the licensed work is permitted. Adaptations must be shared under the same license terms.",
    },
}
WINDOW_WIDTH = 600
WINDOW_HEIGHT = 700
RELOAD_MACRO_NAME = "ReloadExternalIconTheme.FCMacro"
SUPPORTED_ICON_EXTENSIONS = {".svg", ".png", ".xpm", ".ico", ".icns"}
EXPORTABLE_THEME_EXTENSIONS = {".svg", ".png", ".qss", ".cfg", ".ico", ".icns", ".lic"}
THEME_PACKAGE_TYPE = "freecad_ui_theme"
THEME_SCHEMA_VERSION = "1.0"
THEME_PAYLOAD_ENCRYPTION = "launcher_v1"
THEME_PACKAGE_EXTENSION = ".fctheme"


def _is_frozen_app() -> bool:
    return bool(getattr(sys, "frozen", False))


def _resource_base_dir() -> Path:
    if _is_frozen_app():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass).resolve()
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _launcher_entry_path() -> Path:
    if _is_frozen_app():
        return Path(sys.executable).resolve()
    return Path(__file__).resolve()


def _settings_storage_path(base_dir: Path) -> Path:
    if _is_frozen_app():
        return _app_config_base_dir() / SETTINGS_FILE
    return base_dir / SETTINGS_FILE


def _resolve_macos_app_executable(app_path: Path) -> Path | None:
    contents_macos = app_path / "Contents" / "MacOS"
    preferred_names = ["FreeCAD", "freecad"]
    for name in preferred_names:
        candidate = contents_macos / name
        if candidate.exists() and candidate.is_file():
            return candidate
    if contents_macos.exists() and contents_macos.is_dir():
        for child in sorted(contents_macos.iterdir(), key=lambda p: p.name.lower()):
            if child.is_file() and os.access(child, os.X_OK):
                return child
    return None


def _normalize_freecad_executable_path(path_text: str | Path | None) -> Path | None:
    if path_text is None:
        return None
    raw_text = str(path_text).strip()
    if not raw_text:
        return None
    candidate = Path(raw_text).expanduser()
    if platform.system().lower() == "darwin" and candidate.suffix.lower() == ".app":
        resolved = _resolve_macos_app_executable(candidate)
        return resolved if resolved is not None else candidate
    return candidate


def _ensure_linux_appimage_executable(appimage_path: Path) -> None:
    try:
        mode = appimage_path.stat().st_mode
        if not (mode & 0o111):
            appimage_path.chmod(mode | 0o111)
    except Exception:
        pass


def _is_linux_appimage_path(path: Path | str | None) -> bool:
    if path is None:
        return False
    try:
        return str(path).lower().endswith('.appimage')
    except Exception:
        return False


def _shell_join(parts: list[str]) -> str:
    if platform.system().lower() == "windows":
        return subprocess.list2cmdline(parts)
    return " ".join(shlex.quote(part) for part in parts)


def _desktop_exec_escape(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\"')
    return f'"{escaped}"'



def _applescript_quote(value: str) -> str:
    return '"' + value.replace('\', '\\').replace('"', '\"') + '"'


def _run_macos_osascript(lines: list[str]) -> str | None:
    try:
        command = ["/usr/bin/osascript"]
        for line in lines:
            command.extend(["-e", line])
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except Exception:
        return None
    if result.returncode != 0:
        stderr_text = (result.stderr or "").strip().lower()
        if "user canceled" in stderr_text:
            return ""
        return None
    return (result.stdout or "").strip()


def _macos_choose_application_path(prompt: str, title: str) -> str | None:
    return _run_macos_osascript([
        f"set selectedApp to choose application with title {_applescript_quote(title)} with prompt {_applescript_quote(prompt)} as alias",
        "return POSIX path of selectedApp",
    ])


def _macos_choose_folder_path(prompt: str, default_location: str | None = None) -> str | None:
    command = f"set selectedFolder to choose folder with prompt {_applescript_quote(prompt)}"
    if default_location:
        command += f" default location (POSIX file {_applescript_quote(default_location)})"
    command += " showing package contents false"
    return _run_macos_osascript([command, "return POSIX path of selectedFolder"])


def _macos_choose_file_path(prompt: str, default_location: str | None = None) -> str | None:
    command = f"set selectedFile to choose file with prompt {_applescript_quote(prompt)}"
    if default_location:
        command += f" default location (POSIX file {_applescript_quote(default_location)})"
    command += " showing package contents false"
    return _run_macos_osascript([command, "return POSIX path of selectedFile"])

RELOAD_MACRO_CONTENT = """import FreeCADGui as Gui\nGui.reloadExternalIconTheme()\n"""
RELOAD_CONSOLE_COMMAND = "import FreeCADGui as Gui\nGui.reloadExternalIconTheme()"


@dataclass
class AppSettings:
    freecad_executable: str = ""
    theme_folder: str = ""
    theme_file: str = ""
    launch_mode: str = "user"
    use_freecad_user_home: bool = True
    enable_external_icon_theme: bool = True
    prefer_external_icons: bool = True
    close_after_freecad_launch: bool = True
    extra_cli_args: str = ""
    author_key_file: str = ""
    export_theme_name: str = ""
    export_theme_version: str = "1.0.0"
    export_author_name: str = ""
    export_freecad_version_tested: str = ""
    export_description: str = ""
    export_copyright: str = ""
    export_license: str = CUSTOM_LICENSE_OPTION
    export_license_terms: str = ""
    export_license_notice_brief: str = DEFAULT_LICENSE_NOTICE_BRIEF
    export_license_notice: str = DEFAULT_LICENSE_NOTICE


def _slugify_theme_id(theme_name: str) -> str:
    value = theme_name.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value


def _canonical_manifest_bytes(manifest: dict[str, object]) -> bytes:
    return json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _payload_fernet_key() -> bytes:
    return base64.urlsafe_b64encode(hashlib.sha256(b"UI Launcher Theme Payload Key v1").digest())


def _count_suffixes(paths: list[str]) -> dict[str, int]:
    counts = {".svg": 0, ".png": 0, ".qss": 0, ".cfg": 0}
    for rel in paths:
        suffix = Path(rel).suffix.lower()
        if suffix in counts:
            counts[suffix] += 1
    return counts


def _cc_licenses_dir(base_dir: Path) -> Path:
    return base_dir / CC_LICENSES_DIR_NAME


def _license_options_for_dir(base_dir: Path) -> list[str]:
    license_dir = _cc_licenses_dir(base_dir)
    available = {path.stem for path in license_dir.glob('*.lic') if path.is_file()}
    ordered = [name for name in LICENSE_PRESET_DETAILS if name in available]
    extras = sorted(available - set(ordered), key=str.lower)
    return ordered + extras + [CUSTOM_LICENSE_OPTION]


def _license_source_path(base_dir: Path, license_choice: str) -> Path | None:
    if license_choice == CUSTOM_LICENSE_OPTION:
        return None
    details = LICENSE_PRESET_DETAILS.get(license_choice)
    if not details:
        candidate = _cc_licenses_dir(base_dir) / f"{license_choice}.lic"
        return candidate if candidate.exists() else None
    candidate = _cc_licenses_dir(base_dir) / details["filename"]
    return candidate if candidate.exists() else None


def _default_license_brief_for_choice(license_choice: str) -> str:
    details = LICENSE_PRESET_DETAILS.get(license_choice)
    if details:
        return str(details.get("brief", ""))
    return ""


def _top_level_theme_license_relpath(theme_folder: Path) -> str:
    candidate = theme_folder / LICENSE_FILE_NAME
    if candidate.exists() and candidate.is_file():
        return LICENSE_FILE_NAME
    return ""


def _effective_export_file_list(scan: dict[str, object], theme_folder: Path, license_choice: str) -> list[str]:
    included_files = list(scan.get("included_files", []))
    if license_choice == CUSTOM_LICENSE_OPTION:
        custom_rel = _top_level_theme_license_relpath(theme_folder)
        if custom_rel and custom_rel not in included_files:
            included_files.append(custom_rel)
    elif license_choice and license_choice != CUSTOM_LICENSE_OPTION:
        if LICENSE_FILE_NAME not in included_files:
            included_files.append(LICENSE_FILE_NAME)
    return sorted(set(included_files), key=str.lower)


def _detect_existing_license_choice(base_dir: Path, theme_folder: Path) -> str:
    license_path = theme_folder / LICENSE_FILE_NAME
    if not license_path.exists() or not license_path.is_file():
        return CUSTOM_LICENSE_OPTION
    try:
        current_bytes = license_path.read_bytes()
    except Exception:
        return CUSTOM_LICENSE_OPTION
    for option, details in LICENSE_PRESET_DETAILS.items():
        source_path = _cc_licenses_dir(base_dir) / details["filename"]
        try:
            if source_path.exists() and source_path.read_bytes() == current_bytes:
                return option
        except Exception:
            continue
    return CUSTOM_LICENSE_OPTION


def _detect_splash_relpath(paths: list[str]) -> str:
    preferred_exact = {"freecadsplash.png", "splash_image.png"}
    exact_matches = [rel for rel in paths if Path(rel).name.lower() in preferred_exact]
    if exact_matches:
        return sorted(exact_matches, key=lambda rel: rel.lower())[0]
    named_matches = [
        rel for rel in paths
        if Path(rel).suffix.lower() == ".png" and "splash" in Path(rel).stem.lower()
    ]
    if named_matches:
        return sorted(named_matches, key=lambda rel: rel.lower())[0]
    return ""


def _is_safe_relpath(rel: str) -> bool:
    if not rel or rel.startswith("/") or rel.startswith("\\"):
        return False
    pure = Path(rel)
    if pure.is_absolute():
        return False
    parts = pure.parts
    if any(part == ".." for part in parts):
        return False
    if ":" in rel:
        return False
    return True


def _app_config_base_dir() -> Path:
    system = platform.system().lower()
    if system == "windows":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    if system == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / APP_NAME
    return Path.home() / ".config" / APP_NAME


def _theme_user_cfg_path(theme_id: str) -> Path:
    return _app_config_base_dir() / "Themes" / theme_id / "user.cfg"


def _make_obscured_temp_dir() -> Path:
    path = Path(tempfile.gettempdir()) / f".uix_{secrets.token_hex(8)}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def _is_safe_temporary_cleanup_dir(path: Path | None) -> bool:
    if path is None:
        return False
    try:
        resolved = path.resolve()
        temp_root = Path(tempfile.gettempdir()).resolve()
    except Exception:
        return False
    if not resolved.exists() or not resolved.is_dir():
        return False
    if resolved == temp_root:
        return False
    try:
        resolved.relative_to(temp_root)
    except ValueError:
        return False
    return resolved.name.startswith(".uix_")


def _safe_rmtree(path: Path | None) -> bool:
    if not _is_safe_temporary_cleanup_dir(path):
        return False
    shutil.rmtree(path, ignore_errors=True)
    return True


def _require_crypto():
    try:
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
        return Fernet, serialization, Ed25519PrivateKey, Ed25519PublicKey
    except Exception as exc:
        raise LauncherError("The Python package 'cryptography' is required for Author Key, Export Theme, and Launch from Theme features.") from exc


def _load_author_private_key(private_key_path: Path):
    Fernet, serialization, Ed25519PrivateKey, Ed25519PublicKey = _require_crypto()
    private_key = serialization.load_pem_private_key(private_key_path.read_bytes(), password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise LauncherError("The selected Author Key is not an Ed25519 private key.")
    public_key = private_key.public_key()
    public_bytes_raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    fingerprint_hex = public_bytes_raw.hex().upper()
    fingerprint = "-".join(fingerprint_hex[i:i + 4] for i in range(0, min(len(fingerprint_hex), 32), 4))
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_key, public_pem, fingerprint


def _verify_signature(manifest: dict[str, object], public_pem: bytes, signature_b64: str) -> None:
    Fernet, serialization, Ed25519PrivateKey, Ed25519PublicKey = _require_crypto()
    public_key = serialization.load_pem_public_key(public_pem)
    if not isinstance(public_key, Ed25519PublicKey):
        raise LauncherError("Theme package public key is not a valid Ed25519 public key.")
    signature = base64.b64decode(signature_b64.encode("ascii"))
    public_key.verify(signature, _canonical_manifest_bytes(manifest))


def _encrypt_payload(payload_bytes: bytes) -> bytes:
    Fernet, serialization, Ed25519PrivateKey, Ed25519PublicKey = _require_crypto()
    return Fernet(_payload_fernet_key()).encrypt(payload_bytes)


def _decrypt_payload(payload_bytes: bytes) -> bytes:
    Fernet, serialization, Ed25519PrivateKey, Ed25519PublicKey = _require_crypto()
    return Fernet(_payload_fernet_key()).decrypt(payload_bytes)



class LauncherError(Exception):
    pass


class CollapsibleSection(ttk.Frame):
    def __init__(self, parent, title: str, expanded: bool = False, on_toggle=None, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self._expanded = expanded
        self._title = title
        self._on_toggle = on_toggle
        self.columnconfigure(0, weight=1)

        self.toggle_button = ttk.Button(self, text="", command=self.toggle)
        self.toggle_button.grid(row=0, column=0, sticky="ew")

        self.body = ttk.Frame(self, padding=(10, 8, 10, 10))
        self.body.grid(row=1, column=0, sticky="ew")
        self.body.columnconfigure(0, weight=1)

        self._sync()

    def toggle(self) -> None:
        self._expanded = not self._expanded
        self._sync()
        if self._on_toggle is not None:
            self._on_toggle()

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = bool(expanded)
        self._sync()
        if self._on_toggle is not None:
            self._on_toggle()

    def _sync(self) -> None:
        symbol = "▼" if self._expanded else "▶"
        self.toggle_button.configure(text=f"{symbol} {self._title}")
        if self._expanded:
            self.body.grid()
        else:
            self.body.grid_remove()


class ConfigXML:
    @staticmethod
    def _ensure_path(root: ET.Element, path_parts: list[str]) -> ET.Element:
        node = root
        for part in path_parts:
            found = None
            for child in node:
                if child.tag == "FCParamGroup" and child.attrib.get("Name") == part:
                    found = child
                    break
            if found is None:
                found = ET.SubElement(node, "FCParamGroup", {"Name": part})
            node = found
        return node

    @staticmethod
    def _set_string_param(group: ET.Element, name: str, value: str) -> None:
        for child in group:
            if child.attrib.get("Name") == name and child.tag in ("FCString", "FCText"):
                if child.tag == "FCText":
                    child.text = value
                    child.attrib.pop("Value", None)
                else:
                    child.attrib["Value"] = value
                return
        ET.SubElement(group, "FCString", {"Name": name, "Value": value})

    @staticmethod
    def _set_text_param(group: ET.Element, name: str, value: str) -> None:
        for child in group:
            if child.attrib.get("Name") == name and child.tag in ("FCText", "FCString"):
                if child.tag == "FCText":
                    child.text = value
                    child.attrib.pop("Value", None)
                else:
                    child.tag = "FCText"
                    child.attrib.pop("Value", None)
                    child.text = value
                return
        node = ET.SubElement(group, "FCText", {"Name": name})
        node.text = value

    @staticmethod
    def _remove_param(group: ET.Element, name: str) -> None:
        for child in list(group):
            if child.attrib.get("Name") == name:
                group.remove(child)

    @classmethod
    def write_runtime_user_cfg(
        cls,
        source_user_cfg: Path,
        destination_user_cfg: Path,
        stylesheet_text: str | None,
    ) -> None:
        if not source_user_cfg.exists():
            raise LauncherError(f"No .cfg file was found: {source_user_cfg}")

        try:
            tree = ET.parse(source_user_cfg)
            root = tree.getroot()
        except Exception as exc:
            raise LauncherError(
                f"Could not parse the .cfg file as XML:\n{source_user_cfg}\n\n{exc}"
            ) from exc

        group = cls._ensure_path(root, ["Preferences", "MainWindow"])
        if stylesheet_text:
            cls._set_text_param(group, "StyleSheet", stylesheet_text)
        cls._remove_param(group, "Theme")
        cls._remove_param(group, "ThemeStyleParametersFile")

        destination_user_cfg.parent.mkdir(parents=True, exist_ok=True)
        tree.write(destination_user_cfg, encoding="utf-8", xml_declaration=True)




def _path_to_file_uri(path: Path) -> str:
    return path.resolve().as_uri()




def _platform_shortcut_icon_suffix() -> str:
    system = platform.system().lower()
    if system == "windows":
        return ".ico"
    if system == "darwin":
        return ".icns"
    return ".png"


def _find_named_png(folder: Path, name_contains: str) -> Path | None:
    needle = name_contains.lower()
    matches = [
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() == ".png" and needle in p.stem.lower()
    ]
    if not matches:
        return None
    return sorted(matches, key=lambda p: p.name.lower())[0]


def _find_platform_shortcut_icon_in_folder(folder: Path) -> Path | None:
    system = platform.system().lower()
    if system == "linux":
        return _find_named_png(folder, "shortcut")
    wanted = _platform_shortcut_icon_suffix()
    matches = [
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() == wanted
    ]
    if not matches:
        return None
    return sorted(matches, key=lambda p: p.name.lower())[0]


def _find_theme_splash_png(folder: Path) -> Path | None:
    return _find_named_png(folder, "splash")


def _desktop_file_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n")


def _rewrite_qss_urls(qss_text: str, base_folder: Path) -> str:
    pattern = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)

    def repl(match: re.Match[str]) -> str:
        raw_target = match.group(2).strip()
        if not raw_target:
            return match.group(0)
        lower = raw_target.lower()
        if lower.startswith(("file:", "qrc:", ":", "http://", "https://", "data:")):
            return match.group(0)
        candidate = (base_folder / raw_target).resolve()
        if not candidate.exists():
            return match.group(0)
        return f'url("{_path_to_file_uri(candidate)}")'

    return pattern.sub(repl, qss_text)


def _build_runtime_stylesheet(qss_path: Path) -> str:
    try:
        raw = qss_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raw = qss_path.read_text(encoding="utf-8-sig")
    return _rewrite_qss_urls(raw, qss_path.parent)


def _make_startup_stylesheet_script(script_path: Path, qss_text: str) -> Path:
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_text = f"""from __future__ import annotations
try:
    from PySide import QtCore, QtGui
except Exception:
    from PySide6 import QtCore, QtGui
import FreeCADGui as Gui
QSS_TEXT = {qss_text!r}

def _capture_toolbar_sizes(mw):
    saved_main = None
    try:
        size = mw.iconSize()
        saved_main = (size.width(), size.height())
    except Exception:
        saved_main = None
    saved_toolbars = []
    try:
        toolbars = mw.findChildren(QtGui.QToolBar)
    except Exception:
        toolbars = []
    for tb in toolbars:
        try:
            size = tb.iconSize()
            saved_toolbars.append((tb, size.width(), size.height()))
        except Exception:
            pass
    return saved_main, saved_toolbars

def _restore_toolbar_sizes(mw, saved_main, saved_toolbars):
    try:
        if saved_main and saved_main[0] > 0 and saved_main[1] > 0:
            mw.setIconSize(QtCore.QSize(saved_main[0], saved_main[1]))
    except Exception:
        pass
    for tb, width, height in saved_toolbars:
        try:
            if width > 0 and height > 0:
                tb.setIconSize(QtCore.QSize(width, height))
        except Exception:
            pass

def _apply_stylesheet() -> None:
    try:
        mw = Gui.getMainWindow()
    except Exception:
        QtCore.QTimer.singleShot(250, _apply_stylesheet)
        return
    if mw is None:
        QtCore.QTimer.singleShot(250, _apply_stylesheet)
        return
    try:
        saved_main, saved_toolbars = _capture_toolbar_sizes(mw)
        mw.setStyleSheet("")
        mw.setStyleSheet(QSS_TEXT)
        _restore_toolbar_sizes(mw, saved_main, saved_toolbars)
        QtCore.QTimer.singleShot(0, lambda: _restore_toolbar_sizes(mw, saved_main, saved_toolbars))
        QtCore.QTimer.singleShot(200, lambda: _restore_toolbar_sizes(mw, saved_main, saved_toolbars))
        QtCore.QTimer.singleShot(500, lambda: _restore_toolbar_sizes(mw, saved_main, saved_toolbars))
        Gui.updateGui()
    except Exception:
        QtCore.QTimer.singleShot(250, _apply_stylesheet)

QtCore.QTimer.singleShot(0, _apply_stylesheet)
"""
    script_path.write_text(script_text, encoding="utf-8")
    return script_path



class FreeCADLocator:
    @staticmethod
    def candidate_paths() -> list[Path]:
        system = platform.system().lower()
        candidates: list[Path] = []

        if system == "windows":
            env_vars = [
                os.environ.get("PROGRAMFILES"),
                os.environ.get("PROGRAMFILES(X86)"),
                os.environ.get("LOCALAPPDATA"),
            ]
            relative_paths = [
                Path("FreeCAD 1.1/bin/FreeCAD.exe"),
                Path("FreeCAD 1.0/bin/FreeCAD.exe"),
                Path("FreeCAD/bin/FreeCAD.exe"),
                Path("FreeCAD*/bin/FreeCAD.exe"),
            ]
            for base in env_vars:
                if not base:
                    continue
                base_path = Path(base)
                for rel in relative_paths:
                    if "*" in str(rel):
                        candidates.extend(base_path.glob(str(rel)))
                    else:
                        candidates.append(base_path / rel)
            for exe_name in ["FreeCAD.exe", "freecad.exe"]:
                found = shutil.which(exe_name)
                if found:
                    candidates.append(Path(found))

        elif system == "darwin":
            candidates.extend(
                [
                    Path("/Applications/FreeCAD.app/Contents/MacOS/FreeCAD"),
                    Path.home() / "Applications/FreeCAD.app/Contents/MacOS/FreeCAD",
                ]
            )
            for exe_name in ["FreeCAD", "freecad"]:
                found = shutil.which(exe_name)
                if found:
                    candidates.append(Path(found))

        else:
            candidates.extend(
                [
                    Path("/usr/bin/freecad"),
                    Path("/usr/local/bin/freecad"),
                    Path("/snap/bin/freecad"),
                    Path("/var/lib/flatpak/exports/bin/org.freecad.FreeCAD"),
                    Path.home() / ".local/bin/freecad",
                ]
            )
            for exe_name in ["freecad", "FreeCAD", "org.freecad.FreeCAD"]:
                found = shutil.which(exe_name)
                if found:
                    candidates.append(Path(found))

        unique: list[Path] = []
        seen: set[str] = set()
        for path in candidates:
            path_str = str(path)
            if path_str not in seen:
                seen.add(path_str)
                unique.append(path)
        return unique

    @classmethod
    def first_existing_candidate(cls) -> str:
        for path in cls.candidate_paths():
            if path.exists():
                return str(path)
        return ""


class ThemeFolderScanner:
    @staticmethod
    def find_first_file(folder: Path, suffix: str) -> Path | None:
        matches = sorted(
            [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == suffix.lower()],
            key=lambda p: p.name.lower(),
        )
        return matches[0] if matches else None

    @classmethod
    def find_cfg(cls, folder: Path) -> Path | None:
        preferred_names = ["user.cfg", "theme.cfg", "profile.cfg"]
        for name in preferred_names:
            candidate = folder / name
            if candidate.exists() and candidate.is_file():
                return candidate
        return cls.find_first_file(folder, ".cfg")

    @classmethod
    def find_qss(cls, folder: Path) -> Path | None:
        preferred_names = ["theme.qss", "style.qss", "stylesheet.qss"]
        for name in preferred_names:
            candidate = folder / name
            if candidate.exists() and candidate.is_file():
                return candidate
        return cls.find_first_file(folder, ".qss")

    @classmethod
    def find_splash(cls, folder: Path) -> Path | None:
        preferred_names = ["freecadsplash.png", "splash_image.png"]
        for name in preferred_names:
            candidate = folder / name
            if candidate.exists() and candidate.is_file():
                return candidate
        named_matches = [
            p for p in folder.iterdir()
            if p.is_file() and p.suffix.lower() == ".png" and "splash" in p.stem.lower()
        ]
        if named_matches:
            return sorted(named_matches, key=lambda p: p.name.lower())[0]
        return None

    @classmethod
    def find_external_icon_theme_root(cls, folder: Path) -> Path | None:
        preferred_names = ["icons", "Icons", "images", "Images"]
        for name in preferred_names:
            candidate = folder / name
            if candidate.exists() and candidate.is_dir() and cls.folder_contains_supported_icons(candidate):
                return candidate

        if cls.folder_contains_supported_icons(folder):
            return folder

        return None

    @staticmethod
    def folder_contains_supported_icons(folder: Path) -> bool:
        try:
            for child in folder.iterdir():
                if child.is_file() and child.suffix.lower() in SUPPORTED_ICON_EXTENSIONS:
                    return True
        except Exception:
            return False
        return False



class ExportThemeDialog(tk.Toplevel):
    def __init__(self, master: "ThemeLauncherApp", scan: dict[str, object]) -> None:
        super().__init__(master)
        self.master = master
        self.scan = scan
        self.title("Export Theme")
        self.transient(master)
        self.grab_set()
        self.resizable(True, True)
        self.minsize(860, 600)
        self.result: dict[str, str] | None = None
        self.vars: dict[str, object] = {}
        self._suppress_license_choice_events = False
        self._scroll_canvas: tk.Canvas | None = None
        self._scroll_inner: ttk.Frame | None = None
        self._scroll_window_id: int | None = None
        self._build_ui()
        self._populate_from_settings()
        self._refresh_summary()
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.update_idletasks()
        default_width = max(860, self.winfo_reqwidth())
        self.geometry(f"{default_width}x900")

    def _build_ui(self) -> None:
        shell = ttk.Frame(self)
        shell.pack(fill="both", expand=True)

        self._scroll_canvas = tk.Canvas(shell, highlightthickness=0)
        self._scroll_canvas.pack(side="left", fill="both", expand=True)

        vscroll = ttk.Scrollbar(shell, orient="vertical", command=self._scroll_canvas.yview)
        vscroll.pack(side="right", fill="y")
        self._scroll_canvas.configure(yscrollcommand=vscroll.set)

        outer = ttk.Frame(self._scroll_canvas, padding=12)
        self._scroll_inner = outer
        self._scroll_window_id = self._scroll_canvas.create_window((0, 0), window=outer, anchor="nw")

        outer.bind("<Configure>", self._on_export_dialog_content_configure)
        self._scroll_canvas.bind("<Configure>", self._on_export_dialog_canvas_configure)

        metadata = ttk.LabelFrame(outer, text="Theme Metadata", padding=10)
        metadata.pack(fill="x")
        self._add_entry_row(metadata, 0, "Theme Name", "theme_name")
        self._add_readonly_row(metadata, 1, "Theme ID", "theme_id")
        self._add_entry_row(metadata, 2, "Theme Version", "theme_version")
        self._add_entry_row(metadata, 3, "Author Name", "author_name")
        self._add_entry_row(metadata, 4, "FreeCAD Version Tested", "freecad_version_tested")
        self._add_path_row(metadata, 5, "Author Key", "author_key_file", self._browse_author_key, "Create Author Key", self._create_author_key)
        self._add_text_row(metadata, 6, "Description", "description", 4)
        self._add_text_row(metadata, 7, "Copyright", "copyright", 3)
        self._add_text_row(metadata, 8, "License Brief", "license_terms", 4)
        self._add_license_dropdown_row(metadata, 9, "License", "license")
        self._add_text_row(metadata, 10, "License Notice Brief", "license_notice_brief", 3)
        self._add_text_row(metadata, 11, "License Notice", "license_notice", 9)

        package = ttk.LabelFrame(outer, text="Auto-generated Package Info", padding=10)
        package.pack(fill="x", pady=(12, 0))
        self._add_readonly_row(package, 0, "Schema Version", "schema_version")
        self._add_readonly_row(package, 1, "Package Type", "package_type")
        self._add_readonly_row(package, 2, "Launcher Version", "launcher_version")
        self._add_readonly_row(package, 3, "Payload Encryption", "payload_encryption")
        self._add_readonly_row(package, 4, "Key Fingerprint", "key_fingerprint")

        summary = ttk.LabelFrame(outer, text="Theme Folder Summary", padding=10)
        summary.pack(fill="both", expand=True, pady=(12, 0))
        summary.columnconfigure(1, weight=1)
        self._add_readonly_row(summary, 0, "Theme Folder", "theme_folder")
        self._add_readonly_row(summary, 1, "Detected CFG", "detected_cfg")
        self._add_readonly_row(summary, 2, "SVG count", "svg_count")
        self._add_readonly_row(summary, 3, "PNG count", "png_count")
        self._add_readonly_row(summary, 4, "QSS count", "qss_count")
        self._add_readonly_row(summary, 5, "CFG count", "cfg_count")
        self._add_readonly_row(summary, 6, "Total included files", "total_files")

        ttk.Label(summary, text="Included files").grid(row=7, column=0, sticky="nw", padx=(0, 10), pady=(6, 4))
        files_frame = ttk.Frame(summary)
        files_frame.grid(row=7, column=1, columnspan=3, sticky="nsew", pady=(6, 4))
        summary.rowconfigure(7, weight=1)
        files_frame.rowconfigure(0, weight=1)
        files_frame.columnconfigure(0, weight=1)
        self.included_files = tk.Text(files_frame, height=10, wrap="none")
        self.included_files.grid(row=0, column=0, sticky="nsew")
        files_scroll = ttk.Scrollbar(files_frame, orient="vertical", command=self.included_files.yview)
        files_scroll.grid(row=0, column=1, sticky="ns")
        self.included_files.configure(yscrollcommand=files_scroll.set, state="disabled")

        ttk.Label(summary, text="Validation").grid(row=8, column=0, sticky="nw", padx=(0, 10), pady=(6, 4))
        validation_frame = ttk.Frame(summary)
        validation_frame.grid(row=8, column=1, columnspan=3, sticky="nsew", pady=(6, 4))
        validation_frame.rowconfigure(0, weight=1)
        validation_frame.columnconfigure(0, weight=1)
        self.validation_text = tk.Text(validation_frame, height=6, wrap="word")
        self.validation_text.grid(row=0, column=0, sticky="nsew")
        validation_scroll = ttk.Scrollbar(validation_frame, orient="vertical", command=self.validation_text.yview)
        validation_scroll.grid(row=0, column=1, sticky="ns")
        self.validation_text.configure(yscrollcommand=validation_scroll.set, state="disabled")

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text="Cancel", command=self._cancel).pack(side="right")
        ttk.Button(buttons, text="Validate", command=self._refresh_summary).pack(side="right", padx=(0, 8))
        ttk.Button(buttons, text="Export", command=self._export_clicked).pack(side="right", padx=(0, 8))

        self._bind_export_dialog_mousewheel_recursive(self)
        self._on_export_dialog_content_configure()

    def _on_export_dialog_content_configure(self, _event=None) -> None:
        if self._scroll_canvas is None:
            return
        self._scroll_canvas.configure(scrollregion=self._scroll_canvas.bbox("all"))

    def _on_export_dialog_canvas_configure(self, event) -> None:
        if self._scroll_canvas is None or self._scroll_window_id is None:
            return
        self._scroll_canvas.itemconfigure(self._scroll_window_id, width=event.width)

    def _on_export_dialog_mousewheel(self, event) -> str | None:
        if self._scroll_canvas is None:
            return None
        delta = getattr(event, "delta", 0)
        if delta:
            step = -1 if delta > 0 else 1
            self._scroll_canvas.yview_scroll(step, "units")
            return "break"
        num = getattr(event, "num", None)
        if num == 4:
            self._scroll_canvas.yview_scroll(-1, "units")
            return "break"
        if num == 5:
            self._scroll_canvas.yview_scroll(1, "units")
            return "break"
        return None

    def _bind_export_dialog_mousewheel_recursive(self, widget) -> None:
        widget.bind("<MouseWheel>", self._on_export_dialog_mousewheel, add="+")
        widget.bind("<Button-4>", self._on_export_dialog_mousewheel, add="+")
        widget.bind("<Button-5>", self._on_export_dialog_mousewheel, add="+")
        for child in widget.winfo_children():
            self._bind_export_dialog_mousewheel_recursive(child)

    def _add_entry_row(self, parent, row, label, key):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
        self.vars[key] = tk.StringVar(value="")
        entry = ttk.Entry(parent, textvariable=self.vars[key])
        entry.grid(row=row, column=1, columnspan=3, sticky="ew", pady=4)
        entry.bind("<KeyRelease>", lambda _e: self._refresh_summary())
        parent.columnconfigure(1, weight=1)

    def _add_readonly_row(self, parent, row, label, key):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
        self.vars[key] = tk.StringVar(value="")
        entry = ttk.Entry(parent, textvariable=self.vars[key], state="readonly")
        entry.grid(row=row, column=1, columnspan=3, sticky="ew", pady=4)
        parent.columnconfigure(1, weight=1)

    def _add_path_row(self, parent, row, label, key, browse_command, extra_button_text, extra_button_command):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
        self.vars[key] = tk.StringVar(value="")
        entry = ttk.Entry(parent, textvariable=self.vars[key])
        entry.grid(row=row, column=1, sticky="ew", pady=4)
        entry.bind("<KeyRelease>", lambda _e: self._refresh_summary())
        ttk.Button(parent, text="Browse", command=browse_command).grid(row=row, column=2, sticky="ew", padx=(8, 0), pady=4)
        ttk.Button(parent, text=extra_button_text, command=extra_button_command).grid(row=row, column=3, sticky="ew", padx=(8, 0), pady=4)
        parent.columnconfigure(1, weight=1)

    def _add_license_dropdown_row(self, parent, row, label, key):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
        options = _license_options_for_dir(self.master.base_dir)
        self.vars[key] = tk.StringVar(value=options[0] if options else CUSTOM_LICENSE_OPTION)
        combo = ttk.Combobox(parent, textvariable=self.vars[key], values=options, state="readonly")
        combo.grid(row=row, column=1, columnspan=3, sticky="ew", pady=4)
        combo.bind("<<ComboboxSelected>>", self._on_license_choice_changed)
        parent.columnconfigure(1, weight=1)

    def _add_text_row(self, parent, row, label, key, height):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="nw", padx=(0, 10), pady=(6, 4))
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=1, columnspan=3, sticky="nsew", pady=(6, 4))
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        widget = tk.Text(frame, height=height, wrap="word")
        widget.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=widget.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        widget.configure(yscrollcommand=scroll.set)
        widget.bind("<KeyRelease>", lambda _e: self._refresh_summary())
        self.vars[key] = widget
        parent.columnconfigure(1, weight=1)

    def _set_text_widget(self, key, value):
        widget = self.vars[key]
        widget.delete("1.0", "end")
        widget.insert("1.0", value)

    def _get_text_widget(self, key):
        return self.vars[key].get("1.0", "end").strip()

    def _current_theme_folder_path(self) -> Path:
        return Path(str(self.scan.get("theme_folder", "") or "")).expanduser()

    def _apply_license_choice_defaults(self, license_choice: str) -> None:
        if license_choice == CUSTOM_LICENSE_OPTION:
            self._set_text_widget("license_terms", "")
            return
        self._set_text_widget("license_terms", _default_license_brief_for_choice(license_choice))

    def _on_license_choice_changed(self, _event=None) -> None:
        if self._suppress_license_choice_events:
            return
        license_choice = self.vars["license"].get().strip()
        self._apply_license_choice_defaults(license_choice)
        self._refresh_summary()

    def _populate_from_settings(self):
        s = self.master.settings
        self.vars["theme_name"].set(s.export_theme_name)
        self.vars["theme_version"].set(s.export_theme_version)
        self.vars["author_name"].set(s.export_author_name)
        self.vars["freecad_version_tested"].set(s.export_freecad_version_tested)
        self.vars["author_key_file"].set(s.author_key_file)
        self._set_text_widget("description", s.export_description)
        self._set_text_widget("copyright", s.export_copyright)
        self._suppress_license_choice_events = True
        license_options = _license_options_for_dir(self.master.base_dir)
        saved_license = str(getattr(s, "export_license", CUSTOM_LICENSE_OPTION) or CUSTOM_LICENSE_OPTION)
        if saved_license not in license_options:
            saved_license = CUSTOM_LICENSE_OPTION
        self.vars["license"].set(saved_license)
        self._suppress_license_choice_events = False
        license_brief = str(getattr(s, "export_license_terms", "") or "")
        if not license_brief and saved_license != CUSTOM_LICENSE_OPTION:
            license_brief = _default_license_brief_for_choice(saved_license)
        self._set_text_widget("license_terms", license_brief)
        self._set_text_widget("license_notice_brief", str(getattr(s, "export_license_notice_brief", DEFAULT_LICENSE_NOTICE_BRIEF) or DEFAULT_LICENSE_NOTICE_BRIEF))
        self._set_text_widget("license_notice", str(getattr(s, "export_license_notice", DEFAULT_LICENSE_NOTICE) or DEFAULT_LICENSE_NOTICE))
        self.vars["schema_version"].set(THEME_SCHEMA_VERSION)
        self.vars["package_type"].set(THEME_PACKAGE_TYPE)
        self.vars["launcher_version"].set(APP_VERSION)
        self.vars["payload_encryption"].set(THEME_PAYLOAD_ENCRYPTION)
        self.vars["theme_folder"].set(str(self.scan.get("theme_folder", "")))
        self.vars["detected_cfg"].set(str(self.scan.get("detected_cfg", "")))

    def _browse_author_key(self):
        current = self.vars["author_key_file"].get().strip()
        initialdir = str(Path(current).expanduser().parent) if current else str(Path.home())
        path = filedialog.askopenfilename(parent=self, title="Select Author Key", initialdir=initialdir, filetypes=[("PEM files", "*.pem"), ("All files", "*.*")])
        if path:
            self.vars["author_key_file"].set(path)
            self._refresh_summary()

    def _create_author_key(self):
        author_name = self.vars["author_name"].get().strip()
        if not author_name:
            messagebox.showerror(APP_NAME, "Author Name is required before creating an Author Key.", parent=self)
            return
        path = filedialog.asksaveasfilename(parent=self, title="Create Author Key", defaultextension=".pem", initialfile=f"{_slugify_theme_id(author_name) or 'author'}_private.pem", filetypes=[("PEM files", "*.pem"), ("All files", "*.*")])
        if not path:
            return
        try:
            Fernet, serialization, Ed25519PrivateKey, Ed25519PublicKey = _require_crypto()
            private_key = Ed25519PrivateKey.generate()
            private_bytes = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
            public_bytes = private_key.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            private_path = Path(path)
            public_path = private_path.with_name(private_path.stem + ".public.pem")
            private_path.write_bytes(private_bytes)
            public_path.write_bytes(public_bytes)
            self.vars["author_key_file"].set(str(private_path))
            self._refresh_summary()
            messagebox.showinfo(APP_NAME, f"Author Key created:\n{private_path}\n\nPublic Key created:\n{public_path}", parent=self)
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Unable to create Author Key:\n{exc}", parent=self)

    def _collect_values(self):
        values = {
            "theme_name": self.vars["theme_name"].get().strip(),
            "theme_version": self.vars["theme_version"].get().strip(),
            "author_name": self.vars["author_name"].get().strip(),
            "freecad_version_tested": self.vars["freecad_version_tested"].get().strip(),
            "author_key_file": self.vars["author_key_file"].get().strip(),
            "description": self._get_text_widget("description"),
            "copyright": self._get_text_widget("copyright"),
            "license": self.vars["license"].get().strip(),
            "license_terms": self._get_text_widget("license_terms"),
            "license_notice_brief": self._get_text_widget("license_notice_brief"),
            "license_notice": self._get_text_widget("license_notice"),
        }
        values["theme_id"] = _slugify_theme_id(values["theme_name"])
        return values

    def _validate(self, values):
        errors = []
        if not values["theme_name"]:
            errors.append("Theme Name is required.")
        if not values["theme_id"]:
            errors.append("Theme ID could not be generated from Theme Name.")
        if not values["theme_version"]:
            errors.append("Theme Version is required.")
        if not values["author_name"]:
            errors.append("Author Name is required.")
        if not values["freecad_version_tested"]:
            errors.append("FreeCAD Version Tested is required.")
        if not values["description"]:
            errors.append("Description is required.")
        if not values["copyright"]:
            errors.append("Copyright is required.")
        if not values["license"]:
            errors.append("License is required.")
        if not values["license_terms"]:
            errors.append("License Brief is required.")
        if not values["license_notice_brief"]:
            errors.append("License Notice Brief is required.")
        if not values["license_notice"]:
            errors.append("License Notice is required.")
        if values.get("license") == CUSTOM_LICENSE_OPTION:
            theme_folder = self._current_theme_folder_path()
            custom_license_path = theme_folder / LICENSE_FILE_NAME
            if not custom_license_path.exists() or not custom_license_path.is_file():
                errors.append(f'Custom License requires a top-level "{LICENSE_FILE_NAME}" file inside the Theme Folder.')
        elif values.get("license"):
            source_path = _license_source_path(self.master.base_dir, values["license"])
            if source_path is None or not source_path.exists() or not source_path.is_file():
                errors.append(f'Selected CC license file was not found in "{CC_LICENSES_DIR_NAME}".')
        if not values["author_key_file"]:
            errors.append("Author Key is required.")
        else:
            p = Path(values["author_key_file"]).expanduser()
            if not p.exists() or not p.is_file():
                errors.append("Author Key does not exist or is not a file.")
            else:
                try:
                    _, _, fp = _load_author_private_key(p)
                    self.vars["key_fingerprint"].set(fp)
                except Exception as exc:
                    errors.append(str(exc))
        included_files = self.scan.get("included_files", [])
        counts = self.scan.get("counts", {})
        if not included_files:
            errors.append("No exportable theme files were found in the Theme Folder.")
        if counts.get(".cfg", 0) == 0:
            errors.append("Exactly one .cfg file is required, but none was found.")
        elif counts.get(".cfg", 0) > 1:
            errors.append("Exactly one .cfg file is required, but multiple .cfg files were found.")
        if counts.get(".svg", 0) + counts.get(".png", 0) == 0:
            errors.append("The Theme Folder must contain at least one .svg or .png asset.")
        return errors

    def _refresh_summary(self):
        values = self._collect_values()
        self.vars["theme_id"].set(values["theme_id"])
        counts = self.scan.get("counts", {})
        self.vars["svg_count"].set(str(counts.get(".svg", 0)))
        self.vars["png_count"].set(str(counts.get(".png", 0)))
        self.vars["qss_count"].set(str(counts.get(".qss", 0)))
        self.vars["cfg_count"].set(str(counts.get(".cfg", 0)))
        effective_included_files = _effective_export_file_list(self.scan, self._current_theme_folder_path(), values.get("license", ""))
        self.vars["total_files"].set(str(len(effective_included_files)))
        if not values["author_key_file"]:
            self.vars["key_fingerprint"].set("")
        self.included_files.configure(state="normal")
        self.included_files.delete("1.0", "end")
        for rel in effective_included_files:
            self.included_files.insert("end", rel + "\n")
        self.included_files.configure(state="disabled")
        errors = self._validate(values)
        self.validation_text.configure(state="normal")
        self.validation_text.delete("1.0", "end")
        if errors:
            for item in errors:
                self.validation_text.insert("end", "• " + item + "\n")
        else:
            self.validation_text.insert("end", "Ready to export.\n")
        self.validation_text.configure(state="disabled")

    def _save_back_to_launcher_settings(self, values):
        s = self.master.settings
        s.author_key_file = values["author_key_file"]
        s.export_theme_name = values["theme_name"]
        s.export_theme_version = values["theme_version"]
        s.export_author_name = values["author_name"]
        s.export_freecad_version_tested = values["freecad_version_tested"]
        s.export_description = values["description"]
        s.export_copyright = values["copyright"]
        s.export_license = values["license"]
        s.export_license_terms = values["license_terms"]
        s.export_license_notice_brief = values["license_notice_brief"]
        s.export_license_notice = values["license_notice"]
        self.master.settings_path.write_text(json.dumps(asdict(self.master.settings), indent=2, ensure_ascii=False), encoding="utf-8")

    def _export_clicked(self):
        values = self._collect_values()
        errors = self._validate(values)
        if errors:
            self._refresh_summary()
            messagebox.showerror(APP_NAME, "\n".join(errors), parent=self)
            return
        self._save_back_to_launcher_settings(values)
        self.result = values
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()




class CreateShortcutDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, default_name: str = "FreeCAD", default_location: str = "") -> None:
        super().__init__(parent)
        self.title("Create Shortcut")
        self.resizable(True, False)
        self.result: dict[str, str] | None = None
        self.transient(parent)
        self.grab_set()

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        self.name_var = tk.StringVar(value=default_name)
        self.location_var = tk.StringVar(value=default_location)
        self.mode_var = tk.StringVar(value="user")

        ttk.Label(body, text="Name").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=4)
        ttk.Entry(body, textvariable=self.name_var).grid(row=0, column=1, sticky="ew", pady=4)

        ttk.Label(body, text="Location").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=4)
        ttk.Entry(body, textvariable=self.location_var).grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Button(body, text="Browse", command=self._browse_location).grid(row=1, column=2, sticky="ew", padx=(8, 0), pady=4)

        mode_row = ttk.Frame(body)
        mode_row.grid(row=2, column=1, sticky="w", pady=(8, 4))
        ttk.Radiobutton(mode_row, text="User", variable=self.mode_var, value="user").pack(side="left")
        ttk.Radiobutton(mode_row, text="Creator", variable=self.mode_var, value="creator").pack(side="left", padx=(16, 0))

        actions = ttk.Frame(body)
        actions.grid(row=3, column=0, columnspan=3, sticky="e", pady=(12, 0))
        ttk.Button(actions, text="Cancel", command=self._cancel).pack(side="right")
        ttk.Button(actions, text="Create", command=self._accept).pack(side="right", padx=(0, 8))

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.update_idletasks()
        self.minsize(max(460, self.winfo_reqwidth()), self.winfo_reqheight())

    def _browse_location(self) -> None:
        current = self.location_var.get().strip() or str(Path.home())
        path = None
        if platform.system().lower() == "darwin":
            path = _macos_choose_folder_path("Select Shortcut Location", current)
        if path is None:
            path = filedialog.askdirectory(title="Select Shortcut Location", initialdir=current)
        if path:
            self.location_var.set(path)

    def _cancel(self) -> None:
        self.result = None
        self.destroy()

    def _accept(self) -> None:
        name = self.name_var.get().strip()
        location = self.location_var.get().strip()
        mode = self.mode_var.get().strip().lower()
        if not name:
            messagebox.showerror(APP_NAME, "Shortcut Name is required.", parent=self)
            return
        if not location:
            messagebox.showerror(APP_NAME, "Shortcut Location is required.", parent=self)
            return
        if mode not in ("user", "creator"):
            messagebox.showerror(APP_NAME, "Please select User or Creator.", parent=self)
            return
        self.result = {"name": name, "location": location, "mode": mode}
        self.destroy()


class ThemeLauncherApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry(f"{WINDOW_WIDTH}x1")
        self.minsize(WINDOW_WIDTH, 1)
        self.resizable(True, True)

        self.base_dir = _resource_base_dir()
        self.launcher_entry_path = _launcher_entry_path()
        self.settings_path = _settings_storage_path(self.base_dir)
        self.settings = self.load_settings()
        self.vars: dict[str, tk.Variable] = {}
        self._resize_after_id = None

        self._build_ui()
        self._populate_ui_from_settings()
        self.refresh_status()
        self.after(50, self._update_dynamic_window_size)

    def load_settings(self) -> AppSettings:
        if self.settings_path.exists():
            try:
                data = json.loads(self.settings_path.read_text(encoding="utf-8"))
                defaults = asdict(AppSettings())
                defaults.update(data)
                settings = AppSettings(**defaults)
                if "export_license" not in data or not str(getattr(settings, "export_license", "") or "").strip():
                    theme_folder_text = str(getattr(settings, "theme_folder", "") or "").strip()
                    if theme_folder_text:
                        theme_folder = Path(theme_folder_text).expanduser()
                        if theme_folder.exists() and theme_folder.is_dir():
                            settings.export_license = _detect_existing_license_choice(self.base_dir, theme_folder)
                        else:
                            settings.export_license = CUSTOM_LICENSE_OPTION
                    else:
                        settings.export_license = CUSTOM_LICENSE_OPTION
                return settings
            except Exception:
                pass

        return AppSettings()

    def save_settings(self) -> None:
        self._collect_ui_to_settings()
        self.settings_path.write_text(
            json.dumps(asdict(self.settings), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self.status("Settings saved.")

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)

        title = ttk.Label(
            outer,
            text="UI Launcher",
            font=("TkDefaultFont", 15, "bold"),
        )
        title.pack(anchor="w")

        mode_row = ttk.Frame(outer)
        mode_row.pack(fill="x", pady=(8, 0))

        self.vars["user_mode"] = tk.BooleanVar(value=True)
        self.vars["creator_mode"] = tk.BooleanVar(value=False)

        ttk.Checkbutton(
            mode_row,
            text="User Mode",
            variable=self.vars["user_mode"],
            command=self._on_user_mode_changed,
        ).pack(side="left")

        ttk.Checkbutton(
            mode_row,
            text="Creator Mode",
            variable=self.vars["creator_mode"],
            command=self._on_creator_mode_changed,
        ).pack(side="left", padx=(18, 0))

        form = ttk.Frame(outer)
        form.pack(fill="x", expand=False, pady=(8, 0))
        form.columnconfigure(0, weight=1)

        self.user_mode_row = ttk.Frame(form)
        self.user_mode_row.grid(row=0, column=0, sticky="ew")
        self.user_mode_row.columnconfigure(1, weight=1)
        self.user_mode_row.columnconfigure(2, weight=0)
        self._add_path_row(self.user_mode_row, 0, "Theme", "theme_file", self.browse_theme_file)

        self.theme_copyright_var = tk.StringVar(value="")
        self.theme_license_notice_brief_var = tk.StringVar(value="")
        self.theme_license_var = tk.StringVar(value="")
        self.loaded_theme_metadata: dict[str, str] = {}

        self.theme_info_frame = ttk.Frame(self.user_mode_row)
        self.theme_info_frame.grid(row=1, column=0, columnspan=3, sticky="ew", padx=(22, 22), pady=(2, 0))
        self.theme_info_frame.columnconfigure(0, weight=1)

        self.theme_copyright_message = tk.Message(
            self.theme_info_frame,
            textvariable=self.theme_copyright_var,
            justify="left",
            anchor="w",
            width=max(200, WINDOW_WIDTH - 120),
        )
        self.theme_copyright_message.grid(row=0, column=0, sticky="ew", pady=(4, 0))

        self.theme_license_notice_brief_message = tk.Message(
            self.theme_info_frame,
            textvariable=self.theme_license_notice_brief_var,
            justify="left",
            anchor="w",
            width=max(200, WINDOW_WIDTH - 120),
        )
        self.theme_license_notice_brief_message.grid(row=1, column=0, sticky="ew", pady=(12, 0))

        self.theme_license_message = tk.Message(
            self.theme_info_frame,
            textvariable=self.theme_license_var,
            justify="left",
            anchor="w",
            width=max(200, WINDOW_WIDTH - 120),
        )
        self.theme_license_message.grid(row=2, column=0, sticky="ew", pady=(12, 0))

        self.creator_mode_row = ttk.Frame(form)
        self.creator_mode_row.grid(row=0, column=0, sticky="ew")
        self.creator_mode_row.columnconfigure(1, weight=1)
        self._add_path_row(self.creator_mode_row, 0, "Theme Folder", "theme_folder", self.browse_theme_folder)

        self.actions = ttk.Frame(outer)
        self.actions.pack(fill="x", pady=(12, 0))
        self.validate_button = ttk.Button(self.actions, text="Validate Theme Folder", command=self.validate_clicked)
        self.export_button = ttk.Button(self.actions, text="Export Theme", command=self.export_theme_clicked)
        self.launch_freecad_button = ttk.Button(self.actions, text="Launch FreeCAD", command=self.launch_freecad)
        self.launch_from_theme_button = ttk.Button(self.actions, text="Launch FreeCAD", command=self.launch_from_theme_clicked)
        self.show_license_button = ttk.Button(self.actions, text="License", command=self.show_loaded_theme_license)
        self.show_license_notice_button = ttk.Button(self.actions, text="License Notice", command=self.show_loaded_theme_license_notice)

        self.settings_section = CollapsibleSection(outer, "Settings", expanded=False, on_toggle=self._schedule_dynamic_window_size_update)
        self.settings_section.pack(fill="x", pady=(12, 0))
        settings_body = self.settings_section.body
        settings_body.columnconfigure(1, weight=1)

        self.vars["use_freecad_user_home"] = tk.BooleanVar(value=True)
        self.vars["use_external_icons"] = tk.BooleanVar(value=True)
        self.vars["close_after_freecad_launch"] = tk.BooleanVar(value=True)
        self.vars["extra_cli_args"] = tk.StringVar(value="")

        self._add_path_row(settings_body, 0, "FreeCAD executable", "freecad_executable", self.browse_freecad_executable)

        ttk.Checkbutton(
            settings_body,
            text="Set FREECAD_USER_HOME to a runtime folder",
            variable=self.vars["use_freecad_user_home"],
            command=self.refresh_status,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=2)

        ttk.Checkbutton(
            settings_body,
            text="Use external icons",
            variable=self.vars["use_external_icons"],
            command=self._on_use_external_icons_changed,
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=2)

        ttk.Checkbutton(
            settings_body,
            text="Close after FreeCAD launch",
            variable=self.vars["close_after_freecad_launch"],
            command=self.refresh_status,
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=2)

        ttk.Button(
            settings_body,
            text="Create Shortcut",
            command=self.create_shortcut_clicked,
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(10, 0))

        self.status_frame = ttk.LabelFrame(outer, text="Status", padding=10)
        self.status_frame.pack(fill="both", expand=True, pady=(12, 0))

        self.status_text = tk.Text(self.status_frame, height=20, wrap="word")
        self.status_text.pack(fill="both", expand=True)
        self.status_text.configure(state="disabled")

        self.bind("<Configure>", self._on_main_window_configure, add="+")
        self._update_theme_message_wraplengths()

        self._update_mode_ui()
        self.after_idle(self._schedule_dynamic_window_size_update)

    def _on_main_window_configure(self, _event=None) -> None:
        self._update_theme_message_wraplengths()

    def _update_theme_message_wraplengths(self) -> None:
        try:
            container_width = self.theme_info_frame.winfo_width()
        except Exception:
            container_width = 0
        if not container_width or container_width <= 1:
            try:
                container_width = self.user_mode_row.winfo_width() - 44
            except Exception:
                container_width = WINDOW_WIDTH - 88
        available_width = max(260, container_width - 8)
        for widget in (
            getattr(self, "theme_copyright_message", None),
            getattr(self, "theme_license_notice_brief_message", None),
            getattr(self, "theme_license_message", None),
        ):
            if widget is not None:
                try:
                    widget.configure(width=available_width)
                except Exception:
                    pass

    def _theme_file_loaded(self) -> bool:
        theme_text = self.vars["theme_file"].get().strip() if "theme_file" in self.vars else ""
        if not theme_text:
            return False
        theme_path = Path(theme_text).expanduser()
        return theme_path.exists() and theme_path.is_file()

    def _show_scrollable_text_popup(self, title: str, content: str) -> None:
        popup = tk.Toplevel(self)
        popup.title(title)
        popup.transient(self)
        popup.resizable(True, True)
        popup.minsize(520, 360)

        shell = ttk.Frame(popup, padding=12)
        shell.pack(fill="both", expand=True)
        shell.rowconfigure(0, weight=1)
        shell.columnconfigure(0, weight=1)

        text_widget = tk.Text(shell, wrap="word")
        text_widget.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(shell, orient="vertical", command=text_widget.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        text_widget.configure(yscrollcommand=scroll.set)

        text_widget.insert("1.0", content)
        text_widget.configure(state="disabled")

        buttons = ttk.Frame(shell)
        buttons.grid(row=1, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Close", command=popup.destroy).pack(side="right")

        popup.update_idletasks()
        popup.geometry("700x600")
        popup.focus_set()

    def show_loaded_theme_license_notice(self) -> None:
        metadata = getattr(self, "loaded_theme_metadata", {}) or {}
        content = str(metadata.get("license_notice", "") or "").strip()
        if not content:
            messagebox.showinfo(APP_NAME, "No License Notice text is available in the loaded theme.", parent=self)
            return
        self._show_scrollable_text_popup("License Notice", content)

    def show_loaded_theme_license(self) -> None:
        metadata = getattr(self, "loaded_theme_metadata", {}) or {}
        content = str(metadata.get("license_text", "") or "").strip()
        if not content:
            messagebox.showinfo(APP_NAME, "No packaged license text is available in the loaded theme.", parent=self)
            return
        self._show_scrollable_text_popup("License", content)

    def _update_dynamic_window_size(self) -> None:
        self.update_idletasks()

        req_width = WINDOW_WIDTH
        req_height = max(1, self.winfo_reqheight())

        x = self.winfo_x()
        y = self.winfo_y()

        self.minsize(WINDOW_WIDTH, 1)
        self.maxsize(WINDOW_WIDTH, 10000)
        self.geometry(f"{req_width}x{req_height}+{x}+{y}")
        self.update_idletasks()

    def _schedule_dynamic_window_size_update(self) -> None:
        if self._resize_after_id is not None:
            try:
                self.after_cancel(self._resize_after_id)
            except Exception:
                pass
        self._resize_after_id = self.after(25, self._update_dynamic_window_size)

    def _add_path_row(self, parent: ttk.Frame, row: int, label: str, key: str, browse_command) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
        self.vars[key] = tk.StringVar(value="")
        entry = ttk.Entry(parent, textvariable=self.vars[key])
        entry.grid(row=row, column=1, sticky="ew", pady=4)
        entry.bind("<KeyRelease>", lambda _e: self.refresh_status())
        ttk.Button(parent, text="Browse", command=browse_command).grid(row=row, column=2, sticky="ew", padx=(8, 0), pady=4)

    def _refresh_selected_theme_metadata(self) -> None:
        theme_text = self.vars["theme_file"].get().strip() if "theme_file" in self.vars else ""
        copyright_text = ""
        license_notice_brief_text = ""
        license_text = ""
        self.loaded_theme_metadata = {}
        if theme_text:
            theme_path = Path(theme_text).expanduser()
            if theme_path.exists() and theme_path.is_file():
                metadata = _read_theme_package_metadata(theme_path)
                self.loaded_theme_metadata = metadata
                copyright_value = metadata.get("copyright", "").strip()
                license_notice_brief_value = metadata.get("license_notice_brief", "").strip()
                license_value = metadata.get("license_terms", "").strip()
                if copyright_value:
                    copyright_text = f"Copyright:  {copyright_value}"
                if license_notice_brief_value:
                    license_notice_brief_text = f"License Notice Brief:  {license_notice_brief_value}"
                if license_value:
                    license_text = f"License Brief:  {license_value}"
        self.theme_copyright_var.set(copyright_text)
        self.theme_license_notice_brief_var.set(license_notice_brief_text)
        self.theme_license_var.set(license_text)
        self._update_theme_action_buttons()
        self._update_theme_message_wraplengths()
        self._schedule_dynamic_window_size_update()

    def _set_mode(self, mode: str) -> None:
        is_user_mode = mode == "user"
        self.vars["user_mode"].set(is_user_mode)
        self.vars["creator_mode"].set(not is_user_mode)
        self._update_mode_ui()
        self.refresh_status()

    def _on_user_mode_changed(self) -> None:
        if self.vars["user_mode"].get():
            self._set_mode("user")
        else:
            self._set_mode("creator")

    def _on_creator_mode_changed(self) -> None:
        if self.vars["creator_mode"].get():
            self._set_mode("creator")
        else:
            self._set_mode("user")

    def _update_theme_action_buttons(self) -> None:
        self.show_license_button.pack_forget()
        self.show_license_notice_button.pack_forget()
        if bool(self.vars["user_mode"].get()) and self._theme_file_loaded():
            self.show_license_button.pack(side="left")
            self.show_license_notice_button.pack(side="left", padx=(8, 0))

    def _update_mode_ui(self) -> None:
        is_user_mode = bool(self.vars["user_mode"].get())

        self.validate_button.pack_forget()
        self.export_button.pack_forget()
        self.launch_freecad_button.pack_forget()
        self.launch_from_theme_button.pack_forget()
        self.show_license_button.pack_forget()
        self.show_license_notice_button.pack_forget()
        self.status_frame.pack_forget()

        if is_user_mode:
            self.user_mode_row.grid()
            self.creator_mode_row.grid_remove()
            self._update_theme_action_buttons()
            self.launch_from_theme_button.pack(side="right")
        else:
            self.user_mode_row.grid_remove()
            self.creator_mode_row.grid()
            self.validate_button.pack(side="left")
            self.export_button.pack(side="left", padx=(8, 0))
            self.launch_freecad_button.pack(side="right")
            self.status_frame.pack(fill="both", expand=True, pady=(12, 0))

        self.update_idletasks()
        self._update_theme_message_wraplengths()
        self._schedule_dynamic_window_size_update()

    def _populate_ui_from_settings(self) -> None:
        launch_mode = getattr(self.settings, "launch_mode", "user")
        for key, var in self.vars.items():
            if key == "use_external_icons":
                var.set(bool(self.settings.enable_external_icon_theme or self.settings.prefer_external_icons))
                continue
            if key in ("user_mode", "creator_mode"):
                continue
            if hasattr(self.settings, key):
                var.set(getattr(self.settings, key))
        self._sync_external_icon_settings_from_ui()
        self._refresh_selected_theme_metadata()
        self._set_mode("creator" if launch_mode == "creator" else "user")

    def _collect_ui_to_settings(self) -> None:
        self._sync_external_icon_settings_from_ui()
        self.settings.launch_mode = "user" if self.vars["user_mode"].get() else "creator"
        for key, var in self.vars.items():
            if key in ("use_external_icons", "user_mode", "creator_mode"):
                continue
            if hasattr(self.settings, key):
                setattr(self.settings, key, var.get())

    def _sync_external_icon_settings_from_ui(self) -> None:
        use_external_icons = bool(self.vars["use_external_icons"].get())
        self.settings.enable_external_icon_theme = use_external_icons
        self.settings.prefer_external_icons = use_external_icons

    def _on_use_external_icons_changed(self) -> None:
        self._sync_external_icon_settings_from_ui()
        self.refresh_status()


    def browse_freecad_executable(self) -> None:
        system = platform.system().lower()
        current = self.vars["freecad_executable"].get().strip()
        current_path = Path(current).expanduser() if current else None

        initialdir_path: Path | None = None
        if current_path and current_path.exists():
            if system == "darwin":
                app_root = None
                for candidate in [current_path, *current_path.parents]:
                    if candidate.suffix.lower() == ".app":
                        app_root = candidate
                        break
                initialdir_path = app_root.parent if app_root is not None else current_path.parent
            else:
                initialdir_path = current_path.parent
        initialdir = str(initialdir_path) if initialdir_path else str(Path.home())

        if system == "darwin":
            path = filedialog.askdirectory(
                title="Select FreeCAD.app",
                initialdir=initialdir,
                mustexist=True,
            )
            if not path:
                return
            selected = Path(path).expanduser()
            if selected.suffix.lower() != ".app":
                messagebox.showerror(APP_NAME, "Please select the FreeCAD.app application.")
                return
            normalized = _normalize_freecad_executable_path(selected)
            if normalized is None or not normalized.exists():
                messagebox.showerror(APP_NAME, f"Could not find the FreeCAD executable inside:\n{selected}")
                return
            self.vars["freecad_executable"].set(str(selected))
            self.refresh_status()
            return

        if system == "linux":
            path = filedialog.askopenfilename(
                title="Select FreeCAD.AppImage",
                initialdir=initialdir,
                filetypes=[("AppImage", "*.AppImage"), ("All files", "*.*")],
            )
            if not path:
                return
            selected = Path(path).expanduser()
            if selected.suffix.lower() == ".appimage":
                _ensure_linux_appimage_executable(selected)
            self.vars["freecad_executable"].set(str(selected))
            self.refresh_status()
            return

        path = filedialog.askopenfilename(
            title="Select FreeCAD executable",
            initialdir=initialdir,
            filetypes=[("Executable", "*.exe"), ("All files", "*.*")],
        )
        if path:
            self.vars["freecad_executable"].set(path)
            self.refresh_status()

    def browse_theme_folder(self) -> None:
        current = self.vars["theme_folder"].get().strip() or str(Path.home())
        path = None
        if platform.system().lower() == "darwin":
            path = _macos_choose_folder_path("Select Theme Folder", current)
        if path is None:
            path = filedialog.askdirectory(title="Select Theme Folder", initialdir=current)
        if path:
            self.vars["theme_folder"].set(path)
            self.refresh_status()


    def browse_theme_file(self) -> None:
        current = self.vars["theme_file"].get().strip()
        if current:
            initialdir = str(Path(current).expanduser().parent)
        else:
            initialdir = self.vars["theme_folder"].get().strip() or str(Path.home())
        path = None
        if platform.system().lower() == "darwin":
            path = _macos_choose_file_path("Select Theme File", initialdir)
        if path is None:
            path = filedialog.askopenfilename(
                title="Select Theme File",
                initialdir=initialdir,
                filetypes=[("Theme files", f"*{THEME_PACKAGE_EXTENSION}"), ("All files", "*.*")],
            )
        if path:
            self.vars["theme_file"].set(path)
            self._refresh_selected_theme_metadata()
            self.refresh_status()

    def _scan_theme_folder_for_export(self) -> dict[str, object]:
        self._collect_ui_to_settings()
        folder_text = self.settings.theme_folder.strip()
        result: dict[str, object] = {
            "theme_folder": folder_text,
            "included_files": [],
            "counts": {".svg": 0, ".png": 0, ".qss": 0, ".cfg": 0},
            "detected_cfg": "",
            "detected_splash": "",
        }
        if not folder_text:
            return result
        theme_folder = Path(folder_text).expanduser()
        if not theme_folder.exists() or not theme_folder.is_dir():
            return result

        included_files: list[str] = []
        for path in sorted(theme_folder.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(theme_folder).as_posix()
            if rel.startswith(f"{RUNTIME_DIR_NAME}/") or f"/{RUNTIME_DIR_NAME}/" in rel:
                continue
            if path.suffix.lower() not in EXPORTABLE_THEME_EXTENSIONS:
                continue
            if not _is_safe_relpath(rel):
                continue
            included_files.append(rel)

        # For export validation, only top-level .cfg/.qss files count.
        # Nested helper folders may contain backup or unrelated config files and
        # should not trigger the "multiple .cfg files" error.
        top_level_export_files = [
            rel for rel in included_files
            if "/" not in rel
        ]
        counts = _count_suffixes(top_level_export_files)
        cfgs = [rel for rel in top_level_export_files if rel.lower().endswith(".cfg")]

        result["included_files"] = included_files
        result["counts"] = counts
        result["detected_cfg"] = cfgs[0] if len(cfgs) == 1 else ""
        result["detected_splash"] = _detect_splash_relpath(included_files)
        return result

    def _prepare_license_file_for_export(self, values: dict[str, str], theme_folder: Path) -> str:
        license_choice = values.get("license", "").strip()
        target_path = theme_folder / LICENSE_FILE_NAME
        if license_choice == CUSTOM_LICENSE_OPTION:
            if not target_path.exists() or not target_path.is_file():
                raise LauncherError(f'Custom License requires a top-level "{LICENSE_FILE_NAME}" file inside the Theme Folder.')
            return LICENSE_FILE_NAME
        source_path = _license_source_path(self.base_dir, license_choice)
        if source_path is None or not source_path.exists() or not source_path.is_file():
            raise LauncherError(f'Selected CC license file was not found in "{CC_LICENSES_DIR_NAME}".')
        shutil.copy2(source_path, target_path)
        return LICENSE_FILE_NAME

    def _create_theme_package(self, values: dict[str, str], scan: dict[str, object], output_path: Path) -> tuple[dict[str, object], Path]:
        theme_folder = Path(self.settings.theme_folder).expanduser().resolve()
        included_files = list(scan["included_files"])
        license_relpath = self._prepare_license_file_for_export(values, theme_folder)
        if license_relpath and license_relpath not in included_files:
            included_files.append(license_relpath)
        included_files = sorted(set(included_files), key=str.lower)
        default_cfg_relpath = str(scan["detected_cfg"])
        default_splash_relpath = str(scan.get("detected_splash", "") or "")
        private_key, public_pem, fingerprint = _load_author_private_key(Path(values["author_key_file"]).expanduser())
        payload_buffer = io.BytesIO()
        with zipfile.ZipFile(payload_buffer, "w", zipfile.ZIP_DEFLATED) as payload_zip:
            for rel in included_files:
                payload_zip.write(theme_folder / rel, f"files/{rel}")
        encrypted_payload = _encrypt_payload(payload_buffer.getvalue())
        manifest = {
            "schema_version": THEME_SCHEMA_VERSION,
            "package_type": THEME_PACKAGE_TYPE,
            "theme_name": values["theme_name"],
            "theme_id": values["theme_id"],
            "theme_version": values["theme_version"],
            "author_name": values["author_name"],
            "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "freecad_version_tested": values["freecad_version_tested"],
            "launcher_version": APP_VERSION,
            "description": values["description"],
            "copyright": values["copyright"],
            "license": values["license"],
            "license_terms": values["license_terms"],
            "license_notice_brief": values["license_notice_brief"],
            "license_notice": values["license_notice"],
            "payload_encryption": THEME_PAYLOAD_ENCRYPTION,
            "payload_hash_sha256": hashlib.sha256(encrypted_payload).hexdigest(),
            "payload_size_bytes": len(encrypted_payload),
            "payload_file_count": len(included_files),
            "default_cfg_relpath": default_cfg_relpath,
            "default_splash_relpath": default_splash_relpath,
            "included_files": included_files,
        }
        signature = private_key.sign(_canonical_manifest_bytes(manifest))
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as outer_zip:
            outer_zip.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
            outer_zip.writestr("author_public_key.pem", public_pem)
            outer_zip.writestr("signature.sig", base64.b64encode(signature).decode("ascii"))
            outer_zip.writestr("payload.enc", encrypted_payload)
        return manifest, output_path

    def export_theme_clicked(self) -> None:
        self._collect_ui_to_settings()
        scan = self._scan_theme_folder_for_export()
        dialog = ExportThemeDialog(self, scan)
        self.wait_window(dialog)
        if not dialog.result:
            self.append_status("Export Theme canceled.")
            return
        try:
            default_name = f"{dialog.result['theme_id']}_v{dialog.result['theme_version']}{THEME_PACKAGE_EXTENSION}"
            save_path = filedialog.asksaveasfilename(
                title="Export Theme",
                defaultextension=THEME_PACKAGE_EXTENSION,
                initialfile=default_name,
                filetypes=[("Theme files", f"*{THEME_PACKAGE_EXTENSION}"), ("All files", "*.*")],
            )
            if not save_path:
                self.append_status("Export Theme canceled.")
                return
            manifest, output_file = self._create_theme_package(dialog.result, scan, Path(save_path))
            self.vars["theme_file"].set(str(output_file))
            self.clear_status()
            self.append_status("Theme exported successfully.")
            self.append_status(f"Theme Name: {manifest['theme_name']}")
            self.append_status(f"Theme ID: {manifest['theme_id']}")
            self.append_status(f"Theme Version: {manifest['theme_version']}")
            self.append_status(f"Author Name: {manifest['author_name']}")
            self.append_status(f"Included Files: {manifest['payload_file_count']}")
            self.append_status(f"Default CFG: {manifest['default_cfg_relpath']}")
            self.append_status(f"Output: {output_file}")
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))
            self.append_status(f"Export Theme failed: {exc}")

    def _read_theme_package(self, theme_file: Path) -> tuple[dict[str, object], bytes, str, bytes]:
        with zipfile.ZipFile(theme_file, "r") as outer_zip:
            names = set(outer_zip.namelist())
            required = {"manifest.json", "author_public_key.pem", "signature.sig", "payload.enc"}
            missing = sorted(required - names)
            if missing:
                raise LauncherError("Theme package is missing required files: " + ", ".join(missing))
            manifest = json.loads(outer_zip.read("manifest.json").decode("utf-8"))
            public_pem = outer_zip.read("author_public_key.pem")
            signature_b64 = outer_zip.read("signature.sig").decode("ascii").strip()
            payload_enc = outer_zip.read("payload.enc")
        return manifest, public_pem, signature_b64, payload_enc

    def _validate_theme_manifest(self, manifest: dict[str, object]) -> None:
        required = [
            "schema_version", "package_type", "theme_name", "theme_id", "theme_version",
            "author_name", "created_utc", "freecad_version_tested", "launcher_version",
            "description", "copyright", "license_terms", "payload_encryption",
            "payload_hash_sha256", "payload_size_bytes", "payload_file_count",
            "default_cfg_relpath", "included_files",
        ]
        missing = [key for key in required if key not in manifest]
        if missing:
            raise LauncherError("Theme manifest is missing required fields: " + ", ".join(missing))
        if manifest["schema_version"] != THEME_SCHEMA_VERSION:
            raise LauncherError(f"Unsupported theme schema version: {manifest['schema_version']}")
        if manifest["package_type"] != THEME_PACKAGE_TYPE:
            raise LauncherError("Selected file is not a supported UI Launcher theme package.")
        if manifest["payload_encryption"] != THEME_PAYLOAD_ENCRYPTION:
            raise LauncherError("Unsupported theme payload encryption.")
        if not _slugify_theme_id(str(manifest["theme_id"])) == str(manifest["theme_id"]):
            raise LauncherError("Theme package contains an invalid theme_id.")
        included_files = manifest["included_files"]
        if not isinstance(included_files, list) or not included_files:
            raise LauncherError("Theme package included_files is invalid.")
        for rel in included_files:
            if not isinstance(rel, str) or not _is_safe_relpath(rel):
                raise LauncherError("Theme package contains an unsafe file path.")
        cfg_rel = str(manifest["default_cfg_relpath"])
        if cfg_rel not in included_files:
            raise LauncherError("Theme package default_cfg_relpath is missing from included_files.")
        splash_rel = str(manifest.get("default_splash_relpath", "") or "")
        if splash_rel and splash_rel not in included_files:
            raise LauncherError("Theme package default_splash_relpath is missing from included_files.")

    def _extract_theme_payload(self, manifest: dict[str, object], payload_enc: bytes) -> tuple[Path, Path]:
        if hashlib.sha256(payload_enc).hexdigest() != str(manifest["payload_hash_sha256"]):
            raise LauncherError("Theme package payload does not match the signed manifest.")
        payload_bytes = _decrypt_payload(payload_enc)
        extraction_root = _make_obscured_temp_dir()
        theme_root = extraction_root / "theme_files"
        theme_root.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(io.BytesIO(payload_bytes), "r") as payload_zip:
                names = payload_zip.namelist()
                expected = [f"files/{rel}" for rel in manifest["included_files"]]
                for name in names:
                    if not name.startswith("files/"):
                        raise LauncherError("Theme payload contains an unexpected entry.")
                for rel in manifest["included_files"]:
                    if f"files/{rel}" not in names:
                        raise LauncherError(f"Theme payload is missing expected file: {rel}")
                for rel in manifest["included_files"]:
                    if not _is_safe_relpath(rel):
                        raise LauncherError("Theme payload contains an unsafe path.")
                    target = (theme_root / rel).resolve()
                    if theme_root.resolve() not in target.parents and target != theme_root.resolve():
                        raise LauncherError("Theme payload extraction path is unsafe.")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with payload_zip.open(f"files/{rel}") as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
            return extraction_root, theme_root
        except Exception:
            shutil.rmtree(extraction_root, ignore_errors=True)
            raise

    def launch_from_theme_clicked(self) -> None:
        self._collect_ui_to_settings()
        theme_text = self.settings.theme_file.strip()
        if not theme_text:
            messagebox.showerror(APP_NAME, "Theme is not selected.")
            self.append_status("Launch from Theme failed: Theme is not selected.")
            return
        try:
            theme_file = Path(theme_text).expanduser()
            if not theme_file.exists() or not theme_file.is_file():
                raise LauncherError("Theme does not exist or is not a file.")
            manifest, public_pem, signature_b64, payload_enc = self._read_theme_package(theme_file)
            self._validate_theme_manifest(manifest)
            _verify_signature(manifest, public_pem, signature_b64)
            extraction_root, theme_root = self._extract_theme_payload(manifest, payload_enc)

            packaged_cfg = theme_root / str(manifest["default_cfg_relpath"])
            if not packaged_cfg.exists():
                raise LauncherError("Theme package default .cfg was not found after extraction.")

            splash_override_path = None
            splash_rel = str(manifest.get("default_splash_relpath", "") or "")
            if splash_rel:
                candidate_splash = theme_root / splash_rel
                if candidate_splash.exists() and candidate_splash.is_file():
                    splash_override_path = candidate_splash

            permanent_cfg = _theme_user_cfg_path(str(manifest["theme_id"]))
            permanent_cfg.parent.mkdir(parents=True, exist_ok=True)
            if not permanent_cfg.exists():
                shutil.copy2(packaged_cfg, permanent_cfg)

            self._launch_with_prepared_theme(
                theme_folder=theme_root,
                cfg_source=permanent_cfg,
                cfg_writeback_target=permanent_cfg,
                source_label=f"Theme File: {theme_file}",
                cleanup_dir=extraction_root,
                splash_override_path=splash_override_path,
            )
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))
            self.append_status(f"Launch from Theme failed: {exc}")

    def copy_reload_command(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(RELOAD_CONSOLE_COMMAND)
        self.update_idletasks()
        self.append_status("Copied Python reload command to clipboard.")

    def append_status(self, text: str) -> None:
        self.status_text.configure(state="normal")
        self.status_text.insert("end", text + "\n")
        self.status_text.see("end")
        self.status_text.configure(state="disabled")

    def clear_status(self) -> None:
        self.status_text.configure(state="normal")
        self.status_text.delete("1.0", "end")
        self.status_text.configure(state="disabled")

    def status(self, text: str) -> None:
        self.clear_status()
        self.append_status(text)

    def scan_theme_folder(self) -> tuple[Path | None, Path | None, Path | None, Path | None, list[str]]:
        self._collect_ui_to_settings()
        notes: list[str] = []

        folder_text = self.settings.theme_folder.strip()
        if not folder_text:
            return None, None, None, None, notes

        folder = Path(folder_text)
        if not folder.exists() or not folder.is_dir():
            return None, None, None, None, notes

        cfg_files = sorted([p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".cfg"], key=lambda p: p.name.lower())
        qss_files = sorted([p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".qss"], key=lambda p: p.name.lower())

        cfg_path = ThemeFolderScanner.find_cfg(folder)
        qss_path = ThemeFolderScanner.find_qss(folder)
        splash_path = ThemeFolderScanner.find_splash(folder)
        icon_theme_root = ThemeFolderScanner.find_external_icon_theme_root(folder)

        if len(cfg_files) > 1 and cfg_path is not None:
            notes.append(f"Multiple .cfg files found. Using: {cfg_path.name}")
        if len(qss_files) > 1 and qss_path is not None:
            notes.append(f"Multiple .qss files found. Using: {qss_path.name}")
        if self.settings.enable_external_icon_theme and icon_theme_root is None:
            notes.append("External icon theme is enabled, but no icon files were detected in the Theme Folder or in icons/ Icons/ images/ Images/.")

        return cfg_path, qss_path, splash_path, icon_theme_root, notes


    def _scan_specific_theme_folder(self, theme_folder: Path) -> tuple[Path | None, Path | None, Path | None, Path | None, list[str]]:
        notes: list[str] = []
        if not theme_folder.exists() or not theme_folder.is_dir():
            return None, None, None, None, notes
        cfg_files = sorted([p for p in theme_folder.iterdir() if p.is_file() and p.suffix.lower() == ".cfg"], key=lambda p: p.name.lower())
        qss_files = sorted([p for p in theme_folder.iterdir() if p.is_file() and p.suffix.lower() == ".qss"], key=lambda p: p.name.lower())
        cfg_path = ThemeFolderScanner.find_cfg(theme_folder)
        qss_path = ThemeFolderScanner.find_qss(theme_folder)
        splash_path = ThemeFolderScanner.find_splash(theme_folder)
        icon_theme_root = ThemeFolderScanner.find_external_icon_theme_root(theme_folder)
        if len(cfg_files) > 1 and cfg_path is not None:
            notes.append(f"Multiple .cfg files found. Using: {cfg_path.name}")
        if len(qss_files) > 1 and qss_path is not None:
            notes.append(f"Multiple .qss files found. Using: {qss_path.name}")
        if self.settings.enable_external_icon_theme and icon_theme_root is None:
            notes.append("External icon theme is enabled, but no icon files were detected in the Theme Folder or in icons/ Icons/ images/ Images/.")
        return cfg_path, qss_path, splash_path, icon_theme_root, notes

    def validate_theme_folder(self) -> tuple[bool, list[str], list[str], Path | None, Path | None, Path | None, Path | None]:
        self._collect_ui_to_settings()
        errors: list[str] = []
        warnings: list[str] = []
        exe = _normalize_freecad_executable_path(self.settings.freecad_executable)
        theme_folder = Path(self.settings.theme_folder).expanduser() if self.settings.theme_folder else None
        if not exe or not exe.exists():
            errors.append("FreeCAD executable is missing or does not exist.")
        if not theme_folder:
            errors.append("Theme Folder is not selected.")
            return False, errors, warnings, None, None, None, None
        if not theme_folder.exists() or not theme_folder.is_dir():
            errors.append("Theme Folder does not exist or is not a folder.")
            return False, errors, warnings, None, None, None, None
        cfg_path, qss_path, splash_path, icon_theme_root, notes = self._scan_specific_theme_folder(theme_folder)
        warnings.extend(notes)
        if cfg_path is None:
            errors.append("No .cfg file was found in the Theme Folder.")
        if qss_path is None:
            warnings.append("No .qss file was found in the Theme Folder. FreeCAD will launch without a stylesheet override.")
        return len(errors) == 0, errors, warnings, cfg_path, qss_path, splash_path, icon_theme_root

    def validate_clicked(self) -> None:
        ok, errors, warnings, cfg_path, qss_path, splash_path, icon_theme_root = self.validate_theme_folder()
        self.clear_status()
        self.append_status("Validation passed." if ok else "Validation failed.")
        if cfg_path:
            self.append_status(f"Detected .cfg: {cfg_path}")
        if qss_path:
            self.append_status(f"Detected .qss: {qss_path}")
        if splash_path:
            self.append_status(f"Detected splash image: {splash_path}")
        if icon_theme_root:
            self.append_status(f"Detected external icon theme root: {icon_theme_root}")
        if errors:
            self.append_status("\nErrors:")
            for item in errors:
                self.append_status(f"- {item}")
        if warnings:
            self.append_status("\nWarnings:")
            for item in warnings:
                self.append_status(f"- {item}")

    def write_reload_helper_files(self, runtime_root: Path, runtime_user_home: Path | None) -> tuple[Path | None, Path | None]:
        helper_text_path = runtime_root / "reload_external_icon_theme.txt"
        helper_text = (
            "Python console command:\n\n"
            f"{RELOAD_CONSOLE_COMMAND}\n\n"
            "If your patched FreeCAD build exposes Gui.reloadExternalIconTheme(), "
            "run that command after editing icon files in the external theme folder.\n"
        )
        helper_text_path.write_text(helper_text, encoding="utf-8")
        macro_path: Path | None = None
        if runtime_user_home is not None:
            macro_dir = runtime_user_home / "Macro"
            macro_dir.mkdir(parents=True, exist_ok=True)
            macro_path = macro_dir / RELOAD_MACRO_NAME
            macro_path.write_text(RELOAD_MACRO_CONTENT, encoding="utf-8")
        return helper_text_path, macro_path

    def _build_launch_command_for_theme_folder(
        self,
        theme_folder: Path,
        cfg_source: Path,
        cfg_writeback_target: Path,
        source_label: str,
        splash_override_path: Path | None = None,
    ) -> tuple[list[str], dict[str, str], str, Path]:
        cfg_path, qss_path, splash_path, icon_theme_root, notes = self._scan_specific_theme_folder(theme_folder)
        if splash_override_path is not None and splash_override_path.exists() and splash_override_path.is_file():
            splash_path = splash_override_path
        runtime_root = theme_folder / RUNTIME_DIR_NAME
        runtime_root.mkdir(parents=True, exist_ok=True)
        runtime_user_cfg = runtime_root / "user.cfg"
        runtime_qss_text = _build_runtime_stylesheet(qss_path.resolve()) if qss_path else None
        ConfigXML.write_runtime_user_cfg(
            source_user_cfg=cfg_source.resolve(),
            destination_user_cfg=runtime_user_cfg,
            stylesheet_text=runtime_qss_text,
        )
        runtime_user_home: Path | None = None
        runtime_splash_paths: list[Path] = []
        need_runtime_user_home = (
            self.settings.use_freecad_user_home
            or splash_path is not None
            or self.settings.enable_external_icon_theme
        )
        if need_runtime_user_home:
            runtime_user_home = runtime_root / "user_home"
            runtime_user_home.mkdir(parents=True, exist_ok=True)
        if splash_path is not None and runtime_user_home is not None:
            splash_source = splash_path.resolve()
            splash_candidate_dirs = [
                runtime_user_home / "Gui" / "Images",
                runtime_user_home / "Gui" / "images",
                runtime_user_home / "FreeCAD" / "Gui" / "Images",
                runtime_user_home / "FreeCAD" / "Gui" / "images",
            ]
            seen_splash_targets: set[str] = set()
            for images_dir in splash_candidate_dirs:
                images_dir.mkdir(parents=True, exist_ok=True)
                for splash_name in ("splash_image.png", "freecadsplash.png"):
                    splash_target = images_dir / splash_name
                    splash_target_key = str(splash_target.resolve()).lower() if os.name == "nt" else str(splash_target.resolve())
                    if splash_target_key in seen_splash_targets:
                        continue
                    shutil.copy2(splash_source, splash_target)
                    runtime_splash_paths.append(splash_target)
                    seen_splash_targets.add(splash_target_key)
        helper_text_path, macro_path = self.write_reload_helper_files(runtime_root, runtime_user_home)
        runtime_startup_script_path: Path | None = None
        resolved_freecad_executable = _normalize_freecad_executable_path(self.settings.freecad_executable)
        if resolved_freecad_executable is None or not resolved_freecad_executable.exists():
            raise LauncherError("FreeCAD executable is missing or does not exist.")
        cmd = [str(resolved_freecad_executable.resolve()), "--user-cfg", str(runtime_user_cfg)]
        if runtime_qss_text:
            runtime_startup_script_path = runtime_root / "apply_runtime_stylesheet.FCMacro"
            _make_startup_stylesheet_script(runtime_startup_script_path, runtime_qss_text)
        extra_args = self.settings.extra_cli_args.strip()
        if extra_args:
            cmd.extend(shlex.split(extra_args, posix=(platform.system().lower() != "windows")))
        if runtime_startup_script_path is not None:
            cmd.append(str(runtime_startup_script_path))
        env = os.environ.copy()
        if runtime_user_home is not None:
            env["FREECAD_USER_HOME"] = str(runtime_user_home)
        if self.settings.enable_external_icon_theme and icon_theme_root is not None:
            env["FREECAD_EXTERNAL_ICON_THEME"] = str(icon_theme_root.resolve())
            env["FREECAD_EXTERNAL_ICON_THEME_ENABLED"] = "1"
            env["FREECAD_EXTERNAL_ICON_THEME_PREFER_EXTERNAL"] = "1" if self.settings.prefer_external_icons else "0"
        summary: list[str] = []
        summary.append(f"Executable: {self.settings.freecad_executable}")
        if str(resolved_freecad_executable) != str(self.settings.freecad_executable).strip():
            summary.append(f"Resolved executable: {resolved_freecad_executable}")
        summary.append(f"{source_label}: {theme_folder}")
        summary.append(f"Config source: {cfg_source.resolve()}")
        summary.append(f"Detected .qss: {qss_path.resolve()}" if qss_path else "Detected .qss: none")
        summary.append(f"Detected splash image: {splash_path.resolve()}" if splash_path else "Detected splash image: none")
        summary.append(f"Detected external icon theme root: {icon_theme_root.resolve()}" if icon_theme_root else "Detected external icon theme root: none")
        summary.append(f"Runtime user.cfg: {runtime_user_cfg}")
        if runtime_user_home is not None:
            summary.append(f"FREECAD_USER_HOME={runtime_user_home}")
        if runtime_startup_script_path is not None:
            summary.append(f"Startup stylesheet script: {runtime_startup_script_path}")
        if runtime_splash_paths:
            summary.append("Runtime splash destinations:")
            for splash_target in runtime_splash_paths:
                summary.append(f"- {splash_target}")
        if self.settings.enable_external_icon_theme and icon_theme_root is not None:
            summary.append(f"FREECAD_EXTERNAL_ICON_THEME={icon_theme_root.resolve()}")
            summary.append("FREECAD_EXTERNAL_ICON_THEME_ENABLED=1")
            summary.append("FREECAD_EXTERNAL_ICON_THEME_PREFER_EXTERNAL=" + ("1" if self.settings.prefer_external_icons else "0"))
        summary.append(f"Reload helper text: {helper_text_path}")
        summary.append(f"Reload helper macro: {macro_path}" if macro_path else "Reload helper macro: none")
        summary.append(f"Config write-back target: {cfg_writeback_target.resolve()}")
        summary.append("Python console reload command:")
        summary.append(RELOAD_CONSOLE_COMMAND)
        if notes:
            summary.append("Warnings:")
            for item in notes:
                summary.append(f"- {item}")
        return cmd, env, "\n".join(summary), runtime_user_cfg

    def build_launch_command(self) -> tuple[list[str], dict[str, str], str]:
        self._collect_ui_to_settings()
        ok, errors, warnings, cfg_path, qss_path, splash_path, icon_theme_root = self.validate_theme_folder()
        if not ok or cfg_path is None:
            raise LauncherError("\n".join(errors))
        cmd, env, summary, runtime_user_cfg = self._build_launch_command_for_theme_folder(
            theme_folder=Path(self.settings.theme_folder).resolve(),
            cfg_source=cfg_path.resolve(),
            cfg_writeback_target=cfg_path.resolve(),
            source_label="Theme Folder",
        )
        return cmd, env, summary

    def _posix_process_group_is_active(self, process_group_id: int | None) -> bool:
        if os.name == "nt" or process_group_id is None or process_group_id <= 0:
            return False
        try:
            os.killpg(process_group_id, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except Exception:
            return False

    def _wait_for_freecad_ready(self, process, timeout_seconds: float = 90.0, process_group_id: int | None = None) -> bool:
        start = time.time()
        pid = process.pid
        if os.name == "nt":
            while time.time() - start < timeout_seconds:
                if process.poll() is not None:
                    return False
                if self._windows_process_has_visible_top_level_window(pid):
                    return True
                self.update_idletasks()
                self.update()
                time.sleep(0.25)
            return False

        alive_since: float | None = None
        grace_seconds = 5.0 if _is_linux_appimage_path(self.settings.freecad_executable) else 2.0
        while time.time() - start < timeout_seconds:
            process_alive = process.poll() is None
            group_alive = self._posix_process_group_is_active(process_group_id)
            alive = process_alive or group_alive
            now = time.time()
            if alive:
                if alive_since is None:
                    alive_since = now
                elif now - alive_since >= grace_seconds:
                    return True
            else:
                if process.poll() is not None and alive_since is None:
                    return False
                alive_since = None
            self.update_idletasks()
            self.update()
            time.sleep(0.5)
        return alive_since is not None

    def _windows_process_has_visible_top_level_window(self, pid: int) -> bool:
        if os.name != "nt":
            return False
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            found = {"visible_window": False}
            EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
            def callback(hwnd, lparam):
                window_pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
                if window_pid.value != pid:
                    return True
                if not user32.IsWindowVisible(hwnd):
                    return True
                if user32.GetWindowTextLengthW(hwnd) <= 0:
                    return True
                found["visible_window"] = True
                return False
            user32.EnumWindows(EnumWindowsProc(callback), 0)
            return found["visible_window"]
        except Exception:
            return False

    def _spawn_post_exit_helper(self, pid: int, runtime_user_cfg: Path | None, cfg_path: Path | None, cleanup_dir: Path | None, process_group_id: int | None = None) -> None:
        runtime_user_cfg_text = str(runtime_user_cfg.resolve()) if runtime_user_cfg is not None else ""
        cfg_path_text = str(cfg_path.resolve()) if cfg_path is not None else ""
        cleanup_dir_text = str(cleanup_dir.resolve()) if cleanup_dir is not None else ""
        helper_base = Path(tempfile.gettempdir()) / f"ui_launcher_post_exit_{pid}"

        if os.name == "nt":
            def _ps_literal(value: str) -> str:
                return "'" + value.replace("'", "''") + "'"

            helper_path = helper_base.with_suffix(".ps1")
            helper_code = textwrap.dedent(
                f"""\
                $ErrorActionPreference = 'SilentlyContinue'
                $pidToWatch = {pid}
                $runtimeUserCfg = {_ps_literal(runtime_user_cfg_text)}
                $cfgPath = {_ps_literal(cfg_path_text)}
                $cleanupDir = {_ps_literal(cleanup_dir_text)}

                function Test-ProcessRunning([int]$TargetPid) {{
                    try {{
                        $null = Get-Process -Id $TargetPid -ErrorAction Stop
                        return $true
                    }} catch {{
                        return $false
                    }}
                }}

                function Test-SafeTemporaryCleanupDir([string]$PathText) {{
                    if ([string]::IsNullOrWhiteSpace($PathText)) {{
                        return $false
                    }}
                    try {{
                        $resolved = [System.IO.Path]::GetFullPath($PathText)
                        $tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
                    }} catch {{
                        return $false
                    }}
                    if (-not (Test-Path -LiteralPath $resolved -PathType Container)) {{
                        return $false
                    }}
                    if ($resolved.TrimEnd('\') -eq $tempRoot.TrimEnd('\')) {{
                        return $false
                    }}
                    if (-not $resolved.StartsWith($tempRoot, [System.StringComparison]::OrdinalIgnoreCase)) {{
                        return $false
                    }}
                    return ([System.IO.Path]::GetFileName($resolved)).StartsWith('.uix_')
                }}

                while (Test-ProcessRunning $pidToWatch) {{
                    Start-Sleep -Seconds 1
                }}

                if (-not [string]::IsNullOrWhiteSpace($runtimeUserCfg) -and -not [string]::IsNullOrWhiteSpace($cfgPath) -and (Test-Path -LiteralPath $runtimeUserCfg -PathType Leaf)) {{
                    $parent = Split-Path -Parent $cfgPath
                    if (-not [string]::IsNullOrWhiteSpace($parent)) {{
                        New-Item -ItemType Directory -Force -Path $parent | Out-Null
                    }}
                    Copy-Item -LiteralPath $runtimeUserCfg -Destination $cfgPath -Force
                }}

                if (Test-SafeTemporaryCleanupDir $cleanupDir) {{
                    Remove-Item -LiteralPath $cleanupDir -Recurse -Force -ErrorAction SilentlyContinue
                }}

                Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
                """
            )
            helper_path.write_text(helper_code, encoding="utf-8")
            subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", str(helper_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
            )
            return

        def _sh_literal(value: str) -> str:
            return "'" + value.replace("'", "'\"'\"'") + "'"

        helper_path = helper_base.with_suffix(".sh")
        helper_code = textwrap.dedent(
            f"""\
            #!/bin/sh
            pid_to_watch={pid}
            runtime_user_cfg={_sh_literal(runtime_user_cfg_text)}
            cfg_path={_sh_literal(cfg_path_text)}
            cleanup_dir={_sh_literal(cleanup_dir_text)}

            process_is_running() {{
                kill -0 "$1" 2>/dev/null
            }}

            resolve_dir() {{
                if [ -n "$1" ] && [ -d "$1" ]; then
                    (cd "$1" 2>/dev/null && pwd -P)
                fi
            }}

            temp_root=$(resolve_dir "${{TMPDIR:-/tmp}}")
            cleanup_dir_resolved=$(resolve_dir "$cleanup_dir")

            is_safe_temporary_cleanup_dir() {{
                [ -n "$cleanup_dir_resolved" ] || return 1
                [ -n "$temp_root" ] || return 1
                [ "$cleanup_dir_resolved" != "$temp_root" ] || return 1
                case "$cleanup_dir_resolved" in
                    "$temp_root"/.uix_*) return 0 ;;
                    *) return 1 ;;
                esac
            }}

            while process_is_running "$pid_to_watch" || process_group_is_running "$process_group_id"; do
                sleep 1
            done

            if [ -n "$runtime_user_cfg" ] && [ -n "$cfg_path" ] && [ -f "$runtime_user_cfg" ]; then
                mkdir -p "$(dirname "$cfg_path")"
                cp -f "$runtime_user_cfg" "$cfg_path"
            fi

            if is_safe_temporary_cleanup_dir; then
                rm -rf "$cleanup_dir_resolved"
            fi

            rm -f "$0"
            """
        )
        helper_path.write_text(helper_code, encoding="utf-8")
        helper_path.chmod(0o700)
        subprocess.Popen(
            ["/bin/sh", str(helper_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )

    def _launch_with_prepared_theme(
        self,
        theme_folder: Path,
        cfg_source: Path,
        cfg_writeback_target: Path,
        source_label: str,
        cleanup_dir: Path | None = None,
        splash_override_path: Path | None = None,
    ) -> None:
        self.save_settings()
        cmd, env, summary, runtime_user_cfg = self._build_launch_command_for_theme_folder(
            theme_folder=theme_folder.resolve(),
            cfg_source=cfg_source.resolve(),
            cfg_writeback_target=cfg_writeback_target.resolve(),
            source_label=source_label,
            splash_override_path=splash_override_path.resolve() if splash_override_path is not None else None,
        )
        self.clear_status()
        self.append_status("Launching FreeCAD...\n")
        self.append_status(summary)
        self.append_status("\nCommand:")
        self.append_status(" ".join(_quote_arg(part) for part in cmd))
        process = subprocess.Popen(cmd, env=env)
        if self.settings.close_after_freecad_launch:
            self.append_status("\nWaiting for FreeCAD to finish loading before closing the launcher...")
            self.update_idletasks()
            self._spawn_post_exit_helper(process.pid, runtime_user_cfg, cfg_writeback_target, cleanup_dir)
            ready = self._wait_for_freecad_ready(process)
            if ready:
                self.destroy()
                return
            raise RuntimeError("FreeCAD did not finish loading successfully before the launcher timeout.")
        self.append_status("\nFreeCAD started. Waiting for it to exit before syncing the updated .cfg back...")
        self.update_idletasks()
        process.wait()
        if runtime_user_cfg.exists():
            cfg_writeback_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(runtime_user_cfg, cfg_writeback_target)
            self.append_status(f"\nCopied updated .cfg back to: {cfg_writeback_target}")
        else:
            self.append_status("\nRuntime user.cfg was not found after FreeCAD exited, so nothing was copied back.")
        if _safe_rmtree(cleanup_dir):
            self.append_status(f"Removed temporary extracted theme: {cleanup_dir}")

    def launch_freecad(self) -> None:
        try:
            ok, errors, warnings, cfg_path, qss_path, splash_path, icon_theme_root = self.validate_theme_folder()
            if not ok or cfg_path is None:
                raise LauncherError("\n".join(errors))
            self._launch_with_prepared_theme(
                theme_folder=Path(self.settings.theme_folder).resolve(),
                cfg_source=cfg_path.resolve(),
                cfg_writeback_target=cfg_path.resolve(),
                source_label="Theme Folder",
            )
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))
            self.append_status(f"\nLaunch failed:\n{exc}")


    def _resolve_theme_source_for_shortcut(self, mode: str) -> tuple[Path | None, str]:
        if mode == "creator":
            folder_text = self.settings.theme_folder.strip()
            if not folder_text:
                return None, "Theme Folder is not selected."
            folder = Path(folder_text).expanduser()
            if not folder.exists() or not folder.is_dir():
                return None, "Theme Folder does not exist or is not a folder."
            return folder, ""

        theme_text = self.settings.theme_file.strip()
        if not theme_text:
            return None, "Theme is not selected."
        theme_file = Path(theme_text).expanduser()
        if not theme_file.exists() or not theme_file.is_file():
            return None, "Theme does not exist or is not a file."
        return theme_file, ""

    def _extract_theme_for_shortcut(self, theme_file: Path) -> tuple[Path, Path]:
        manifest, public_pem, signature_b64, payload_enc = self._read_theme_package(theme_file)
        self._validate_theme_manifest(manifest)
        _verify_signature(manifest, public_pem, signature_b64)
        extraction_root, theme_root = self._extract_theme_payload(manifest, payload_enc)
        return extraction_root, theme_root

    def _resolve_shortcut_icon_for_source(self, source_path: Path) -> tuple[Path | None, Path | None]:
        cleanup_dir = None
        theme_root = source_path
        if source_path.is_file() and source_path.suffix.lower() == THEME_PACKAGE_EXTENSION:
            cleanup_dir, theme_root = self._extract_theme_for_shortcut(source_path)

        icon_path = _find_platform_shortcut_icon_in_folder(theme_root)
        if icon_path is not None and icon_path.exists():
            return icon_path, cleanup_dir

        default_icons_dir = self.base_dir / DEFAULT_SHORTCUT_ICONS_DIR_NAME
        fallback_icon = None
        if default_icons_dir.exists() and default_icons_dir.is_dir():
            fallback_icon = _find_platform_shortcut_icon_in_folder(default_icons_dir)

        return fallback_icon, cleanup_dir



    def _shortcut_target_and_args(self, mode: str) -> tuple[Path, list[str]]:
        mode_arg = "--launch-as-user" if mode == "user" else "--launch-as-creator"
        if _is_frozen_app():
            if platform.system().lower() == "linux":
                appimage_path = os.environ.get("APPIMAGE", "").strip()
                if appimage_path:
                    return Path(appimage_path).resolve(), [mode_arg]
            return self.launcher_entry_path, [mode_arg]
        return Path(sys.executable).resolve(), [str(_launcher_entry_path()), mode_arg]

    def _create_windows_shortcut(self, shortcut_path: Path, target_path: Path, arguments: list[str], icon_path: Path | None) -> None:
        arg_string = subprocess.list2cmdline(arguments) if arguments else ""
        script = textwrap.dedent(f"""\
            $WshShell = New-Object -ComObject WScript.Shell
            $Shortcut = $WshShell.CreateShortcut({str(shortcut_path)!r})
            $Shortcut.TargetPath = {str(target_path)!r}
            $Shortcut.WorkingDirectory = {str(target_path.parent)!r}
            {f"$Shortcut.Arguments = {arg_string!r}" if arg_string else ""}
            {f"$Shortcut.IconLocation = {str(icon_path)!r}" if icon_path is not None else ""}
            $Shortcut.Save()
        """)
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _create_macos_shortcut(self, shortcut_path: Path, target_path: Path, arguments: list[str], icon_path: Path | None) -> None:
        app_dir = shortcut_path
        contents = app_dir / "Contents"
        macos_dir = contents / "MacOS"
        resources_dir = contents / "Resources"
        macos_dir.mkdir(parents=True, exist_ok=True)
        resources_dir.mkdir(parents=True, exist_ok=True)

        launcher_script = macos_dir / shortcut_path.stem
        command_parts = [str(target_path)] + arguments
        launcher_script.write_text(
            "#!/bin/sh\n"
            f'cd "{str(target_path.parent)}" || exit 1\n'
            f'exec {_shell_join(command_parts)}\n',
            encoding="utf-8",
        )
        os.chmod(launcher_script, 0o755)

        icon_file_name = ""
        if icon_path is not None and icon_path.exists():
            icon_file_name = "shortcut.icns"
            shutil.copy2(icon_path, resources_dir / icon_file_name)

        info_plist = contents / "Info.plist"
        plist_text = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDisplayName</key>
    <string>{shortcut_path.stem}</string>
    <key>CFBundleExecutable</key>
    <string>{shortcut_path.stem}</string>
    <key>CFBundleIdentifier</key>
    <string>com.ui.launcher.shortcut.{shortcut_path.stem.lower().replace(" ", "-")}</string>
    <key>CFBundleName</key>
    <string>{shortcut_path.stem}</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    {f"<key>CFBundleIconFile</key>\n    <string>{icon_file_name}</string>" if icon_file_name else ""}
</dict>
</plist>
"""
        info_plist.write_text(plist_text, encoding="utf-8")

    def _create_linux_shortcut(self, shortcut_path: Path, target_path: Path, arguments: list[str], icon_path: Path | None) -> None:
        exec_parts = [_desktop_exec_escape(str(target_path))] + [_desktop_exec_escape(part) for part in arguments]
        desktop_text = f"""[Desktop Entry]
Type=Application
Version=1.0
Name={_desktop_file_escape(shortcut_path.stem)}
Exec={' '.join(exec_parts)}
Path={str(target_path.parent)}
Terminal=false
"""
        if icon_path is not None and icon_path.exists():
            desktop_text += f"Icon={str(icon_path)}\n"
        desktop_text += "Categories=Graphics;Engineering;\n"
        shortcut_path.write_text(desktop_text, encoding="utf-8")
        os.chmod(shortcut_path, 0o755)

    def create_shortcut_clicked(self) -> None:
        self._collect_ui_to_settings()
        self.save_settings()
        default_location = str(Path.home() / "Desktop")
        dialog = CreateShortcutDialog(self, default_name="FreeCAD", default_location=default_location)
        self.wait_window(dialog)
        if not dialog.result:
            return

        mode = dialog.result["mode"]
        source_path, error = self._resolve_theme_source_for_shortcut(mode)
        if source_path is None:
            messagebox.showerror(APP_NAME, error)
            return

        target_path, shortcut_arguments = self._shortcut_target_and_args(mode)
        if not target_path.exists():
            messagebox.showerror(APP_NAME, f"Launcher target was not found:\n{target_path}")
            return

        location_path = Path(dialog.result["location"]).expanduser()
        if not location_path.exists() or not location_path.is_dir():
            messagebox.showerror(APP_NAME, "Shortcut Location does not exist or is not a folder.")
            return

        cleanup_dir = None
        try:
            icon_path, cleanup_dir = self._resolve_shortcut_icon_for_source(source_path)
            system = platform.system().lower()
            name = dialog.result["name"].strip()
            if system == "windows":
                shortcut_path = location_path / f"{name}.lnk"
                self._create_windows_shortcut(shortcut_path, target_path, shortcut_arguments, icon_path)
            elif system == "darwin":
                shortcut_path = location_path / f"{name}.app"
                self._create_macos_shortcut(shortcut_path, target_path, shortcut_arguments, icon_path)
            else:
                shortcut_path = location_path / f"{name}.desktop"
                self._create_linux_shortcut(shortcut_path, target_path, shortcut_arguments, icon_path)
            messagebox.showinfo(APP_NAME, f"Shortcut created successfully:\n{shortcut_path}")
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))
        finally:
            _safe_rmtree(cleanup_dir)

    def refresh_status(self) -> None:
        self._refresh_selected_theme_metadata()
        ok, errors, warnings, cfg_path, qss_path, splash_path, icon_theme_root = self.validate_theme_folder()
        self.clear_status()
        self.append_status("Ready" if ok else "Needs attention")
        self.append_status("")
        self.append_status(f"Theme file: {self.settings.theme_file}" if self.settings.theme_file else "Theme file: none")
        self.append_status(f"Author Key: {self.settings.author_key_file}" if self.settings.author_key_file else "Author Key: none")
        self.append_status(f"Detected .cfg: {cfg_path}" if cfg_path else "Detected .cfg: none")
        self.append_status(f"Detected .qss: {qss_path}" if qss_path else "Detected .qss: none")
        self.append_status(f"Detected splash image: {splash_path}" if splash_path else "Detected splash image: none")
        self.append_status(f"Detected external icon theme root: {icon_theme_root}" if icon_theme_root else "Detected external icon theme root: none")
        self.append_status("")
        if errors:
            self.append_status("Errors:")
            for item in errors:
                self.append_status(f"- {item}")
            self.append_status("")
        if warnings:
            self.append_status("Warnings:")
            for item in warnings:
                self.append_status(f"- {item}")
            self.append_status("")


def _quote_arg(value: str) -> str:
    if not value:
        return '""'
    escaped = value.replace('"', '\\"')
    if any(ch.isspace() for ch in value) or any(ch in value for ch in '"\''):
        return f'"{escaped}"'
    return value




def _load_saved_settings_for_headless_launch() -> AppSettings:
    settings_candidates: list[Path] = []
    primary_settings_path = _settings_storage_path(_resource_base_dir())
    settings_candidates.append(primary_settings_path)

    legacy_local_settings_path = Path(__file__).resolve().parent / SETTINGS_FILE
    if legacy_local_settings_path not in settings_candidates:
        settings_candidates.append(legacy_local_settings_path)

    for settings_path in settings_candidates:
        if settings_path.exists():
            try:
                data = json.loads(settings_path.read_text(encoding="utf-8"))
                defaults = asdict(AppSettings())
                defaults.update(data)
                return AppSettings(**defaults)
            except Exception as exc:
                raise LauncherError(f"Could not read saved settings:\n{exc}") from exc

    return AppSettings()


def _show_headless_error(message: str) -> None:
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(APP_NAME, message)
        root.destroy()
    except Exception:
        print(message, file=sys.stderr)


def _launch_freecad_without_ui(mode: str) -> int:
    app = None
    destroyed = False
    try:
        settings = _load_saved_settings_for_headless_launch()
        freecad_executable = str(settings.freecad_executable).strip()
        if not freecad_executable:
            raise LauncherError("Saved setting 'FreeCAD executable' is empty.")

        app = ThemeLauncherApp()
        app.withdraw()

        app.vars["freecad_executable"].set(freecad_executable)

        if mode == "user":
            theme_file = str(settings.theme_file).strip()
            if not theme_file:
                raise LauncherError("Saved setting 'Theme' is empty.")
            theme_path = Path(theme_file).expanduser()
            if not theme_path.exists() or not theme_path.is_file():
                raise LauncherError(f"Saved Theme was not found:\n{theme_path}")
            app.vars["user_mode"].set(True)
            app.vars["creator_mode"].set(False)
            app.vars["theme_file"].set(str(theme_path))
            app._collect_ui_to_settings()
            app.launch_from_theme_clicked()
        elif mode == "creator":
            theme_folder = str(settings.theme_folder).strip()
            if not theme_folder:
                raise LauncherError("Saved setting 'Theme Folder' is empty.")
            theme_folder_path = Path(theme_folder).expanduser()
            if not theme_folder_path.exists() or not theme_folder_path.is_dir():
                raise LauncherError(f"Saved Theme Folder was not found:\n{theme_folder_path}")
            app.vars["user_mode"].set(False)
            app.vars["creator_mode"].set(True)
            app.vars["theme_folder"].set(str(theme_folder_path))
            app._collect_ui_to_settings()
            app.launch_freecad()
        else:
            raise LauncherError(f"Unsupported launch mode: {mode}")

        try:
            app.update_idletasks()
        except Exception:
            pass

        try:
            exists = bool(int(app.winfo_exists()))
        except Exception:
            exists = False

        if exists:
            try:
                app.destroy()
            except Exception:
                pass
        else:
            destroyed = True

        return 0
    except Exception as exc:
        if app is not None and not destroyed:
            try:
                exists = bool(int(app.winfo_exists()))
            except Exception:
                exists = False
            if exists:
                try:
                    app.destroy()
                except Exception:
                    pass
        _show_headless_error(str(exc))
        return 1




def _read_theme_package_metadata(theme_file: Path) -> dict[str, str]:
    empty = {
        "copyright": "",
        "license_terms": "",
        "license_notice_brief": "",
        "license_notice": "",
        "license": "",
        "license_text": "",
    }
    try:
        with zipfile.ZipFile(theme_file, "r") as outer_zip:
            if "manifest.json" not in outer_zip.namelist():
                return empty
            manifest = json.loads(outer_zip.read("manifest.json").decode("utf-8"))
            license_text = ""
            if "payload.enc" in outer_zip.namelist():
                try:
                    payload_bytes = _decrypt_payload(outer_zip.read("payload.enc"))
                    with zipfile.ZipFile(io.BytesIO(payload_bytes), "r") as payload_zip:
                        payload_names = set(payload_zip.namelist())
                        for candidate_name in (LICENSE_FILE_NAME, f"files/{LICENSE_FILE_NAME}"):
                            if candidate_name in payload_names:
                                license_text = payload_zip.read(candidate_name).decode("utf-8", errors="replace")
                                break
                except Exception:
                    license_text = ""
        return {
            "copyright": str(manifest.get("copyright", "") or ""),
            "license_terms": str(manifest.get("license_terms", "") or ""),
            "license_notice_brief": str(manifest.get("license_notice_brief", "") or ""),
            "license_notice": str(manifest.get("license_notice", "") or ""),
            "license": str(manifest.get("license", "") or ""),
            "license_text": str(license_text or ""),
        }
    except Exception:
        return empty

def main() -> int:
    try:
        args = sys.argv[1:]
        if "--launch-as-user" in args:
            return _launch_freecad_without_ui("user")
        if "--launch-as-creator" in args:
            return _launch_freecad_without_ui("creator")
        app = ThemeLauncherApp()
        app.mainloop()
        return 0
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
