#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -x .venv/bin/python ]]; then
  exec .venv/bin/python -m jobsearch_assistant.gui
fi
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m jobsearch_assistant.gui
