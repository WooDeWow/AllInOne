"""PDF compression and PDF ↔ Word conversion (100% local)."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def find_soffice() -> str | None:
    """Locate LibreOffice / OpenOffice soffice binary if installed."""
    candidates = [
        "soffice",
        "libreoffice",
        "/usr/bin/soffice",
        "/usr/bin/libreoffice",
        "/usr/lib/libreoffice/program/soffice",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]
    for name in candidates:
        is_abs = os.path.sep in name or (len(name) > 1 and name[1] == ":")
        if is_abs:
            if os.path.isfile(name):
                return name
        else:
            found = shutil.which(name)
            if found:
                return found
    return None


def compress_pdf(
    input_path: str | Path,
    output_path: str | Path,
    level: int = 5,
) -> Path:
    """
    Compress PDF with pikepdf (stream compression + optional image re-encode).
    level: 1–10 (higher = smaller / more aggressive image recompression).
    Falls back to pypdf rewrite if pikepdf fails.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    level = max(1, min(10, int(level)))

    try:
        return _compress_pikepdf(input_path, output_path, level)
    except Exception as pike_err:
        try:
            return _compress_pypdf(input_path, output_path)
        except Exception as pypdf_err:
            raise RuntimeError(
                f"PDF compression failed.\npikepdf: {pike_err}\npypdf: {pypdf_err}"
            ) from pypdf_err


def _compress_pikepdf(input_path: Path, output_path: Path, level: int) -> Path:
    import pikepdf
    from PIL import Image

    # Higher level → lower JPEG quality / smaller max dimension
    jpeg_quality = max(28, 92 - (level * 6))  # ~86 … 32
    max_side = None
    if level >= 8:
        max_side = 1500
    elif level >= 6:
        max_side = 2000
    elif level >= 4:
        max_side = 2800

    with pikepdf.open(input_path) as pdf:
        try:
            pdf.remove_unreferenced_resources()
        except Exception:
            pass

        if level >= 3:
            _recompress_page_images(pdf, jpeg_quality=jpeg_quality, max_side=max_side)

        pdf.save(
            output_path,
            compress_streams=True,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
            recompress_flate=True,
        )

    # If somehow larger, keep the smaller of original rewrite-only vs result
    # (caller still shows sizes; we just ensure we wrote a valid file)
    if not output_path.is_file():
        raise RuntimeError("pikepdf did not write an output file.")
    return output_path


def _recompress_page_images(pdf, jpeg_quality: int, max_side: int | None) -> None:
    """Best-effort re-encode of embedded images (skip on failure)."""
    import pikepdf
    from PIL import Image

    for page in pdf.pages:
        try:
            images = getattr(page, "images", None)
            if not images:
                continue
            for _name, raw in list(images.items()):
                try:
                    pdfimage = pikepdf.PdfImage(raw)
                    pil = pdfimage.as_pil_image()
                except Exception:
                    continue

                try:
                    w, h = pil.size
                    if max_side and max(w, h) > max_side:
                        pil = pil.copy()
                        pil.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)

                    buf = io.BytesIO()
                    # Keep alpha as PNG; photos as JPEG
                    if pil.mode in ("RGBA", "LA"):
                        pil.save(buf, format="PNG", optimize=True)
                        fmt = "png"
                    elif pil.mode == "P":
                        # Palette: convert carefully
                        if "transparency" in pil.info:
                            pil = pil.convert("RGBA")
                            pil.save(buf, format="PNG", optimize=True)
                            fmt = "png"
                        else:
                            pil = pil.convert("RGB")
                            pil.save(
                                buf,
                                format="JPEG",
                                quality=jpeg_quality,
                                optimize=True,
                            )
                            fmt = "jpeg"
                    else:
                        if pil.mode != "RGB":
                            pil = pil.convert("RGB")
                        pil.save(
                            buf,
                            format="JPEG",
                            quality=jpeg_quality,
                            optimize=True,
                        )
                        fmt = "jpeg"

                    buf.seek(0)
                    # pikepdf PdfImage.replace accepts a file-like + pillow format hint
                    try:
                        pdfimage.replace(buf, pillow_image=Image.open(buf))
                    except TypeError:
                        buf.seek(0)
                        try:
                            pdfimage.replace(buf)
                        except Exception:
                            pass
                    except Exception:
                        pass
                except Exception:
                    continue
        except Exception:
            continue


def _compress_pypdf(input_path: Path, output_path: Path) -> Path:
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(input_path))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    try:
        writer.compress_identical_objects()
    except Exception:
        pass
    for page in writer.pages:
        try:
            page.compress_content_streams()
        except Exception:
            pass
    with open(output_path, "wb") as f:
        writer.write(f)
    return output_path


def pdf_to_docx(input_path: str | Path, output_path: str | Path) -> Path:
    """Convert PDF to Word (.docx) using pdf2docx."""
    from pdf2docx import Converter

    input_path = Path(input_path)
    output_path = Path(output_path)
    if output_path.suffix.lower() != ".docx":
        output_path = output_path.with_suffix(".docx")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cv = Converter(str(input_path))
    try:
        cv.convert(str(output_path))
    finally:
        cv.close()
    if not output_path.is_file():
        raise RuntimeError("pdf2docx finished but output file was not created.")
    return output_path


def docx_to_pdf(input_path: str | Path, output_path: str | Path) -> Path:
    """
    Convert Word (.doc/.docx) → PDF via LibreOffice headless.
    Raises RuntimeError with install instructions if soffice is missing.
    """
    input_path = Path(input_path).resolve()
    output_path = Path(output_path).resolve()
    if output_path.suffix.lower() != ".pdf":
        output_path = output_path.with_suffix(".pdf")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    soffice = find_soffice()
    if not soffice:
        raise RuntimeError(_libreoffice_help())

    with tempfile.TemporaryDirectory(prefix="allinone_lo_") as tmp:
        tmp_dir = Path(tmp)
        work_in = tmp_dir / input_path.name
        shutil.copy2(input_path, work_in)

        cmd = [
            soffice,
            "--headless",
            "--nologo",
            "--nofirststartwizard",
            "--convert-to",
            "pdf",
            "--outdir",
            str(tmp_dir),
            str(work_in),
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(
                "LibreOffice conversion timed out after 180s. "
                "Try a smaller document or run soffice manually."
            ) from e
        except FileNotFoundError as e:
            raise RuntimeError(_libreoffice_help()) from e

        produced = tmp_dir / (work_in.stem + ".pdf")
        if not produced.is_file():
            err = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(
                "LibreOffice did not produce a PDF.\n"
                f"Exit code: {proc.returncode}\n"
                f"Details: {err or '(no output)'}\n\n" + _libreoffice_help()
            )
        shutil.copy2(produced, output_path)

    return output_path


def _libreoffice_help() -> str:
    return (
        "LibreOffice is required for Word → PDF (runs fully offline).\n\n"
        "Install LibreOffice, then restart this app:\n"
        "  • Linux:   sudo apt install libreoffice   (or your distro's package)\n"
        "  • macOS:   brew install --cask libreoffice  (or download from libreoffice.org)\n"
        "  • Windows: Download installer from https://www.libreoffice.org/download/\n\n"
        "After install, ensure `soffice` / `libreoffice` is on your PATH "
        "(Windows: typically under 'C:\\Program Files\\LibreOffice\\program')."
    )
