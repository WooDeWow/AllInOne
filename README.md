# AllInOne — File Compressor & Converter

**Compress · Convert · Stay local**

Desktop web app to **compress PDFs & images to a max size**, **convert image formats**, and **convert PDF ↔ Word**.  
Runs on your machine. Optional indie license gate for sellers (Google Sheets + Apps Script).

---

## Launch (coworkers — no Terminal)

Unzip the folder, then double-click the launcher for your OS. On first run it creates a local `.venv` and installs dependencies (wait for “First-time setup…”). When the app starts, **your browser opens automatically**.

### Mac

1. Unzip `AllInOne`.
2. Double-click **`AllInOne.command`**.
3. First run installs packages (please wait); later runs start faster.
4. Browser opens to the app. Leave the Terminal window open while you use it.

**If macOS Gatekeeper blocks it:** Right-click `AllInOne.command` → **Open** → confirm Open. (Or: System Settings → Privacy & Security → allow.)

Optional: double-click **`Setup Once.command`** first if you want to install dependencies without starting the app yet.

### Windows

1. Unzip `AllInOne`.
2. Double-click **`AllInOne.bat`**.
3. First run installs packages (please wait); later runs start faster.
4. Browser opens to the app. Leave the Command Prompt window open while you use it.

Requires **Python 3** installed and on PATH ([python.org](https://www.python.org/downloads/) — check “Add python.exe to PATH”).

Optional: double-click **`Setup Once.bat`** for a one-time install without launching.

---

## Features

| Feature | Details |
|--------|---------|
| Compress PDF | Quality presets (**A little / Medium / A lot**) + **max size** target (5–100 MB, default **25 MB**) |
| Compress images | Same presets + max size target |
| Convert images | jpg, png, webp, gif, bmp, tiff, ico |
| PDF → Word | `pdf2docx` → `.docx` |
| Word → PDF | LibreOffice headless (`soffice`) |
| License | Trial then key activation (see below) |

### Max file size (PDF & images)

1. Starts from your quality preset (preserves quality as long as possible).
2. If still over the target, steps up aggressiveness (medium → lot → stronger internal JPEG / resize steps).
3. Never returns a file larger than the input when a smaller rewrite exists.
4. Status shows before / after / target / starting preset / whether the target was met (or a clear best-effort message).

---

## Packaged desktop builds (experimental / for selling)

GitHub Actions workflow **Build desktop** (`.github/workflows/build-desktop.yml`) builds **onedir** apps with PyInstaller on:

- `macos-latest` → artifact **`AllInOne-mac`**
- `windows-latest` → artifact **`AllInOne-windows`**

Trigger via **workflow_dispatch** or a version tag (`v*`). Local helpers: `scripts/build_mac.sh`, `scripts/build_windows.bat`.

> **Caveat:** PyInstaller + Gradio is fragile (missing static assets, large folders). Treat CI/release artifacts as **experimental**. The primary coworker path remains **`AllInOne.command` / `AllInOne.bat`**.

---

## Install & run (developers / Terminal)

```bash
cd AllInOne
python3 -m venv .venv

# Linux / macOS
source .venv/bin/activate

# Windows
# .venv\Scripts\activate

pip install -r requirements.txt
python app.py
```

Browser should open automatically (`inbrowser=True`). Or open **http://127.0.0.1:7860**.

### Dev unlock (builders only)

```bash
export ALLINONE_DEV_UNLOCK=1   # bypass license gate while developing — not for production
python app.py
```

---

## License & trial (customers)

- **Trial:** full features for **7 days from first run** or **10 uses** (whichever comes first).
- Then Compress / Convert lock until you activate a key on the **License** tab.
- Licensed installs re-check about every **24 hours** when online; **7-day offline grace** after a successful check.
- Keys are stored in `~/.allinone/license.json` (survives git pulls).

## For sellers

See **[LICENSE_SETUP.md](LICENSE_SETUP.md)** — use your private Google Sheet + Apps Script Web App as the license database.

1. Copy `config.example.json` → `config.json`.
2. Deploy the Apps Script from the setup doc (bound to sheet ID `1-ucqexWNSVjXSivPqnosI2BNRSaIjwndVj8dVIFnmS0`).
3. Put the **Web App** URL in `config.json` as `license_url` (never the spreadsheet `/edit` link).
4. Issue keys by adding rows; revoke by setting Status to `revoked`.

```bash
cp config.example.json config.json
# edit license_url
```

Or: `export ALLINONE_LICENSE_URL='https://script.google.com/macros/s/.../exec'`

## LibreOffice (optional — only for Word → PDF)

Other features work without it. If `soffice` is missing, the UI shows install tips.

- **Linux:** `sudo apt install libreoffice`
- **macOS:** `brew install --cask libreoffice` or [libreoffice.org](https://www.libreoffice.org/download/)
- **Windows:** install from [libreoffice.org](https://www.libreoffice.org/download/), ensure `soffice` is on PATH

## Privacy

Compression and conversion stay on your machine. The only network call (when configured) is a license key check to **your** Apps Script endpoint. Gradio analytics are disabled.

## Requirements

See `requirements.txt` (Gradio, Pillow, pikepdf, pypdf, pdf2docx).
