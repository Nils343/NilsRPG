# Nils' RPG

A Tk/ttkbootstrap desktop RPG that uses Google's Gemini via the `google-genai` SDK.

## Quick start (Windows)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:GEMINI_API_KEY="your_key_here"
python NilsRPG.py
```

The application will automatically read your `GEMINI_API_KEY` from the Windows
user environment, even when running inside a virtual environment. You can also
configure or update the key from the in‑game **API** menu, which also lets you
set the text model's thinking budget (0‑4096) for deeper reasoning.

## Narration models

Nils' RPG uses Gemini's text-to-speech models to read story updates aloud. The
default configuration targets `gemini-2.5-flash-preview-tts`, a low-latency TTS
model able to speak several sentences at once. For higher quality narration you
can switch to `gemini-2.5-pro-preview-tts` from the in-game **API** menu. Real-
time experiments can use the `gemini-live-2.5-flash-preview` model.
