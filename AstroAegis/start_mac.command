#!/bin/bash
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  osascript -e 'display alert "Python 3 is required" message "Install Python 3.10 or later, then reopen AstroAegis."'
  exit 1
fi
python3 desktop.py
