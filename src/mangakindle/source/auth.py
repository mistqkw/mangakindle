"""Токен доступа к mangalib — свой, а не подменённый.

Приложение не логинится за тебя и не проходит капчу: ты входишь на сайте
в браузере сам и отдаёшь приложению готовый токен своей сессии. Дальше оно
ходит на сайт как ты — этого достаточно, чтобы отдавали страницы закрытых
разделов, которые твоему аккаунту и так доступны.

Токен лежит в системном хранилище паролей (keyring), не в конфиге.
"""

from __future__ import annotations

SERVICE = "mangakindle"
ACCOUNT = "mangalib"

# Строка для консоли браузера: находит токен в localStorage и кладёт
# в буфер обмена. copy() есть в консоли и Chrome, и Firefox.
CONSOLE_SNIPPET = (
    "copy((f=o=>o&&typeof o=='object'?Object.entries(o)"
    ".reduce((a,[k,v])=>a||(k=='access_token'?v:f(v)),null):null)"
    "(JSON.parse(localStorage.auth||'{}'))||'НЕ НАЙДЕН - войди в аккаунт')"
)

HOW_TO = f"""Токен — это пропуск твоей уже открытой сессии на сайте.
Он появляется только после входа в аккаунт.

1. Открой в браузере mangalib.me или hentailib.me и войди.
2. Нажми F12, вкладка Console (Консоль).
3. Вставь туда эту строку и нажми Enter — токен уйдёт в буфер обмена:

{CONSOLE_SNIPPET}

4. Вернись сюда и выполни:  mangakindle --token

   Без аргумента он сам возьмёт токен из буфера обмена
   и сразу проверит его на сайте.

Приложение не спрашивает логин с паролем, не логинится за тебя и не
проходит капчу. Токен лежит в системном хранилище, не в конфиге."""


class AuthError(Exception):
    """Текст готов к показу пользователю."""


def _keyring():
    try:
        import keyring
    except ImportError as exc:  # pragma: no cover - зависимость стоит из pyproject
        raise AuthError("Не установлен keyring — переустанови приложение.") from exc
    return keyring


def _wrap(action: str, exc: Exception) -> AuthError:
    return AuthError(
        f"Не получилось {action} токен в системном хранилище: {exc}\n"
        "Проверь, что запущен gnome-keyring или kwallet."
    )


def clean_token(token: str) -> str:
    """Приводит вставленное к виду токена и отсекает явно не токен."""
    token = (token or "").strip().strip('"\'')
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token:
        raise AuthError("Пустой токен.")
    if not token.isascii() or any(ch.isspace() for ch in token):
        raise AuthError(
            "Это не похоже на токен — в нём пробелы или нелатинские буквы.\n"
            "Скопируй значение целиком, без кавычек: mangakindle --token-help"
        )
    if len(token) < 20:
        raise AuthError("Слишком короткая строка для токена — скопировалось не всё.")
    return token


def save_token(token: str) -> None:
    token = clean_token(token)
    keyring = _keyring()
    try:
        keyring.set_password(SERVICE, ACCOUNT, token)
    except Exception as exc:  # backend может быть любой
        raise _wrap("сохранить", exc) from exc


def load_token() -> str | None:
    keyring = _keyring()
    try:
        return keyring.get_password(SERVICE, ACCOUNT) or None
    except Exception:
        # нет хранилища — просто работаем без токена
        return None


def clear_token() -> bool:
    keyring = _keyring()
    try:
        if keyring.get_password(SERVICE, ACCOUNT) is None:
            return False
        keyring.delete_password(SERVICE, ACCOUNT)
        return True
    except Exception as exc:
        raise _wrap("удалить", exc) from exc


CLIPBOARD_COMMANDS = (
    ["wl-paste", "--no-newline"],
    ["xclip", "-selection", "clipboard", "-o"],
    ["xsel", "--clipboard", "--output"],
    ["pbpaste"],
    ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
)


def from_clipboard() -> str:
    """Достаёт токен из буфера обмена — чтобы не таскать его руками."""
    import shutil
    import subprocess

    for command in CLIPBOARD_COMMANDS:
        if shutil.which(command[0]) is None:
            continue
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            continue
        value = (result.stdout or "").strip()
        if value:
            return value
    raise AuthError(
        "Буфер обмена пуст или его нечем прочитать.\n"
        "Скопируй токен и повтори, либо передай его явно:\n"
        "    mangakindle --token ТОКЕН"
    )
