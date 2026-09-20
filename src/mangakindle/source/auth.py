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

HOW_TO = """Как достать свой токен mangalib:

1. Открой mangalib.me в браузере и войди в аккаунт.
2. F12 -> вкладка Network (Сеть), обнови страницу.
3. Найди любой запрос к api2.mangalib.me или api.cdnlibs.org.
4. В Headers (Заголовки запроса) скопируй значение Authorization
   целиком после слова Bearer.

Дальше: mangakindle --token ВСТАВЬ_СЮДА

Токен ляжет в системное хранилище паролей. Приложение не просит логин
и пароль и не проходит за тебя капчу — только пользуется твоей сессией."""


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


def save_token(token: str) -> None:
    token = token.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token:
        raise AuthError("Пустой токен.")
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
