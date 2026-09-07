#!/bin/bash
# AllInOne — optional one-time dependency install (macOS)
set -e
cd "$(dirname "$0")"

echo "============================================"
echo "  AllInOne setup"
echo "  Creating/updating .venv and installing deps"
echo "============================================"
echo

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

echo
echo "Setup complete. You can double-click AllInOne.command to launch."
echo "Press Enter to close."
read -r _
