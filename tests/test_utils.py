import sys
import pathlib

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
import pytest

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

