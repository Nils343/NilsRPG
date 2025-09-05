"""Utility helpers for the NilsRPG application."""

from collections.abc import Mapping, Sequence
import unicodedata
import os
import tempfile
import importlib.resources as pkg_resources
import sys
import atexit

if sys.platform.startswith("win"):
    import ctypes
    import winreg
else:  # pragma: no cover - platform specific
    ctypes = None
    winreg = None


_FONT_TEMP_FILES: list[str] = []


def _cleanup_fonts() -> None:
    """Remove registered fonts and delete temporary files."""
    if not _FONT_TEMP_FILES or ctypes is None or not sys.platform.startswith("win"):
        return
    fr_private = 0x10
    for path in _FONT_TEMP_FILES:
        try:
            ctypes.windll.gdi32.RemoveFontResourceExW(path, fr_private, 0)
        except Exception:  # pragma: no cover - best effort cleanup
            pass
        try:
            os.remove(path)
        except OSError:  # pragma: no cover - best effort cleanup
            pass


atexit.register(_cleanup_fonts)


def set_user_env_var(name: str, value: str) -> None:
    """Write a user-level environment variable on Windows.

    This uses the Windows registry and broadcasts an update message so that
    new processes inherit the variable immediately.
    """
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


def get_user_env_var(name: str) -> str | None:
    r"""Retrieve a user-level environment variable on Windows.

    This helper reads the ``HKCU\Environment`` registry key so that values
    configured globally are discovered even when the current process environment
    does not include them (for example when running inside a virtual
    environment).  On non-Windows platforms it simply falls back to
    ``os.environ``.
    """
    if not sys.platform.startswith("win") or winreg is None:
        return os.environ.get(name)
    try:
        reg_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment")
        try:
            value, _ = winreg.QueryValueEx(reg_key, name)
            return value
        finally:
            winreg.CloseKey(reg_key)
    except FileNotFoundError:
        return os.environ.get(name)


def clean_unicode(obj):
    """Recursively strip Unicode control characters from nested structures."""
    if isinstance(obj, str):
        return "".join(ch for ch in obj if unicodedata.category(ch)[0] != "C")
    if isinstance(obj, Mapping):
        return {k: clean_unicode(v) for k, v in obj.items()}
    if isinstance(obj, Sequence) and not isinstance(obj, str):
        return type(obj)(clean_unicode(v) for v in obj)
    return obj


def get_response_tokens(usage) -> int:
    """Return generated token count from a usage metadata object.

    The Google GenAI SDK has used different attribute names for this value
    across API surfaces.  The modern ``responses`` API exposes
    ``response_token_count`` while the older ``models.generate_content`` API
    provided ``candidates_token_count``.  This helper checks for both so callers
    remain compatible regardless of which object type they receive.  When the
    attribute is missing or ``usage`` is ``None`` the function returns ``0``.
    """

    if usage is None:  # pragma: no cover - defensive
        return 0

    if hasattr(usage, "response_token_count") and getattr(
        usage, "response_token_count"
    ) is not None:
        return getattr(usage, "response_token_count")

    if hasattr(usage, "candidates_token_count") and getattr(
        usage, "candidates_token_count"
    ) is not None:
        return getattr(usage, "candidates_token_count")

    return 0


def load_embedded_fonts() -> None:
    """Register fonts embedded in the assets package.

    On Windows the fonts are written to a temporary directory and registered
    with the system for the duration of the process.
    """
    if not sys.platform.startswith("win") or ctypes is None:  # pragma: no cover
        return
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    fr_private = 0x10
    for family_dir in ("Cormorant_Garamond", "Cardo"):
        pkg = f"assets.{family_dir}"
        for font_name in pkg_resources.contents(pkg):
            if font_name.lower().endswith((".ttf", ".otf")):
                data = pkg_resources.read_binary(pkg, font_name)
                suffix = os.path.splitext(font_name)[1]
                fd, path = tempfile.mkstemp(suffix=suffix)
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                ctypes.windll.gdi32.AddFontResourceExW(path, fr_private, 0)
                _FONT_TEMP_FILES.append(path)

