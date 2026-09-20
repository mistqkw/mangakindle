"""Небольшие окна настроек. Пароль отсюда уходит в keyring, не в конфиг."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from ..config import Settings
from ..deliver import email
from . import theme
from .widgets import PixelButton


class EmailDialog(QDialog):
    """Адрес Kindle и доступ к почте, с которой отправляем."""

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Отправка письмом")
        self.setMinimumWidth(460)
        self.setStyleSheet(theme.QSS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        note = QLabel(
            "Адрес отправителя должен быть в списке разрешённых в аккаунте\n"
            "Amazon: Личные документы → Список адресов e-mail для отправки.\n"
            "Для Gmail нужен пароль приложения, обычный не подойдёт."
        )
        note.setFont(theme.body_font(9))
        note.setStyleSheet(f"color: {theme.MUTED};")
        layout.addWidget(note)

        form = QFormLayout()
        form.setSpacing(8)
        self.kindle_email = self._field(settings.kindle_email, "имя@kindle.com")
        self.host = self._field(settings.smtp_host or "smtp.gmail.com", "smtp.gmail.com")
        self.port = self._field(str(settings.smtp_port or 587), "587")
        self.user = self._field(settings.smtp_user, "твой@gmail.com")
        self.password = self._field("", "пароль приложения")
        self.password.setEchoMode(QLineEdit.Password)
        if settings.smtp_user and email.load_password(settings.smtp_user):
            self.password.setPlaceholderText("уже сохранён — оставь пустым")

        for label, widget in (
            ("Адрес Kindle", self.kindle_email),
            ("SMTP-сервер", self.host),
            ("Порт", self.port),
            ("Логин", self.user),
            ("Пароль", self.password),
        ):
            caption = QLabel(label)
            caption.setFont(theme.body_font(9))
            form.addRow(caption, widget)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = PixelButton("Отмена")
        cancel.setFixedWidth(96)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)

        save = PixelButton("Сохранить", primary=True)
        save.setFixedWidth(126)
        save.clicked.connect(self._save)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def _field(self, value: str, placeholder: str) -> QLineEdit:
        field = QLineEdit(value)
        field.setPlaceholderText(placeholder)
        field.setFont(theme.body_font(10))
        return field

    def _save(self) -> None:
        self.settings.kindle_email = self.kindle_email.text().strip()
        self.settings.smtp_host = self.host.text().strip()
        port = self.port.text().strip()
        self.settings.smtp_port = int(port) if port.isdigit() else 587
        self.settings.smtp_user = self.user.text().strip()

        password = self.password.text().strip()
        if password and self.settings.smtp_user:
            email.save_password(self.settings.smtp_user, password)
        self.settings.save()
        self.accept()
