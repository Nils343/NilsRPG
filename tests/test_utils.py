import sys
import pathlib

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
import pytest

from utils import clean_unicode, set_user_env_var, load_embedded_fonts


def test_clean_unicode_removes_control_chars():
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
    with pytest.raises(OSError):
        set_user_env_var('TEST_VAR', 'value')


@pytest.mark.skipif(sys.platform.startswith('win'), reason='Windows-specific functionality')
def test_load_embedded_fonts_noop_on_non_windows():
    # Should simply return without raising on non-Windows systems
    assert load_embedded_fonts() is None

