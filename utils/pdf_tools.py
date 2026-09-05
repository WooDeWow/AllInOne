"""PDF compression and PDF ↔ Word conversion (100% local)."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

# Quality-first compression presets
PDF_PRESETS: dict[str, dict] = {
    "little": {
        "label": "A little (best quality)",
        "jpeg_quality": 91,
        "max_side": None,
        "recompress_images": False,  # structure / stream cleanup only
    },
    "medium": {
        "label": "Medium (balanced)",
        "jpeg_quality": 84,
        "max_side": 3200,  # only shrink truly huge images
        "recompress_images": True,
    },
    "lot": {
        "label": "A lot (smaller file)",
        "jpeg_quality": 70,
        "max_side": 2000,
        "recompress_images": True,
    },
}

# Stronger internal steps after named presets (quality-preserving as long as possible)
PDF_EXTRA_STEPS: list[dict] = [
    {"label": "stronger (q60 / 1600px)", "jpeg_quality": 60, "max_side": 1600, "recompress_images": True},
    {"label": "stronger (q50 / 1400px)", "jpeg_quality": 50, "max_side": 1400, "recompress_images": True},
    {"label": "stronger (q42 / 1200px)", "jpeg_quality": 42, "max_side": 1200, "recompress_images": True},
    {"label": "stronger (q35 / 1000px)", "jpeg_quality": 35, "max_side": 1000, "recompress_images": True},
    {"label": "stronger (q28 / 800px)", "jpeg_quality": 28, "max_side": 800, "recompress_images": True},
]

# UI / status aliases
PRESET_ALIASES: dict[str, str] = {
    "little": "little",
    "a little": "little",
    "a little — best quality (recommended)": "little",
    "medium": "medium",
    "medium — balanced": "medium",
    "lot": "lot",
    "a lot": "lot",
    "a lot — smaller file": "lot",
}

PRESET_ORDER = ("little", "medium", "lot")


def normalize_preset(preset: str | None) -> str:
    """Map UI label or short key to little|medium|lot."""
    if not preset:
        return "little"
    key = str(preset).strip().lower()
    # Exact alias
    if key in PRESET_ALIASES:
        return PRESET_ALIASES[key]
    # Prefix / contains
    if key.startswith("a little") or key == "little":
        return "little"
    if key.startswith("medium"):
        return "medium"
    if key.startswith("a lot") or key == "lot":
        return "lot"
    return "little"


def preset_label(preset: str | None) -> str:
    """Human-readable preset name for status text."""
    key = normalize_preset(preset)
    return PDF_PRESETS[key]["label"]


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


def _level_to_preset(level: int) -> str:
    """Internal mapping if a numeric level is still passed."""
    level = max(1, min(10, int(level)))
    if level <= 3:
        return "little"
    if level <= 6:
        return "medium"
    return "lot"


def _build_aggressiveness_ladder(start_preset: str) -> list[dict]:
    """Named presets from start upward, then stronger internal steps."""
    start = normalize_preset(start_preset)
    try:
        idx = PRESET_ORDER.index(start)
    except ValueError:
        idx = 0
    steps: list[dict] = []
    for key in PRESET_ORDER[idx:]:
        cfg = dict(PDF_PRESETS[key])
        cfg["step_key"] = key
        steps.append(cfg)
    for i, extra in enumerate(PDF_EXTRA_STEPS):
        cfg = dict(extra)
        cfg["step_key"] = f"extra_{i}"
        steps.append(cfg)
    return steps


@dataclass
class CompressResult:
    path: Path
    before_bytes: int
    after_bytes: int
    target_bytes: int | None
    started_preset: str
    final_step_label: str
    target_met: bool | None  # None if no target set
    best_effort: bool


def compress_pdf(
    input_path: str | Path,
    output_path: str | Path,
    preset: str = "little",
    level: int | None = None,
    max_bytes: int | None = None,
) -> Path:
    """
    Compress PDF with pikepdf (stream compression + optional image re-encode).

    preset: "little" | "medium" | "lot" (quality-first; default little).
    level: optional legacy 1–10.
    max_bytes: optional size cap — steps up aggressiveness until under target
               (or best effort). Never writes an output larger than the input
               if a smaller rewrite exists.
    Falls back to pypdf rewrite if pikepdf fails.
    """
    result = compress_pdf_detailed(
        input_path,
        output_path,
        preset=preset,
        level=level,
        max_bytes=max_bytes,
    )
    return result.path


def compress_pdf_detailed(
    input_path: str | Path,
    output_path: str | Path,
    preset: str = "little",
    level: int | None = None,
    max_bytes: int | None = None,
) -> CompressResult:
    """Like compress_pdf but returns size/target metadata for UI status."""
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if level is not None and (
        preset is None
        or str(preset).strip() == ""
        or str(preset).strip().isdigit()
    ):
        start_key = _level_to_preset(int(level))
    else:
        start_key = normalize_preset(preset)

    before = input_path.stat().st_size
    target = int(max_bytes) if max_bytes and max_bytes > 0 else None

    # Effective target never asks for larger than input (we always prefer ≤ input)
    effective_target = target
    if effective_target is not None:
        effective_target = min(effective_target, before)

    ladder = _build_aggressiveness_ladder(start_key)
    best_path: Path | None = None
    best_size = before + 1
    best_label = PDF_PRESETS[start_key]["label"]
    target_met = False if effective_target is not None else None

    with tempfile.TemporaryDirectory(prefix="allinone_pdf_") as tmp:
        tmp_dir = Path(tmp)
        for step_i, cfg in enumerate(ladder):
            candidate = tmp_dir / f"step_{step_i}.pdf"
            try:
                result = _compress_pikepdf(
                    input_path,
                    candidate,
                    jpeg_quality=int(cfg["jpeg_quality"]),
                    max_side=cfg["max_side"],
                    recompress_images=bool(cfg["recompress_images"]),
                )
            except Exception as pike_err:
                if step_i == 0:
                    # First step: allow pypdf fallback once
                    try:
                        result = _compress_pypdf(input_path, candidate)
                    except Exception as pypdf_err:
                        raise RuntimeError(
                            f"PDF compression failed.\npikepdf: {pike_err}\npypdf: {pypdf_err}"
                        ) from pypdf_err
                else:
                    continue

            try:
                size = Path(result).stat().st_size
            except OSError:
                continue

            # Track best (smallest) rewrite that is ≤ input
            if size <= before and size < best_size:
                best_size = size
                best_label = str(cfg.get("label") or cfg.get("step_key"))
                # Copy into a stable best slot
                best_slot = tmp_dir / "best.pdf"
                shutil.copy2(result, best_slot)
                best_path = best_slot

            if effective_target is not None and size <= effective_target:
                # Prefer this if ≤ target (and preferably ≤ input)
                if size <= before:
                    shutil.copy2(result, output_path)
                    return CompressResult(
                        path=Path(output_path),
                        before_bytes=before,
                        after_bytes=size,
                        target_bytes=target,
                        started_preset=start_key,
                        final_step_label=str(cfg.get("label") or cfg.get("step_key")),
                        target_met=True,
                        best_effort=False,
                    )
                # Over input but under target — still keep looking for ≤ input
                target_met = True

            # If no size target, stop after the user's starting preset (first step)
            if effective_target is None:
                break

            # Meaningful shrink stall: if we already have ≤ target, done above;
            # if last few steps barely help, ladder will exhaust naturally.

        # Decide final output
        if best_path is not None and best_size <= before:
            shutil.copy2(best_path, output_path)
            after = best_size
            final_label = best_label
        else:
            # No smaller rewrite — keep original (never enlarge)
            shutil.copy2(input_path, output_path)
            after = before
            final_label = PDF_PRESETS[start_key]["label"] + " (original kept)"

        if effective_target is not None:
            target_met = after <= effective_target
            best_effort = not target_met
        else:
            target_met = None
            best_effort = False

        return CompressResult(
            path=Path(output_path),
            before_bytes=before,
            after_bytes=after,
            target_bytes=target,
            started_preset=start_key,
            final_step_label=final_label,
            target_met=target_met,
            best_effort=best_effort,
        )


def _compress_pikepdf(
    input_path: Path,
    output_path: Path,
    jpeg_quality: int,
    max_side: int | None,
    recompress_images: bool,
) -> Path:
    import pikepdf

    with pikepdf.open(input_path) as pdf:
        try:
            pdf.remove_unreferenced_resources()
        except Exception:
            pass

        if recompress_images:
            _recompress_page_images(
                pdf,
                jpeg_quality=jpeg_quality,
                max_side=max_side,
                only_if_smaller=True,
            )

        pdf.save(
            output_path,
            compress_streams=True,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
            recompress_flate=True,
        )

    if not output_path.is_file():
        raise RuntimeError("pikepdf did not write an output file.")
    return output_path


def _recompress_page_images(
    pdf,
    jpeg_quality: int,
    max_side: int | None,
    only_if_smaller: bool = True,
) -> None:
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
                    # Approximate original stream size when available
                    try:
                        orig_len = len(raw.read_bytes())
                    except Exception:
                        try:
                            orig_len = len(raw.get_stream_buffer())
                        except Exception:
                            orig_len = None

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

                    data = buf.getvalue()
                    if only_if_smaller and orig_len is not None and len(data) >= orig_len:
                        # Re-encode would not shrink this image — keep original
                        continue

                    buf.seek(0)
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
