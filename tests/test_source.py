import io
import zipfile

import pytest

from y0mu.cli import _select
from y0mu.source.local import LocalSource, _natural_key
from y0mu.source.mangalib import parse_link
from y0mu.source.models import ChapterRef, SourceError


def test_parse_manga_link():
    target = parse_link("https://mangalib.me/ru/manga/1357--vagabond")
    assert target.slug == "1357--vagabond"
    assert not target.is_chapter


def test_parse_chapter_link():
    target = parse_link("https://mangalib.me/ru/1357--vagabond/read/v1/c12.5")
    assert target.slug == "1357--vagabond"
    assert (target.volume, target.number) == ("1", "12.5")
    assert target.is_chapter


def test_parse_link_rejects_garbage():
    with pytest.raises(SourceError):
        parse_link("https://example.com/manga")


def _chapters(*numbers):
    return [ChapterRef(volume="1", number=n) for n in numbers]


def test_select_range_and_list():
    chapters = _chapters("1", "2", "3", "4", "10")
    assert [c.number for c in _select(chapters, "2-3")] == ["2", "3"]
    assert [c.number for c in _select(chapters, "1,10")] == ["1", "10"]
    assert len(_select(chapters, "all")) == 5


def test_select_deduplicates_overlapping_ranges():
    chapters = _chapters("1", "2", "3")
    assert [c.number for c in _select(chapters, "1-2,2-3")] == ["1", "2", "3"]


def test_natural_sort_puts_page2_before_page10():
    names = sorted(["page10.jpg", "page2.jpg", "page1.jpg"], key=_natural_key)
    assert names == ["page1.jpg", "page2.jpg", "page10.jpg"]


def test_local_source_reads_zip(tmp_path):
    archive = tmp_path / "chapter.cbz"
    with zipfile.ZipFile(archive, "w") as z:
        for name in ("02.jpg", "10.jpg", "01.jpg"):
            z.writestr(name, b"not-a-real-image")
    with LocalSource(archive) as source:
        chapters = source.chapters()
        assert len(chapters) == 1
        pages = source.pages("", chapters[0])
        assert pages == ["01.jpg", "02.jpg", "10.jpg"]
        assert source.download(pages[0]) == b"not-a-real-image"


def test_local_source_rejects_empty_folder(tmp_path):
    with pytest.raises(SourceError):
        LocalSource(tmp_path)
