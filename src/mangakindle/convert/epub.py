"""Сборка fixed-layout EPUB 3 с чтением справа налево.

Этот формат нужен для отправки по e-mail: Send to Kindle принимает EPUB
и конвертирует его на стороне Amazon. Для USB используется PDF — EPUB,
скопированный в documents/, Kindle не открывает.
"""

from __future__ import annotations

import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .image import KINDLE_HEIGHT, KINDLE_WIDTH

CONTAINER = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

STYLE = """html, body { margin: 0; padding: 0; height: 100%; background: #ffffff; }
img { display: block; width: 100%; height: 100%; object-fit: contain; }
"""


@dataclass
class EpubPage:
    jpeg: bytes
    width: int
    height: int
    chapter_title: str = ""   # непусто только на первой странице главы


@dataclass
class EpubBuilder:
    title: str
    direction: str = "rtl"
    language: str = "ru"
    cover: bytes | None = None
    pages: list[EpubPage] = field(default_factory=list)

    def add_page(
        self, jpeg: bytes, width: int, height: int, chapter_title: str = ""
    ) -> None:
        self.pages.append(EpubPage(jpeg, width, height, chapter_title))

    def write(self, path: Path) -> Path:
        if not self.pages:
            raise ValueError("В EPUB нет ни одной страницы.")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        book_id = f"urn:uuid:{uuid.uuid4()}"

        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as epub:
            # mimetype обязан идти первым и без сжатия
            epub.writestr(
                zipfile.ZipInfo("mimetype"), "application/epub+zip", zipfile.ZIP_STORED
            )
            epub.writestr("META-INF/container.xml", CONTAINER)
            epub.writestr("OEBPS/css/style.css", STYLE)

            if self.cover:
                epub.writestr("OEBPS/images/cover.jpg", self.cover)
                epub.writestr("OEBPS/xhtml/cover.xhtml", self._page_xhtml("cover.jpg"))

            for index, page in enumerate(self.pages):
                epub.writestr(f"OEBPS/images/p{index:04d}.jpg", page.jpeg)
                epub.writestr(
                    f"OEBPS/xhtml/p{index:04d}.xhtml",
                    self._page_xhtml(f"p{index:04d}.jpg", page.width, page.height),
                )

            epub.writestr("OEBPS/content.opf", self._opf(book_id))
            epub.writestr("OEBPS/nav.xhtml", self._nav())
            epub.writestr("OEBPS/toc.ncx", self._ncx(book_id))
        return path

    # --- части книги ----------------------------------------------------

    def _page_xhtml(
        self, image: str, width: int = KINDLE_WIDTH, height: int = KINDLE_HEIGHT
    ) -> str:
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{self.language}">
<head>
  <meta charset="utf-8"/>
  <title>{_escape(self.title)}</title>
  <meta name="viewport" content="width={width}, height={height}"/>
  <link rel="stylesheet" type="text/css" href="../css/style.css"/>
</head>
<body>
  <img src="../images/{image}" alt=""/>
</body>
</html>
"""

    def _opf(self, book_id: str) -> str:
        manifest = [
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
            '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
            '<item id="css" href="css/style.css" media-type="text/css"/>',
        ]
        spine = []
        if self.cover:
            manifest.append(
                '<item id="cover-image" href="images/cover.jpg" media-type="image/jpeg" '
                'properties="cover-image"/>'
            )
            manifest.append(
                '<item id="cover" href="xhtml/cover.xhtml" media-type="application/xhtml+xml"/>'
            )
            spine.append('<itemref idref="cover"/>')

        for index in range(len(self.pages)):
            manifest.append(
                f'<item id="img{index:04d}" href="images/p{index:04d}.jpg" media-type="image/jpeg"/>'
            )
            manifest.append(
                f'<item id="p{index:04d}" href="xhtml/p{index:04d}.xhtml" '
                'media-type="application/xhtml+xml"/>'
            )
            spine.append(f'<itemref idref="p{index:04d}"/>')

        cover_meta = '<meta name="cover" content="cover-image"/>' if self.cover else ""
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid"
         prefix="rendition: http://www.idpf.org/vocab/rendition/#">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">{book_id}</dc:identifier>
    <dc:title>{_escape(self.title)}</dc:title>
    <dc:language>{self.language}</dc:language>
    <meta property="rendition:layout">pre-paginated</meta>
    <meta property="rendition:orientation">portrait</meta>
    <meta property="rendition:spread">none</meta>
    <meta property="dcterms:modified">1970-01-01T00:00:00Z</meta>
    <meta name="original-resolution" content="{KINDLE_WIDTH}x{KINDLE_HEIGHT}"/>
    <meta name="fixed-layout" content="true"/>
    <meta name="book-type" content="comic"/>
    <meta name="primary-writing-mode" content="{'horizontal-rl' if self.direction == 'rtl' else 'horizontal-lr'}"/>
    {cover_meta}
  </metadata>
  <manifest>
    {"".join(manifest)}
  </manifest>
  <spine toc="ncx" page-progression-direction="{self.direction}">
    {"".join(spine)}
  </spine>
</package>
"""

    def _toc_entries(self) -> list[tuple[str, str]]:
        entries = [
            (page.chapter_title, f"xhtml/p{index:04d}.xhtml")
            for index, page in enumerate(self.pages)
            if page.chapter_title
        ]
        return entries or [(self.title, "xhtml/p0000.xhtml")]

    def _nav(self) -> str:
        items = "".join(
            f'<li><a href="{href}">{_escape(title)}</a></li>'
            for title, href in self._toc_entries()
        )
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"
      xml:lang="{self.language}">
<head><meta charset="utf-8"/><title>Оглавление</title></head>
<body>
  <nav epub:type="toc" id="toc"><h1>Оглавление</h1><ol>{items}</ol></nav>
</body>
</html>
"""

    def _ncx(self, book_id: str) -> str:
        points = "".join(
            f'<navPoint id="n{index}" playOrder="{index + 1}">'
            f"<navLabel><text>{_escape(title)}</text></navLabel>"
            f'<content src="{href}"/></navPoint>'
            for index, (title, href) in enumerate(self._toc_entries())
        )
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head><meta name="dtb:uid" content="{book_id}"/></head>
  <docTitle><text>{_escape(self.title)}</text></docTitle>
  <navMap>{points}</navMap>
</ncx>
"""


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
