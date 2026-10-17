"""Load the exported layers and layout.json, and stack them into frames.

Layer files follow the contract in the art repo (aseprite-demo/living/CONTRACT.md):
per-frame layers are named <stem>_f01.png .. <stem>_fNN.png (a single
<stem>.png is accepted when a layer does not animate), every PNG is the layout
size, the screen font is font_tiny (or screenText.font) and the note font is
font_digits (or noteText.font) when it exists. Keys of layout.json this code
does not use (rects of the window and moon, notes for people) are ignored.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from moonphase import PHASES
from pixelfont import Font, TextBlock, layout_title
from solar import SKIES

LAYER_NAMES = ("sky", "stars", "moon", "base", "screen", "screenText", "cursor", "note", "noteText")
MAX_NUMBER = 999

Color = tuple[int, int, int]


def clamp_number(value: int, limit: int = MAX_NUMBER) -> int:
    """The note has room for three digits."""
    return max(0, min(limit, int(value)))


def parse_color(value: str) -> Color:
    text = str(value).lstrip("#")
    if len(text) != 6:
        raise ValueError(f"expected a #rrggbb colour, got {value!r}")
    return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))


def _rect(value, name: str) -> tuple[int, int, int, int]:
    if not (isinstance(value, list) and len(value) == 4 and all(isinstance(v, int) for v in value)):
        raise ValueError(f"{name}.rect must be [x, y, w, h] integers")
    return tuple(value)


def _visibility(table: dict | None, default: dict, name: str, kind: type) -> dict:
    merged = {**default, **(table or {})}
    out = {}
    for sky in SKIES:
        value = merged.get(sky)
        if isinstance(value, bool) or (kind is float and isinstance(value, (int, float))):
            out[sky] = kind(value)
        else:
            expected = "a number from 0 to 1" if kind is float else "true or false"
            raise ValueError(f"{name}.{sky} must be {expected}, got {value!r}")
        if kind is float and not 0 <= out[sky] <= 1:
            raise ValueError(f"{name}.{sky} must be between 0 and 1, got {value!r}")
    return out


@dataclass(frozen=True)
class ScreenText:
    rect: tuple[int, int, int, int]
    lines: int
    line_height: int
    color: Color
    prefix: str
    prefix_color: Color
    cursor_color: Color
    cursor_blink_frames: frozenset[int]
    cursor_size: tuple[int, int] | None
    hanging_indent: bool
    font: str


@dataclass(frozen=True)
class NoteText:
    rect: tuple[int, int, int, int]
    color: Color
    align: str
    clamp_to: int
    font: str | None


@dataclass(frozen=True)
class MoonFaint:
    """How a partly visible moon is drawn: unlit pixels dropped, the rest one flat colour."""

    applies_below: float
    drop_color: Color
    lit_color: Color


@dataclass(frozen=True)
class Layout:
    size: tuple[int, int]
    frame_durations_ms: tuple[int, ...]
    layer_order: tuple[str, ...]
    screen: ScreenText
    note: NoteText
    moon_visible: dict[str, float]
    moon_faint: MoonFaint | None
    stars_visible: dict[str, bool]
    background: Color

    @property
    def frame_count(self) -> int:
        return len(self.frame_durations_ms)

    @classmethod
    def from_dict(cls, d: dict) -> Layout:
        size = d.get("size")
        if not (isinstance(size, list) and len(size) == 2 and all(isinstance(v, int) and v > 0 for v in size)):
            raise ValueError("size must be [width, height]")
        durations = d.get("frameDurationsMs")
        if not (isinstance(durations, list) and durations and all(isinstance(v, int) and v > 0 for v in durations)):
            raise ValueError("frameDurationsMs must be a non-empty list of positive integers")
        order = d.get("layerOrder")
        if not isinstance(order, list) or not order:
            raise ValueError("layerOrder must be a non-empty list")
        unknown = [name for name in order if name not in LAYER_NAMES]
        if unknown:
            raise ValueError(f"layerOrder has unknown layers {unknown}; known: {list(LAYER_NAMES)}")

        st = d.get("screenText") or {}
        blink = st.get("cursorBlinkFrames", [])
        if not all(isinstance(f, int) and 1 <= f <= len(durations) for f in blink):
            raise ValueError(f"screenText.cursorBlinkFrames must be frame numbers 1..{len(durations)}")
        cursor_size = st.get("cursorSize")
        if cursor_size is not None and not (
            isinstance(cursor_size, list) and len(cursor_size) == 2 and all(isinstance(v, int) for v in cursor_size)
        ):
            raise ValueError("screenText.cursorSize must be [w, h] integers")
        screen = ScreenText(
            rect=_rect(st.get("rect"), "screenText"),
            lines=int(st["lines"]),
            line_height=int(st["lineHeight"]),
            color=parse_color(st["color"]),
            prefix=str(st.get("prefix", "")),
            prefix_color=parse_color(st.get("prefixColor", st["color"])),
            cursor_color=parse_color(st.get("cursorColor", st["color"])),
            cursor_blink_frames=frozenset(blink),
            cursor_size=tuple(cursor_size) if cursor_size else None,
            hanging_indent=bool(st.get("hangingIndent", False)),
            font=str(st.get("font", "font_tiny")),
        )

        nt = d.get("noteText") or {}
        align = nt.get("align", "center")
        if align not in ("left", "center", "right"):
            raise ValueError("noteText.align must be left, center or right")
        note = NoteText(
            rect=_rect(nt.get("rect"), "noteText"),
            color=parse_color(nt["color"]),
            align=align,
            clamp_to=clamp_number(nt.get("clampTo", MAX_NUMBER)),
            font=nt.get("font"),
        )

        faint = d.get("moonFaint")
        moon_faint = (
            MoonFaint(
                applies_below=float(faint.get("appliesBelow", 1.0)),
                drop_color=parse_color(faint["dropColor"]),
                lit_color=parse_color(faint["litColor"]),
            )
            if faint
            else None
        )

        return cls(
            size=tuple(size),
            frame_durations_ms=tuple(durations),
            layer_order=tuple(order),
            screen=screen,
            note=note,
            moon_visible=_visibility(
                d.get("moonVisible"), {"night": 1.0, "dawn": 0.0, "day": 0.0, "dusk": 0.0}, "moonVisible", float
            ),
            moon_faint=moon_faint,
            stars_visible=_visibility(
                d.get("starsVisible"), {"night": True, "dawn": False, "day": False, "dusk": False}, "starsVisible", bool
            ),
            background=parse_color(d.get("background", "#000000")),
        )


class Scene:
    """Everything loaded from a layers directory, ready to compose."""

    def __init__(self, layers_dir: Path):
        self.dir = Path(layers_dir)
        self.layout = Layout.from_dict(json.loads((self.dir / "layout.json").read_text(encoding="utf-8")))
        n = self.layout.frame_count
        self.base = self._frames("base", n)
        self.screen = self._frames("screen_blank", n)
        self.stars = self._frames("stars", n)
        self.skies = {sky: self._image(f"sky_{sky}.png") for sky in SKIES}
        self.moons = {phase: self._image(f"moon_{phase}.png") for phase in PHASES}
        self.note = self._image("note_blank.png")
        self.font = self._font(self.layout.screen.font)
        note_font = self.layout.note.font or "font_digits"
        if self.layout.note.font or (self.dir / f"{note_font}.json").exists():
            self.digits = self._font(note_font)
        else:
            self.digits = self.font

    def _font(self, stem: str) -> Font:
        png, meta = self.dir / f"{stem}.png", self.dir / f"{stem}.json"
        for path in (png, meta):
            if not path.exists():
                raise FileNotFoundError(f"missing font file {path}")
        return Font.load(png, meta)

    def _image(self, name: str) -> Image.Image:
        path = self.dir / name
        if not path.exists():
            raise FileNotFoundError(f"missing layer {path}")
        with Image.open(path) as im:
            image = im.convert("RGBA")
        if image.size != self.layout.size:
            raise ValueError(
                f"{name} is {image.size[0]}x{image.size[1]}, expected {self.layout.size[0]}x{self.layout.size[1]}"
            )
        return image

    def _frames(self, stem: str, n: int) -> list[Image.Image]:
        names = [f"{stem}_f{i:02d}.png" for i in range(1, n + 1)]
        if all((self.dir / name).exists() for name in names):
            return [self._image(name) for name in names]
        if (self.dir / f"{stem}.png").exists():
            return [self._image(f"{stem}.png")] * n
        missing = [name for name in names if not (self.dir / name).exists()]
        raise FileNotFoundError(f"missing layers in {self.dir}: {', '.join(missing)}")

    def screen_text(self, title: str) -> tuple[Image.Image, Image.Image]:
        """The title layer and the cursor layer, each the full canvas size."""
        st = self.layout.screen
        x, y, w, h = st.rect
        cursor_w, cursor_h = st.cursor_size or (self.font.cell_width, self.font.height)
        block = layout_title(title, self.font, w, st.lines, st.line_height, st.prefix, cursor_w, st.hanging_indent)
        colors = {"prefix": st.prefix_color, "text": st.color}
        text_layer = self._clipped(st.rect, lambda box: block.draw(box, self.font, colors))
        cx, cy = block.cursor
        cursor_layer = self._clipped(
            st.rect, lambda box: box.paste(st.cursor_color + (255,), (cx, cy, cx + cursor_w, cy + cursor_h))
        )
        return text_layer, cursor_layer

    def note_text(self, number: int) -> Image.Image:
        nt = self.layout.note
        x, y, w, h = nt.rect
        label = str(clamp_number(number, nt.clamp_to))
        ink = self.digits.ink_width(label)
        left = {"left": 0, "center": (w - ink) // 2, "right": w - ink}[nt.align]
        top = (h - self.digits.height) // 2
        block = TextBlock(runs=((left, top, label, "text"),), cursor=(0, 0))
        return self._clipped(nt.rect, lambda box: block.draw(box, self.digits, {"text": nt.color}))

    def moon_layer(self, phase: str, sky: str) -> Image.Image | None:
        """The moon as the sky shows it: hidden, faint or full."""
        visible = self.layout.moon_visible[sky]
        image = self.moons[phase]
        faint = self.layout.moon_faint
        if visible <= 0:
            return None
        if faint and visible < faint.applies_below:
            data, drop, lit = image.tobytes(), bytes(faint.drop_color), bytes(faint.lit_color) + b"\xff"
            pixels = bytearray()
            for i in range(0, len(data), 4):
                hidden = data[i + 3] == 0 or data[i : i + 3] == drop
                pixels += b"\0\0\0\0" if hidden else lit
            return Image.frombytes("RGBA", image.size, bytes(pixels))
        if visible >= 1:
            return image
        faded = image.copy()  # no moonFaint rule: fade with alpha instead
        faded.putalpha(image.getchannel("A").point(lambda a: (a * round(visible * 255) + 127) // 255))
        return faded

    def _clipped(self, rect: tuple[int, int, int, int], paint) -> Image.Image:
        x, y, w, h = rect
        box = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        paint(box)
        layer = Image.new("RGBA", self.layout.size, (0, 0, 0, 0))
        layer.paste(box, (x, y))
        return layer

    def compose(self, sky: str, moon: str, title: str | None, number: int | None) -> list[Image.Image]:
        """The RGB frames for one state of the room. A None title or number leaves that part blank."""
        if sky not in SKIES:
            raise ValueError(f"unknown sky {sky!r}")
        if moon not in PHASES:
            raise ValueError(f"unknown moon phase {moon!r}")
        layout = self.layout
        text_layer, cursor_layer = self.screen_text(title) if title is not None else (None, None)
        static = {
            "sky": self.skies[sky],
            "moon": self.moon_layer(moon, sky),
            "screenText": text_layer,
            "note": self.note,
            "noteText": self.note_text(number) if number is not None else None,
        }
        frames = []
        for i in range(layout.frame_count):
            per_frame = {
                "base": self.base[i],
                "screen": self.screen[i],
                "stars": self.stars[i] if layout.stars_visible[sky] else None,
                "cursor": cursor_layer if (i + 1) in layout.screen.cursor_blink_frames else None,
            }
            canvas = Image.new("RGBA", layout.size, layout.background + (255,))
            for name in layout.layer_order:
                layer = per_frame[name] if name in per_frame else static[name]
                if layer is not None:
                    canvas.alpha_composite(layer)
            frames.append(canvas.convert("RGB"))
        return frames
