"""Utilities for working with the Google GenAI client.

This module centralises API key resolution and client creation so that the
rest of the application can remain agnostic of the underlying SDK. Having a
single, easily mocked location for API access greatly simplifies testing and
development.
"""
from __future__ import annotations

import os
import logging
from google import genai
from google.genai import types, errors

from utils import get_user_env_var

logger = logging.getLogger(__name__)

# Cached client instance and the key used to create it
client: genai.Client | None = None
_client_key: str | None = None

def resolve_api_key() -> str:
    """Return the best available Gemini API key.

    The environment variable ``GEMINI_API_KEY`` takes precedence but we fall
    back to :func:`utils.get_user_env_var` for user-level variables.  When a key
    is found it is written back into ``os.environ`` so that downstream code can
    rely on it.
    """
    key = (
        os.environ.get("GEMINI_API_KEY")
        or get_user_env_var("GEMINI_API_KEY")
        or ""
    ).strip()
    if key:
        os.environ["GEMINI_API_KEY"] = key
    return key

def ensure_client() -> genai.Client | None:
    """Return a Gemini client for the current environment key.

    Lazily creates or updates the cached :class:`google.genai.Client` when the
    API key changes.  ``None`` is returned if no key is available.
    """
    global client, _client_key
    key = resolve_api_key()
    if not key:
        client = None
        _client_key = None
        return None
    if client is None or key != _client_key:
        try:
            client = genai.Client(api_key=key)
            _client_key = key
        except (getattr(errors, "GenAIError", Exception), Exception) as exc:
            logger.error("Failed to create GenAI client: %s", exc)
            client = None
            _client_key = None
            return None
    return client

def set_client_for_key(new_client: genai.Client, key: str) -> None:
    """Replace the cached client with ``new_client`` bound to ``key``.

    Primarily used when the application validates a new API key and wants to
    reuse the instantiated client.
    """
    global client, _client_key
    client = new_client
    _client_key = key

__all__ = [
    "client",
    "ensure_client",
    "resolve_api_key",
    "set_client_for_key",
    "types",
    "errors",
    "genai",
]
