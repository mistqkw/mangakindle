"""AZW3 — единственный формат, который показывает обложку на главном
экране Kindle при заливке по USB.

PDF, скопированный в documents/, обложки на полке не получает: прошивка
не делает для него миниатюру. AZW3 несёт обложку внутри себя.

Собираем через calibre (`ebook-convert`), потому что своего генератора
KF8 у нас нет. Если calibre не стоит — честно говорим об этом, а не
подсовываем файл, который не откроется.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

CONVERTER = "ebook-convert"
READER = "ebook-meta"

# поля, которые иначе калибр добавит от себя
CONVERT_FLAGS = [
    "--margin-top", "0",
    "--margin-bottom", "0",
    "--margin-left", "0",
    "--margin-right", "0",
    "--disable-font-rescaling",
    "--no-inline-toc",
]

UUID_RE = re.compile(r"mobi-asin:\s*([0-9a-fA-F-]{36})")


class ConvertError(Exception):
    """Текст готов к показу пользователю."""


def available() -> bool:
    return shutil.which(CONVERTER) is not None


def requirement_message() -> str:
    return (
        "Для AZW3 нужен calibre — приложение зовёт его ebook-convert.\n"
        "Поставь: sudo pacman -S calibre (или с calibre-ebook.com).\n"
        "Без него остаются PDF и EPUB."
    )


def from_epub(epub: Path, target: Path) -> Path:
    if not available():
        raise ConvertError(requirement_message())
    target.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [CONVERTER, str(epub), str(target), *CONVERT_FLAGS],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not target.exists():
        tail = (result.stderr or result.stdout or "").strip().splitlines()
        raise ConvertError("calibre не смог собрать AZW3:\n" + "\n".join(tail[-3:]))
    return target


def document_uuid(path: Path) -> str | None:
    """UUID, под которым Kindle хранит миниатюру этого документа."""
    if shutil.which(READER) is None:
        return None
    result = subprocess.run(
        [READER, str(path)], capture_output=True, text=True, check=False
    )
    match = UUID_RE.search(result.stdout or "")
    return match.group(1) if match else None


def extract_cover(path: Path) -> bytes | None:
    """Достаёт обложку из готового AZW3 — для миниатюры на полке Kindle."""
    if shutil.which(READER) is None:
        return None
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        cover = Path(folder) / "cover.jpg"
        subprocess.run(
            [READER, str(path), "--get-cover", str(cover)],
            capture_output=True,
            text=True,
            check=False,
        )
        return cover.read_bytes() if cover.exists() else None
