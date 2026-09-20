"""Тема TexFi для Qt: резкая графика, без Material-мягкости.

Пиксельный шрифт — только заголовки и крупные числа. Всё, что читают
(названия глав, подписи, настройки), набрано обычным шрифтом: bitmap
на 12px не читается, сколько его ни люби.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase

# --- палитра -----------------------------------------------------------

BG = "#14161b"
SURFACE = "#1c2026"
SURFACE_ALT = "#232830"
BORDER = "#2f3641"
TEXT = "#e8ecf2"
MUTED = "#8a94a6"
ACCENT = "#4a7dfb"          # фирменный синий экосистемы
ACCENT_DARK = "#2d55b8"
PAPER = "#e0c48c"           # вторичный акцент: тёплая бумага e-ink
OK = "#4ec27a"
ERROR = "#e5484d"
SHADOW = "#0b0d11"

SHADOW_OFFSET = 3           # смещение тени, без размытия

PIXEL_FAMILY = "Press Start 2P"
BODY_STACK = ("Inter", "Google Sans Flex", "Open Sans", "Cantarell", "Noto Sans", "DejaVu Sans")


def has_pixel_font() -> bool:
    return PIXEL_FAMILY in QFontDatabase.families()


def pixel_font(size: int) -> QFont:
    """Заголовки. Если пиксельного шрифта в системе нет — жирный обычный."""
    if has_pixel_font():
        font = QFont(PIXEL_FAMILY, size)
        font.setLetterSpacing(QFont.PercentageSpacing, 100)
        return font
    font = body_font(size + 3)
    font.setBold(True)
    return font


def body_font(size: int) -> QFont:
    families = QFontDatabase.families()
    for name in BODY_STACK:
        if name in families:
            return QFont(name, size)
    return QFont("", size)


def color(value: str) -> QColor:
    return QColor(value)


# --- стили -------------------------------------------------------------

QSS = f"""
QWidget {{
    background: {BG};
    color: {TEXT};
}}
QLineEdit {{
    background: {SURFACE_ALT};
    border: 2px solid {BORDER};
    border-radius: 0px;
    padding: 8px 10px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus {{
    border: 2px solid {ACCENT};
}}
QComboBox {{
    background: {SURFACE_ALT};
    border: 2px solid {BORDER};
    border-radius: 0px;
    padding: 6px 10px;
}}
QComboBox:hover {{ border: 2px solid {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE_ALT};
    border: 2px solid {ACCENT};
    selection-background-color: {ACCENT};
    selection-color: #ffffff;
    outline: none;
}}
QListWidget {{
    background: {SURFACE};
    border: 2px solid {BORDER};
    border-radius: 0px;
    outline: none;
    padding: 2px;
}}
QListWidget::item {{
    padding: 5px 4px;
    border: none;
}}
QListWidget::item:selected {{
    background: {SURFACE_ALT};
    color: {TEXT};
}}
QListWidget::indicator, QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border: 2px solid {BORDER};
    border-radius: 0px;
    background: {BG};
}}
QListWidget::indicator:hover, QCheckBox::indicator:hover {{
    border: 2px solid {ACCENT};
}}
QListWidget::indicator:checked, QCheckBox::indicator:checked {{
    background: {ACCENT};
    border: 2px solid {ACCENT};
}}
QScrollBar:vertical {{
    background: {BG};
    width: 12px;
    margin: 0px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: {ACCENT}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0px; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: {BG}; }}
QToolTip {{
    background: {SURFACE_ALT};
    color: {TEXT};
    border: 2px solid {ACCENT};
    padding: 4px;
}}
"""
