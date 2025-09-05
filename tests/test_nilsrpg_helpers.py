import os
import types
import sys
import pathlib
import base64
from io import BytesIO

from PIL import Image

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

import NilsRPG as nr
import genai_api as ga


def test_parse_world_extracts_sections():
    """Ensure style and difficulty sections are parsed from world.txt."""
    styles, diffs = nr._parse_world()
    assert "Grimdark Fantasy" in styles
    assert styles["Grimdark Fantasy"].startswith("## STYLE:Grimdark Fantasy")
    assert "Peaceful Stroll" in diffs
    assert diffs["Peaceful Stroll"].startswith("## DIFFICULTY:Peaceful Stroll")


def test_resolve_api_key_precedence(monkeypatch):
    """Environment variables take precedence over user-level variables."""
    monkeypatch.setenv("GEMINI_API_KEY", "env_key")
    monkeypatch.setattr(ga, "get_user_env_var", lambda name: "user_key")
    assert ga.resolve_api_key() == "env_key"
    assert os.environ["GEMINI_API_KEY"] == "env_key"

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(ga, "get_user_env_var", lambda name: "user_key")
    assert ga.resolve_api_key() == "user_key"
    assert os.environ["GEMINI_API_KEY"] == "user_key"


def test_ensure_client_reuses_and_updates(monkeypatch):
    """Client is created, cached, and recreated when key changes."""
    class DummyClient:
        def __init__(self, api_key):
            self.api_key = api_key

    monkeypatch.setattr(ga, "genai", types.SimpleNamespace(Client=DummyClient))
    monkeypatch.setattr(ga, "get_user_env_var", lambda name: None)

    # reset globals
    ga.client = None
    ga._client_key = None

    monkeypatch.setenv("GEMINI_API_KEY", "key1")
    c1 = ga.ensure_client()
    assert isinstance(c1, DummyClient)
    assert c1.api_key == "key1"

    # same key returns same instance
    c2 = ga.ensure_client()
    assert c2 is c1

    # changing key creates new client
    monkeypatch.setenv("GEMINI_API_KEY", "key2")
    c3 = ga.ensure_client()
    assert c3 is not c1
    assert c3.api_key == "key2"


def test_ensure_client_handles_error(monkeypatch, caplog):
    """ensure_client returns None and resets state when client creation fails."""

    class DummyError(Exception):
        pass

    def raising_client(api_key):
        raise DummyError("boom")

    monkeypatch.setattr(ga, "genai", types.SimpleNamespace(Client=raising_client))
    monkeypatch.setattr(ga.errors, "GenAIError", DummyError, raising=False)
    monkeypatch.setattr(ga, "get_user_env_var", lambda name: None)

    ga.client = None
    ga._client_key = None
    monkeypatch.setenv("GEMINI_API_KEY", "bad")

    with caplog.at_level("ERROR"):
        assert ga.ensure_client() is None

    assert ga.client is None
    assert ga._client_key is None
    assert "Failed to create GenAI client" in caplog.text


def test_scene_image_fallback_on_invalid_b64():
    """Fallback image should load when scene_image_b64 is invalid."""
    invalid = "not_base64"
    try:
        Image.open(BytesIO(base64.b64decode(invalid)))
    except Exception:
        img_bytes = nr.pkg_resources.read_binary("assets", "default.png")
        img = Image.open(BytesIO(img_bytes))
        assert img.size[0] > 0 and img.size[1] > 0
