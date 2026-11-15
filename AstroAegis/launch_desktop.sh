#!/bin/bash
PROJECT_DIR="/Users/parismarkou/Documents/nasa project/AstroAegis"
cd "$PROJECT_DIR" || exit 1

PYTHON="$PROJECT_DIR/.venv/bin/python"

if [ ! -x "$PYTHON" ]; then
    /usr/bin/python3 -m venv "$PROJECT_DIR/.venv"
fi

if ! "$PYTHON" -c "import webview" >/dev/null 2>&1; then
    "$PYTHON" -m pip install pywebview
fi

nohup "$PYTHON" "$PROJECT_DIR/desktop.py" \
    >> "$HOME/Library/Logs/AstroAegis.log" 2>&1 </dev/null &
