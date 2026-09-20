"""Общие структуры данных для всех источников."""

from __future__ import annotations

from dataclasses import dataclass, field


class SourceError(Exception):
    """Ошибка получения данных, текст сразу пригоден для показа пользователю."""


@dataclass
class MangaInfo:
    slug: str
    name: str
    cover_url: str | None = None
    author: str = ""
    year: str = ""
    site: int = 1          # 1 — обычный раздел, 4 — закрытый 18+

    @property
    def title(self) -> str:
        return self.name


@dataclass
class ChapterRef:
    """Ссылка на главу. Порядковый номер тома и главы у mangalib — строки
    ("1", "10.5"), поэтому храним как есть, а для сортировки считаем float."""

    volume: str
    number: str
    name: str = ""
    branch_id: int | None = None
    extra: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        head = f"Том {self.volume} Глава {self.number}"
        return f"{head} — {self.name}" if self.name else head

    @property
    def sort_key(self) -> tuple[float, float]:
        return (_num(self.volume), _num(self.number))

    @property
    def file_stem(self) -> str:
        return f"v{self.volume}_c{self.number}"


def _num(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
