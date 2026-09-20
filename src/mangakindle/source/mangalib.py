"""Получение манги с mangalib.me через её публичный JSON-API.

Ничего не обходим: API отвечает без логина и без капчи. Картинкам нужен
заголовок Referer — это защита от хотлинка, а не от доступа. Если сайт
отвечает "нужен вход", мы честно говорим об этом и останавливаемся.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

import httpx

from .. import USER_AGENT
from .models import ChapterRef, MangaInfo, SourceError

API_BASE = "https://api.cdnlibs.org/api"
SITE_ID = "1"  # 1 = MangaLib
REFERER = "https://mangalib.me/"
FALLBACK_IMAGE_SERVERS = ("https://img2.imglib.info", "https://img3.cdnlibs.org")

# 1357--vagabond в любом месте ссылки
SLUG_RE = re.compile(r"(\d+--[A-Za-z0-9\-_]+)")
# .../read/v1/c12 или .../read/v1/c12.5
READ_RE = re.compile(r"/read/v([\d.]+)/c([\d.]+)")


@dataclass
class LinkTarget:
    slug: str
    volume: str | None = None
    number: str | None = None

    @property
    def is_chapter(self) -> bool:
        return self.volume is not None and self.number is not None


def parse_link(url: str) -> LinkTarget:
    """Разбирает ссылку на тайтл или на конкретную главу."""
    url = url.strip()
    slug_match = SLUG_RE.search(url)
    if not slug_match:
        raise SourceError(
            "Не похоже на ссылку mangalib. Нужна ссылка вида\n"
            "https://mangalib.me/ru/manga/1357--vagabond"
        )
    target = LinkTarget(slug=slug_match.group(1))
    read_match = READ_RE.search(url)
    if read_match:
        target.volume, target.number = read_match.group(1), read_match.group(2)
    return target


class MangaLib:
    """Клиент API. Держит паузу между запросами и не ходит в несколько потоков."""

    def __init__(self, delay: float = 0.7, timeout: float = 30.0) -> None:
        self.delay = delay
        self._last_request = 0.0
        self._image_servers: list[str] | None = None
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Site-Id": SITE_ID,
            },
        )

    # --- инфраструктура -------------------------------------------------

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "MangaLib":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _throttle(self) -> None:
        wait = self.delay - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def _get(self, path: str, **params: object) -> dict:
        self._throttle()
        try:
            response = self._client.get(f"{API_BASE}/{path}", params=params)
        except httpx.HTTPError as exc:
            raise SourceError(f"Нет связи с mangalib: {exc}") from exc

        if response.status_code in (401, 403):
            raise SourceError(
                "Mangalib требует вход для этого тайтла (18+ или закрытая глава).\n"
                "Обходить защиту приложение не будет — сохрани страницы вручную\n"
                "и открой папку через --local."
            )
        if response.status_code == 404:
            raise SourceError("Страница не найдена: проверь ссылку или номер главы.")
        if response.status_code == 429:
            raise SourceError("Слишком много запросов. Подожди минуту и повтори.")
        if response.status_code >= 400:
            raise SourceError(f"Mangalib ответил {response.status_code}.")
        try:
            return response.json()
        except ValueError as exc:
            raise SourceError("Mangalib вернул не JSON — возможно, сайт лежит.") from exc

    # --- данные ---------------------------------------------------------

    def manga(self, slug: str) -> MangaInfo:
        data = self._get(f"manga/{slug}").get("data") or {}
        if not data:
            raise SourceError("Тайтл не найден.")
        name = data.get("rus_name") or data.get("eng_name") or data.get("name") or slug
        cover = (data.get("cover") or {}).get("default")
        return MangaInfo(
            slug=data.get("slug_url", slug),
            name=name,
            cover_url=cover,
            year=str(data.get("releaseDateString") or ""),
        )

    def chapters(self, slug: str) -> list[ChapterRef]:
        """Список глав одной ветки перевода — той, где глав больше всего."""
        data = self._get(f"manga/{slug}/chapters").get("data")
        if not isinstance(data, list) or not data:
            raise SourceError(
                "У этого тайтла нет доступных глав.\n"
                "Обычно это значит, что их сняли по требованию правообладателя."
            )

        counts: dict[int | None, int] = {}
        for raw in data:
            for branch in raw.get("branches") or [{}]:
                key = branch.get("branch_id")
                counts[key] = counts.get(key, 0) + 1
        best = max(counts.items(), key=lambda kv: kv[1])[0]

        chapters: list[ChapterRef] = []
        for raw in data:
            branches = raw.get("branches") or [{}]
            if best is not None and not any(b.get("branch_id") == best for b in branches):
                continue
            chapters.append(
                ChapterRef(
                    volume=str(raw.get("volume", "")),
                    number=str(raw.get("number", "")),
                    name=raw.get("name") or "",
                    branch_id=best,
                )
            )
        chapters.sort(key=lambda c: c.sort_key)
        return chapters

    def image_servers(self) -> list[str]:
        if self._image_servers is None:
            servers: list[str] = []
            try:
                data = self._get("constants", **{"fields[]": "imageServers"}).get("data", {})
                for server in data.get("imageServers", []):
                    if 1 in (server.get("site_ids") or []) and server.get("id") in (
                        "main",
                        "compress",
                    ):
                        servers.append(server["url"].rstrip("/"))
            except SourceError:
                servers = []
            self._image_servers = servers or list(FALLBACK_IMAGE_SERVERS)
        return self._image_servers

    def pages(self, slug: str, chapter: ChapterRef) -> list[str]:
        """Полные URL страниц главы в порядке чтения."""
        params: dict[str, object] = {"number": chapter.number, "volume": chapter.volume}
        if chapter.branch_id is not None:
            params["branch_id"] = chapter.branch_id
        data = self._get(f"manga/{slug}/chapter", **params).get("data") or {}
        raw_pages = data.get("pages") or []
        if not raw_pages:
            raise SourceError(f"{chapter.label}: страницы недоступны.")
        base = self.image_servers()[0]
        return [f"{base}/{str(page['url']).lstrip('/')}" for page in raw_pages]

    def download(self, url: str) -> bytes:
        """Скачивает одну страницу. При отказе основного сервера пробует запасной."""
        candidates = [url]
        for server in self.image_servers()[1:]:
            path = url.split("//", 2)[-1]
            path = path[path.index("/") :] if "/" in path else path
            candidates.append(f"{server}/{path.lstrip('/')}")

        last_error = ""
        for candidate in candidates:
            self._throttle()
            try:
                response = self._client.get(
                    candidate,
                    headers={"Referer": REFERER, "Accept": "image/*"},
                )
            except httpx.HTTPError as exc:
                last_error = str(exc)
                continue
            if response.status_code == 200 and response.content:
                return response.content
            last_error = f"HTTP {response.status_code}"
        raise SourceError(f"Не получилось скачать страницу ({last_error}).")
