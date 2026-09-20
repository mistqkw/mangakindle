"""Командная строка: ссылка -> файл для Kindle.

GUI появится на этапе 2 и будет дёргать те же функции, что и этот модуль.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import APP_NAME, __version__
from .config import Settings
from .convert import azw3
from .deliver import email, usb
from .pipeline import Cancelled, build
from .source import auth
from .source.local import LocalSource
from .source.mangalib import MangaLib, parse_link
from .source.models import ChapterRef, SourceError


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.token_help:
        print(auth.HOW_TO)
        return 0
    if args.token is not None:
        return _save_token(args.token)
    if args.forget_token:
        print("Токен удалён." if auth.clear_token() else "Токена и не было.")
        return 0
    if args.setup_email:
        return _setup_email()

    if not args.url and not args.local:
        if sys.stdin.isatty() and sys.stdout.isatty():
            # запуск без аргументов из меню или двойным кликом
            return _interactive()
        parser.error("нужна ссылка на mangalib или --local с папкой/архивом")

    settings = Settings.load()
    if args.out:
        settings.output_dir = Path(args.out).expanduser()
    # по почте Amazon сам конвертирует EPUB, поэтому для неё это разумный
    # выбор по умолчанию; явный --format всегда сильнее
    settings.output_format = args.format or ("epub" if args.to == "email" else "pdf")
    settings.direction = args.direction
    settings.spread = args.spread
    settings.trim = not args.no_trim
    settings.per_chapter = args.split
    settings.keep_cache = args.keep_cache
    settings.cover = not args.no_cover
    if args.to == "email":
        settings.max_part_bytes = email.limit_bytes(settings)
    settings.jpeg_quality = args.quality
    settings.delay = args.delay

    try:
        return _run(args, settings)
    except Cancelled:
        print("\nОтменено.")
        return 130
    except KeyboardInterrupt:
        print("\nОтменено.")
        return 130
    except (email.MailError, auth.AuthError, SourceError) as exc:
        sys.stdout.flush()
        print(f"\n{exc}", file=sys.stderr)
        return 2


def _run(args: argparse.Namespace, settings: Settings) -> int:
    wanted: str | None = args.chapters

    if args.local:
        source = LocalSource(args.local)
        manga = source.manga()
        chapters = source.chapters()
    else:
        target = parse_link(args.url)
        source = MangaLib(
            delay=settings.delay,
            token=auth.load_token(),
            site_id=target.site_id,
        )
        manga = source.manga(target.slug)
        chapters = source.chapters(target.slug)
        if target.is_chapter and not wanted:
            wanted = target.number

    with source:
        print(f"{manga.title}{_where(manga)} — глав доступно: {len(chapters)}")

        if args.list or not wanted:
            _print_chapters(chapters)
            if not args.list:
                print("\nВыбери главы: --chapters 1-3  |  --chapters 1,5,7  |  --chapters all")
            return 0

        selected = _select(chapters, wanted)
        if not selected:
            print(f"Под «{wanted}» не подошла ни одна глава.", file=sys.stderr)
            return 2

        where = "на Kindle" if args.to == "kindle" else f"в {settings.output_dir}"
        target = "по файлу на главу" if settings.per_chapter else "одним файлом"
        print(f"Беру {len(selected)} гл. {target}, формат {settings.output_format}, "
              f"направление {settings.direction}, разворот: {settings.spread}, {where}")
        if args.to == "email":
            email.check_settings(settings)  # до скачивания, а не после
        warning = _size_warning(selected, settings)
        if warning:
            print(warning)

        result = build(source, manga, selected, settings, on_progress=_progress)

    print()
    for path in result.files:
        size = path.stat().st_size / 1024 / 1024
        print(f"Готово: {path}  ({size:.1f} МБ)")
    print(f"Страниц всего: {result.pages}")

    if args.to == "kindle":
        _send_to_kindle(result.files, eject_after=args.eject)
    elif args.to == "email":
        _send_by_email(result.files, settings)
    if result.skipped:
        print(f"Пропущено: {len(result.skipped)}")
        for line in result.skipped[:5]:
            print(f"  · {line}")
    return 0


def _force_utf8_output() -> None:
    """Windows по умолчанию отдаёт консоли cp1251 и падает на кириллице."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _interactive() -> int:
    """Диалог в терминале для запуска из меню — без ключей и без GUI."""
    print(f"{APP_NAME} {__version__} — манга на Kindle\n")
    try:
        url = input("Ссылка на мангу: ").strip()
        if not url:
            return 0
        argv = [url]
        spec = input("Главы (1-3, 1,5,7 или all): ").strip()
        if spec:
            argv += ["--chapters", spec]
        fmt = input("Формат — pdf для USB, epub для почты [pdf]: ").strip().lower()
        if fmt in ("pdf", "epub", "cbz"):
            argv += ["--format", fmt]
        where = input("Куда — [1] сразу на Kindle, [2] в папку [1]: ").strip()
        if where in ("", "1", "kindle"):
            argv += ["--to", "kindle"]
        if input("Каждую главу отдельным файлом? [нет/да]: ").strip().lower() in ("y", "д", "да"):
            argv.append("--split")
        print()
        code = main(argv)
    except (EOFError, KeyboardInterrupt):
        print("\nОтменено.")
        return 130
    try:
        input("\nEnter — закрыть окно ")
    except (EOFError, KeyboardInterrupt):
        pass
    return code


def _send_to_kindle(files: list[Path], eject_after: bool = False) -> None:
    """Копирует готовые файлы на устройство. Ошибка доставки не отменяет сборку."""
    sys.stdout.flush()
    try:
        kindle = usb.find_kindle()
        if kindle is None:
            raise usb.KindleError(
                "Kindle не найден. Подключи его по USB и разбуди экран —\n"
                "в спящем режиме он отключает режим накопителя."
            )
        print(f"\nKindle: {kindle.root}")
        for path in files:
            target = usb.send(path, kindle)
            print(f"  скопировано: {target.name}")
            thumb = _put_cover_on_shelf(kindle, target)
            if thumb:
                print("  обложка положена на полку")
        if eject_after and usb.eject():
            print("Устройство отмонтировано — можно отключать кабель.")
        else:
            print("Запись сброшена на диск — можно отключать кабель.")
    except usb.KindleError as exc:
        print(f"\n{exc}", file=sys.stderr)
        print("Файлы остались в папке, отправишь позже.", file=sys.stderr)


def _send_by_email(files: list[Path], settings: Settings) -> None:
    sys.stdout.flush()
    try:
        sent = email.send(files, settings)
        print(f"\nОтправлено на {settings.kindle_email}: {', '.join(sent)}")
        print("Amazon сконвертирует сам — книга появится на устройстве через пару минут.")
    except email.MailError as exc:
        print(f"\n{exc}", file=sys.stderr)
        print("Файлы остались в папке, отправишь позже.", file=sys.stderr)


def _save_token(value: str) -> int:
    """Проверяет токен на сайте и только потом кладёт в хранилище."""
    if not value:
        print("Беру токен из буфера обмена…")
        value = auth.from_clipboard()
    token = auth.clean_token(value)

    print("Проверяю на сайте…")
    with MangaLib(delay=0.2, token=token) as source:
        who = source.whoami()
    if who is None:
        print(
            "\nСайт не принял этот токен.\n"
            "Скорее всего скопировалось не то или сессия истекла.\n"
            "Как взять свежий: y0mu --token-help",
            file=sys.stderr,
        )
        return 2

    auth.save_token(token)
    print(f"Токен принят: ты вошёл как {who}. Закрытый раздел открыт.")
    return 0


def _setup_email() -> int:
    """Спрашивает настройки почты. Пароль уходит в keyring, не в конфиг."""
    import getpass

    settings = Settings.load()
    print("Настройка отправки на Kindle письмом.\n")
    print("Адрес отправителя должен быть в списке разрешённых в аккаунте Amazon:")
    print("Личные документы -> Список адресов e-mail для отправки.\n")

    def ask(label: str, current: str) -> str:
        suffix = f" [{current}]" if current else ""
        value = input(f"{label}{suffix}: ").strip()
        return value or current

    settings.kindle_email = ask("Адрес Kindle (...@kindle.com)", settings.kindle_email)
    settings.smtp_host = ask("SMTP-сервер", settings.smtp_host or "smtp.gmail.com")
    port = ask("Порт", str(settings.smtp_port or 587))
    settings.smtp_port = int(port) if port.isdigit() else 587
    settings.smtp_user = ask("Логин (твой почтовый адрес)", settings.smtp_user)

    password = getpass.getpass("Пароль приложения (не показывается): ").strip()
    if password:
        email.save_password(settings.smtp_user, password)
    settings.save()

    print("\nСохранено. Пароль лежит в системном хранилище, в конфиге его нет.")
    print("Для Gmail нужен именно пароль приложения, обычный не подойдёт.")
    return 0


def _put_cover_on_shelf(kindle, path: Path):
    """Для AZW3 миниатюру можно положить сразу — UUID документа лежит в файле."""
    if path.suffix.lower() != ".azw3":
        return None
    document_uuid = azw3.document_uuid(path)
    cover = azw3.extract_cover(path)
    if not document_uuid or not cover:
        return None
    return usb.write_thumbnail(kindle, document_uuid, cover)


def _size_warning(selected: list[ChapterRef], settings: Settings) -> str:
    """Грубая прикидка: ~40 страниц на главу, ~0.4 МБ на страницу."""
    if settings.per_chapter or len(selected) < 20:
        return ""
    estimate = len(selected) * 40 * 0.4
    if estimate < 500:
        return ""
    return (
        f"Осторожно: {len(selected)} глав одним файлом — это примерно "
        f"{estimate / 1024:.1f} ГБ.\n"
        "Kindle такой файл откроет нескоро. Лучше взять диапазон поменьше "
        "или добавить --split."
    )


def _where(manga) -> str:
    """Раздел и возрастная метка. Метка ни на что не влияет — закрыт только
    отдельный раздел 18+, и видеть это полезно сразу."""
    from .source.mangalib import SITE_NAMES

    parts = [p for p in (manga.age, SITE_NAMES.get(manga.site)) if p]
    return f" ({', '.join(parts)})" if parts else ""


def _progress(phase: str, done: int, total: int) -> None:
    bar = ""
    if total:
        filled = int(20 * done / total)
        bar = "[" + "#" * filled + "." * (20 - filled) + f"] {done}/{total}"
    sys.stdout.write(f"\r{phase} {bar}   ")
    sys.stdout.flush()


def _print_chapters(chapters: list[ChapterRef], limit: int = 40) -> None:
    for chapter in chapters[:limit]:
        print(f"  {chapter.label}")
    if len(chapters) > limit:
        print(f"  ... и ещё {len(chapters) - limit}")


def _select(chapters: list[ChapterRef], spec: str) -> list[ChapterRef]:
    """Отбор глав по номеру: all | 3 | 1-10 | 1,4,7-9"""
    spec = spec.strip().lower()
    if spec in ("all", "все", "*"):
        return list(chapters)

    def number(chapter: ChapterRef) -> float:
        try:
            return float(chapter.number)
        except ValueError:
            return -1.0

    selected: list[ChapterRef] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part[1:]:
            low, _, high = part.partition("-")
            try:
                start, end = float(low), float(high)
            except ValueError:
                raise SourceError(f"Не понял диапазон «{part}».") from None
            selected += [c for c in chapters if start <= number(c) <= end]
        else:
            try:
                value = float(part)
            except ValueError:
                raise SourceError(f"Не понял номер главы «{part}».") from None
            selected += [c for c in chapters if number(c) == value]

    seen: set[tuple[str, str]] = set()
    unique = []
    for chapter in selected:
        key = (chapter.volume, chapter.number)
        if key not in seen:
            seen.add(key)
            unique.append(chapter)
    return unique


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="y0mu",
        description=f"{APP_NAME} {__version__} — манга с mangalib.me в файл для Kindle 11th gen",
    )
    parser.add_argument("url", nargs="?", help="ссылка на мангу или на главу")
    parser.add_argument("--local", help="папка или ZIP/CBZ с сохранёнными страницами")
    parser.add_argument("--chapters", help="all | 3 | 1-10 | 1,4,7-9")
    parser.add_argument("--list", action="store_true", help="показать список глав и выйти")
    parser.add_argument("--split", action="store_true",
                        help="каждая глава отдельным файлом (по умолчанию — один файл на выбор)")
    parser.add_argument("--to", choices=("folder", "kindle", "email"), default="folder",
                        help="folder — в папку, kindle — по USB, email — письмом на Kindle")
    parser.add_argument("--eject", action="store_true",
                        help="отмонтировать Kindle после копирования")
    parser.add_argument("--format", choices=("pdf", "azw3", "epub", "cbz"), default=None,
                        help="pdf — для USB, azw3 — для USB с обложкой на полке "
                             "(нужен calibre), epub — для отправки по почте")
    parser.add_argument("--direction", choices=("rtl", "ltr"), default="rtl")
    parser.add_argument("--spread", choices=("split", "rotate", "keep"), default="split")
    parser.add_argument("--no-trim", action="store_true", help="не обрезать поля")
    parser.add_argument("--no-cover", action="store_true",
                        help="не класть обложку с сайта первой страницей")
    parser.add_argument("--out", help="папка для готовых файлов")
    parser.add_argument("--keep-cache", action="store_true", help="не удалять скачанные страницы")
    parser.add_argument("--quality", type=int, default=85, help="качество JPEG, по умолчанию 85")
    parser.add_argument("--delay", type=float, default=0.7, help="пауза между запросами, сек")
    parser.add_argument("--setup-email", action="store_true",
                        help="настроить отправку письмом на Kindle")
    parser.add_argument("--token", nargs="?", const="", metavar="ТОКЕН",
                        help="сохранить токен mangalib; без значения — взять из буфера обмена")
    parser.add_argument("--token-help", action="store_true",
                        help="как достать свой токен из браузера")
    parser.add_argument("--forget-token", action="store_true", help="удалить сохранённый токен")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    return parser
