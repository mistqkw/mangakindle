"""Иконка MangaKindle: пиксельная страница манги с загнутым уголком.

Рисуется по сетке 16x16, масштабируется только целым числом и только
методом NEAREST — ни размытия, ни градиентов. Запуск:

    uv run python assets/make_icon.py [папка]
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

# . — прозрачно, # — тёмная плитка, B — страница, F — тень загнутого уголка, G — облако реплики
GRID = [
    ".##############.",
    "################",
    "###BBBBBBB######",
    "###BBBBBBBF#####",
    "###BBBBBBBFF####",
    "###BBBBBBBBBB###",
    "###BBBGGGGBBB###",
    "###BBGGGGGGBB###",
    "###BBGGGGGGBB###",
    "###BBBGGGGBBB###",
    "###BBBGBBBBBB###",
    "###BBBBBBBBBB###",
    "###BBBBBBBBBB###",
    "###BBBBBBBBBB###",
    "################",
    ".##############.",
]

COLORS = {
    ".": (0, 0, 0, 0),
    "#": (20, 22, 27, 255),      # тёмная плитка TexFi
    "B": (74, 125, 251, 255),    # #4a7dfb — фирменный синий
    "F": (45, 85, 184, 255),     # тот же синий в тени, для уголка
    "G": (20, 22, 27, 255),      # реплика вырезана до цвета плитки
}

SIZES = (16, 24, 32, 48, 64, 128, 256, 512)


def render(cell: int = 1) -> Image.Image:
    size = len(GRID)
    image = Image.new("RGBA", (size, size))
    for y, row in enumerate(GRID):
        for x, char in enumerate(row):
            image.putpixel((x, y), COLORS[char])
    if cell == 1:
        return image
    return image.resize((size * cell, size * cell), Image.NEAREST)


def scaled(pixels: int) -> Image.Image:
    """Точный размер в пикселях. Кратные 16 идут через NEAREST без потерь."""
    base = len(GRID)
    if pixels % base == 0:
        return render(pixels // base)
    cell = max(1, round(pixels / base)) * 4
    return render(cell).resize((pixels, pixels), Image.NEAREST)


def svg() -> str:
    size = len(GRID)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
        f'width="512" height="512" shape-rendering="crispEdges">'
    ]
    for y, row in enumerate(GRID):
        for x, char in enumerate(row):
            rgba = COLORS[char]
            if rgba[3] == 0:
                continue
            color = "#%02x%02x%02x" % rgba[:3]
            parts.append(f'<rect x="{x}" y="{y}" width="1" height="1" fill="{color}"/>')
    parts.append("</svg>")
    return "\n".join(parts)


def main(target: str | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    out = Path(target or Path(__file__).parent / "icons")
    out.mkdir(parents=True, exist_ok=True)
    for size in SIZES:
        scaled(size).save(out / f"mangakindle-{size}.png")
    (out / "mangakindle.svg").write_text(svg(), encoding="utf-8")
    # .ico для Windows-сборки
    scaled(256).save(
        out / "mangakindle.ico",
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"Иконки готовы: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
