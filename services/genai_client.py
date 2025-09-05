"""Simple wrapper around a hypothetical generative AI client."""

from dataclasses import dataclass
import os


@dataclass
class GenAIClient:
    """Represents the external AI service client."""

    api_key: str


def create_client() -> GenAIClient:
    """Create the client using environment configuration."""

    key = os.getenv("GENAI_API_KEY", "")
    return GenAIClient(api_key=key)
