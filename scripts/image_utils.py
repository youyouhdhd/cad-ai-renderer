#!/usr/bin/env python3
"""Image helpers used by cad-ai-renderer."""

from __future__ import annotations

import base64
import io
import math
from pathlib import Path
from typing import Iterable, Sequence

from PIL import Image, ImageDraw, ImageFont, ImageOps


def ensure_rgb(image: Image.Image) -> Image.Image:
    if image.mode == "RGB":
        return image
    if image.mode == "RGBA":
        background = Image.new("RGB", image.size, "white")
        background.paste(image, mask=image.getchannel("A"))
        return background
    return image.convert("RGB")


def load_image(path: str | Path) -> Image.Image:
    with Image.open(path) as image:
        return image.copy()


def image_to_data_url(path: str | Path, max_edge: int | None = None, quality: int = 92) -> str:
    image = load_image(path)
    if max_edge and max(image.size) > max_edge:
        image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    image = ensure_rgb(image)
    buffer = io.BytesIO()
    suffix = Path(path).suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        mime = "image/jpeg"
        image.save(buffer, format="JPEG", quality=quality)
    else:
        mime = "image/png"
        image.save(buffer, format="PNG", optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except Exception:
                pass
    return ImageFont.load_default()


def make_contact_sheet(
    images: Sequence[str | Path | Image.Image],
    output_path: str | Path,
    labels: Sequence[str] | None = None,
    columns: int | None = None,
    cell_size: tuple[int, int] = (512, 512),
    margin: int = 16,
    label_height: int = 44,
    background: str = "white",
) -> Path:
    if not images:
        raise ValueError("At least one image is required")
    loaded: list[Image.Image] = []
    for item in images:
        loaded.append(item.copy() if isinstance(item, Image.Image) else load_image(item))
    labels = list(labels or [f"Candidate {index + 1}" for index in range(len(loaded))])
    if len(labels) != len(loaded):
        raise ValueError("labels must have the same length as images")
    columns = columns or min(4, max(1, math.ceil(math.sqrt(len(loaded)))))
    rows = math.ceil(len(loaded) / columns)
    cell_w, cell_h = cell_size
    width = margin + columns * (cell_w + margin)
    height = margin + rows * (cell_h + label_height + margin)
    sheet = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(sheet)
    font = _font(max(16, min(28, label_height - 12)))

    for index, (image, label) in enumerate(zip(loaded, labels)):
        row, column = divmod(index, columns)
        x = margin + column * (cell_w + margin)
        y = margin + row * (cell_h + label_height + margin)
        fitted = ImageOps.contain(ensure_rgb(image), (cell_w, cell_h), Image.Resampling.LANCZOS)
        tile = Image.new("RGB", (cell_w, cell_h), "white")
        px = (cell_w - fitted.width) // 2
        py = (cell_h - fitted.height) // 2
        tile.paste(fitted, (px, py))
        sheet.paste(tile, (x, y))
        draw.rectangle((x, y, x + cell_w - 1, y + cell_h - 1), outline=(190, 190, 190), width=1)
        draw.text((x + 8, y + cell_h + 8), label, fill=(20, 20, 20), font=font)

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
    return output


def save_json_contact_sheet(
    paths: Iterable[str | Path],
    output_path: str | Path,
    labels: Sequence[str] | None = None,
) -> Path:
    items = list(paths)
    return make_contact_sheet(items, output_path, labels=labels)
