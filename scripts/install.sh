#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
python -m jobsearch_assistant init --language es
printf 'Installation complete. Run ./scripts/run-gui.sh\n'
