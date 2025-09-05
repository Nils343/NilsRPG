import sys
import pathlib

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

import billing


def test_compute_text_costs():
    rates = {"text_input_cost_per_token": 0.1, "text_output_cost_per_token": 0.2}
    cp, cc, total = billing.compute_text_costs(10, 5, rates)
    assert cp == 1.0
    assert cc == 1.0
    assert total == 2.0


def test_compute_audio_costs():
    rates = {"text_input_cost_per_token": 0.1, "audio_output_cost_per_token": 0.3}
    cp, co, total = billing.compute_audio_costs(10, 5, rates)
    assert cp == 1.0
    assert co == 1.5
    assert total == 2.5


def test_compute_image_costs():
    rates = {"output_cost_per_image": 0.5}
    assert billing.compute_image_costs(3, rates) == 1.5


def test_text_completion_uses_text_output_rate():
    rates = {
        "text_input_cost_per_token": 0.0,
        "text_output_cost_per_token": 0.2,
        "audio_output_cost_per_token": 0.9,
    }
    _, completion_cost, _ = billing.compute_text_costs(0, 1, rates)
    assert completion_cost == rates["text_output_cost_per_token"]
    assert completion_cost != rates["audio_output_cost_per_token"]
