#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

LOG_FILE="$ROOT_DIR/jobsearch-startup.log"
VENV_DIR="$ROOT_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"
PYTHON_CMD=""

{
  printf 'Job Search Assistant startup log\n'
  printf 'Started: %s\n' "$(date --iso-8601=seconds 2>/dev/null || date)"
  printf 'Folder: %s\n\n' "$ROOT_DIR"
} >"$LOG_FILE"

is_noninteractive() {
  [[ "${JOBSEARCH_NONINTERACTIVE:-0}" == "1" ]]
}

pause_on_error() {
  if ! is_noninteractive && [[ -t 0 ]]; then
    printf '\nPress Enter to close...'
    read -r _
  fi
}

show_dependency_help() {
  printf '\nInstall the missing Linux packages, then run START_LINUX.sh again.\n\n'
  if command -v apt-get >/dev/null 2>&1; then
    printf 'Ubuntu / Debian / Linux Mint:\n'
    printf '  sudo apt update && sudo apt install python3 python3-venv python3-tk\n'
  elif command -v dnf >/dev/null 2>&1; then
    printf 'Fedora:\n'
    printf '  sudo dnf install python3 python3-tkinter\n'
  elif command -v pacman >/dev/null 2>&1; then
    printf 'Arch / Manjaro:\n'
    printf '  sudo pacman -S python tk\n'
  elif command -v zypper >/dev/null 2>&1; then
    printf 'openSUSE:\n'
    printf '  sudo zypper install python3 python3-tk\n'
  else
    printf 'Install Python 3.10+, the Python venv module, and Tkinter using your distribution package manager.\n'
  fi
}

fail() {
  local message="$1"
  printf '\n==================================================\n'
  printf '  Job Search Assistant could not start.\n'
  printf '==================================================\n'
  printf '%s\n' "$message"
  printf 'Complete report: %s\n' "$LOG_FILE"
  printf '%s\n' "ERROR: $message" >>"$LOG_FILE"
  pause_on_error
  exit 1
}

on_error() {
  local exit_code=$?
  local line_number=${BASH_LINENO[0]:-unknown}
  local command_name=${BASH_COMMAND:-unknown}
  printf 'Unhandled error on line %s: %s (exit %s)\n' \
    "$line_number" "$command_name" "$exit_code" >>"$LOG_FILE"
  fail "An unexpected error occurred."
}
trap on_error ERR

printf '==================================================\n'
printf '      JOB SEARCH ASSISTANT - ONE CLICK START\n'
printf '==================================================\n\n'
printf 'This script will prepare and open the application.\n\n'

# Reuse a healthy environment. Rebuild it automatically when its Python is broken.
if [[ -e "$VENV_PYTHON" ]]; then
  if ! "$VENV_PYTHON" --version >>"$LOG_FILE" 2>&1; then
    printf 'The existing virtual environment is damaged. Rebuilding it...\n'
    printf 'Existing virtual environment failed its health check.\n' >>"$LOG_FILE"
    rm -rf -- "$VENV_DIR"
  fi
fi

# Find a supported system Python only when a new environment is required.
if [[ ! -x "$VENV_PYTHON" ]]; then
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && \
      "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
        >>"$LOG_FILE" 2>&1; then
      PYTHON_CMD="$candidate"
      break
    fi
  done

  if [[ -z "$PYTHON_CMD" ]]; then
    show_dependency_help
    fail "Python 3.10 or newer was not found."
  fi

  printf '[1/5] Python detected: '
  "$PYTHON_CMD" --version

  printf '[2/5] Creating the private environment...\n'
  if ! "$PYTHON_CMD" -m venv "$VENV_DIR" >>"$LOG_FILE" 2>&1; then
    show_dependency_help
    fail "Python could not create the virtual environment. The venv package may be missing."
  fi
fi

printf '[3/5] Checking the application installation...\n'
if ! "$VENV_PYTHON" -c 'import jobsearch_assistant' >>"$LOG_FILE" 2>&1; then
  printf 'Installing Job Search Assistant for the first time...\n'
  "$VENV_PYTHON" -m pip install --disable-pip-version-check --no-deps -e . \
    >>"$LOG_FILE" 2>&1
  "$VENV_PYTHON" -m jobsearch_assistant init --language es >>"$LOG_FILE" 2>&1
else
  printf 'Application installation found.\n'
fi

printf '[4/5] Checking the desktop interface...\n'
if ! "$VENV_PYTHON" -c 'import tkinter; print("Tkinter", tkinter.TkVersion)' \
  >>"$LOG_FILE" 2>&1; then
  show_dependency_help
  fail "Tkinter is not available in this Python installation."
fi

printf '[5/5] Running diagnostics...\n'
"$VENV_PYTHON" -m jobsearch_assistant doctor 2>&1 | tee -a "$LOG_FILE"

printf 'Diagnostics completed successfully.\n' >>"$LOG_FILE"

# Used by CI and advanced users to prepare the app without opening the desktop window.
if [[ "${JOBSEARCH_PREPARE_ONLY:-0}" == "1" ]]; then
  printf 'Preparation completed successfully.\n'
  printf 'Preparation-only mode completed successfully.\n' >>"$LOG_FILE"
  exit 0
fi

if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
  fail "No graphical desktop session was detected (DISPLAY and WAYLAND_DISPLAY are empty)."
fi

printf '\nOpening Job Search Assistant...\n'
printf 'You may minimize this terminal while the application is open.\n\n'
printf 'Opening GUI at %s.\n' "$(date --iso-8601=seconds 2>/dev/null || date)" >>"$LOG_FILE"

set +e
"$VENV_PYTHON" -X faulthandler -m jobsearch_assistant gui \
  2> >(tee -a "$LOG_FILE" >&2)
APP_EXIT=$?
set -e

if (( APP_EXIT != 0 )); then
  fail "The graphical application exited with code $APP_EXIT."
fi

exit 0
