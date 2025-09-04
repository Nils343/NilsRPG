"""Utility helpers for the NilsRPG application."""

from collections.abc import Mapping, Sequence
import unicodedata
import os
import tempfile
import importlib.resources as pkg_resources
import sys

if sys.platform.startswith("win"):
    import ctypes
    import winreg
else:  # pragma: no cover - platform specific
    ctypes = None
    winreg = None


def set_user_env_var(name: str, value: str) -> None:
    """Write a user-level environment variable on Windows."""
    if not sys.platform.startswith("win") or winreg is None:  # pragma: no cover
        raise OSError("set_user_env_var is only supported on Windows")
    reg_key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE
    )
    winreg.SetValueEx(reg_key, name, 0, winreg.REG_EXPAND_SZ, value)
    winreg.CloseKey(reg_key)

    HWND_BROADCAST = 0xFFFF
    WM_SETTINGCHANGE = 0x001A
    SMTO_ABORTIFHUNG = 0x0002
    ctypes.windll.user32.SendMessageTimeoutW(
        HWND_BROADCAST,
        WM_SETTINGCHANGE,
        0,
        "Environment",
        SMTO_ABORTIFHUNG,
        5000,
        None,
    )


def clean_unicode(obj):
    """Recursively remove Unicode control characters from mappings and sequences."""
    if isinstance(obj, str):
        return "".join(ch for ch in obj if unicodedata.category(ch)[0] != "C")
    if isinstance(obj, Mapping):
        return {k: clean_unicode(v) for k, v in obj.items()}
    if isinstance(obj, Sequence) and not isinstance(obj, str):
        return type(obj)(clean_unicode(v) for v in obj)
    return obj


def load_embedded_fonts() -> None:
    """Register fonts embedded in the assets package."""
    if not sys.platform.startswith("win") or ctypes is None:  # pragma: no cover
        return
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    fr_private = 0x10
    for family_dir in ("Cormorant_Garamond", "Cardo"):
        pkg = f"assets.{family_dir}"
        for font_name in pkg_resources.contents(pkg):
            if font_name.lower().endswith((".ttf", ".otf")):
                data = pkg_resources.read_binary(pkg, font_name)
                tmpdir = tempfile.gettempdir()
                path = os.path.join(tmpdir, font_name)
                with open(path, "wb") as f:
                    f.write(data)
                ctypes.windll.gdi32.AddFontResourceExW(path, fr_private, 0)

