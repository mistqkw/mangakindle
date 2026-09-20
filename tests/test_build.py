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
