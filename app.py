#!/usr/bin/env python3
"""
AllInOne — File Compressor & Converter
Local desktop web UI. Compress PDFs & images to a max size, convert formats, PDF ↔ Word.
"""

from __future__ import annotations

import os
import tempfile

# Disable Gradio telemetry / version phone-home (stay fully local)
os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from pathlib import Path

import gradio as gr

from utils.common import file_size, format_size, size_summary
from utils.images import compress_image_to_target, convert_image, normalize_image_preset
from utils.license import (
    activate_license,
    clear_license,
    get_access,
    record_use,
    status_banner,
)
from utils.pdf_tools import (
    compress_pdf_detailed,
    docx_to_pdf,
    find_soffice,
    normalize_preset,
    pdf_to_docx,
    preset_label,
)

APP_NAME = "AllInOne"
APP_TAGLINE = "Compress · Convert · Stay local"
APP_TITLE = f"{APP_NAME} — File Compressor & Converter"
OUTPUT_ROOT = Path(tempfile.gettempdir()) / "allinone_outputs"
OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

PDF_PRESET_CHOICES = [
    "A little — best quality (recommended)",
    "Medium — balanced",
    "A lot — smaller file",
]

IMAGE_PRESET_CHOICES = [
    "A little — best quality (recommended)",
    "Medium — balanced",
    "A lot — smaller file",
]

MAX_SIZE_MB_CHOICES = [5, 10, 15, 20, 25, 30, 40, 50, 75, 100]
DEFAULT_MAX_MB = 25


def _safe_name(upload_path: str | Path, default_stem: str, suffix: str) -> Path:
    """Build a unique output path under OUTPUT_ROOT."""
    src = Path(upload_path)
    stem = src.stem or default_stem
    out = OUTPUT_ROOT / f"{stem}{suffix}"
    if out.exists():
        i = 1
        while True:
            candidate = OUTPUT_ROOT / f"{stem}_{i}{suffix}"
            if not candidate.exists():
                out = candidate
                break
            i += 1
    return out


def _err(msg: str) -> tuple:
    return None, msg


def _mb_to_bytes(mb) -> int:
    try:
        return int(float(mb) * 1024 * 1024)
    except (TypeError, ValueError):
        return DEFAULT_MAX_MB * 1024 * 1024


def _gate_or_none():
    """Return error tuple if features are locked; else None."""
    info = get_access(force_recheck=False)
    if info.allowed:
        return None
    return _err(
        "🔒 AllInOne is locked — trial ended (7 days or 10 uses).\n"
        "Open the License tab, enter your key, and click Activate."
    )


def _format_target_status(
    *,
    before: int,
    after: int,
    target_bytes: int | None,
    started_label: str,
    final_step: str,
    target_met: bool | None,
    best_effort: bool,
    kind: str = "PDF",
) -> str:
    lines = [
        f"{kind} compression complete.",
        size_summary(before, after),
    ]
    if target_bytes is not None:
        lines.append(f"Target: ≤ {format_size(target_bytes)}")
    lines.append(f"Started with preset: {started_label}")
    if final_step and final_step != started_label:
        lines.append(f"Final step used: {final_step}")

    if target_bytes is None:
        lines.append("No max-size cap applied.")
    elif target_met:
        lines.append("Target met ✓")
    elif best_effort:
        target_mb = target_bytes / (1024 * 1024)
        after_mb = after / (1024 * 1024)
        lines.append(
            f"Could not reach {target_mb:g} MB without destroying quality — "
            f"best effort {after_mb:.2f} MB"
        )
    else:
        lines.append("Target not met.")

    if after >= before:
        lines.append("(No size win — original kept so the file is never made larger.)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tab handlers
# ---------------------------------------------------------------------------

def handle_compress_pdf(file, preset_choice, max_mb):
    gated = _gate_or_none()
    if gated:
        return gated
    if file is None:
        return _err("Please upload a PDF file.")
    try:
        src = Path(file if isinstance(file, str) else file.name)
        if src.suffix.lower() != ".pdf":
            return _err("Please upload a .pdf file.")
        preset = normalize_preset(preset_choice)
        max_bytes = _mb_to_bytes(max_mb)
        out = _safe_name(src, "compressed", ".pdf")
        result = compress_pdf_detailed(
            src, out, preset=preset, max_bytes=max_bytes
        )
        record_use()
        info = _format_target_status(
            before=result.before_bytes,
            after=result.after_bytes,
            target_bytes=result.target_bytes,
            started_label=preset_label(result.started_preset),
            final_step=result.final_step_label,
            target_met=result.target_met,
            best_effort=result.best_effort,
            kind="PDF",
        )
        return str(result.path), info
    except Exception as e:
        return _err(f"PDF compression failed:\n{e}")


def handle_compress_image(file, preset_choice, max_mb, keep_format):
    gated = _gate_or_none()
    if gated:
        return gated
    if file is None:
        return _err("Please upload an image file.")
    try:
        src = Path(file if isinstance(file, str) else file.name)
        max_bytes = _mb_to_bytes(max_mb)
        start = normalize_image_preset(preset_choice)

        if keep_format:
            ext = src.suffix.lower() or ".jpg"
            if not ext.startswith("."):
                ext = f".{ext}"
        else:
            ext = ".jpg"
        out = _safe_name(src, "compressed", ext)

        result = compress_image_to_target(
            src,
            out,
            preset=start,
            max_bytes=max_bytes,
            keep_format=bool(keep_format),
        )
        record_use()

        short = {
            "little": "A little (best quality)",
            "medium": "Medium (balanced)",
            "lot": "A lot (smaller file)",
        }.get(result.started_preset, "A little (best quality)")

        info = _format_target_status(
            before=result.before_bytes,
            after=result.after_bytes,
            target_bytes=result.target_bytes,
            started_label=short,
            final_step=result.final_step_label,
            target_met=result.target_met,
            best_effort=result.best_effort,
            kind="Image",
        )
        dim = (
            f" · Max dimension: {result.max_dim_used}px"
            if result.max_dim_used
            else " · Original dimensions preferred"
        )
        info += f"\nQuality used: {result.quality_used}{dim}"
        return str(result.path), info
    except Exception as e:
        return _err(f"Image compression failed:\n{e}")


def handle_convert_image(file, target_format, quality):
    gated = _gate_or_none()
    if gated:
        return gated
    if file is None:
        return _err("Please upload an image file.")
    try:
        src = Path(file if isinstance(file, str) else file.name)
        before = file_size(src)
        key = target_format.lower().lstrip(".")
        preferred = "jpg" if key == "jpeg" else ("tiff" if key in ("tif", "tiff") else key)
        out = _safe_name(src, "converted", f".{preferred}")
        convert_image(src, out, target_format=key, quality=int(quality))
        after = file_size(out)
        record_use()
        info = (
            f"Converted to {preferred.upper()}.\n"
            f"Before: {format_size(before)} → After: {format_size(after)}"
        )
        return str(out), info
    except Exception as e:
        return _err(f"Image conversion failed:\n{e}")


def handle_pdf_to_docx(file):
    gated = _gate_or_none()
    if gated:
        return gated
    if file is None:
        return _err("Please upload a PDF file.")
    try:
        src = Path(file if isinstance(file, str) else file.name)
        if src.suffix.lower() != ".pdf":
            return _err("Please upload a .pdf file.")
        before = file_size(src)
        out = _safe_name(src, "converted", ".docx")
        pdf_to_docx(src, out)
        after = file_size(out)
        record_use()
        info = (
            f"PDF → Word (.docx) done.\n"
            f"Before: {format_size(before)} → After: {format_size(after)}\n"
            f"Note: complex layouts may not be perfect — this is a local converter."
        )
        return str(out), info
    except Exception as e:
        return _err(f"PDF → Word failed:\n{e}")


def handle_docx_to_pdf(file):
    gated = _gate_or_none()
    if gated:
        return gated
    if file is None:
        return _err("Please upload a Word file (.docx or .doc).")
    try:
        src = Path(file if isinstance(file, str) else file.name)
        if src.suffix.lower() not in (".docx", ".doc"):
            return _err("Please upload a .docx or .doc file.")

        if not find_soffice():
            help_msg = (
                "LibreOffice not found — Word → PDF needs it (still 100% offline).\n\n"
                "Install LibreOffice, then restart this app:\n"
                "  • Linux:   sudo apt install libreoffice\n"
                "  • macOS:   brew install --cask libreoffice\n"
                "  • Windows: https://www.libreoffice.org/download/\n\n"
                "Make sure `soffice` is on your PATH after installing."
            )
            return None, help_msg

        before = file_size(src)
        out = _safe_name(src, "converted", ".pdf")
        docx_to_pdf(src, out)
        after = file_size(out)
        record_use()
        info = (
            f"Word → PDF done (via LibreOffice).\n"
            f"Before: {format_size(before)} → After: {format_size(after)}"
        )
        return str(out), info
    except Exception as e:
        msg = str(e)
        if "LibreOffice" in msg:
            return None, f"{msg}"
        return _err(f"Word → PDF failed:\n{msg}")


def handle_activate(key: str):
    info = activate_license(key or "")
    return info.message, status_banner()


def handle_refresh_license():
    info = get_access(force_recheck=True)
    return info.message, status_banner()


def handle_clear_license():
    info = clear_license()
    return info.message, status_banner()


def _soffice_status_md() -> str:
    path = find_soffice()
    if path:
        return f"**LibreOffice:** found (`{path}`) — Word → PDF is available."
    return (
        "**LibreOffice:** not found — Word → PDF will show install instructions. "
        "All other features work without it."
    )


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

FORMAT_CHOICES = ["jpg", "png", "webp", "gif", "bmp", "tiff", "ico"]

APP_CSS = """
:root {
  --aio-accent: #2563eb;
  --aio-bg: #f8fafc;
  --aio-card: #ffffff;
  --aio-text: #0f172a;
  --aio-muted: #64748b;
  --aio-border: #e2e8f0;
}
.gradio-container {
  max-width: 980px !important;
  margin-left: auto !important;
  margin-right: auto !important;
  font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif !important;
}
.aio-hero {
  background: linear-gradient(135deg, #eff6ff 0%, #f8fafc 55%, #ffffff 100%);
  border: 1px solid var(--aio-border);
  border-radius: 14px;
  padding: 1.25rem 1.5rem 1rem 1.5rem;
  margin-bottom: 0.75rem;
}
.aio-hero h1 {
  margin: 0 0 0.25rem 0 !important;
  font-size: 1.75rem !important;
  font-weight: 700 !important;
  color: var(--aio-text) !important;
  letter-spacing: -0.02em;
}
.aio-tagline {
  color: var(--aio-accent);
  font-weight: 600;
  font-size: 0.95rem;
  margin: 0 0 0.5rem 0;
}
.aio-sub {
  color: var(--aio-muted);
  font-size: 0.92rem;
  margin: 0;
  line-height: 1.45;
}
.aio-banner {
  border: 1px solid var(--aio-border);
  background: var(--aio-card);
  border-radius: 10px;
  padding: 0.65rem 1rem;
  margin: 0.5rem 0 1rem 0;
  font-size: 0.9rem;
}
footer { display: none !important; }
button.primary, .primary {
  min-width: 9rem;
}
"""


def build_ui() -> gr.Blocks:
    with gr.Blocks(title=APP_TITLE, analytics_enabled=False, css=APP_CSS, theme=gr.themes.Soft()) as demo:
        gr.HTML(
            f"""
            <div class="aio-hero">
              <h1>{APP_NAME}</h1>
              <p class="aio-tagline">{APP_TAGLINE}</p>
              <p class="aio-sub">
                Compress PDFs &amp; images to a target size, convert image formats, and convert PDF ↔ Word —
                processing stays on your machine.
              </p>
            </div>
            """
        )
        license_md = gr.Markdown(status_banner(), elem_classes=["aio-banner"])
        gr.Markdown(_soffice_status_md())

        with gr.Tabs():
            # ---- Compress ----
            with gr.Tab("Compress"):
                with gr.Tab("PDF"):
                    gr.Markdown(
                        "### PDF compression\n"
                        "Pick a **quality preset**, then a **max file size**. "
                        "AllInOne starts gentle, then steps up only as needed to hit the target. "
                        "If compression would make the file larger, the original is kept."
                    )
                    pdf_in = gr.File(label="Upload PDF", file_types=[".pdf"])
                    with gr.Row():
                        pdf_preset = gr.Radio(
                            choices=PDF_PRESET_CHOICES,
                            value=PDF_PRESET_CHOICES[0],
                            label="Quality preset",
                        )
                        pdf_max = gr.Dropdown(
                            choices=MAX_SIZE_MB_CHOICES,
                            value=DEFAULT_MAX_MB,
                            label="Max file size (default 25 MB)",
                        )
                    pdf_btn = gr.Button("Compress PDF", variant="primary")
                    pdf_out = gr.File(label="Download compressed PDF")
                    pdf_info = gr.Textbox(label="Status", lines=7)

                    pdf_btn.click(
                        handle_compress_pdf,
                        inputs=[pdf_in, pdf_preset, pdf_max],
                        outputs=[pdf_out, pdf_info],
                    )

                with gr.Tab("Image"):
                    gr.Markdown(
                        "### Image compression\n"
                        "Same idea as PDF: quality preset + optional max size. "
                        "Uncheck “keep format” to save as JPEG for smaller files."
                    )
                    img_in = gr.File(
                        label="Upload image",
                        file_types=[".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".tif", ".ico"],
                    )
                    with gr.Row():
                        img_preset = gr.Radio(
                            choices=IMAGE_PRESET_CHOICES,
                            value=IMAGE_PRESET_CHOICES[0],
                            label="Quality preset",
                        )
                        img_max = gr.Dropdown(
                            choices=MAX_SIZE_MB_CHOICES,
                            value=DEFAULT_MAX_MB,
                            label="Max file size (default 25 MB)",
                        )
                    img_keep = gr.Checkbox(
                        value=True,
                        label="Keep original format (unchecked → save as JPEG for smaller size)",
                    )
                    img_btn = gr.Button("Compress image", variant="primary")
                    img_out = gr.File(label="Download compressed image")
                    img_info = gr.Textbox(label="Status", lines=7)

                    img_btn.click(
                        handle_compress_image,
                        inputs=[img_in, img_preset, img_max, img_keep],
                        outputs=[img_out, img_info],
                    )

            # ---- Image convert ----
            with gr.Tab("Image Convert"):
                gr.Markdown(
                    "Convert between **jpg, png, webp, gif, bmp, tiff, ico**. "
                    "Quality applies to JPEG / WebP."
                )
                conv_in = gr.File(
                    label="Upload image",
                    file_types=[".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".tif", ".ico"],
                )
                with gr.Row():
                    conv_fmt = gr.Dropdown(
                        choices=FORMAT_CHOICES,
                        value="webp",
                        label="Target format",
                    )
                    conv_quality = gr.Slider(
                        10, 95, value=90, step=1,
                        label="Quality (JPEG / WebP)",
                    )
                conv_btn = gr.Button("Convert image", variant="primary")
                conv_out = gr.File(label="Download converted image")
                conv_info = gr.Textbox(label="Status", lines=3)

                conv_btn.click(
                    handle_convert_image,
                    inputs=[conv_in, conv_fmt, conv_quality],
                    outputs=[conv_out, conv_info],
                )

            # ---- PDF ↔ Word ----
            with gr.Tab("PDF ↔ Word"):
                with gr.Row():
                    with gr.Column():
                        gr.Markdown("### PDF → Word (.docx)\nUses **pdf2docx** locally.")
                        p2d_in = gr.File(label="Upload PDF", file_types=[".pdf"])
                        p2d_btn = gr.Button("Convert to Word", variant="primary")
                        p2d_out = gr.File(label="Download .docx")
                        p2d_info = gr.Textbox(label="Status", lines=5)
                        p2d_btn.click(
                            handle_pdf_to_docx,
                            inputs=[p2d_in],
                            outputs=[p2d_out, p2d_info],
                        )

                    with gr.Column():
                        gr.Markdown(
                            "### Word → PDF\n"
                            "Uses **LibreOffice** headless (`soffice`) when installed."
                        )
                        d2p_in = gr.File(label="Upload Word", file_types=[".docx", ".doc"])
                        d2p_btn = gr.Button("Convert to PDF", variant="primary")
                        d2p_out = gr.File(label="Download .pdf")
                        d2p_info = gr.Textbox(label="Status", lines=8)
                        d2p_btn.click(
                            handle_docx_to_pdf,
                            inputs=[d2p_in],
                            outputs=[d2p_out, d2p_info],
                        )

            # ---- License ----
            with gr.Tab("License"):
                gr.Markdown(
                    "### Activate AllInOne\n"
                    "**Trial:** full features for **7 days from first run** or **10 uses** "
                    "(whichever comes first). After that, Compress and Convert lock until you activate.\n\n"
                    "**Licensed:** full access. The app re-checks your key about every 24 hours when online. "
                    "If you are offline but the last check was valid within 7 days, a grace period applies.\n\n"
                    "Paste the license key you received after purchase, then click **Activate**."
                )
                lic_key = gr.Textbox(
                    label="License key",
                    placeholder="AIO-XXXX-XXXX-XXXX",
                    lines=1,
                )
                with gr.Row():
                    lic_activate = gr.Button("Activate", variant="primary")
                    lic_refresh = gr.Button("Re-check")
                    lic_clear = gr.Button("Clear key")
                lic_status = gr.Textbox(label="License status", lines=5)
                gr.Markdown(
                    "*Dev only:* set env `ALLINONE_DEV_UNLOCK=1` to bypass the gate while building. "
                    "Do **not** ship production builds with that set. "
                    "Seller setup: see `LICENSE_SETUP.md` and `config.example.json`."
                )
                lic_activate.click(
                    handle_activate,
                    inputs=[lic_key],
                    outputs=[lic_status, license_md],
                )
                lic_refresh.click(
                    handle_refresh_license,
                    inputs=[],
                    outputs=[lic_status, license_md],
                )
                lic_clear.click(
                    handle_clear_license,
                    inputs=[],
                    outputs=[lic_status, license_md],
                )

        gr.Markdown(
            "---\n"
            f"*{APP_NAME} · {APP_TAGLINE} · Temp outputs: system temp / allinone_outputs*"
        )

    return demo


def main():
    # Touch trial clock / state on launch
    get_access(force_recheck=False)
    demo = build_ui()
    port = int(os.environ.get("ALLINONE_PORT", os.environ.get("GRADIO_SERVER_PORT", "7860")))
    print(f"Starting {APP_TITLE}")
    print(f"Open http://127.0.0.1:{port} in your browser (Ctrl+C to stop)")
    demo.launch(
        server_name="127.0.0.1",
        server_port=port,
        share=False,
        inbrowser=True,
    )


if __name__ == "__main__":
    main()
