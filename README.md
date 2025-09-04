# Nils' RPG

A Tk/ttkbootstrap desktop RPG that uses Google's Gemini via the `google-genai` SDK.

## Quick start (Windows)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:GEMINI_API_KEY="your_key_here"
python NilsRPG.py