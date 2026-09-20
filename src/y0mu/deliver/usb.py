"""Отправка готового файла на Kindle по USB.

Ищем том Kindle, кладём файл в documents/ и сбрасываем кэш записи.
Если устройства нет — честно говорим об этом и оставляем файл в папке.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DOCUMENTS = "documents"
THUMBNAILS = Path("system") / "thumbnails"
LABEL = "Kindle"
THUMB_HEIGHT = 500  # столько же, сколько у миниатюр, которые делает сам Kindle


class KindleError(Exception):
    """Текст готов к показу пользователю."""


@dataclass
class Kindle:
    root: Path

    @property
    def documents(self) -> Path:
        return self.root / DOCUMENTS

    def free_bytes(self) -> int:
        usage = shutil.disk_usage(self.root)
        return usage.free


def _looks_like_kindle(path: Path) -> bool:
    """У Kindle в корне всегда есть documents/ и system/."""
    try:
        return (path / DOCUMENTS).is_dir() and (path / "system").is_dir()
    except OSError:
        return False


def _mount_points() -> list[Path]:
    if sys.platform == "win32":
        return _windows_volumes()
    user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    roots = [Path("/run/media") / user, Path("/media") / user, Path("/media"), Path("/mnt")]
    found: list[Path] = []
    for root in roots:
        try:
            found += [item for item in root.iterdir() if item.is_dir()]
        except OSError:
            continue
    return found


def _windows_volumes() -> list[Path]:
    import ctypes
    import string

    volumes: list[Path] = []
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    buffer = ctypes.create_unicode_buffer(1024)
    for letter in string.ascii_uppercase:
        drive = f"{letter}:\\"
        if not kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(drive), buffer, ctypes.sizeof(buffer),
            None, None, None, None, 0,
        ):
            continue
        if buffer.value.strip().lower() == LABEL.lower():
            volumes.append(Path(drive))
    return volumes


def _try_mount() -> None:
    """Kindle часто подключён, но не смонтирован. Просим udisks смонтировать."""
    if sys.platform == "win32":
        return
    device = Path("/dev/disk/by-label") / LABEL
    if not device.exists() or not shutil.which("udisksctl"):
        return
    subprocess.run(
        ["udisksctl", "mount", "-b", str(device)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def find_kindle(allow_mount: bool = True) -> Kindle | None:
    for point in _mount_points():
        if _looks_like_kindle(point):
            return Kindle(point)
    if allow_mount:
        _try_mount()
        for point in _mount_points():
            if _looks_like_kindle(point):
                return Kindle(point)
    return None


def send(path: Path, kindle: Kindle | None = None) -> Path:
    """Копирует файл в documents/ и проверяет, что он долетел целиком."""
    path = Path(path)
    if not path.exists():
        raise KindleError(f"Файла нет: {path}")

    kindle = kindle or find_kindle()
    if kindle is None:
        raise KindleError(
            "Kindle не найден. Подключи его по USB и разбуди экран —\n"
            "в спящем режиме он отключает режим накопителя.\n"
            "Файл никуда не делся, он лежит в папке с готовыми файлами."
        )

    size = path.stat().st_size
    free = kindle.free_bytes()
    if size > free:
        raise KindleError(
            f"На Kindle не хватает места: нужно {size / 1024 / 1024:.0f} МБ, "
            f"свободно {free / 1024 / 1024:.0f} МБ."
        )

    kindle.documents.mkdir(parents=True, exist_ok=True)
    target = kindle.documents / path.name
    shutil.copyfile(path, target)
    _flush()

    copied = target.stat().st_size
    if copied != size:
        raise KindleError(
            f"Файл скопирован не полностью: {copied} из {size} байт. "
            "Проверь кабель и повтори."
        )
    return target


def write_thumbnail(kindle: Kindle, document_uuid: str, cover: bytes) -> Path | None:
    """Кладёт обложку на полку Kindle рядом с его собственными миниатюрами.

    Имя файла Kindle берёт из UUID документа — у AZW3 он лежит внутри файла,
    поэтому миниатюру можно положить заранее, не дожидаясь, пока устройство
    само откроет книгу. Ничего чужого не трогаем: файл только добавляется.
    """
    import io

    from PIL import Image

    folder = kindle.root / THUMBNAILS
    if not folder.is_dir():
        return None
    try:
        image = Image.open(io.BytesIO(cover)).convert("L")
        scale = THUMB_HEIGHT / image.height
        image = image.resize(
            (max(1, round(image.width * scale)), THUMB_HEIGHT), Image.LANCZOS
        )
        target = folder / f"thumbnail_{document_uuid}_PDOC_portrait.jpg"
        image.save(target, format="JPEG", quality=85)
    except (OSError, ValueError):
        return None
    _flush()
    return target


def eject() -> bool:
    """Размонтирует том, чтобы кабель можно было выдернуть без вопросов."""
    if sys.platform == "win32":
        return False
    device = Path("/dev/disk/by-label") / LABEL
    if not device.exists() or not shutil.which("udisksctl"):
        return False
    result = subprocess.run(
        ["udisksctl", "unmount", "-b", str(device)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return result.returncode == 0


def _flush() -> None:
    if hasattr(os, "sync"):
        os.sync()
