# AllInOne — Free File Compressor & Converter

Local web app to **compress PDFs & images**, **convert image formats**, and **convert PDF ↔ Word**.  
Runs **100% offline** after `pip install`. No accounts, no API keys, no cloud services.

## Features

| Feature | How |
|--------|-----|
| Compress PDF | `pikepdf` (+ `pypdf` fallback) |
| Compress images | Pillow (JPEG/PNG/WebP/…) |
| Convert images | jpg, png, webp, gif, bmp, tiff, ico |
| PDF → Word | `pdf2docx` → `.docx` |
| Word → PDF | LibreOffice headless (`soffice`) |

## Install

```bash
cd AllInOne
python3 -m venv .venv

# Linux / macOS
source .venv/bin/activate

# Windows
# .venv\Scripts\activate

pip install -r requirements.txt
```

## Run

```bash
python app.py
```

Open **http://127.0.0.1:7860** in your browser.

## LibreOffice (optional — only for Word → PDF)

Other features work without it. If `soffice` is missing, the UI shows install tips instead of crashing.

- **Linux:** `sudo apt install libreoffice` (or your distro equivalent)
- **macOS:** `brew install --cask libreoffice` or [libreoffice.org](https://www.libreoffice.org/download/)
- **Windows:** install from [libreoffice.org](https://www.libreoffice.org/download/), then ensure  
  `C:\Program Files\LibreOffice\program` is on your PATH (so `soffice` is found)

## Usage tips

- **Compress:** upload → set quality / level → download. Status shows before/after sizes.
- **Image Convert:** pick a target format (e.g. PNG → WebP).
- **PDF → Word:** layout fidelity varies on complex PDFs (tables, multi-column).
- **Word → PDF:** needs LibreOffice once; then fully offline.

## Privacy

Everything stays on your machine. No telemetry.

## License

Use freely. Dependencies are open-source packages under their own licenses.
