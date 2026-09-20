"""Подготовка страниц под экран Kindle 11th gen: 1072x1448, 300 ppi, серый."""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageFilter, ImageOps

KINDLE_WIDTH = 1072
KINDLE_HEIGHT = 1448

# Pillow иначе ругается на длинные вебтун-страницы
Image.MAX_IMAGE_PIXELS = None


@dataclass
class PageOptions:
    direction: str = "rtl"      # порядок половинок разворота
    spread: str = "split"       # split | rotate | keep
    trim: bool = True
    width: int = KINDLE_WIDTH
    height: int = KINDLE_HEIGHT
    quality: int = 85


def prepare_page(data: bytes, opts: PageOptions) -> list[Image.Image]:
    """Одна скачанная страница -> одна или две готовые картинки Kindle-размера."""
    with Image.open(io.BytesIO(data)) as raw:
        raw.load()
        image = ImageOps.exif_transpose(raw)
        image = image.convert("L")

    if opts.trim:
        image = trim_borders(image)

    parts = handle_spread(image, opts)
    return [_fit_to_screen(part, opts) for part in parts]


def trim_borders(image: Image.Image, tolerance: int = 12, keep: float = 0.15) -> Image.Image:
    """Срезает однотонные поля (белые или чёрные) по краям страницы.

    Если от страницы остаётся меньше keep её площади, считаем обрезку
    ошибкой (страница-заливка, сильный градиент) и оставляем картинку как есть.
    """
    width, height = image.size
    corners = [
        image.getpixel((0, 0)),
        image.getpixel((width - 1, 0)),
        image.getpixel((0, height - 1)),
        image.getpixel((width - 1, height - 1)),
    ]
    corners.sort()
    border = corners[1]

    background = Image.new("L", image.size, border)
    diff = ImageChops.difference(image, background)
    mask = diff.point(lambda p: 255 if p > tolerance else 0)
    bbox = mask.getbbox()
    if not bbox:
        return image

    left, top, right, bottom = bbox
    pad = 2
    bbox = (
        max(0, left - pad),
        max(0, top - pad),
        min(width, right + pad),
        min(height, bottom + pad),
    )
    new_area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
    if new_area < keep * width * height:
        return image
    return image.crop(bbox)


def is_spread(image: Image.Image) -> bool:
    return image.width > image.height


def handle_spread(image: Image.Image, opts: PageOptions) -> list[Image.Image]:
    """Разворот -> две половинки в порядке чтения, поворот или как есть."""
    if not is_spread(image) or opts.spread == "keep":
        return [image]

    if opts.spread == "rotate":
        # Манга читается справа налево: наклоняем страницу так, чтобы
        # правый край развернулся вверх.
        rotation = Image.Transpose.ROTATE_270 if opts.direction == "rtl" else Image.Transpose.ROTATE_90
        return [image.transpose(rotation)]

    middle = image.width // 2
    left = image.crop((0, 0, middle, image.height))
    right = image.crop((middle, 0, image.width, image.height))
    return [right, left] if opts.direction == "rtl" else [left, right]


def _fit_to_screen(image: Image.Image, opts: PageOptions) -> Image.Image:
    """Вписывает страницу в экран без обрезки и добивает поля до точного размера."""
    image = ImageOps.autocontrast(image, cutoff=1)

    scale = min(opts.width / image.width, opts.height / image.height)
    target = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    image = image.resize(target, Image.LANCZOS)
    image = image.filter(ImageFilter.UnsharpMask(radius=1.2, percent=60, threshold=3))

    if image.size == (opts.width, opts.height):
        return image
    canvas = Image.new("L", (opts.width, opts.height), 255)
    canvas.paste(image, ((opts.width - image.width) // 2, (opts.height - image.height) // 2))
    return canvas


def encode_jpeg(image: Image.Image, quality: int = 85) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality, optimize=True, dpi=(300, 300))
    return buffer.getvalue()
