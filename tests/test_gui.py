"""Дымовые тесты окна. Qt рисует в offscreen, дисплей не нужен."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# QtWidgets тянет системные libEGL/libGL — на голой машине их может не быть
pytest.importorskip("PySide6.QtWidgets", reason="Qt не грузится в этой системе")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mangakindle.source.models import ChapterRef, MangaInfo  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    from mangakindle.config import Settings
    from mangakindle.gui import window as window_module

    monkeypatch.setattr(Settings, "load", classmethod(lambda cls: Settings(output_dir=tmp_path)))
    monkeypatch.setattr(Settings, "save", lambda self, path=None: tmp_path / "config.toml")
    monkeypatch.setattr(window_module.usb, "find_kindle", lambda allow_mount=True: None)

    win = window_module.MainWindow()
    chapters = [ChapterRef(volume="1", number=str(n), name=f"Глава {n}") for n in range(1, 6)]
    win._on_loaded(MangaInfo(slug="1--x", name="Бродяга", site=1, age="18+"), chapters, None)
    return win


def test_loaded_title_shows_section_and_count(window):
    assert window.manga_title.text() == "Бродяга"
    assert "mangalib" in window.manga_subtitle.text()
    assert "глав: 5" in window.manga_subtitle.text()
    assert window.chapter_list.count() == 5


def test_range_field_checks_exactly_that_range(window):
    window.range_field.setText("2-4")
    window.select_range()

    checked = [c.number for c in window.selected_chapters()]
    assert checked == ["2", "3", "4"]
    assert window.counter.text() == "выбрано 3"


def test_select_all_and_clear(window):
    window.set_all(True)
    assert len(window.selected_chapters()) == 5
    window.set_all(False)
    assert window.selected_chapters() == []
    assert not window.convert_button.isEnabled()  # нечего конвертировать


def test_bad_range_is_reported_not_crashed(window):
    window.range_field.setText("абв")
    window.select_range()
    assert "Не понял" in window.status.text()
    assert window.selected_chapters() == []


def test_progress_updates_bar_and_percent(window):
    window._on_progress("Скачиваю", 5, 20)
    assert window.percent.text() == "25%"
    assert abs(window.progress.value() - 0.25) < 0.01
