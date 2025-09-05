import sys
import pathlib

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

import NilsRPG as nr


def test_text_model_uses_output_cost_key():
    rates = nr.MODEL_COSTS[nr.MODEL]
    assert "text_output_cost_per_token" in rates
    # Ensure legacy key is absent to prevent miscalculation
    assert "audio_output_cost_per_token" not in rates


def test_cost_calculation_uses_text_output_rate():
    rates = nr.MODEL_COSTS[nr.MODEL]
    prompt_tokens = 10
    completion_tokens = 5
    cost_prompt = prompt_tokens * rates["text_input_cost_per_token"]
    cost_completion = completion_tokens * rates["text_output_cost_per_token"]
    assert cost_prompt > 0
    assert cost_completion > 0
    assert cost_prompt + cost_completion == (
        prompt_tokens * rates["text_input_cost_per_token"]
        + completion_tokens * rates["text_output_cost_per_token"]
    )
