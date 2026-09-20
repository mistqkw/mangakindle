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
        calls.append(request.url.host)
        return httpx.Response(404, json={"data": {"toast": {"message": "Not Found"}}})

    with _client(handler) as source:
        with pytest.raises(SourceError, match="не найдена"):
            source.manga("1--x")
    assert len(calls) == 1  # по остальным хостам не бегаем


def test_empty_chapter_list_explains_licensing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    with _client(handler) as source:
        with pytest.raises(SourceError, match="правообладателя"):
            source.chapters("1--x")
