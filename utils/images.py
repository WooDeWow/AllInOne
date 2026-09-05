"""Image compress & convert with Pillow."""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

# Formats we accept for conversion output
SUPPORTED_OUT = {
    "jpg": "JPEG",
    "jpeg": "JPEG",
    "png": "PNG",
    "webp": "WEBP",
    "gif": "GIF",
    "bmp": "BMP",
    "tiff": "TIFF",
    "tif": "TIFF",
    "ico": "ICO",
}

# Modes that need conversion for certain formats
_RGB_ONLY = {"JPEG", "BMP"}
_RGBA_FRIENDLY = {"PNG", "WEBP", "GIF", "TIFF", "ICO"}

# Named presets (quality-first)
IMAGE_PRESETS: dict[str, dict] = {
    "little": {"label": "A little (best quality)", "quality": 90, "max_dim": 0},
    "medium": {"label": "Medium (balanced)", "quality": 78, "max_dim": 0},
    "lot": {"label": "A lot (smaller file)", "quality": 65, "max_dim": 2000},
}

IMAGE_EXTRA_STEPS: list[dict] = [
    {"label": "stronger (q55 / 1600px)", "quality": 55, "max_dim": 1600},
    {"label": "stronger (q45 / 1280px)", "quality": 45, "max_dim": 1280},
    {"label": "stronger (q35 / 1024px)", "quality": 35, "max_dim": 1024},
    {"label": "stronger (q28 / 800px)", "quality": 28, "max_dim": 800},
]

PRESET_ORDER = ("little", "medium", "lot")


def normalize_image_preset(preset: str | None) -> str:
    if not preset:
        return "little"
    key = str(preset).strip().lower()
    if key.startswith("a little") or key == "little":
        return "little"
    if key.startswith("medium"):
        return "medium"
    if key.startswith("a lot") or key == "lot":
        return "lot"
    if key in IMAGE_PRESETS:
        return key
    return "little"


def _build_image_ladder(start_preset: str) -> list[dict]:
    start = normalize_image_preset(start_preset)
    try:
        idx = PRESET_ORDER.index(start)
    except ValueError:
        idx = 0
    steps: list[dict] = []
    for key in PRESET_ORDER[idx:]:
        cfg = dict(IMAGE_PRESETS[key])
        cfg["step_key"] = key
        steps.append(cfg)
    for i, extra in enumerate(IMAGE_EXTRA_STEPS):
        cfg = dict(extra)
        cfg["step_key"] = f"extra_{i}"
        steps.append(cfg)
    return steps


def _load(path: str | Path) -> Image.Image:
    img = Image.open(path)
    # Load fully so file handle can close
    img.load()
    return img


def _prepare_for_format(img: Image.Image, fmt: str) -> Image.Image:
    """Convert mode so Pillow can save to the target format."""
    fmt = fmt.upper()
    if fmt == "JPEG":
        if img.mode in ("RGBA", "LA", "P"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            alpha = img.split()[-1] if img.mode in ("RGBA", "LA") else None
            if alpha is not None:
                background.paste(img, mask=alpha)
            else:
                background.paste(img)
            return background
        if img.mode != "RGB":
            return img.convert("RGB")
        return img
    if fmt == "ICO":
        # ICO works best with RGBA; resize if huge (browsers/OS expect small icons)
        img = img.convert("RGBA") if img.mode != "RGBA" else img
        max_side = max(img.size)
        if max_side > 256:
            img = img.copy()
            img.thumbnail((256, 256), Image.Resampling.LANCZOS)
        return img
    if fmt == "GIF":
        # Simple palette GIF (no animation stitching)
        if img.mode not in ("P", "L"):
            return img.convert("P", palette=Image.Palette.ADAPTIVE, colors=256)
        return img
    if fmt in _RGBA_FRIENDLY:
        return img
    if fmt in _RGB_ONLY and img.mode not in ("RGB", "L"):
        return img.convert("RGB")
    return img


@dataclass
class ImageCompressResult:
    path: Path
    before_bytes: int
    after_bytes: int
    target_bytes: int | None
    started_preset: str
    final_step_label: str
    target_met: bool | None
    best_effort: bool
    quality_used: int
    max_dim_used: int | None


def compress_image(
    input_path: str | Path,
    output_path: str | Path,
    quality: int = 75,
    max_dimension: int | None = None,
) -> Path:
    """
    Re-encode image to reduce size.
    quality: 1–95 (JPEG/WebP). PNG uses compress_level derived from quality.
    max_dimension: optional longest-side resize (None = keep original size).
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    quality = max(1, min(95, int(quality)))
    img = _load(input_path)

    if max_dimension and max_dimension > 0:
        w, h = img.size
        longest = max(w, h)
        if longest > max_dimension:
            img = img.copy()
            img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

    # Prefer keeping a compressed-friendly format based on extension / original
    ext = output_path.suffix.lower().lstrip(".")
    if not ext:
        # Default: JPEG for photos, PNG otherwise
        orig = input_path.suffix.lower().lstrip(".")
        ext = orig if orig in SUPPORTED_OUT else "jpg"
        output_path = output_path.with_suffix(f".{ext}")

    fmt = SUPPORTED_OUT.get(ext, "JPEG")
    img = _prepare_for_format(img, fmt)

    save_kwargs: dict = {}
    if fmt in ("JPEG", "WEBP"):
        save_kwargs["quality"] = quality
        save_kwargs["optimize"] = True
        if fmt == "JPEG":
            save_kwargs["progressive"] = True
    elif fmt == "PNG":
        # Map quality slider (higher = better looking / larger) → compress_level 0–9
        # High quality → lower compress effort is fine; we always optimize.
        compress_level = max(0, min(9, round((100 - quality) / 10)))
        save_kwargs["optimize"] = True
        save_kwargs["compress_level"] = compress_level
    elif fmt == "GIF":
        save_kwargs["optimize"] = True

    img.save(output_path, format=fmt, **save_kwargs)
    return output_path


def compress_image_to_target(
    input_path: str | Path,
    output_path: str | Path,
    preset: str = "little",
    max_bytes: int | None = None,
    keep_format: bool = True,
) -> ImageCompressResult:
    """
    Compress with quality preset, then step up aggressiveness until ≤ max_bytes
    (or best effort). Never returns a file larger than the input if a smaller
    rewrite exists.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    start = normalize_image_preset(preset)
    before = input_path.stat().st_size
    target = int(max_bytes) if max_bytes and max_bytes > 0 else None
    effective_target = min(target, before) if target is not None else None

    if keep_format:
        ext = input_path.suffix.lower() or ".jpg"
        if not ext.startswith("."):
            ext = f".{ext}"
    else:
        ext = ".jpg"

    # Ensure output has correct extension for this run
    out_base = output_path.with_suffix(ext)

    ladder = _build_image_ladder(start)
    best_path: Path | None = None
    best_size = before + 1
    best_label = IMAGE_PRESETS[start]["label"]
    best_q = int(IMAGE_PRESETS[start]["quality"])
    best_dim: int | None = None

    with tempfile.TemporaryDirectory(prefix="allinone_img_") as tmp:
        tmp_dir = Path(tmp)
        for step_i, cfg in enumerate(ladder):
            quality = int(cfg["quality"])
            max_dim = int(cfg["max_dim"]) if cfg.get("max_dim") else None
            candidate = tmp_dir / f"step_{step_i}{ext}"
            try:
                compress_image(
                    input_path,
                    candidate,
                    quality=quality,
                    max_dimension=max_dim,
                )
                size = candidate.stat().st_size
            except Exception:
                continue

            if size <= before and size < best_size:
                best_size = size
                best_label = str(cfg.get("label") or cfg.get("step_key"))
                best_q = quality
                best_dim = max_dim
                best_slot = tmp_dir / f"best{ext}"
                shutil.copy2(candidate, best_slot)
                best_path = best_slot

            if effective_target is not None and size <= effective_target and size <= before:
                shutil.copy2(candidate, out_base)
                return ImageCompressResult(
                    path=out_base,
                    before_bytes=before,
                    after_bytes=size,
                    target_bytes=target,
                    started_preset=start,
                    final_step_label=str(cfg.get("label") or cfg.get("step_key")),
                    target_met=True,
                    best_effort=False,
                    quality_used=quality,
                    max_dim_used=max_dim,
                )

            if effective_target is None:
                break

        if best_path is not None and best_size <= before:
            shutil.copy2(best_path, out_base)
            after = best_size
            final_label = best_label
            q_used = best_q
            dim_used = best_dim
        else:
            shutil.copy2(input_path, out_base)
            after = before
            final_label = IMAGE_PRESETS[start]["label"] + " (original kept)"
            q_used = int(IMAGE_PRESETS[start]["quality"])
            dim_used = None

        if effective_target is not None:
            target_met = after <= effective_target
            best_effort = not target_met
        else:
            target_met = None
            best_effort = False

        return ImageCompressResult(
            path=out_base,
            before_bytes=before,
            after_bytes=after,
            target_bytes=target,
            started_preset=start,
            final_step_label=final_label,
            target_met=target_met,
            best_effort=best_effort,
            quality_used=q_used,
            max_dim_used=dim_used,
        )


def convert_image(
    input_path: str | Path,
    output_path: str | Path,
    target_format: str,
    quality: int = 90,
) -> Path:
    """Convert image to another format (jpg/png/webp/gif/bmp/tiff/ico)."""
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    key = target_format.lower().lstrip(".")
    if key not in SUPPORTED_OUT:
        raise ValueError(
            f"Unsupported format '{target_format}'. "
            f"Choose one of: {', '.join(sorted(set(SUPPORTED_OUT.keys())))}"
        )

    fmt = SUPPORTED_OUT[key]
    # Normalize extension on output
    preferred_ext = "jpg" if key == "jpeg" else ("tif" if key == "tiff" else key)
    if key == "tif":
        preferred_ext = "tiff"
    output_path = output_path.with_suffix(f".{preferred_ext}")

    img = _load(input_path)
    img = _prepare_for_format(img, fmt)

    quality = max(1, min(95, int(quality)))
    save_kwargs: dict = {}
    if fmt in ("JPEG", "WEBP"):
        save_kwargs["quality"] = quality
        save_kwargs["optimize"] = True
    elif fmt == "PNG":
        save_kwargs["optimize"] = True
        save_kwargs["compress_level"] = 6
    elif fmt == "GIF":
        save_kwargs["optimize"] = True

    img.save(output_path, format=fmt, **save_kwargs)
    return output_path
