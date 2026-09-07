#!/bin/bash
# AllInOne — double-click launcher (macOS)
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "============================================"
  echo "  First-time setup, please wait..."
  echo "  Creating virtual environment and installing"
  echo "  dependencies. This only runs once."
  echo "============================================"
  echo
  python3 -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  python -m pip install --upgrade pip
  pip install -r requirements.txt
  echo
  echo "Setup complete."
  echo
else
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

echo "Starting AllInOne..."
echo "A browser window should open automatically."
echo "Leave this window open while using the app."
echo "Press Ctrl+C to stop."
echo

set +e
python app.py
status=$?
set -e

if [ "$status" -ne 0 ]; then
  echo
  echo "AllInOne exited with an error (code $status)."
  echo "Press Enter to close this window."
  read -r _
  exit "$status"
fi
