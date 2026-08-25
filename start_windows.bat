@echo off
rem Bogeyboard launcher for Windows — double-click this file.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo First run: creating a private Python environment ^(one-time, a few minutes^)...
    python -m venv .venv
    .venv\Scripts\python -m pip install --upgrade pip --quiet
    .venv\Scripts\python -m pip install -r requirements.txt
    echo Setup complete.
)

echo Starting Bogeyboard — your browser will open at http://localhost:8501
.venv\Scripts\streamlit run app.py

pause
