import io

from PIL import Image

from y0mu.convert.image import (
    KINDLE_HEIGHT,
    KINDLE_WIDTH,
    PageOptions,
    handle_spread,
    prepare_page,
    trim_borders,
)


def _jpeg(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.convert("L").save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


def _spread() -> Image.Image:
    """Разворот: левая половина тёмная, правая светлая — так видно порядок."""
    image = Image.new("L", (1600, 1000), 200)
    image.paste(Image.new("L", (800, 1000), 20), (0, 0))
    return image


def _center(image: Image.Image) -> int:
    return image.getpixel((image.width // 2, image.height // 2))


def test_single_page_gets_exact_kindle_size():
    page = Image.new("L", (900, 1300), 128)
    page.paste(Image.new("L", (400, 600), 20), (100, 100))
    result = prepare_page(_jpeg(page), PageOptions())
    assert len(result) == 1
    assert result[0].size == (KINDLE_WIDTH, KINDLE_HEIGHT)
    assert result[0].mode == "L"


def test_spread_is_split_right_half_first_for_rtl():
    halves = handle_spread(_spread(), PageOptions(direction="rtl"))
    assert len(halves) == 2
    # светлая правая половина идёт первой при чтении справа налево
    assert _center(halves[0]) > _center(halves[1])


def test_spread_split_order_flips_for_ltr():
    halves = handle_spread(_spread(), PageOptions(direction="ltr"))
    assert _center(halves[0]) < _center(halves[1])


def test_spread_split_gives_two_kindle_pages():
    result = prepare_page(_jpeg(_spread()), PageOptions(trim=False))
    assert len(result) == 2
    assert {page.size for page in result} == {(KINDLE_WIDTH, KINDLE_HEIGHT)}


def test_spread_keep_leaves_one_page():
    result = prepare_page(_jpeg(_spread()), PageOptions(spread="keep"))
    assert len(result) == 1
    assert result[0].size == (KINDLE_WIDTH, KINDLE_HEIGHT)


def test_spread_rotate_leaves_one_page():
    result = prepare_page(_jpeg(_spread()), PageOptions(spread="rotate", trim=False))
    assert len(result) == 1


def test_trim_removes_white_margins():
    image = Image.new("L", (600, 800), 255)
    image.paste(Image.new("L", (520, 700), 30), (40, 50))
    trimmed = trim_borders(image)
    assert trimmed.size == (524, 704)  # рамка в 2px вокруг рисунка остаётся


def test_trim_keeps_page_when_it_would_eat_everything():
    image = Image.new("L", (600, 800), 255)
    image.paste(Image.new("L", (10, 10), 0), (300, 400))
    assert trim_borders(image).size == (600, 800)
