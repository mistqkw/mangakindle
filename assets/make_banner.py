"""Баннер и аватарка канала в стиле TexFi.

Пиксельная графика рисуется по сетке и масштабируется только NEAREST,
текст — Press Start 2P на заголовке и обычный шрифт на подписях.

    uv run python assets/make_banner.py [папка]
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).parent))
from make_icon import GRID, render  # noqa: E402

BG = (20, 22, 27)
SURFACE = (28, 32, 38)
BORDER = (47, 54, 65)
TEXT = (232, 236, 242)
MUTED = (138, 148, 166)
ACCENT = (74, 125, 251)
PAPER = (224, 196, 140)

PIXEL_FONT = Path.home() / ".local/share/fonts/texfi/PressStart2P-Regular.ttf"
BODY_FONTS = (
    Path("/usr/share/fonts/TTF/OpenSans-Regular.ttf"),
    Path("/usr/share/fonts/TTF/OpenSans-CondensedRegular.ttf"),
    Path("/usr/share/fonts/TTF/DejaVuSans.ttf"),
)


def pixel_font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(PIXEL_FONT), size)


def body_font(size: int) -> ImageFont.FreeTypeFont:
    for path in BODY_FONTS:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _dotted_grid(image: Image.Image, step: int = 16) -> None:
    """Еле заметная пиксельная сетка вместо градиента."""
    draw = ImageDraw.Draw(image)
    for y in range(0, image.height, step):
        for x in range(0, image.width, step):
            draw.point((x, y), fill=(28, 31, 38))


# Kindle: слэб с подбородком, на экране — страница из трёх панелей
KINDLE_GRID = [
    "################",
    "################",
    "##SSSSSSSSSSSS##",
    "##SPPPPPPPPPPS##",
    "##SPPPPPPPPPPS##",
    "##SPPPPPPPPPPS##",
    "##SSSSSSSSSSSS##",
    "##SPPPPSSPPPPS##",
    "##SPPPPSSPPPPS##",
    "##SPPPPSSPPPPS##",
    "##SSSSSSSSSSSS##",
    "##SPPPPPPPPPPS##",
    "##SPPPPPPPPPPS##",
    "##SSSSSSSSSSSS##",
    "################",
    "################",
    "################",
    "################",
]
KINDLE_COLORS = {
    "#": (47, 54, 65),
    "S": (232, 224, 208),
    "P": (34, 32, 30),
}


def kindle(cell: int) -> Image.Image:
    width, height = len(KINDLE_GRID[0]), len(KINDLE_GRID)
    image = Image.new("RGB", (width, height))
    for y, row in enumerate(KINDLE_GRID):
        for x, char in enumerate(row):
            image.putpixel((x, y), KINDLE_COLORS[char])
    return image.resize((width * cell, height * cell), Image.NEAREST)


def arrow(cell: int, color=ACCENT) -> Image.Image:
    grid = [
        "......#....",
        "......##...",
        "......###..",
        "###########",
        "###########",
        "###########",
        "......###..",
        "......##...",
        "......#....",
    ]
    width, height = len(grid[0]), len(grid)
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for y, row in enumerate(grid):
        for x, char in enumerate(row):
            if char == "#":
                image.putpixel((x, y), (*color, 255))
    return image.resize((width * cell, height * cell), Image.NEAREST)


def _blocks(draw: ImageDraw.ImageDraw, x: int, y: int, count: int, filled: int,
            size: int = 18, gap: int = 6) -> None:
    """Полоска прогресса из блоков — узнаваемый элемент интерфейса."""
    for index in range(count):
        left = x + index * (size + gap)
        draw.rectangle(
            [left, y, left + size - 1, y + size - 1],
            fill=ACCENT if index < filled else BORDER,
        )


def _icon_symbol(cell: int) -> Image.Image:
    """Иконка без тёмной плитки — на баннере она лишняя."""
    from make_icon import COLORS

    width, height = len(GRID[0]), len(GRID)
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for y, row in enumerate(GRID):
        for x, char in enumerate(row):
            if char in ("B", "F", "G"):
                image.putpixel((x, y), COLORS[char])
    return image.resize((width * cell, height * cell), Image.NEAREST)


def banner(width: int = 1280, height: int = 640) -> Image.Image:
    image = Image.new("RGB", (width, height), BG)
    _dotted_grid(image)
    draw = ImageDraw.Draw(image)

    margin, shadow = 26, 6
    box = [margin, margin, width - margin - shadow, height - margin - shadow]
    draw.rectangle([box[0] + shadow, box[1] + shadow, box[2] + shadow, box[3] + shadow],
                   fill=(11, 13, 17))
    draw.rectangle(box, fill=SURFACE, outline=BORDER, width=4)

    # заголовок по центру
    # имя короткое, поэтому кегль крупнее, а под ним поясняющая строка
    title_font = pixel_font(72)
    title = "y0mu"
    draw.text(((width - draw.textlength(title, font=title_font)) // 2, 84),
              title, font=title_font, fill=ACCENT)

    sub_font = body_font(26)
    sub = "манга на Kindle"
    draw.text(((width - draw.textlength(sub, font=sub_font)) // 2, 176),
              sub, font=sub_font, fill=MUTED)

    # ряд-история: страница -> стрелка -> Kindle
    page = _icon_symbol(14)          # 16*14 = 224
    device = kindle(13)              # 16*13 = 208 в ширину
    tip = arrow(8)
    gap = 56
    row_width = page.width + gap + tip.width + gap + device.width
    x = (width - row_width) // 2
    row_top = 238
    row_height = max(page.height, device.height)

    image.paste(page, (x, row_top + (row_height - page.height) // 2), page)
    x += page.width + gap
    image.paste(tip, (x, row_top + (row_height - tip.height) // 2), tip)
    x += tip.width + gap
    image.paste(device, (x, row_top + (row_height - device.height) // 2))

    # подписи
    tagline = "ссылка с mangalib — готовый файл на устройстве"
    tag_font = body_font(30)
    draw.text(((width - draw.textlength(tagline, font=tag_font)) // 2, 468),
              tagline, font=tag_font, fill=TEXT)

    formats = "PDF · AZW3 · EPUB     по USB и почтой"
    fmt_font = body_font(24)
    draw.text(((width - draw.textlength(formats, font=fmt_font)) // 2, 512),
              formats, font=fmt_font, fill=PAPER)

    link = "github.com/mistqkw/y0mu"
    link_font = body_font(22)
    draw.text(((width - draw.textlength(link, font=link_font)) // 2, 552),
              link, font=link_font, fill=MUTED)
    return image


def avatar(size: int = 512) -> Image.Image:
    """Квадратная аватарка: только силуэт, без текста.

    Telegram обрезает аватарку в круг, поэтому символ ужат до 80% —
    иначе загнутый уголок и углы страницы уходят под обрезку."""
    cell = int(size * 0.8) // len(GRID)      # целое число пикселей на клетку
    icon = _icon_symbol(cell)
    image = Image.new("RGB", (size, size), BG)
    _dotted_grid(image)
    image.paste(icon, ((size - icon.width) // 2, (size - icon.height) // 2), icon)
    return image


def main(target: str | None = None) -> int:
    out = Path(target or Path(__file__).parent / "channel")
    out.mkdir(parents=True, exist_ok=True)
    banner().save(out / "banner-1280x640.png")
    avatar().save(out / "avatar-512.png")
    print(f"Готово: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
