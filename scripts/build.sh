#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
. .venv/bin/activate
python -m pip install -e '.[build]'
python -m PyInstaller --noconfirm --clean --onefile --windowed --paths src --name job-search-assistant run_gui.py
printf 'Build complete: dist/job-search-assistant\n'
