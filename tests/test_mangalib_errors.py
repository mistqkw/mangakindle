"""Как приложение объясняет отказы сайта. Сеть не нужна — httpx.MockTransport."""

import httpx
import pytest

from mangakindle.source.mangalib import API_HOSTS, MangaLib
from mangakindle.source.models import SourceError

DDOS_GUARD_HTML = "<!DOCTYPE html><title>Error 403</title><p>403 - Forbidden"


def _client(handler) -> MangaLib:
    return MangaLib(delay=0, transport=httpx.MockTransport(handler))


def test_falls_back_to_second_host_when_first_refuses():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        if request.url.host == httpx.URL(API_HOSTS[0]).host:
            return httpx.Response(403, text=DDOS_GUARD_HTML)
        return httpx.Response(200, json={"data": {"slug_url": "1--x", "name": "X"}})

    with _client(handler) as source:
        assert source.manga("1--x").title == "X"
    assert len(seen) == 2


def test_refusal_on_all_hosts_does_not_blame_the_title():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text=DDOS_GUARD_HTML)

    with _client(handler) as source:
        with pytest.raises(SourceError) as error:
            source.manga("1--x")

    message = str(error.value)
    assert "18+" not in message  # вот эту ошибку и чинили
    assert "не отвечает ни на одном" in message
    assert "--local" in message
    for host in API_HOSTS:
        assert host.split("//")[1].split("/")[0] in message


def test_unauthorized_says_login_is_needed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Unauthorized"})

    with _client(handler) as source:
        with pytest.raises(SourceError, match="требует вход"):
            source.manga("1--x")


def test_forbidden_with_site_message_is_quoted_as_is():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403, json={"data": {"toast": {"type": "error", "message": "Глава в раннем доступе"}}}
        )

    with _client(handler) as source:
        with pytest.raises(SourceError, match="Глава в раннем доступе"):
            source.manga("1--x")


def test_not_found_is_not_a_host_problem():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.host, request.headers.get("Site-Id")))
        return httpx.Response(404, json={"data": {"toast": {"message": "Not Found"}}})

    with _client(handler) as source:
        with pytest.raises(SourceError, match="ни в одном разделе"):
            source.manga("1--x")

    hosts = {host for host, _ in calls}
    assert hosts == {httpx.URL(API_HOSTS[0]).host}  # по запасным хостам не бегаем
    assert len({site for _, site in calls}) > 1     # зато обходим разделы сайта


def test_empty_chapter_list_explains_licensing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    with _client(handler) as source:
        with pytest.raises(SourceError, match="правообладателя"):
            source.chapters("1--x")


def test_link_host_picks_the_section():
    from mangakindle.source.mangalib import SITE_ADULT, SITE_MANGA, parse_link

    assert parse_link("https://hentailib.me/ru/manga/1--x").site_id == SITE_ADULT
    assert parse_link("https://mangalib.me/ru/manga/1--x").site_id == SITE_MANGA
    assert parse_link("https://example.org/1--x").site_id is None  # решим перебором


def test_own_token_goes_out_as_bearer():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        seen["site"] = request.headers.get("Site-Id")
        return httpx.Response(200, json={"data": {"slug_url": "1--x", "name": "X", "site": 4}})

    source = MangaLib(delay=0, transport=httpx.MockTransport(handler), token="abc", site_id=4)
    with source:
        source.manga("1--x")

    assert seen["auth"] == "Bearer abc"
    assert seen["site"] == "4"


def _adult_client(handler, token=None):
    return MangaLib(delay=0, transport=httpx.MockTransport(handler), token=token, site_id=4)


def _hidden(request: httpx.Request) -> httpx.Response:
    return httpx.Response(404, json={"data": {"toast": {"type": "silent", "message": "Not Found"}}})


def _chapter():
    from mangakindle.source.models import ChapterRef

    return ChapterRef(volume="1", number="1")


def test_closed_section_without_token_says_where_to_get_one():
    with _adult_client(_hidden) as source:
        with pytest.raises(SourceError) as error:
            source.pages("1--x", _chapter())

    message = str(error.value)
    assert "18+" in message and "--token-help" in message
    assert "капчу" in message  # честно говорим, чего приложение не делает


def test_closed_section_with_token_blames_the_token_not_the_title():
    with _adult_client(_hidden, token="stale") as source:
        with pytest.raises(SourceError, match="токен истёк"):
            source.pages("1--x", _chapter())


def test_ordinary_section_keeps_the_licensing_explanation():
    with _client(_hidden) as source:
        with pytest.raises(SourceError, match="правообладателя"):
            source.pages("1--x", _chapter())


def test_age_label_and_section_are_reported_separately():
    """Метка 18+ и закрытый раздел — разные вещи, и это должно быть видно."""
    from mangakindle.cli import _where

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": {"slug_url": "1--x", "name": "X", "site": 1,
                           "ageRestriction": {"label": "18+"}}},
        )

    with _client(handler) as source:
        info = source.manga("1--x")

    assert info.age == "18+" and info.site == 1
    assert _where(info) == " (18+, mangalib)"
