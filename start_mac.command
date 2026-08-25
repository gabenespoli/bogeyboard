#!/bin/bash
# Bogeyboard launcher for macOS — double-click from Finder.
set -e
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
    echo "First run: creating a private Python environment (one-time, a few minutes)..."
    python3 -m venv .venv
    .venv/bin/python -m pip install --upgrade pip --quiet
    .venv/bin/python -m pip install -r requirements.txt
    echo "Setup complete."
fi

echo "Starting Bogeyboard — your browser will open at http://localhost:8501"
.venv/bin/streamlit run app.py

read -n 1 -s -r -p "Dashboard closed. Press any key to close this window."
