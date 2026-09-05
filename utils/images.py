"""Image compress & convert with Pillow."""

from __future__ import annotations

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
