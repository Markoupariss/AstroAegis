#!/bin/bash
set -e
cd "$(dirname "$0")"
python3 -m pip install --upgrade pywebview pyinstaller
pyinstaller --noconfirm --clean --windowed --name AstroAegis \
  --add-data "static:static" --add-data "data:data" --add-data "engine:engine" \
  --add-data "store.py:." --hidden-import webview desktop.py
printf '\nDesktop app created in dist/AstroAegis.app\n'
