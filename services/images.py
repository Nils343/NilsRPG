"""Image generation service stub."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable


Callback = Callable[[bytes], None]


@dataclass
class PictureService:
    """Thread safe image generation helper."""

    def __post_init__(self) -> None:
        self._lock = threading.Lock()

    def generate(self, prompt: str, callback: Callback | None = None) -> None:
        """Generate an image for *prompt* and invoke *callback* asynchronously."""

        def worker() -> None:
            data = b""  # placeholder image bytes
            if callback:
                callback(data)

        threading.Thread(target=worker, daemon=True).start()

    def save(self, data: bytes, path: str) -> None:
        """Persist *data* to *path* in a thread safe manner."""

        with self._lock:
            with open(path, "wb") as f:
                f.write(data)
