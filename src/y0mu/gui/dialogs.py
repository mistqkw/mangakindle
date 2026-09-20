"""Небольшие окна настроек. Пароль отсюда уходит в keyring, не в конфиг."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal
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
from ..source import auth
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


class _TokenCheck(QThread):
    """Проверка токена на сайте — короткая, но всё же сеть."""

    done = Signal(object)

    def __init__(self, token: str) -> None:
        super().__init__()
        self.token = token

    def run(self) -> None:
        from ..source.mangalib import MangaLib

        try:
            with MangaLib(delay=0.2, token=self.token) as source:
                self.done.emit(source.whoami())
        except Exception:
            self.done.emit(None)


class TokenDialog(QDialog):
    """Токен для закрытого раздела: подсказка, буфер обмена, проверка."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Токен mangalib")
        self.setMinimumWidth(560)
        self.setStyleSheet(theme.QSS)
        self.checker: _TokenCheck | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        steps = QLabel(
            "Токен — пропуск твоей уже открытой сессии, он появляется только\n"
            "после входа в аккаунт на сайте.\n\n"
            "1. Войди на mangalib.me или hentailib.me в браузере\n"
            "2. F12 → вкладка Application (Приложение)\n"
            "3. Слева: Local storage → адрес сайта → строка с ключом auth\n"
            "4. Правой кнопкой по значению → Copy value\n"
            "5. Здесь нажми «Вставить из буфера» — токен я достану сам"
        )
        steps.setFont(theme.body_font(9))
        steps.setStyleSheet(f"color: {theme.MUTED};")
        layout.addWidget(steps)

        hint = QLabel(
            "Можно и через консоль: набери там руками  localStorage.auth  —\n"
            "вставлять код в консоль браузер не даст, и правильно сделает."
        )
        hint.setFont(theme.body_font(9))
        hint.setStyleSheet(f"color: {theme.MUTED};")
        layout.addWidget(hint)

        self.token = QLineEdit()
        self.token.setPlaceholderText("сюда попадёт токен или всё значение ключа auth")
        self.token.setFont(theme.body_font(9))
        layout.addWidget(self.token)

        self.result = QLabel(" ")
        self.result.setFont(theme.body_font(9))
        self.result.setWordWrap(True)
        layout.addWidget(self.result)

        buttons = QHBoxLayout()
        forget = PixelButton("Забыть токен")
        forget.setFixedWidth(148)
        forget.clicked.connect(self._forget)
        buttons.addWidget(forget)
        buttons.addStretch(1)

        paste = PixelButton("Вставить из буфера")
        paste.setFixedWidth(186)
        paste.clicked.connect(self._paste)
        buttons.addWidget(paste)

        self.save_button = PixelButton("Проверить и сохранить", primary=True)
        self.save_button.setFixedWidth(230)
        self.save_button.clicked.connect(self._check_and_save)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)

    # --- действия ---

    def _copy(self, text: str) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(text)
        self._show("Строка скопирована — вставь её в консоль браузера.", theme.MUTED)

    def _paste(self) -> None:
        from PySide6.QtWidgets import QApplication

        value = (QApplication.clipboard().text() or "").strip()
        if not value:
            self._show("Буфер пуст.", theme.ERROR)
            return
        self.token.setText(value)
        self._check_and_save()

    def _forget(self) -> None:
        try:
            self._show("Токен удалён." if auth.clear_token() else "Токена и не было.", theme.MUTED)
        except auth.AuthError as exc:
            self._show(str(exc), theme.ERROR)

    def _check_and_save(self) -> None:
        try:
            token = auth.clean_token(self.token.text())
        except auth.AuthError as exc:
            self._show(str(exc), theme.ERROR)
            return

        self.save_button.setEnabled(False)
        self._show("Проверяю на сайте…", theme.MUTED)
        self.checker = _TokenCheck(token)
        self.checker.done.connect(lambda who: self._on_checked(who, token))
        self.checker.start()

    def _on_checked(self, who, token: str) -> None:
        self.save_button.setEnabled(True)
        if who is None:
            self._show(
                "Сайт не принял этот токен — скопировалось не то или сессия истекла.",
                theme.ERROR,
            )
            return
        try:
            auth.save_token(token)
        except auth.AuthError as exc:
            self._show(str(exc), theme.ERROR)
            return
        self._show(f"Принято: ты вошёл как {who}.", theme.OK)
        self.accept()

    def _show(self, text: str, tone: str) -> None:
        self.result.setText(text)
        self.result.setStyleSheet(f"color: {tone};")
