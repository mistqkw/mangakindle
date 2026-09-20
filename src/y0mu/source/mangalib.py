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

# Один и тот же API живёт на двух хостах, и любой из них может начать
# отвечать 403 целиком, независимо от тайтла. Поэтому ходим по списку.
API_HOSTS = ("https://api2.mangalib.me/api", "https://api.cdnlibs.org/api")
# Разделы одной и той же библиотеки. Страницы закрытого раздела сайт
# отдаёт только своему аккаунту, поэтому туда нужен токен.
SITE_MANGA = 1
SITE_RANOBE = 3
SITE_ADULT = 4
SITE_ORDER = (SITE_MANGA, SITE_ADULT, SITE_RANOBE, 2)
SITE_NAMES = {
    SITE_MANGA: "mangalib",
    2: "slashlib",
    SITE_RANOBE: "ranobelib",
    SITE_ADULT: "закрытый раздел",
}
SITE_BY_HOST = {
    "mangalib.me": SITE_MANGA,
    "mangalib.org": SITE_MANGA,
    "ranobelib.me": SITE_RANOBE,
    "hentailib.me": SITE_ADULT,
    "hentailib.org": SITE_ADULT,
    "yaoilib.me": SITE_ADULT,
}
# У каждого раздела свой домен и свои серверы картинок: закрытый раздел
# отдаёт страницы только с hentaicdn, а на imglib молча вернёт пустоту.
SITE_DOMAINS = {
    SITE_MANGA: "mangalib.me",
    2: "slashlib.me",
    SITE_RANOBE: "ranobelib.me",
    SITE_ADULT: "hentailib.me",
    5: "anilib.me",
}
FALLBACK_IMAGE_SERVERS = {
    SITE_ADULT: ("https://img2h.hentaicdn.org", "https://img3h.hentaicdn.org"),
    2: ("https://img2.hentaicdn.org", "https://img3.hentaicdn.org"),
}
DEFAULT_IMAGE_SERVERS = ("https://img2.imglib.info", "https://img3.cdnlibs.org")

# 1357--vagabond в любом месте ссылки
SLUG_RE = re.compile(r"(\d+--[A-Za-z0-9\-_]+)")
# .../read/v1/c12 или .../read/v1/c12.5
READ_RE = re.compile(r"/read/v([\d.]+)/c([\d.]+)")


class Unauthorized(SourceError):
    """Сайт сказал «ты не вошёл»."""


class NotFound(SourceError):
    """Сайт ответил «нет такого» — иногда это правда, иногда так прячут 18+."""


@dataclass
class LinkTarget:
    slug: str
    volume: str | None = None
    number: str | None = None
    site_id: int | None = None

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
    host = url.split("//", 1)[-1].split("/", 1)[0].lower().removeprefix("www.")
    target.site_id = SITE_BY_HOST.get(host)
    read_match = READ_RE.search(url)
    if read_match:
        target.volume, target.number = read_match.group(1), read_match.group(2)
    return target


class MangaLib:
    """Клиент API. Держит паузу между запросами и не ходит в несколько потоков."""

    def __init__(
        self,
        delay: float = 0.7,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        token: str | None = None,
        site_id: int | None = None,
    ) -> None:
        self.delay = delay
        # заголовки уходят в ASCII: кривую строку лучше не брать вовсе
        self.token = token if (token or "").isascii() else None
        self.site_id = site_id or SITE_MANGA
        self._site_known = site_id is not None
        self._last_request = 0.0
        self._image_servers: dict[int, list[str]] = {}
        self._host = API_HOSTS[0]
        self._client = httpx.Client(
            timeout=timeout,
            transport=transport,
            follow_redirects=True,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
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
        """Запрос к API с переходом на запасной хост, если текущий отказал."""
        hosts = self._hosts()
        refusals: list[str] = []
        for index, host in enumerate(hosts):
            self._throttle()
            outcome = self._try_get(host, path, params)
            if isinstance(outcome, dict):
                self._host = host
                return outcome
            refusals.append(f"{_host_name(host)}: {outcome}")
            if index < len(hosts) - 1:
                continue
        raise SourceError(
            "Mangalib не отвечает ни на одном из своих адресов:\n  "
            + "\n  ".join(refusals)
            + "\n\nЭто отказ всего API, а не запрет на конкретный тайтл.\n"
            "Обычно проходит само через несколько минут. Если спешишь —\n"
            "сохрани страницы из браузера и собери файл через --local."
        )

    def _try_get(self, host: str, path: str, params: dict) -> dict | str:
        """Возвращает данные или короткую причину, по которой хост не годится."""
        headers = {"Site-Id": str(self.site_id)}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            response = self._client.get(f"{host}/{path}", params=params, headers=headers)
        except httpx.HTTPError as exc:
            return f"нет связи ({exc.__class__.__name__})"

        payload = _json_or_none(response)
        toast = _toast(payload)
        status = response.status_code

        if status == 401:
            raise Unauthorized(
                "Mangalib требует вход для этого тайтла — обычно это 18+.\n"
                "Логин и капчу приложение не обходит: сохрани страницы\n"
                "из браузера и собери файл через --local."
            )
        if status == 404:
            raise NotFound("Страница не найдена: проверь ссылку или номер главы.")
        if status == 429:
            raise SourceError("Слишком много запросов. Подожди минуту и повтори.")
        if status == 403:
            # Если отказ пришёл от самого API — показываем его формулировку.
            # Если это HTML от ddos-guard, дело в хосте, а не в тайтле.
            if toast:
                raise SourceError(f"Mangalib отказал: {toast}")
            return "403, отказ на уровне сайта"
        if status >= 500:
            return f"сервер вернул {status}"
        if status >= 400:
            raise SourceError(toast or f"Mangalib ответил {status}.")
        if payload is None:
            return "ответ не в формате JSON"
        return payload

    def _hosts(self) -> list[str]:
        """Рабочий хост первым, остальные — как запасные."""
        return [self._host] + [h for h in API_HOSTS if h != self._host]

    # --- данные ---------------------------------------------------------

    def manga(self, slug: str) -> MangaInfo:
        data = {}
        for site in self._site_candidates():
            self.site_id = site
            try:
                data = self._get(f"manga/{slug}").get("data") or {}
            except NotFound:
                continue
            if data:
                self._site_known = True
                break
        if not data:
            raise SourceError(
                "Тайтл не найден ни в одном разделе mangalib.\n"
                "Проверь ссылку — она должна вести на страницу тайтла."
            )
        name = data.get("rus_name") or data.get("eng_name") or data.get("name") or slug
        cover = (data.get("cover") or {}).get("default")
        self.site_id = int(data.get("site") or self.site_id)
        return MangaInfo(
            slug=data.get("slug_url", slug),
            name=name,
            cover_url=cover,
            year=str(data.get("releaseDateString") or ""),
            site=self.site_id,
            age=str((data.get("ageRestriction") or {}).get("label") or ""),
        )

    def _site_candidates(self) -> list[int]:
        if self._site_known:
            return [self.site_id]
        return [self.site_id] + [s for s in SITE_ORDER if s != self.site_id]

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
        """Серверы картинок текущего раздела — у каждого они свои."""
        site = self.site_id
        if site not in self._image_servers:
            servers: list[str] = []
            try:
                data = self._get("constants", **{"fields[]": "imageServers"}).get("data", {})
                for server in data.get("imageServers", []):
                    url = (server.get("url") or "").rstrip("/")
                    if not url or server.get("id") not in ("main", "compress"):
                        continue
                    if site in (server.get("site_ids") or []) and url not in servers:
                        servers.append(url)
            except SourceError:
                servers = []
            fallback = FALLBACK_IMAGE_SERVERS.get(site, DEFAULT_IMAGE_SERVERS)
            self._image_servers[site] = servers or list(fallback)
        return self._image_servers[site]

    def referer(self) -> str:
        return f"https://{SITE_DOMAINS.get(self.site_id, SITE_DOMAINS[SITE_MANGA])}/"

    def pages(self, slug: str, chapter: ChapterRef) -> list[str]:
        """Полные URL страниц главы в порядке чтения."""
        params: dict[str, object] = {"number": chapter.number, "volume": chapter.volume}
        if chapter.branch_id is not None:
            params["branch_id"] = chapter.branch_id
        try:
            data = self._get(f"manga/{slug}/chapter", **params).get("data") or {}
        except NotFound:
            raise SourceError(self._closed_chapter_message(chapter)) from None
        raw_pages = data.get("pages") or []
        if not raw_pages:
            raise SourceError(self._closed_chapter_message(chapter))
        base = self.image_servers()[0]
        return [f"{base}/{str(page['url']).lstrip('/')}" for page in raw_pages]

    def whoami(self) -> str | None:
        """Проверяет токен на сайте. Возвращает имя аккаунта или None."""
        try:
            data = self._get("auth/me").get("data") or {}
        except SourceError:
            return None
        for key in ("username", "name", "login", "email"):
            if data.get(key):
                return str(data[key])
        return "аккаунт" if data else None

    def _closed_chapter_message(self, chapter: ChapterRef) -> str:
        """Сайт прячет закрытые главы под «нет такой страницы», без 401."""
        if self.site_id != SITE_ADULT:
            return (
                f"{chapter.label}: страницы недоступны.\n"
                "Глава могла быть снята по требованию правообладателя."
            )
        if not self.token:
            return (
                f"{chapter.label}: это раздел 18+, страницы он отдаёт только\n"
                "своему аккаунту. Войди на сайте в браузере и отдай приложению\n"
                "токен своей сессии:\n\n"
                "    y0mu --token-help\n\n"
                "Логин и капчу приложение за тебя не проходит."
            )
        return (
            f"{chapter.label}: сайт всё ещё не отдаёт страницы.\n"
            "Скорее всего токен истёк — возьми свежий: y0mu --token-help\n"
            "Ещё вариант: в профиле на сайте не включён показ 18+."
        )

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
                    headers={"Referer": self.referer(), "Accept": "image/*"},
                )
            except httpx.HTTPError as exc:
                last_error = str(exc)
                continue
            if response.status_code == 200 and response.content:
                return response.content
            if response.status_code == 200:
                # так отвечает чужой раздел: страница есть, а тела нет
                last_error = f"{_host_name(candidate)} вернул пустой ответ"
            else:
                last_error = f"{_host_name(candidate)}: HTTP {response.status_code}"
        raise SourceError(f"Не получилось скачать страницу ({last_error}).")


def _json_or_none(response: httpx.Response) -> dict | None:
    if "json" not in response.headers.get("content-type", ""):
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def _toast(payload: dict | None) -> str:
    """Свой текст ошибки mangalib отдаёт в data.toast.message."""
    if not payload:
        return ""
    data = payload.get("data")
    if isinstance(data, dict):
        toast = data.get("toast")
        if isinstance(toast, dict) and toast.get("message"):
            return str(toast["message"])
    message = payload.get("message")
    return str(message) if message else ""


def _host_name(host: str) -> str:
    return host.split("//", 1)[-1].split("/", 1)[0]
