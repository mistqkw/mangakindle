"""Отправка письмом. Настоящий SMTP не поднимаем — подменяем соединение."""

from contextlib import contextmanager

import pytest

from mangakindle.config import Settings
from mangakindle.deliver import email


class _FakeSmtp:
    def __init__(self) -> None:
        self.sent = []

    def send_message(self, message) -> None:
        self.sent.append(message)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def configured(monkeypatch):
    settings = Settings(
        kindle_email="me@kindle.com",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_user="me@example.com",
        max_email_mb=1,
    )
    monkeypatch.setattr(email, "load_password", lambda user: "app-password")
    return settings


def test_missing_settings_name_what_is_missing():
    with pytest.raises(email.MailError) as error:
        email.check_settings(Settings())
    message = str(error.value)
    assert "адрес Kindle" in message and "SMTP-сервер" in message
    assert "--setup-email" in message


def test_configured_settings_pass(configured):
    email.check_settings(configured)


def test_each_file_goes_as_its_own_letter(tmp_path, configured, monkeypatch):
    smtp = _FakeSmtp()
    monkeypatch.setattr(email, "_connect", lambda settings, password: smtp)

    files = []
    for name in ("Бродяга — гл1-2 часть 1.epub", "Бродяга — гл1-2 часть 2.epub"):
        path = tmp_path / name
        path.write_bytes(b"epub" * 100)
        files.append(path)

    report = email.send(files, configured)

    assert report == [f.name for f in files]
    assert len(smtp.sent) == 2
    first = smtp.sent[0]
    assert first["To"] == "me@kindle.com"
    assert first["From"] == "me@example.com"
    assert first["Subject"] == "Бродяга — гл1-2 часть 1"
    attachment = next(part for part in first.iter_attachments())
    assert attachment.get_filename() == "Бродяга — гл1-2 часть 1.epub"


def test_oversized_file_is_refused_with_advice(tmp_path, configured, monkeypatch):
    monkeypatch.setattr(email, "_connect", lambda settings, password: _FakeSmtp())
    big = tmp_path / "том.epub"
    big.write_bytes(b"x" * (2 * 1024 * 1024))  # лимит в фикстуре — 1 МБ

    with pytest.raises(email.MailError) as error:
        email.send([big], configured)

    assert "--split" in str(error.value)
    assert "лимит 1 МБ" in str(error.value)


def test_missing_password_is_reported_before_sending(configured, monkeypatch):
    monkeypatch.setattr(email, "load_password", lambda user: None)
    with pytest.raises(email.MailError, match="Нет пароля"):
        email.check_settings(configured)
