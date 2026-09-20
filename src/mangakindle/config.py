"""Настройки приложения и пути к данным.

Конфиг лежит в ~/.config/mangakindle/config.toml (Linux) и
%APPDATA%\\mangakindle\\config.toml (Windows). Пароли сюда не пишутся —
для них на этапе доставки будет keyring.
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

APP_DIR_NAME = "mangakindle"


def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_DIR_NAME


def cache_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / APP_DIR_NAME


def default_output_dir() -> Path:
    return Path.home() / "MangaKindle"


@dataclass
class Settings:
    # вывод
    output_dir: Path = field(default_factory=default_output_dir)
    output_format: str = "pdf"          # pdf | epub | cbz
    per_chapter: bool = False           # True — каждая глава отдельным файлом
    keep_cache: bool = False

    # обработка страниц
    direction: str = "rtl"              # rtl (манга) | ltr (манхва)
    spread: str = "split"               # split | rotate | keep
    trim: bool = True
    jpeg_quality: int = 85

    # сеть
    delay: float = 0.7                  # пауза между страницами, сек

    # доставка (заполняется на этапе 3)
    kindle_email: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or (config_dir() / "config.toml")
        if not path.exists():
            return cls()
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        flat: dict[str, object] = {}
        for section in raw.values():
            if isinstance(section, dict):
                flat.update(section)
        known = {f.name: f for f in fields(cls)}
        kwargs: dict[str, object] = {}
        for key, value in flat.items():
            f = known.get(key)
            if f is None:
                continue
            kwargs[key] = Path(value).expanduser() if f.name == "output_dir" else value
        return cls(**kwargs)

    def save(self, path: Path | None = None) -> Path:
        path = path or (config_dir() / "config.toml")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._to_toml(), encoding="utf-8")
        return path

    def _to_toml(self) -> str:
        def val(v: object) -> str:
            if isinstance(v, bool):
                return "true" if v else "false"
            if isinstance(v, (int, float)):
                return str(v)
            return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'

        out = ["# MangaKindle — настройки. Пароль SMTP здесь не хранится.", "", "[output]"]
        for name in ("output_dir", "output_format", "per_chapter", "keep_cache"):
            out.append(f"{name} = {val(getattr(self, name))}")
        out += ["", "[pages]"]
        for name in ("direction", "spread", "trim", "jpeg_quality"):
            out.append(f"{name} = {val(getattr(self, name))}")
        out += ["", "[network]", f"delay = {val(self.delay)}"]
        out += ["", "[kindle]"]
        for name in ("kindle_email", "smtp_host", "smtp_port", "smtp_user"):
            out.append(f"{name} = {val(getattr(self, name))}")
        return "\n".join(out) + "\n"
