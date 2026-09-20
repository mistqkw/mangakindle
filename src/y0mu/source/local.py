"""Запасной источник: страницы, сохранённые вручную.

Принимает папку с картинками, папку с подпапками-главами или ZIP/CBZ.
Нужен, когда глава закрыта на сайте — приложение ничего не обходит,
но собрать файл из того, что у тебя уже есть, оно умеет.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from .models import ChapterRef, MangaInfo, SourceError

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"}


def _natural_key(name: str) -> list:
    """Сортировка, при которой page2 идёт раньше page10."""
    parts: list = []
    number = ""
    for char in name.lower():
        if char.isdigit():
            number += char
        else:
            if number:
                parts.append((1, int(number), ""))
                number = ""
            parts.append((0, 0, char))
    if number:
        parts.append((1, int(number), ""))
    return parts


class LocalSource:
    """Читает главы из папки или архива; интерфейс близок к MangaLib."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        if not self.path.exists():
            raise SourceError(f"Путь не найден: {self.path}")
        self._chapters: dict[str, list] = {}
        self._zip: zipfile.ZipFile | None = None
        self._scan()

    def close(self) -> None:
        if self._zip is not None:
            self._zip.close()
            self._zip = None

    def __enter__(self) -> "LocalSource":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- разбор ---------------------------------------------------------

    def _scan(self) -> None:
        if self.path.is_file():
            if self.path.suffix.lower() not in (".zip", ".cbz"):
                raise SourceError("Поддерживаются папка, ZIP или CBZ.")
            self._zip = zipfile.ZipFile(self.path)
            entries: dict[str, list[str]] = {}
            for name in self._zip.namelist():
                if name.endswith("/") or Path(name).suffix.lower() not in IMAGE_SUFFIXES:
                    continue
                entries.setdefault(str(Path(name).parent), []).append(name)
            for key in entries:
                entries[key].sort(key=_natural_key)
            self._chapters = {
                (Path(k).name or "1"): v for k, v in sorted(entries.items())
            }
        else:
            subdirs = [d for d in sorted(self.path.iterdir()) if d.is_dir()]
            if subdirs:
                for folder in subdirs:
                    files = sorted(
                        (f for f in folder.iterdir() if f.suffix.lower() in IMAGE_SUFFIXES),
                        key=lambda f: _natural_key(f.name),
                    )
                    if files:
                        self._chapters[folder.name] = files
            else:
                files = sorted(
                    (f for f in self.path.iterdir() if f.suffix.lower() in IMAGE_SUFFIXES),
                    key=lambda f: _natural_key(f.name),
                )
                if files:
                    self._chapters[self.path.name] = files

        if not self._chapters:
            raise SourceError("Картинок не нашлось. Ожидаю jpg/png/webp внутри.")

    # --- интерфейс источника --------------------------------------------

    def manga(self, slug: str = "") -> MangaInfo:
        name = self.path.stem if self.path.is_file() else self.path.name
        return MangaInfo(slug=name, name=name)

    def chapters(self, slug: str = "") -> list[ChapterRef]:
        chapters = []
        for index, title in enumerate(self._chapters, start=1):
            chapters.append(
                ChapterRef(volume="1", number=str(index), name=title, extra={"key": title})
            )
        return chapters

    def pages(self, slug: str, chapter: ChapterRef) -> list[str]:
        key = chapter.extra.get("key")
        entries = self._chapters.get(key, [])
        return [str(entry) for entry in entries]

    def download(self, url: str) -> bytes:
        if self._zip is not None:
            return self._zip.read(url)
        return Path(url).read_bytes()
