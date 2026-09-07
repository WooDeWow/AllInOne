#!/bin/bash
# Local / CI macOS packaging with PyInstaller (onedir).
# Gradio apps are flaky under PyInstaller; prefer AllInOne.command for coworkers.
set -euo pipefail
cd "$(dirname "$0")/.."

python -m pip install --upgrade pip
pip install -r requirements.txt
pip install "pyinstaller>=6.0,<7"

# Collect Gradio package data when possible
GRADIO_ARGS=()
if python -c "import gradio, pathlib; print(pathlib.Path(gradio.__file__).parent)" >/dev/null 2>&1; then
  GRADIO_DIR="$(python -c "import gradio, pathlib; print(pathlib.Path(gradio.__file__).parent)")"
  GRADIO_ARGS+=(--collect-all gradio)
  GRADIO_ARGS+=(--collect-all gradio_client)
  # Helpful when templates/static are missed
  if [ -d "$GRADIO_DIR" ]; then
    GRADIO_ARGS+=(--add-data "${GRADIO_DIR}:gradio")
  fi
fi

rm -rf build dist AllInOne.spec

pyinstaller \
  --noconfirm \
  --clean \
  --onedir \
  --name AllInOne \
  --console \
  "${GRADIO_ARGS[@]}" \
  --hidden-import utils \
  --hidden-import utils.common \
  --hidden-import utils.images \
  --hidden-import utils.license \
  --hidden-import utils.pdf_tools \
  --hidden-import pikepdf \
  --hidden-import pypdf \
  --hidden-import pdf2docx \
  --hidden-import PIL \
  app.py

echo
echo "Built: dist/AllInOne/"
echo "Run:   ./dist/AllInOne/AllInOne"
echo "Note: packaged Gradio builds are experimental; coworkers should use AllInOne.command."
