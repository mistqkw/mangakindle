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


def test_thumbnail_lands_where_kindle_looks_for_it(tmp_path, fake_kindle):
    import io

    from PIL import Image

    from mangakindle.convert.image import KINDLE_HEIGHT, KINDLE_WIDTH

    (fake_kindle / "system" / "thumbnails").mkdir()
    buffer = io.BytesIO()
    Image.new("L", (KINDLE_WIDTH, KINDLE_HEIGHT), 180).save(buffer, format="JPEG")

    target = usb.write_thumbnail(usb.Kindle(fake_kindle), "abc-123", buffer.getvalue())

    assert target.name == "thumbnail_abc-123_PDOC_portrait.jpg"
    thumb = Image.open(target)
    assert thumb.height == usb.THUMB_HEIGHT and thumb.mode == "L"


def test_thumbnail_is_skipped_when_device_has_no_such_folder(tmp_path, fake_kindle):
    assert usb.write_thumbnail(usb.Kindle(fake_kindle), "abc-123", b"not-an-image") is None


def test_azw3_without_calibre_fails_before_downloading(tmp_path, monkeypatch):
    import pytest as _pytest

    from mangakindle import pipeline
    from mangakindle.convert import azw3
    from mangakindle.source.models import MangaInfo, SourceError

    monkeypatch.setattr(azw3, "available", lambda: False)

    class _Boom:
        def pages(self, *_):
            raise AssertionError("до скачивания дойти не должно")

    settings = Settings(output_dir=tmp_path, output_format="azw3")
    with _pytest.raises(SourceError, match="нужен calibre"):
        pipeline.build(_Boom(), MangaInfo(slug="1--x", name="X"), _chapters(), settings)


def _chapters():
    from mangakindle.source.models import ChapterRef

    return [ChapterRef(volume="1", number="1")]


def test_token_can_be_pasted_as_whole_browser_value():
    """Из браузера проще скопировать весь ключ auth, чем выковыривать токен."""
    from mangakindle.source import auth

    whole = (
        '{"auth":{"id":42,"username":"mista"},'
        '"token":{"token_type":"Bearer","access_token":"eyJhbGci.payload.signature12345"}}'
    )
    assert auth.clean_token(whole) == "eyJhbGci.payload.signature12345"
    assert auth.clean_token(" Bearer eyJhbGci.payload.signature12345 ") == (
        "eyJhbGci.payload.signature12345"
    )


def test_anonymous_browser_value_says_you_are_not_logged_in():
    from mangakindle.source import auth

    with pytest.raises(auth.AuthError, match="выполнен вход"):
        auth.clean_token('{"prevUrl":"","timestamp":1789934118370}')


def test_cyrillic_junk_is_rejected_before_it_reaches_http():
    from mangakindle.source import auth

    with pytest.raises(auth.AuthError, match="не похоже на токен"):
        auth.clean_token("это точно не токен")
