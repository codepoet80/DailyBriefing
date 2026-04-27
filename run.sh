#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

VENV="$SCRIPT_DIR/.venv"

# Create venv if it doesn't exist
if [ ! -d "$VENV" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV"
fi

# Reinstall if requirements.txt is newer than the sentinel file
SENTINEL="$VENV/.installed"
if [ ! -f "$SENTINEL" ] || [ requirements.txt -nt "$SENTINEL" ]; then
    echo "Installing dependencies..."
    "$VENV/bin/pip" install --quiet -r requirements.txt && touch "$SENTINEL"
fi

"$VENV/bin/python3" src/build_briefing.py 2>&1 | tee -a data/briefing.log
