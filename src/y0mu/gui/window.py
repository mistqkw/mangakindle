"""Одно окно: ссылка -> главы -> файл -> Kindle."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, __version__
from ..config import Settings
from ..deliver import email, usb
from ..source import auth
from ..source.mangalib import SITE_NAMES
from . import theme
from .widgets import PixelButton, PixelCard, PixelProgress, SectionTitle
from .worker import BuildWorker, Job, LoadWorker

FORMATS = [("PDF — для USB", "pdf"), ("AZW3 — обложка на полке", "azw3"),
           ("EPUB — для почты", "epub"), ("CBZ — архив", "cbz")]
DIRECTIONS = [("← справа налево (манга)", "rtl"), ("→ слева направо (манхва)", "ltr")]
SPREADS = [("Разрезать", "split"), ("Повернуть", "rotate"), ("Оставить", "keep")]
DESTINATIONS = [("Сразу на Kindle", "kindle"), ("В папку", "folder"),
                ("Письмом на Kindle", "email")]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = Settings.load()
        self.manga = None
        self.chapters: list = []
        self.loader: LoadWorker | None = None
        self.builder: BuildWorker | None = None
        self.last_files: list[Path] = []

        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(QSize(620, 760))
        self._set_icon()
        self._build_ui()
        self._update_kindle_hint()
        self._set_busy(False)

    # --- сборка интерфейса ----------------------------------------------

    def _set_icon(self) -> None:
        # в сборке PyInstaller иконки лежат рядом с распакованным бандлом
        roots = [Path(getattr(sys, "_MEIPASS", "")), Path(__file__).resolve().parents[3]]
        for root in roots:
            for size in (256, 128, 48):
                path = root / "assets" / "icons" / f"y0mu-{size}.png"
                if path.is_file():
                    self.setWindowIcon(QIcon(str(path)))
                    return

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(12)

        title = QLabel(APP_NAME)
        title.setFont(theme.pixel_font(13))
        title.setStyleSheet(f"color: {theme.ACCENT};")
        layout.addWidget(title)

        layout.addLayout(self._link_row())
        layout.addWidget(self._info_card())
        layout.addLayout(self._chapters_toolbar())

        self.chapter_list = QListWidget()
        self.chapter_list.setFont(theme.body_font(10))
        self.chapter_list.itemChanged.connect(lambda _: self._update_counter())
        layout.addWidget(self.chapter_list, stretch=1)

        layout.addLayout(self._options_grid())
        layout.addWidget(self._progress_block())
        layout.addLayout(self._action_row())

        self.setCentralWidget(root)
        self.setStyleSheet(theme.QSS)

    def _link_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.link = QLineEdit()
        self.link.setPlaceholderText("Вставь ссылку на мангу или главу")
        self.link.setFont(theme.body_font(10))
        self.link.returnPressed.connect(self.load_manga)
        row.addWidget(self.link, stretch=1)

        self.load_button = PixelButton("Ок", primary=True)
        self.load_button.setFixedWidth(64)
        self.load_button.clicked.connect(self.load_manga)
        row.addWidget(self.load_button)

        folder_button = PixelButton("Папка…")
        folder_button.setFixedWidth(86)
        folder_button.setToolTip("Собрать из сохранённых страниц: папка, ZIP или CBZ")
        folder_button.clicked.connect(self.pick_local)
        row.addWidget(folder_button)
        return row

    def _info_card(self) -> PixelCard:
        card = PixelCard()
        row = QHBoxLayout()
        row.setSpacing(12)

        self.cover = QLabel()
        self.cover.setFixedSize(84, 118)
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setStyleSheet(f"background: {theme.SURFACE_ALT}; border: 2px solid {theme.BORDER};")
        row.addWidget(self.cover)

        column = QVBoxLayout()
        column.setSpacing(4)
        self.manga_title = QLabel("Пока пусто")
        self.manga_title.setFont(theme.body_font(12))
        self.manga_title.setWordWrap(True)
        self.manga_subtitle = QLabel("Вставь ссылку и жми «Ок»")
        self.manga_subtitle.setFont(theme.body_font(9))
        self.manga_subtitle.setStyleSheet(f"color: {theme.MUTED};")
        self.manga_subtitle.setWordWrap(True)
        column.addWidget(self.manga_title)
        column.addWidget(self.manga_subtitle)
        column.addStretch(1)
        row.addLayout(column, stretch=1)
        card.body.addLayout(row)
        return card

    def _chapters_toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        self.chapters_title = SectionTitle("ГЛАВЫ")
        row.addWidget(self.chapters_title)
        row.addStretch(1)

        self.range_field = QLineEdit()
        self.range_field.setPlaceholderText("1-3")
        self.range_field.setFixedWidth(84)
        self.range_field.setFont(theme.body_font(10))
        self.range_field.returnPressed.connect(self.select_range)
        row.addWidget(self.range_field)

        for text, slot, width in (
            ("Отметить", self.select_range, 92),
            ("Все", lambda: self.set_all(True), 56),
            ("Снять", lambda: self.set_all(False), 66),
        ):
            button = PixelButton(text)
            button.setFixedWidth(width)
            button.clicked.connect(slot)
            row.addWidget(button)
        return row

    def _options_grid(self) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(6)
        box.addWidget(SectionTitle("НАСТРОЙКИ"))

        row = QHBoxLayout()
        row.setSpacing(8)
        self.format_box = self._combo(FORMATS, self.settings.output_format)
        self.direction_box = self._combo(DIRECTIONS, self.settings.direction)
        self.spread_box = self._combo(SPREADS, self.settings.spread)
        self.destination_box = self._combo(DESTINATIONS, "kindle")
        self.destination_box.currentIndexChanged.connect(self._on_destination_changed)
        for widget in (self.format_box, self.direction_box, self.spread_box, self.destination_box):
            widget.setFont(theme.body_font(9))
            row.addWidget(widget, stretch=1)
        box.addLayout(row)

        hint_row = QHBoxLayout()
        self.kindle_hint = QLabel()
        self.kindle_hint.setFont(theme.body_font(9))
        hint_row.addWidget(self.kindle_hint)
        hint_row.addStretch(1)

        self.mail_button = PixelButton("Почта…")
        self.mail_button.setFixedWidth(88)
        self.mail_button.setToolTip("Настройки Send to Kindle")
        self.mail_button.clicked.connect(self.setup_email)
        hint_row.addWidget(self.mail_button)

        token_button = PixelButton("Токен 18+")
        token_button.setFixedWidth(100)
        token_button.setToolTip("Свой токен для закрытого раздела")
        token_button.clicked.connect(self.ask_token)
        hint_row.addWidget(token_button)
        box.addLayout(hint_row)
        return box

    def _combo(self, options, current) -> QComboBox:
        box = QComboBox()
        for label, value in options:
            box.addItem(label, value)
        index = box.findData(current)
        box.setCurrentIndex(max(0, index))
        return box

    def _progress_block(self) -> PixelCard:
        card = PixelCard(background=theme.SURFACE_ALT)
        top = QHBoxLayout()
        self.status = QLabel("Готов к работе")
        self.status.setFont(theme.body_font(9))
        self.status.setWordWrap(True)
        top.addWidget(self.status, stretch=1)

        self.percent = QLabel("0%")
        self.percent.setFont(theme.pixel_font(10))
        self.percent.setStyleSheet(f"color: {theme.ACCENT};")
        top.addWidget(self.percent)
        card.body.addLayout(top)

        self.progress = PixelProgress()
        card.body.addWidget(self.progress)
        return card

    def _action_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.counter = QLabel("выбрано 0")
        self.counter.setFont(theme.body_font(9))
        self.counter.setStyleSheet(f"color: {theme.MUTED};")
        row.addWidget(self.counter)
        row.addStretch(1)

        self.open_button = PixelButton("Открыть папку")
        self.open_button.setFixedWidth(136)
        self.open_button.clicked.connect(self.open_folder)
        row.addWidget(self.open_button)

        self.cancel_button = PixelButton("Отмена")
        self.cancel_button.setFixedWidth(96)
        self.cancel_button.clicked.connect(self.cancel_build)
        row.addWidget(self.cancel_button)

        self.convert_button = PixelButton("Конвертировать", primary=True)
        self.convert_button.setFixedWidth(168)
        self.convert_button.clicked.connect(self.start_build)
        row.addWidget(self.convert_button)
        return row

    # --- состояние -------------------------------------------------------

    def _set_busy(self, busy: bool) -> None:
        self.convert_button.setEnabled(not busy and bool(self.chapters))
        self.load_button.setEnabled(not busy)
        self.cancel_button.setVisible(busy)
        self.open_button.setEnabled(bool(self.last_files) and not busy)

    def _say(self, text: str, tone: str = theme.TEXT) -> None:
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {tone};")

    def _update_counter(self) -> None:
        count = len(self.selected_chapters())
        self.counter.setText(f"выбрано {count}")
        self.convert_button.setEnabled(count > 0 and self.builder is None)

    def _update_kindle_hint(self) -> None:
        kindle = usb.find_kindle(allow_mount=False)
        if kindle:
            self.kindle_hint.setText("Kindle подключён")
            self.kindle_hint.setStyleSheet(f"color: {theme.OK};")
        else:
            self.kindle_hint.setText("Kindle не подключён")
            self.kindle_hint.setStyleSheet(f"color: {theme.MUTED};")

    # --- действия --------------------------------------------------------

    def pick_local(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Папка со страницами")
        if folder:
            self.link.setText(folder)
            self.load_manga()

    def load_manga(self) -> None:
        value = self.link.text().strip()
        if not value:
            self._say("Сначала вставь ссылку", theme.ERROR)
            return
        local = value if Path(value).expanduser().exists() else None

        self._say("Ищу тайтл…")
        self._set_busy(True)
        self.loader = LoadWorker(value, local, self.settings)
        self.loader.loaded.connect(self._on_loaded)
        self.loader.failed.connect(self._on_failed)
        self.loader.finished.connect(lambda: self._set_busy(False))
        self.loader.start()

    def _on_loaded(self, manga, chapters, cover) -> None:
        self.manga = manga
        self.chapters = chapters
        self.manga_title.setText(manga.title)
        parts = [p for p in (manga.age, SITE_NAMES.get(manga.site)) if p]
        self.manga_subtitle.setText(
            f"{', '.join(parts)} · глав: {len(chapters)}" if parts else f"глав: {len(chapters)}"
        )
        if cover:
            pixmap = QPixmap()
            if pixmap.loadFromData(cover):
                self.cover.setPixmap(
                    pixmap.scaled(84, 118, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )

        self.chapter_list.clear()
        for chapter in chapters:
            item = QListWidgetItem(chapter.label)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.chapter_list.addItem(item)
        self._say(f"Нашёл {len(chapters)} гл. Отметь, что берём.", theme.OK)
        self._update_counter()
        self._update_kindle_hint()

    def _on_failed(self, message: str) -> None:
        self._say(message, theme.ERROR)

    def set_all(self, checked: bool) -> None:
        state = Qt.Checked if checked else Qt.Unchecked
        for index in range(self.chapter_list.count()):
            self.chapter_list.item(index).setCheckState(state)

    def select_range(self) -> None:
        from ..cli import _select
        from ..source.models import SourceError

        spec = self.range_field.text().strip()
        if not spec or not self.chapters:
            return
        try:
            wanted = {(c.volume, c.number) for c in _select(self.chapters, spec)}
        except SourceError as exc:
            self._say(str(exc), theme.ERROR)
            return
        for index, chapter in enumerate(self.chapters):
            state = Qt.Checked if (chapter.volume, chapter.number) in wanted else Qt.Unchecked
            self.chapter_list.item(index).setCheckState(state)
        self._say(f"Отмечено по «{spec}»: {len(wanted)}")

    def selected_chapters(self) -> list:
        return [
            chapter
            for index, chapter in enumerate(self.chapters)
            if index < self.chapter_list.count()
            and self.chapter_list.item(index).checkState() == Qt.Checked
        ]

    def setup_email(self) -> None:
        from .dialogs import EmailDialog

        dialog = EmailDialog(self.settings, self)
        if dialog.exec():
            self._say(f"Почта настроена: {self.settings.kindle_email}", theme.OK)

    def _on_destination_changed(self) -> None:
        if self.destination_box.currentData() != "email":
            return
        try:
            email.check_settings(self.settings)
        except email.MailError:
            self._say("Почта ещё не настроена — жми «Почта…»", theme.MUTED)

    def ask_token(self) -> None:
        from .dialogs import TokenDialog

        if TokenDialog(self).exec():
            self._say("Токен принят. Закрытый раздел открыт.", theme.OK)

    def start_build(self) -> None:
        chapters = self.selected_chapters()
        if not self.manga or not chapters:
            self._say("Не выбрано ни одной главы", theme.ERROR)
            return

        self.settings.output_format = self.format_box.currentData()
        self.settings.direction = self.direction_box.currentData()
        self.settings.spread = self.spread_box.currentData()

        destination = self.destination_box.currentData()
        if destination == "email":
            try:
                email.check_settings(self.settings)
            except email.MailError as exc:
                self._say(str(exc), theme.ERROR)
                return
            self.settings.max_part_bytes = email.limit_bytes(self.settings)
        else:
            self.settings.max_part_bytes = 0
        self.settings.save()

        value = self.link.text().strip()
        local = value if Path(value).expanduser().exists() else None
        job = Job(
            url=value,
            local=local,
            manga=self.manga,
            chapters=chapters,
            settings=self.settings,
            destination=self.destination_box.currentData(),
            eject=False,
        )
        self.progress.set_value(0)
        self.percent.setText("0%")
        self._say(f"Беру {len(chapters)} гл. одним файлом…")
        self._set_busy(True)

        self.builder = BuildWorker(job)
        self.builder.progress.connect(self._on_progress)
        self.builder.finished_ok.connect(self._on_built)
        self.builder.failed.connect(self._on_failed)
        self.builder.cancelled.connect(lambda: self._say("Отменено."))
        self.builder.finished.connect(self._on_build_finished)
        self.builder.start()

    def _on_progress(self, phase: str, done: int, total: int) -> None:
        share = done / total if total else 0.0
        self.progress.set_value(share)
        self.percent.setText(f"{round(share * 100)}%")
        self._say(phase)

    def _on_built(self, result, delivery: str) -> None:
        self.last_files = list(result.files)
        names = ", ".join(path.name for path in result.files)
        size = sum(path.stat().st_size for path in result.files) / 1024 / 1024
        message = f"Готово: {names} · {size:.1f} МБ · {result.pages} стр."
        if delivery:
            message += f"\n{delivery}"
        self._say(message, theme.OK)
        self.progress.set_value(1.0)
        self.percent.setText("100%")

    def _on_build_finished(self) -> None:
        self.builder = None
        self._set_busy(False)
        self._update_counter()
        self._update_kindle_hint()

    def cancel_build(self) -> None:
        if self.builder:
            self.builder.cancel()
            self._say("Останавливаюсь…")

    def open_folder(self) -> None:
        target = self.last_files[0].parent if self.last_files else self.settings.output_dir
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    # --- закрытие --------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.builder:
            self.builder.cancel()
            self.builder.wait(3000)
        if self.loader:
            self.loader.wait(2000)
        self.settings.save()
        super().closeEvent(event)
