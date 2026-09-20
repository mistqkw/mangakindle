"""Связка: скачать -> обработать -> собрать файл.

Здесь нет ни одного обращения к GUI: на этапе 2 этот же код поедет
в фоновый поток Qt, поэтому прогресс и отмена — через колбэки.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from .config import Settings, cache_dir
from .convert import azw3
from .convert.cbz import CbzBuilder
from .convert.epub import EpubBuilder
from .convert.image import PageOptions, encode_jpeg, prepare_page
from .convert.pdf import PdfBuilder
from .source.models import ChapterRef, MangaInfo, SourceError

ProgressFn = Callable[[str, int, int], None]
CancelFn = Callable[[], bool]


class Cancelled(Exception):
    """Пользователь нажал «Отмена» — это не ошибка."""


@dataclass
class BuildResult:
    files: list[Path]
    pages: int
    skipped: list[str]


def build(
    source,
    manga: MangaInfo,
    chapters: Sequence[ChapterRef],
    settings: Settings,
    on_progress: ProgressFn | None = None,
    is_cancelled: CancelFn | None = None,
) -> BuildResult:
    """Собирает файлы для выбранных глав и возвращает пути к ним."""
    if not chapters:
        raise SourceError("Не выбрано ни одной главы.")
    if settings.output_format == "azw3" and not azw3.available():
        # проверяем до скачивания, а не после сотни страниц
        raise SourceError(azw3.requirement_message())

    progress = on_progress or (lambda phase, done, total: None)
    cancelled = is_cancelled or (lambda: False)

    options = PageOptions(
        direction=settings.direction,
        spread=settings.spread,
        trim=settings.trim,
        quality=settings.jpeg_quality,
    )
    settings.output_dir.mkdir(parents=True, exist_ok=True)

    groups: list[list[ChapterRef]] = (
        [[chapter] for chapter in chapters] if settings.per_chapter else [list(chapters)]
    )

    files: list[Path] = []
    skipped: list[str] = []
    total_pages = 0
    cover = _fetch_cover(source, manga, options) if settings.cover else None

    for group in groups:
        if cancelled():
            raise Cancelled
        part = _Part(settings, manga, group, cover)

        for chapter in group:
            if cancelled():
                raise Cancelled
            try:
                urls = source.pages(manga.slug, chapter)
            except SourceError as exc:
                skipped.append(f"{chapter.label}: {exc}")
                continue

            progress(f"Скачиваю {chapter.label}", 0, len(urls))
            pending_title = chapter.label
            for index, url in enumerate(urls, start=1):
                if cancelled():
                    raise Cancelled
                try:
                    data = _page_bytes(source, manga, chapter, index, url, settings)
                except SourceError as exc:
                    skipped.append(f"{chapter.label}, стр. {index}: {exc}")
                    continue

                for image in prepare_page(data, options):
                    jpeg = encode_jpeg(image, options.quality)
                    # письмо не резиновое: начинаем новую часть, не дожидаясь конца
                    if part.would_overflow(len(jpeg)):
                        part.flush()
                        pending_title = chapter.label
                    part.add(jpeg, image, pending_title)
                    pending_title = ""
                progress(f"Скачиваю {chapter.label}", index, len(urls))

        progress("Собираю файл", 0, 1)
        written = part.finish()
        progress("Собираю файл", 1, 1)
        files += written
        total_pages += part.total_pages

        if not settings.keep_cache:
            _clear_cache(manga, group)

    if not files:
        raise SourceError(
            "Не удалось собрать ни одного файла.\n" + ("\n".join(skipped[:3]) or "")
        )
    return BuildResult(files=files, pages=total_pages, skipped=skipped)


# --- внутренности -------------------------------------------------------


class _Part:
    """Один выходной файл. Если задан предел размера — режет его на части."""

    def __init__(self, settings: Settings, manga: MangaInfo, group, cover) -> None:
        self.settings = settings
        self.manga = manga
        self.group = group
        self.cover = cover
        self.total_pages = 0
        self.written: list[Path] = []
        self._pages_in_part = 0
        self._bytes = 0
        self._builder = None

    # --- наполнение ---

    def _ensure_builder(self):
        if self._builder is None:
            self._builder = _make_builder(self.settings, self.manga, self.group, self.cover)
            self._bytes = 0
            self._pages_in_part = 0
            if self.cover is not None:
                self.total_pages += 1
        return self._builder

    def would_overflow(self, size: int) -> bool:
        limit = self.settings.max_part_bytes
        return bool(limit) and self._pages_in_part > 0 and self._bytes + size > limit

    def add(self, jpeg: bytes, image, chapter_title: str) -> None:
        _add_page(self._ensure_builder(), jpeg, image, chapter_title)
        self._bytes += len(jpeg)
        self._pages_in_part += 1
        self.total_pages += 1

    # --- запись ---

    def flush(self) -> None:
        if self._builder is None or self._pages_in_part == 0:
            return
        number = len(self.written) + 1
        path = self.settings.output_dir / _filename(
            self.manga, self.group, self.settings.output_format, part=number
        )
        _write(self._builder, path, self.settings)
        self.written.append(path)
        self._builder = None

    def finish(self) -> list[Path]:
        self.flush()
        if len(self.written) == 1:
            # частей не понадобилось — возвращаем имя без «часть 1»
            plain = self.settings.output_dir / _filename(
                self.manga, self.group, self.settings.output_format
            )
            if plain != self.written[0]:
                self.written[0].replace(plain)
                self.written[0] = plain
        return self.written


def _make_builder(settings: Settings, manga: MangaInfo, group: list[ChapterRef], cover):
    title = manga.title if len(group) > 1 else f"{manga.title} — {group[0].label}"
    fmt = settings.output_format
    jpeg = encode_jpeg(cover, settings.jpeg_quality) if cover is not None else None

    if fmt in ("epub", "azw3"):
        builder = EpubBuilder(title=title, direction=settings.direction)
        builder.cover = jpeg
        return builder
    if fmt == "cbz":
        builder = CbzBuilder()
        if jpeg is not None:
            builder.add_page(jpeg)
        return builder

    builder = PdfBuilder(title=title)
    if jpeg is not None:
        page = builder.add_page(jpeg, cover.width, cover.height)
        builder.add_bookmark("Обложка", page)
    return builder


def _write(builder, path: Path, settings: Settings) -> Path:
    """AZW3 собирается из нашего же EPUB — промежуточный файл не оставляем."""
    if settings.output_format != "azw3":
        return builder.write(path)
    staging = path.with_name(path.stem + ".staging.epub")
    try:
        builder.write(staging)
        return azw3.from_epub(staging, path)
    except azw3.ConvertError as exc:
        raise SourceError(str(exc)) from exc
    finally:
        staging.unlink(missing_ok=True)


def _add_page(builder, jpeg: bytes, image, chapter_title: str) -> None:
    if isinstance(builder, PdfBuilder):
        index = builder.add_page(jpeg, image.width, image.height)
        if chapter_title:
            builder.add_bookmark(chapter_title, index)
    elif isinstance(builder, EpubBuilder):
        builder.add_page(jpeg, image.width, image.height, chapter_title)
    else:
        builder.add_page(jpeg)


def _chapter_cache(manga: MangaInfo, chapter: ChapterRef) -> Path:
    return cache_dir() / _safe(manga.slug) / _safe(chapter.file_stem)


def _page_bytes(source, manga, chapter, index: int, url: str, settings: Settings) -> bytes:
    folder = _chapter_cache(manga, chapter)
    cached = folder / f"{index:04d}.bin"
    if cached.exists() and cached.stat().st_size > 0:
        return cached.read_bytes()
    data = source.download(url)
    folder.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(data)
    return data


def _clear_cache(manga: MangaInfo, group: list[ChapterRef]) -> None:
    for chapter in group:
        folder = _chapter_cache(manga, chapter)
        if not folder.exists():
            continue
        for item in folder.iterdir():
            item.unlink(missing_ok=True)
        folder.rmdir()


def _fetch_cover(source, manga: MangaInfo, options: PageOptions):
    """Обложка с сайта. Она маленькая (около 375x534), поэтому её тянет
    вверх почти втрое — резкость приглушаем, иначе лезут артефакты JPEG."""
    if not getattr(manga, "cover_url", None):
        return None
    cover_options = replace(options, spread="keep", trim=False, sharpen=25)
    try:
        data = source.download(manga.cover_url)
        pages = prepare_page(data, cover_options)
        return pages[0] if pages else None
    except (SourceError, OSError, ValueError):
        return None


def _filename(manga: MangaInfo, group: list[ChapterRef], fmt: str, part: int | None = None) -> str:
    name = _safe(manga.title)
    if len(group) == 1:
        tail = f"т{group[0].volume} гл{group[0].number}"
    else:
        tail = f"гл{group[0].number}-{group[-1].number}"
    if part:
        tail += f" часть {part}"
    return f"{name} — {tail}.{fmt}"


def _safe(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", value).strip(" .")
    return value[:120] or "manga"
