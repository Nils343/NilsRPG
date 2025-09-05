from dataclasses import dataclass
from typing import Mapping, Tuple


@dataclass
class Rates:
    """Pricing information for a model.

    All fields default to ``0`` so missing rates are treated as free.
    """
    text_input_cost_per_token: float = 0.0
    text_output_cost_per_token: float = 0.0
    audio_output_cost_per_token: float = 0.0
    output_cost_per_image: float = 0.0

    @classmethod
    def from_mapping(cls, data: Mapping[str, float]) -> "Rates":
        return cls(
            text_input_cost_per_token=data.get("text_input_cost_per_token", 0.0),
            text_output_cost_per_token=data.get("text_output_cost_per_token", 0.0),
            audio_output_cost_per_token=data.get("audio_output_cost_per_token", 0.0),
            output_cost_per_image=data.get("output_cost_per_image", 0.0),
        )


def compute_text_costs(prompt_tokens: int, completion_tokens: int, rates: Mapping[str, float]) -> Tuple[float, float, float]:
    """Return (prompt_cost, completion_cost, total) for text tokens."""
    r = Rates.from_mapping(rates)
    cost_prompt = prompt_tokens * r.text_input_cost_per_token
    cost_completion = completion_tokens * r.text_output_cost_per_token
    return cost_prompt, cost_completion, cost_prompt + cost_completion


def compute_audio_costs(prompt_tokens: int, output_tokens: int, rates: Mapping[str, float]) -> Tuple[float, float, float]:
    """Return (prompt_cost, output_cost, total) for audio tokens."""
    r = Rates.from_mapping(rates)
    cost_prompt = prompt_tokens * r.text_input_cost_per_token
    cost_output = output_tokens * r.audio_output_cost_per_token
    return cost_prompt, cost_output, cost_prompt + cost_output


def compute_image_costs(image_count: int, rates: Mapping[str, float]) -> float:
    """Return total cost for ``image_count`` images."""
    r = Rates.from_mapping(rates)
    return image_count * r.output_cost_per_image
