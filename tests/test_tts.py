"""Tests for text-to-speech integration helpers.

These tests exercise a minimal slice of the `_speak_situation` helper to
ensure that it interacts with the asynchronous Google GenAI client using the
correct API surface.  The real client places the streaming functionality under
``client.aio.models.generate_content_stream``.  A regression previously called
``client.aio.responses.stream_generate_content`` which no longer exists and
raised ``AttributeError``.  The tests below replace the GenAI client and audio
output with lightweight fakes so that the method can run without external
dependencies.
"""

from types import SimpleNamespace
import threading

import NilsRPG as nrpg


class DummySDStream:
    """Minimal stand‑in for ``sounddevice.OutputStream``."""

    def __init__(self, *_, **__):
        self.started = False

    def start(self):  # pragma: no cover - simple stub
        self.started = True

    def write(self, arr):  # pragma: no cover - simple stub
        pass

    def stop(self):  # pragma: no cover - simple stub
        pass

    def close(self):  # pragma: no cover - simple stub
        pass


async def _dummy_stream():
    """Yield a single chunk containing fake audio data."""

    yield SimpleNamespace(
        content=SimpleNamespace(parts=[SimpleNamespace(data=b"00")]),
        usage_metadata=None,
    )


def test_speak_situation_streams_via_models(monkeypatch):
    """``_speak_situation`` should call models.generate_content_stream."""

    # Track whether ``generate_content_stream`` was invoked.
    called = {"flag": False}

    def gen_content_stream(**_):
        called["flag"] = True
        return _dummy_stream()

    dummy_client = SimpleNamespace(
        aio=SimpleNamespace(models=SimpleNamespace(generate_content_stream=gen_content_stream))
    )

    # Replace external dependencies with fakes.
    monkeypatch.setattr(nrpg.ga, "ensure_client", lambda: dummy_client)
    monkeypatch.setattr(nrpg, "SOUND_ENABLED", True)
    monkeypatch.setattr(nrpg, "HAVE_SD", True)

    # Provide a fake sounddevice module if one was not imported successfully.
    if not hasattr(nrpg, "sd"):
        monkeypatch.setattr(nrpg, "sd", SimpleNamespace(), raising=False)
    monkeypatch.setattr(nrpg.sd, "OutputStream", lambda *a, **k: DummySDStream(), raising=False)

    # Create a minimally initialised game instance.
    game = nrpg.RPGGame.__new__(nrpg.RPGGame)
    game._audio_stream = None
    game._audio_stream_lock = threading.Lock()
    game._debug_t_text_done = None
    game._debug_logged_once = False
    game.total_audio_prompt_tokens = 0
    game.total_audio_output_tokens = 0

    # Should run without raising and invoke our stubbed method.
    game._speak_situation("hello world")
    assert called["flag"]

