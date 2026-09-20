"""Фоновые потоки: сеть и обработка картинок не должны трогать GUI.

Каждый поток заводит свой клиент к сайту — так httpx не делят между
потоками, и отменённая задача забирает своё соединение с собой.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..config import Settings
from ..convert import azw3
from ..deliver import usb
from ..pipeline import BuildResult, Cancelled, build
from ..source import auth
from ..source.local import LocalSource
from ..source.mangalib import MangaLib, parse_link
from ..source.models import ChapterRef, MangaInfo, SourceError


def open_source(url: str | None, local: str | None, delay: float):
    """Один и тот же источник для загрузки списка и для сборки."""
    if local:
        return LocalSource(local), None
    target = parse_link(url or "")
    source = MangaLib(delay=delay, token=auth.load_token(), site_id=target.site_id)
    return source, target


class LoadWorker(QThread):
    """Тянет название, обложку и список глав."""

    loaded = Signal(object, object, object)  # MangaInfo, list[ChapterRef], bytes | None
    failed = Signal(str)

    def __init__(self, url: str, local: str | None, settings: Settings) -> None:
        super().__init__()
        self.url = url
        self.local = local
        self.settings = settings

    def run(self) -> None:
        source = None
        try:
            source, target = open_source(self.url, self.local, self.settings.delay)
            slug = target.slug if target else ""
            manga = source.manga(slug)
            chapters = source.chapters(slug)
            cover = None
            if manga.cover_url:
                try:
                    cover = source.download(manga.cover_url)
                except SourceError:
                    cover = None
            self.loaded.emit(manga, chapters, cover)
        except SourceError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # чтобы окно не падало молча
            self.failed.emit(f"Неожиданная ошибка: {exc}")
        finally:
            if source is not None:
                source.close()


@dataclass
class Job:
    url: str
    local: str | None
    manga: MangaInfo
    chapters: list[ChapterRef]
    settings: Settings
    to_kindle: bool = False
    eject: bool = False
    extra: dict = field(default_factory=dict)


class BuildWorker(QThread):
    """Скачивание, обработка, сборка и, если попросили, отправка на Kindle."""

    progress = Signal(str, int, int)
    finished_ok = Signal(object, str)   # BuildResult, сообщение о доставке
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, job: Job) -> None:
        super().__init__()
        self.job = job
        self._stop = False

    def cancel(self) -> None:
        self._stop = True

    def run(self) -> None:
        source = None
        try:
            source, _ = open_source(self.job.url, self.job.local, self.job.settings.delay)
            result = build(
                source,
                self.job.manga,
                self.job.chapters,
                self.job.settings,
                on_progress=lambda phase, done, total: self.progress.emit(phase, done, total),
                is_cancelled=lambda: self._stop,
            )
            self.finished_ok.emit(result, self._deliver(result))
        except Cancelled:
            self.cancelled.emit()
        except SourceError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"Неожиданная ошибка: {exc}")
        finally:
            if source is not None:
                source.close()

    # --- доставка -------------------------------------------------------

    def _deliver(self, result: BuildResult) -> str:
        if not self.job.to_kindle:
            return ""
        self.progress.emit("Отправляю на Kindle", 0, 1)
        try:
            kindle = usb.find_kindle()
            if kindle is None:
                return (
                    "Kindle не найден — подключи по USB и разбуди экран.\n"
                    "Файлы остались в папке."
                )
            names = []
            for path in result.files:
                target = usb.send(path, kindle)
                self._put_cover_on_shelf(kindle, target)
                names.append(target.name)
            self.progress.emit("Отправляю на Kindle", 1, 1)
            if self.job.eject and usb.eject():
                return f"На Kindle: {', '.join(names)}. Устройство отмонтировано."
            return f"На Kindle: {', '.join(names)}. Запись сброшена, можно отключать."
        except usb.KindleError as exc:
            return f"{exc}\nФайлы остались в папке."

    @staticmethod
    def _put_cover_on_shelf(kindle, path: Path) -> None:
        if path.suffix.lower() != ".azw3":
            return
        document_uuid = azw3.document_uuid(path)
        cover = azw3.extract_cover(path)
        if document_uuid and cover:
            usb.write_thumbnail(kindle, document_uuid, cover)
