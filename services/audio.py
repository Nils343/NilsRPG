"""Audio narration helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Narrator:
    """Very small text to speech stub."""

    last_text: str | None = None
    stopped: bool = False

    def speak(self, text: str) -> None:
        self.last_text = text
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True
