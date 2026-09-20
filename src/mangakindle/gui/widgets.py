"""Виджеты TexFi: квадратные, с офсетной тенью без размытия.

Тень рисуется вручную — сдвинутый прямоугольник, а не Material elevation.
У кнопки при нажатии тень уезжает внутрь, иначе пиксельная кнопка выглядит
мёртвой картинкой.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QWidget

from . import theme


class PixelCard(QFrame):
    """Блок с бордером 2px и офсетной тенью."""

    def __init__(self, parent: QWidget | None = None, background: str = theme.SURFACE) -> None:
        super().__init__(parent)
        self._background = QColor(background)
        self.setContentsMargins(0, 0, 0, 0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12 + theme.SHADOW_OFFSET, 10 + theme.SHADOW_OFFSET)
        layout.setSpacing(8)
        self.body = layout

    def paintEvent(self, event) -> None:  # noqa: N802 - имя от Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        offset = theme.SHADOW_OFFSET
        area = self.rect().adjusted(0, 0, -offset - 1, -offset - 1)

        painter.fillRect(area.translated(offset, offset), QColor(theme.SHADOW))
        painter.fillRect(area, self._background)
        painter.setPen(QPen(QColor(theme.BORDER), 2))
        painter.drawRect(area)


class PixelButton(QPushButton):
    """Кнопка с офсетной тенью; при нажатии вдавливается."""

    def __init__(self, text: str, primary: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.primary = primary
        self.setCursor(Qt.PointingHandCursor)
        self.setFont(theme.body_font(10))
        self.setMinimumHeight(34)
        self.setFlat(True)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        offset = theme.SHADOW_OFFSET
        pressed = self.isDown()
        enabled = self.isEnabled()

        area = self.rect().adjusted(0, 0, -offset - 1, -offset - 1)
        if pressed:
            area = area.translated(offset, offset)
        else:
            painter.fillRect(area.translated(offset, offset), QColor(theme.SHADOW))

        if not enabled:
            fill, border, text = QColor(theme.SURFACE), QColor(theme.BORDER), QColor(theme.MUTED)
        elif self.primary:
            fill = QColor(theme.ACCENT_DARK if pressed else theme.ACCENT)
            border, text = QColor(theme.ACCENT_DARK), QColor("#ffffff")
        else:
            fill = QColor(theme.SURFACE_ALT)
            border = QColor(theme.ACCENT if self.underMouse() else theme.BORDER)
            text = QColor(theme.TEXT)

        painter.fillRect(area, fill)
        painter.setPen(QPen(border, 2))
        painter.drawRect(area)
        painter.setPen(text)
        painter.setFont(self.font())
        painter.drawText(area, Qt.AlignCenter, self.text())


class PixelProgress(QWidget):
    """Прогресс пиксельными блоками — без плавной заливки."""

    BLOCKS = 24

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._value = 0.0
        self.setFixedHeight(18)

    def set_value(self, value: float) -> None:
        value = max(0.0, min(1.0, value))
        if abs(value - self._value) > 0.001:
            self._value = value
            self.update()

    def value(self) -> float:
        return self._value

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.fillRect(self.rect(), QColor(theme.BG))

        gap = 2
        width = (self.width() - gap * (self.BLOCKS - 1)) / self.BLOCKS
        filled = round(self._value * self.BLOCKS)
        for index in range(self.BLOCKS):
            left = round(index * (width + gap))
            block = QRect(left, 0, max(1, round(width)), self.height())
            painter.fillRect(block, QColor(theme.ACCENT if index < filled else theme.BORDER))


class SectionTitle(QLabel):
    """Заголовок секции — здесь пиксельный шрифт уместен."""

    def __init__(self, text: str, size: int = 8, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setFont(theme.pixel_font(size))
        self.setStyleSheet(f"color: {theme.MUTED};")
