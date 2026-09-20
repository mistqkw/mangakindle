"""CBZ — архив с картинками. Kindle его не читает, но формат удобен
для просмотра на компьютере и для переноса в другие читалки."""

from __future__ import annotations

import zipfile
from pathlib import Path


class CbzBuilder:
    def __init__(self) -> None:
        self._pages: list[bytes] = []

    def add_page(self, jpeg: bytes, *_: object, **__: object) -> None:
        self._pages.append(jpeg)

    def write(self, path: Path) -> Path:
        if not self._pages:
            raise ValueError("В CBZ нет ни одной страницы.")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as archive:
            for index, jpeg in enumerate(self._pages):
                archive.writestr(f"{index:04d}.jpg", jpeg)
        return path
