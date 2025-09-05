# AGENTS Instructions

This repository contains a small Tk based role playing game.  The code is organised as follows:

- `NilsRPG.py` – the thin Tk user interface.
- `config.py` – dataclass based configuration handling.
- `services/` – service classes and helpers for AI, audio and image generation.
- `storage/` – saving and loading of game state.
- `state.py` – dataclasses representing in‑memory game state.
- `tests/` – unit tests.  Run with `python -m unittest -q`.

## Development rules

- Do not modify widget styling or fonts in the UI code.
- Keep `NilsRPG.py` free from direct file, network, or multimedia I/O.
- All new code should use dataclasses where appropriate.

## Verification commands

Before committing ensure the following commands run and pass:

```bash
python -m unittest -q
python -m compileall .
grep -R "pickle" -n NilsRPG.py || true
grep -R "genai" -n NilsRPG.py || true
grep -R "Image" -n NilsRPG.py || true
```

The grep commands should produce **no output** indicating forbidden terms are absent.
