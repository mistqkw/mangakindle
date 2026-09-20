"""Доставка по USB на подставном томе — настоящий Kindle не нужен."""

import pytest

from mangakindle.config import Settings
from mangakindle.deliver import usb
from mangakindle.pipeline import _filename
from mangakindle.source.models import ChapterRef, MangaInfo


@pytest.fixture
def fake_kindle(tmp_path, monkeypatch):
    root = tmp_path / "Kindle"
    (root / "documents").mkdir(parents=True)
    (root / "system").mkdir()
    (tmp_path / "Флешка").mkdir()  # посторонний том рядом
    monkeypatch.setattr(usb, "_mount_points", lambda: list(tmp_path.iterdir()))
    return root


def test_finds_volume_by_kindle_layout(fake_kindle):
    found = usb.find_kindle(allow_mount=False)
    assert found is not None and found.root == fake_kindle


def test_ignores_volumes_without_kindle_layout(tmp_path, monkeypatch):
    (tmp_path / "Флешка" / "documents").mkdir(parents=True)  # documents есть, system нет
    monkeypatch.setattr(usb, "_mount_points", lambda: list(tmp_path.iterdir()))
    assert usb.find_kindle(allow_mount=False) is None


def test_send_copies_into_documents(tmp_path, fake_kindle):
    book = tmp_path / "Бродяга — гл1-3.pdf"
    book.write_bytes(b"%PDF-1.4 fake" * 1000)

    target = usb.send(book)

    assert target == fake_kindle / "documents" / book.name
    assert target.read_bytes() == book.read_bytes()


def test_send_without_device_explains_where_file_stayed(tmp_path, monkeypatch):
    monkeypatch.setattr(usb, "_mount_points", list)
    monkeypatch.setattr(usb, "_try_mount", lambda: None)
    book = tmp_path / "book.pdf"
    book.write_bytes(b"x")

    with pytest.raises(usb.KindleError, match="Kindle не найден"):
        usb.send(book)


def test_send_checks_free_space(tmp_path, fake_kindle, monkeypatch):
    book = tmp_path / "big.pdf"
    book.write_bytes(b"x" * 5000)
    monkeypatch.setattr(usb.Kindle, "free_bytes", lambda self: 100)

    with pytest.raises(usb.KindleError, match="не хватает места"):
        usb.send(book)
    assert not (fake_kindle / "documents" / "big.pdf").exists()


def test_range_becomes_one_file_by_default():
    assert Settings().per_chapter is False


def test_filename_keeps_the_taken_range():
    manga = MangaInfo(slug="1--x", name="Бродяга")
    group = [ChapterRef(volume="1", number=str(n)) for n in (1, 2, 3)]
    assert _filename(manga, group, "pdf") == "Бродяга — гл1-3.pdf"
    assert _filename(manga, group[:1], "pdf") == "Бродяга — т1 гл1.pdf"
