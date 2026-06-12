#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

VENV="$SCRIPT_DIR/.venv"

_spin() {
    local pid=$1 msg=$2 i=0
    local frames=('-' '\' '|' '/')
    while kill -0 "$pid" 2>/dev/null; do
        printf "\r  %s  %s" "${frames[i % 4]}" "$msg"
        sleep 0.1
        (( i++ ))
    done
    printf "\r\033[K"
}

if [ ! -d "$VENV" ]; then
    python3 -m venv "$VENV" &
    _spin $! "Creating virtual environment"
    wait
fi

SENTINEL="$VENV/.installed"
if [ ! -f "$SENTINEL" ] || [ requirements.txt -nt "$SENTINEL" ]; then
    "$VENV/bin/pip" install --quiet -r requirements.txt >/dev/null 2>&1 &
    PIP_PID=$!
    _spin $PIP_PID "Installing dependencies"
    wait $PIP_PID && touch "$SENTINEL"
fi

"$VENV/bin/python3" -u src/build_briefing.py 2>&1 | tee -a data/briefing.log
"$VENV/bin/python3" -u src/run_agent.py 2>&1 | tee -a data/briefing.log
"$VENV/bin/python3" -u src/agent/sessions.py prune 24 2>&1 | tee -a data/briefing.log
