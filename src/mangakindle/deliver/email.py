"""Отправка на Kindle по почте (Send to Kindle).

Amazon принимает письмо с вложением на адрес вида имя@kindle.com и сам
конвертирует EPUB в свой формат — поэтому по почте едет EPUB, а не PDF.

Пароль приложения лежит в keyring, в конфиге его нет. Адрес отправителя
должен быть в списке разрешённых в аккаунте Amazon — это делается на
сайте Amazon, приложение туда не лезет.
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from mimetypes import guess_type
from pathlib import Path

from ..config import Settings

SERVICE = "mangakindle-smtp"

# Amazon держит лимит около 50 МБ, но обычная почта режет раньше:
# у Gmail потолок 25 МБ на письмо. Берём с запасом.
DEFAULT_LIMIT_MB = 24


class MailError(Exception):
    """Текст готов к показу пользователю."""


def save_password(user: str, password: str) -> None:
    import keyring

    try:
        keyring.set_password(SERVICE, user, password)
    except Exception as exc:
        raise MailError(f"Не получилось сохранить пароль: {exc}") from exc


def load_password(user: str) -> str | None:
    try:
        import keyring

        return keyring.get_password(SERVICE, user) or None
    except Exception:
        return None


def check_settings(settings: Settings) -> None:
    missing = [
        name
        for name, value in (
            ("адрес Kindle", settings.kindle_email),
            ("SMTP-сервер", settings.smtp_host),
            ("логин SMTP", settings.smtp_user),
        )
        if not value
    ]
    if missing:
        raise MailError(
            "Почта не настроена, не хватает: " + ", ".join(missing) + ".\n"
            "Настроить: mangakindle --setup-email"
        )
    if not load_password(settings.smtp_user):
        raise MailError(
            f"Нет пароля для {settings.smtp_user} в хранилище.\n"
            "Настроить заново: mangakindle --setup-email"
        )


def limit_bytes(settings: Settings) -> int:
    return max(1, settings.max_email_mb) * 1024 * 1024


def send(files: list[Path], settings: Settings) -> list[str]:
    """Каждый файл уходит отдельным письмом. Возвращает строки для отчёта."""
    check_settings(settings)
    password = load_password(settings.smtp_user) or ""
    limit = limit_bytes(settings)

    oversized = [f for f in files if f.stat().st_size > limit]
    if oversized:
        names = ", ".join(f"{f.name} ({f.stat().st_size / 1024 / 1024:.0f} МБ)" for f in oversized)
        raise MailError(
            f"Не влезает в письмо (лимит {settings.max_email_mb} МБ): {names}.\n"
            "Собери с --split или возьми диапазон поменьше."
        )

    report: list[str] = []
    with _connect(settings, password) as smtp:
        for path in files:
            smtp.send_message(_message(path, settings))
            report.append(path.name)
    return report


def _connect(settings: Settings, password: str):
    context = ssl.create_default_context()
    try:
        if settings.smtp_port == 465:
            smtp = smtplib.SMTP_SSL(settings.smtp_host, 465, context=context, timeout=60)
        else:
            smtp = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=60)
            smtp.starttls(context=context)
        smtp.login(settings.smtp_user, password)
        return smtp
    except smtplib.SMTPAuthenticationError as exc:
        raise MailError(
            "Почтовый сервер не принял логин или пароль.\n"
            "Для Gmail нужен пароль приложения, а не обычный пароль от ящика."
        ) from exc
    except (OSError, smtplib.SMTPException) as exc:
        raise MailError(f"Не получилось соединиться с {settings.smtp_host}: {exc}") from exc


def _message(path: Path, settings: Settings) -> EmailMessage:
    message = EmailMessage()
    message["From"] = settings.smtp_user
    message["To"] = settings.kindle_email
    message["Subject"] = path.stem
    message.set_content("Отправлено из MangaKindle.")

    guessed = guess_type(path.name)[0] or "application/octet-stream"
    maintype, _, subtype = guessed.partition("/")
    message.add_attachment(
        path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name
    )
    return message
