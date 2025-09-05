import sys
import pathlib
import os
import types

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
import pytest

import utils
from utils import (
    clean_unicode,
    set_user_env_var,
    load_embedded_fonts,
    get_user_env_var,
    get_response_tokens,
)

from google.genai.types import UsageMetadata, GenerateContentResponseUsageMetadata


def test_clean_unicode_removes_control_chars():
    """Verify control characters are stripped from nested collections."""

    data = {
        'text': 'Hello\x00World',
        'list': ['A\x01', 'B'],
        'tuple': ('C', 'D\x02'),
    }
    cleaned = clean_unicode(data)
    assert cleaned == {
        'text': 'HelloWorld',
        'list': ['A', 'B'],
        'tuple': ('C', 'D'),
    }


@pytest.mark.skipif(sys.platform.startswith('win'), reason='Windows-specific functionality')
def test_set_user_env_var_raises_on_non_windows():
    """set_user_env_var should raise on unsupported platforms."""

    with pytest.raises(OSError):
        set_user_env_var('TEST_VAR', 'value')


@pytest.mark.skipif(sys.platform.startswith('win'), reason='Windows-specific functionality')
def test_load_embedded_fonts_noop_on_non_windows():
    """load_embedded_fonts should exit quietly on non-Windows systems."""

    # Should simply return without raising on non-Windows systems
    assert load_embedded_fonts() is None


def test_get_user_env_var_reads_from_env(monkeypatch):
    """On non-Windows platforms the helper falls back to os.environ."""

    # Ensure variable missing initially
    monkeypatch.delenv('TEST_VAR', raising=False)
    assert get_user_env_var('TEST_VAR') is None

    # When present in the environment it should be returned
    monkeypatch.setenv('TEST_VAR', 'value')
    assert get_user_env_var('TEST_VAR') == 'value'


def test_get_response_tokens_handles_legacy_and_new_fields():
    """Ensure response token extraction works for both SDK variants."""

    modern = UsageMetadata(response_token_count=7)
    legacy = GenerateContentResponseUsageMetadata(candidates_token_count=9)

    assert get_response_tokens(modern) == 7
    assert get_response_tokens(legacy) == 9
    # When no relevant field exists, result should be zero
    assert get_response_tokens(UsageMetadata()) == 0


def test_get_response_tokens_returns_zero_when_explicitly_zero():
    """Ensure zero response_token_count is respected without fallback."""

    both = type(
        "Usage", (), {"response_token_count": 0, "candidates_token_count": 9}
    )()
    assert get_response_tokens(both) == 0


def test_load_embedded_fonts_registers_and_cleans(monkeypatch, tmp_path):
    """Fonts written to temporary files should be cleaned up on exit."""

    utils._FONT_TEMP_FILES.clear()
    monkeypatch.setattr(utils.sys, "platform", "win32")

    dummy_gdi = types.SimpleNamespace(
        AddFontResourceExW=lambda *args: 1,
        RemoveFontResourceExW=lambda *args: 1,
    )
    dummy_windll = types.SimpleNamespace(
        gdi32=dummy_gdi,
        shcore=types.SimpleNamespace(SetProcessDpiAwareness=lambda *args: None),
    )
    monkeypatch.setattr(utils, "ctypes", types.SimpleNamespace(windll=dummy_windll))
    monkeypatch.setattr(utils.pkg_resources, "contents", lambda pkg: ["fake.ttf"])
    monkeypatch.setattr(utils.pkg_resources, "read_binary", lambda pkg, name: b"data")
    monkeypatch.setenv("TMP", str(tmp_path))

    load_embedded_fonts()
    assert utils._FONT_TEMP_FILES
    temp_path = utils._FONT_TEMP_FILES[0]
    assert os.path.exists(temp_path)

    utils._cleanup_fonts()
    assert not os.path.exists(temp_path)

