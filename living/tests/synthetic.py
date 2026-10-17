"""Synthetic layers with the contract's file names and sizes: flat rectangles and a fake font."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

SIZE = (160, 90)
DURATIONS = [150, 110, 130, 110, 170, 110, 130, 110, 160, 120]
WINDOW = (8, 8, 48, 40)  # left, top, right, bottom
SCREEN = [70, 20, 44, 20]  # x, y, w, h
NOTE = [124, 22, 14, 9]
# Head bob per frame; frames 2 and 3 are the same, so a day sky gives two identical frames.
HEAD_OFFSETS = [0, 1, 1, 2, 3, 3, 2, 1, 0, 2]
CURSOR_FRAMES = [1, 2, 3, 4, 5]

WALL = (40, 32, 56)
SKY_COLORS = {"night": (10, 14, 40), "dawn": (180, 120, 140), "day": (120, 180, 230), "dusk": (200, 110, 70)}
MOON_COLORS = {
    "new": (30, 30, 50),
    "waxing_crescent": (200, 200, 170),
    "first_quarter": (210, 210, 180),
    "waxing_gibbous": (220, 220, 190),
    "full": (240, 240, 210),
    "waning_gibbous": (225, 225, 195),
    "last_quarter": (215, 215, 185),
    "waning_crescent": (205, 205, 175),
}
STAR = (250, 250, 255)
SCREEN_BG = (10, 60, 60)
NOTE_BG = (240, 220, 90)
HEAD = (230, 180, 150)
TEXT = "#9ff0d0"
CURSOR = "#f0fff8"
NOTE_INK = "#302010"
MOON_BOX = (30, 14, 36, 20)
MOON_UNLIT = (23, 58, 69)  # the moonFaint drop colour: its first column is the unlit disc
MOON_FAINT = (154, 164, 168)
MOON_LIT_PX = (32, 15)
MOON_UNLIT_PX = (30, 15)
PREFIX = "#f0c070"
FONT_CHARS = [chr(c) for c in range(33, 127)]


def _canvas() -> Image.Image:
    return Image.new("RGBA", SIZE, (0, 0, 0, 0))


def _fill(image: Image.Image, box, color) -> None:
    image.paste(tuple(color) + (255,), box)


def _rect_box(rect) -> tuple[int, int, int, int]:
    x, y, w, h = rect
    return (x, y, x + w, y + h)


def write_font(directory: Path, stem: str, chars, cell=(3, 5), advance=4, as_list=False, with_space=True) -> None:
    """A fake pixel font: each glyph is a pattern from the bits of its code point, one row of cells."""
    w, h = cell
    atlas = Image.new("RGBA", ((w + 1) * len(chars), h), (0, 0, 0, 0))
    glyphs = {}
    for i, ch in enumerate(chars):
        x0 = i * (w + 1)
        bits = (ord(ch) * 2654435761) & 0xFFFFFFFF
        for p in range(w * h):
            if p == 0 or (bits >> (p % 32)) & 1:
                atlas.putpixel((x0 + p % w, p // w), (255, 255, 255, 255))
        glyphs[ch] = {"x": x0, "y": 0, "w": w, "advance": advance}
    if with_space:
        glyphs[" "] = {"x": 0, "y": 0, "w": 0, "advance": advance}
    atlas.save(directory / f"{stem}.png")
    meta = {"height": h, "glyphs": [{"char": c, **g} for c, g in glyphs.items()] if as_list else glyphs}
    (directory / f"{stem}.json").write_text(json.dumps(meta), encoding="utf-8")


def layout_dict(**overrides) -> dict:
    layout = {
        "size": list(SIZE),
        "frameDurationsMs": DURATIONS,
        "layerOrder": ["sky", "stars", "moon", "base", "screen", "screenText", "cursor", "note", "noteText"],
        "screenText": {
            "rect": SCREEN,
            "lines": 3,
            "lineHeight": 6,
            "color": TEXT,
            "prefix": "> ",
            "prefixColor": PREFIX,
            "cursorColor": CURSOR,
            "cursorBlinkFrames": CURSOR_FRAMES,
        },
        "noteText": {"rect": NOTE, "color": NOTE_INK, "align": "center"},
        "moonVisible": {"night": 1.0, "dawn": 0.4, "day": 0, "dusk": 0.4},
        "moonFaint": {"appliesBelow": 1.0, "dropColor": "#173a45", "litColor": "#9aa4a8"},
        "starsVisible": {"night": True, "dawn": False, "day": False, "dusk": False},
    }
    layout.update(overrides)
    return layout


def make_layers(directory: Path, layout: dict | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for i, offset in enumerate(HEAD_OFFSETS, start=1):
        base = _canvas()
        _fill(base, (0, 0) + SIZE, WALL)
        base.paste((0, 0, 0, 0), WINDOW)
        base.paste((0, 0, 0, 0), _rect_box(SCREEN))
        _fill(base, (60, 60 + offset, 68, 68 + offset), HEAD)
        base.save(directory / f"base_f{i:02d}.png")

        stars = _canvas()
        stars.putpixel((12 + i, 12), STAR + (255,))
        stars.putpixel((40, 30 - i), STAR + (255,))
        stars.save(directory / f"stars_f{i:02d}.png")

        screen = _canvas()
        _fill(screen, _rect_box(SCREEN), SCREEN_BG)
        screen.save(directory / f"screen_blank_f{i:02d}.png")

    for sky, color in SKY_COLORS.items():
        image = _canvas()
        _fill(image, WINDOW, color)
        image.save(directory / f"sky_{sky}.png")
    for phase, color in MOON_COLORS.items():
        image = _canvas()
        _fill(image, MOON_BOX, color)
        _fill(image, (MOON_BOX[0], MOON_BOX[1], MOON_BOX[0] + 1, MOON_BOX[3]), MOON_UNLIT)
        image.save(directory / f"moon_{phase}.png")
    note = _canvas()
    _fill(note, _rect_box(NOTE), NOTE_BG)
    note.save(directory / "note_blank.png")

    write_font(directory, "font_tiny", FONT_CHARS)
    write_font(directory, "font_digits", [str(d) for d in range(10)], cell=(3, 5), advance=4)
    (directory / "layout.json").write_text(json.dumps(layout or layout_dict(), indent=2), encoding="utf-8")
    return directory
