"""Минимальный писатель PDF: страницы-картинки + оглавление по главам.

Kindle открывает PDF, скопированный по USB, без конвертации. Страницы тут
ровно 1072x1448 при 300 ppi, то есть лист PDF совпадает с экраном один в один.

JPEG кладём в файл как есть (DCTDecode) — не распаковывая: так сборка тома
на 400 страниц не съедает память ноутбука.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

PPI = 300.0
POINTS_PER_INCH = 72.0


@dataclass
class PdfPage:
    jpeg: bytes
    width: int
    height: int


@dataclass
class PdfBookmark:
    title: str
    page_index: int


@dataclass
class PdfBuilder:
    title: str = ""
    pages: list[PdfPage] = field(default_factory=list)
    bookmarks: list[PdfBookmark] = field(default_factory=list)

    def add_page(self, jpeg: bytes, width: int, height: int) -> int:
        self.pages.append(PdfPage(jpeg, width, height))
        return len(self.pages) - 1

    def add_bookmark(self, title: str, page_index: int) -> None:
        self.bookmarks.append(PdfBookmark(title, page_index))

    def write(self, path: Path) -> Path:
        if not self.pages:
            raise ValueError("В PDF нет ни одной страницы.")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self._build())
        return path

    # --- сборка ---------------------------------------------------------

    def _build(self) -> bytes:
        # Номера объектов: 1 — каталог, 2 — дерево страниц, 3 — Info,
        # 4 — Outlines, дальше по три объекта на страницу, затем закладки.
        page_count = len(self.pages)
        first_page_obj = 5
        objects: dict[int, bytes] = {}

        page_ids = [first_page_obj + i * 3 for i in range(page_count)]
        kids = " ".join(f"{pid} 0 R" for pid in page_ids)
        outlines_id = 4
        bookmark_first = first_page_obj + page_count * 3

        objects[1] = self._dict(
            f"/Type /Catalog /Pages 2 0 R /Outlines {outlines_id} 0 R"
            + (" /PageMode /UseOutlines" if self.bookmarks else "")
        )
        objects[2] = self._dict(f"/Type /Pages /Count {page_count} /Kids [{kids}]")
        objects[3] = self._dict(
            f"/Producer {_pdf_text('y0mu')} /Title {_pdf_text(self.title)}"
        )

        for index, page in enumerate(self.pages):
            page_id = page_ids[index]
            image_id, content_id = page_id + 1, page_id + 2
            width_pt = page.width * POINTS_PER_INCH / PPI
            height_pt = page.height * POINTS_PER_INCH / PPI
            objects[page_id] = self._dict(
                f"/Type /Page /Parent 2 0 R "
                f"/MediaBox [0 0 {width_pt:.2f} {height_pt:.2f}] "
                f"/Resources << /XObject << /Im0 {image_id} 0 R >> >> "
                f"/Contents {content_id} 0 R"
            )
            objects[image_id] = self._stream(
                f"/Type /XObject /Subtype /Image /Width {page.width} /Height {page.height} "
                f"/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /DCTDecode",
                page.jpeg,
            )
            content = f"q {width_pt:.2f} 0 0 {height_pt:.2f} 0 0 cm /Im0 Do Q".encode("ascii")
            objects[content_id] = self._stream("", content)

        objects.update(self._outline_objects(outlines_id, bookmark_first, page_ids))
        return self._serialize(objects)

    def _outline_objects(
        self, outlines_id: int, first_id: int, page_ids: list[int]
    ) -> dict[int, bytes]:
        if not self.bookmarks:
            return {outlines_id: self._dict("/Type /Outlines /Count 0")}

        ids = [first_id + i for i in range(len(self.bookmarks))]
        objects = {
            outlines_id: self._dict(
                f"/Type /Outlines /First {ids[0]} 0 R /Last {ids[-1]} 0 R "
                f"/Count {len(ids)}"
            )
        }
        for position, (bookmark, obj_id) in enumerate(zip(self.bookmarks, ids)):
            page_index = min(max(bookmark.page_index, 0), len(page_ids) - 1)
            parts = [
                f"/Title {_pdf_text(bookmark.title)}",
                f"/Parent {outlines_id} 0 R",
                f"/Dest [{page_ids[page_index]} 0 R /Fit]",
            ]
            if position > 0:
                parts.append(f"/Prev {ids[position - 1]} 0 R")
            if position < len(ids) - 1:
                parts.append(f"/Next {ids[position + 1]} 0 R")
            objects[obj_id] = self._dict(" ".join(parts))
        return objects

    @staticmethod
    def _dict(body: str) -> bytes:
        return f"<< {body} >>".encode("latin-1")

    @staticmethod
    def _stream(header: str, payload: bytes) -> bytes:
        head = f"<< {header} /Length {len(payload)} >>".encode("latin-1")
        return head + b"\nstream\n" + payload + b"\nendstream"

    @staticmethod
    def _serialize(objects: dict[int, bytes]) -> bytes:
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets: dict[int, int] = {}
        for number in sorted(objects):
            offsets[number] = len(out)
            out += f"{number} 0 obj\n".encode("ascii")
            out += objects[number]
            out += b"\nendobj\n"

        xref_offset = len(out)
        highest = max(objects)
        out += f"xref\n0 {highest + 1}\n".encode("ascii")
        out += b"0000000000 65535 f \n"
        for number in range(1, highest + 1):
            if number in offsets:
                out += f"{offsets[number]:010d} 00000 n \n".encode("ascii")
            else:
                out += b"0000000000 65535 f \n"
        out += (
            f"trailer\n<< /Size {highest + 1} /Root 1 0 R /Info 3 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
        return bytes(out)


def _pdf_text(value: str) -> str:
    """Строка PDF. Кириллицу пишем как UTF-16BE в hex — так её читают все просмотрщики."""
    if not value:
        return "()"
    try:
        value.encode("ascii")
    except UnicodeEncodeError:
        return "<" + b"\xfe\xff".hex() + value.encode("utf-16-be").hex() + ">"
    escaped = value.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    return f"({escaped})"
