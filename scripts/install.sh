#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
JOBSEARCH_PREPARE_ONLY=1 exec bash "$ROOT_DIR/START_LINUX.sh"
