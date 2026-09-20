"""Точка входа GUI."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .. import APP_NAME, __version__
from . import theme


def main(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setFont(theme.body_font(10))

    from .window import MainWindow

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
