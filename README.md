# Nils' RPG

A tiny Tk based role playing demo.  The user interface is intentionally slim and
delegates most work to service modules.

## Quick start

```bash
python NilsRPG.py  # launches the UI
```

## Running the tests

```bash
python -m unittest -q
python -m compileall .
```

The project also uses simple grep checks to ensure the UI remains thin:

```bash
grep -R "pickle" -n NilsRPG.py || true
grep -R "genai" -n NilsRPG.py || true
grep -R "Image" -n NilsRPG.py || true
```

All commands should produce no output.

## Module layout

- `NilsRPG.py` – Tk user interface.
- `config.py` – application configuration.
- `services/` – narrative, audio, image and AI helpers.
- `storage/` – versioned JSON save files.
- `state.py` – dataclasses for game state.
- `tests/` – unit tests.
