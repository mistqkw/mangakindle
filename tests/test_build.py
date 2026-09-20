import io
import zipfile

from PIL import Image

from mangakindle.convert.cbz import CbzBuilder
from mangakindle.convert.epub import EpubBuilder
from mangakindle.convert.pdf import PdfBuilder


def _jpeg(size=(1072, 1448)) -> bytes:
    buffer = io.BytesIO()
    Image.new("L", size, 200).save(buffer, format="JPEG", quality=80)
    return buffer.getvalue()


def test_pdf_has_pages_and_bookmarks(tmp_path):
    builder = PdfBuilder(title="Бродяга")
    for index in range(3):
        page = builder.add_page(_jpeg(), 1072, 1448)
        if index == 0:
            builder.add_bookmark("Том 1 Глава 1", page)
    path = builder.write(tmp_path / "out.pdf")

    data = path.read_bytes()
    assert data.startswith(b"%PDF-1.4")
    assert data.rstrip().endswith(b"%%EOF")
    assert data.count(b"/Type /Page\n") + data.count(b"/Type /Page ") == 3
    assert b"/Count 3" in data
    assert b"/Outlines" in data
    # кириллица в закладке пишется как UTF-16BE hex
    assert b"<feff" in data.lower()


def test_pdf_page_size_matches_300ppi(tmp_path):
    builder = PdfBuilder(title="t")
    builder.add_page(_jpeg(), 1072, 1448)
    data = builder.write(tmp_path / "size.pdf").read_bytes()
    assert b"/MediaBox [0 0 257.28 347.52]" in data


def test_epub_mimetype_is_first_and_stored(tmp_path):
    builder = EpubBuilder(title="Бродяга", direction="rtl")
    builder.add_page(_jpeg(), 1072, 1448, chapter_title="Том 1 Глава 1")
    builder.add_page(_jpeg(), 1072, 1448)
    path = builder.write(tmp_path / "out.epub")

    with zipfile.ZipFile(path) as epub:
        first = epub.infolist()[0]
        assert first.filename == "mimetype"
        assert first.compress_type == zipfile.ZIP_STORED
        opf = epub.read("OEBPS/content.opf").decode()
        assert 'page-progression-direction="rtl"' in opf
        assert "pre-paginated" in opf
        assert "Том 1 Глава 1" in epub.read("OEBPS/nav.xhtml").decode()


def test_cbz_pages_are_ordered(tmp_path):
    builder = CbzBuilder()
    for _ in range(3):
        builder.add_page(_jpeg((100, 100)))
    path = builder.write(tmp_path / "out.cbz")
    with zipfile.ZipFile(path) as archive:
        assert archive.namelist() == ["0000.jpg", "0001.jpg", "0002.jpg"]


class _FakeSource:
    """Источник из двух глав по две страницы — чтобы не ходить в сеть."""

    def pages(self, slug, chapter):
        return [f"{chapter.number}-1", f"{chapter.number}-2"]

    def download(self, url):
        return _jpeg((400, 600))


def _chapters():
    from mangakindle.source.models import ChapterRef

    return [ChapterRef(volume="1", number="1"), ChapterRef(volume="1", number="2")]


def _settings(tmp_path, **extra):
    from mangakindle.config import Settings

    return Settings(output_dir=tmp_path, keep_cache=False, **extra)


def test_selected_range_lands_in_one_file_with_bookmark_per_chapter(tmp_path, monkeypatch):
    from mangakindle import pipeline
    from mangakindle.source.models import MangaInfo

    monkeypatch.setattr(pipeline, "cache_dir", lambda: tmp_path / "cache")
    manga = MangaInfo(slug="1--x", name="Бродяга")
    result = pipeline.build(_FakeSource(), manga, _chapters(), _settings(tmp_path))

    assert len(result.files) == 1
    assert result.files[0].name == "Бродяга — гл1-2.pdf"
    data = result.files[0].read_bytes()
    assert b"/Type /Outlines /First" in data and b"/Count 2" in data


def test_split_makes_a_file_per_chapter(tmp_path, monkeypatch):
    from mangakindle import pipeline
    from mangakindle.source.models import MangaInfo

    monkeypatch.setattr(pipeline, "cache_dir", lambda: tmp_path / "cache")
    manga = MangaInfo(slug="1--x", name="Бродяга")
    result = pipeline.build(
        _FakeSource(), manga, _chapters(), _settings(tmp_path, per_chapter=True)
    )

    assert [f.name for f in result.files] == ["Бродяга — т1 гл1.pdf", "Бродяга — т1 гл2.pdf"]
