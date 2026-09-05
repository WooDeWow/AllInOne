#!/usr/bin/env python3
"""
AllInOne — Free File Compressor & Converter
100% local / offline after pip install. No APIs, no accounts, no telemetry.
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
from utils.images import compress_image, convert_image
from utils.pdf_tools import compress_pdf, docx_to_pdf, find_soffice, pdf_to_docx

APP_TITLE = "AllInOne — Free File Compressor & Converter"
OUTPUT_ROOT = Path(tempfile.gettempdir()) / "allinone_outputs"
OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)


def _safe_name(upload_path: str | Path, default_stem: str, suffix: str) -> Path:
    """Build a unique output path under OUTPUT_ROOT."""
    src = Path(upload_path)
    stem = src.stem or default_stem
    out = OUTPUT_ROOT / f"{stem}{suffix}"
    # Avoid clobbering if user runs twice quickly
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


# ---------------------------------------------------------------------------
# Tab handlers
# ---------------------------------------------------------------------------

def handle_compress_pdf(file, level):
    if file is None:
        return _err("Please upload a PDF file.")
    try:
        src = Path(file if isinstance(file, str) else file.name)
        if src.suffix.lower() != ".pdf":
            return _err("Please upload a .pdf file.")
        before = file_size(src)
        out = _safe_name(src, "compressed", ".pdf")
        compress_pdf(src, out, level=int(level))
        after = file_size(out)
        info = (
            f"✅ PDF compressed successfully.\n"
            f"{size_summary(before, after)}\n"
            f"Compression level: {int(level)}/10"
        )
        return str(out), info
    except Exception as e:
        return _err(f"❌ PDF compression failed:\n{e}")


def handle_compress_image(file, quality, max_dim, keep_format):
    if file is None:
        return _err("Please upload an image file.")
    try:
        src = Path(file if isinstance(file, str) else file.name)
        before = file_size(src)
        max_dimension = int(max_dim) if max_dim and int(max_dim) > 0 else None

        if keep_format:
            ext = src.suffix.lower() or ".jpg"
            if not ext.startswith("."):
                ext = f".{ext}"
            out = _safe_name(src, "compressed", ext)
        else:
            # Default compressed output to JPEG for max size savings
            out = _safe_name(src, "compressed", ".jpg")

        compress_image(src, out, quality=int(quality), max_dimension=max_dimension)
        after = file_size(out)
        info = (
            f"✅ Image compressed successfully.\n"
            f"{size_summary(before, after)}\n"
            f"Quality: {int(quality)}"
            + (f" · Max dimension: {max_dimension}px" if max_dimension else " · Original dimensions kept")
        )
        return str(out), info
    except Exception as e:
        return _err(f"❌ Image compression failed:\n{e}")


def handle_convert_image(file, target_format, quality):
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
        info = (
            f"✅ Converted to {preferred.upper()}.\n"
            f"Before: {format_size(before)} → After: {format_size(after)}"
        )
        return str(out), info
    except Exception as e:
        return _err(f"❌ Image conversion failed:\n{e}")


def handle_pdf_to_docx(file):
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
        info = (
            f"✅ PDF → Word (.docx) done.\n"
            f"Before: {format_size(before)} → After: {format_size(after)}\n"
            f"Note: complex layouts may not be perfect — this is a free local converter."
        )
        return str(out), info
    except Exception as e:
        return _err(f"❌ PDF → Word failed:\n{e}")


def handle_docx_to_pdf(file):
    if file is None:
        return _err("Please upload a Word file (.docx or .doc).")
    try:
        src = Path(file if isinstance(file, str) else file.name)
        if src.suffix.lower() not in (".docx", ".doc"):
            return _err("Please upload a .docx or .doc file.")

        if not find_soffice():
            help_msg = (
                "⚠️ LibreOffice not found — Word → PDF needs it (still 100% offline).\n\n"
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
        info = (
            f"✅ Word → PDF done (via LibreOffice).\n"
            f"Before: {format_size(before)} → After: {format_size(after)}"
        )
        return str(out), info
    except Exception as e:
        # Surface install help without a scary traceback for the common case
        msg = str(e)
        if "LibreOffice" in msg:
            return None, f"⚠️ {msg}"
        return _err(f"❌ Word → PDF failed:\n{msg}")


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
.status-ok textarea { color: #0a7; }
footer { display: none !important; }
"""


def build_ui() -> gr.Blocks:
    with gr.Blocks(title=APP_TITLE, analytics_enabled=False, css=APP_CSS) as demo:
        gr.Markdown(
            f"# {APP_TITLE}\n"
            "Compress PDFs & images, convert image formats, and convert PDF ↔ Word — "
            "**fully offline**, no accounts, no paid APIs.\n\n"
            + _soffice_status_md()
        )

        with gr.Tabs():
            # ---- Compress ----
            with gr.Tab("Compress"):
                with gr.Tab("PDF"):
                    gr.Markdown("Reduce PDF file size (structure + optional image recompression).")
                    pdf_in = gr.File(label="Upload PDF", file_types=[".pdf"])
                    pdf_level = gr.Slider(
                        1, 10, value=5, step=1,
                        label="Compression level (higher = smaller, may reduce image quality)",
                    )
                    pdf_btn = gr.Button("Compress PDF", variant="primary")
                    pdf_out = gr.File(label="Download compressed PDF")
                    pdf_info = gr.Textbox(label="Status", lines=4)

                    pdf_btn.click(
                        handle_compress_pdf,
                        inputs=[pdf_in, pdf_level],
                        outputs=[pdf_out, pdf_info],
                    )

                with gr.Tab("Image"):
                    gr.Markdown(
                        "Compress JPEG, PNG, WebP, and other common image formats. "
                        "Uses Pillow — quality slider controls re-encode strength."
                    )
                    img_in = gr.File(
                        label="Upload image",
                        file_types=[".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".tif", ".ico"],
                    )
                    img_quality = gr.Slider(
                        10, 95, value=75, step=1,
                        label="Quality (higher = better looking / larger file)",
                    )
                    img_max_dim = gr.Number(
                        value=0,
                        label="Max dimension in px (0 = keep original size)",
                        precision=0,
                    )
                    img_keep = gr.Checkbox(
                        value=True,
                        label="Keep original format (unchecked → save as JPEG for smaller size)",
                    )
                    img_btn = gr.Button("Compress image", variant="primary")
                    img_out = gr.File(label="Download compressed image")
                    img_info = gr.Textbox(label="Status", lines=4)

                    img_btn.click(
                        handle_compress_image,
                        inputs=[img_in, img_quality, img_max_dim, img_keep],
                        outputs=[img_out, img_info],
                    )

            # ---- Image convert ----
            with gr.Tab("Image Convert"):
                gr.Markdown(
                    "Convert between: **jpg, png, webp, gif, bmp, tiff, ico**."
                )
                conv_in = gr.File(
                    label="Upload image",
                    file_types=[".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".tif", ".ico"],
                )
                conv_fmt = gr.Dropdown(
                    choices=FORMAT_CHOICES,
                    value="webp",
                    label="Target format",
                )
                conv_quality = gr.Slider(
                    10, 95, value=90, step=1,
                    label="Quality (for JPEG / WebP)",
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
                        gr.Markdown("### PDF → Word (.docx)\nUses **pdf2docx** (local).")
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

        gr.Markdown(
            "---\n"
            "*All processing happens on your machine. Temp outputs go to your system temp folder.*"
        )

    return demo


def main():
    demo = build_ui()
    port = int(os.environ.get("ALLINONE_PORT", os.environ.get("GRADIO_SERVER_PORT", "7860")))
    print(f"Starting {APP_TITLE}")
    print(f"Open http://127.0.0.1:{port} in your browser (Ctrl+C to stop)")
    # Local-only server; share=False means no Gradio public tunnel
    demo.launch(
        server_name="127.0.0.1",
        server_port=port,
        share=False,
        inbrowser=False,
    )


if __name__ == "__main__":
    main()
