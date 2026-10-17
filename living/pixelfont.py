"""Pixel font atlases, text clean-up, word wrap with ellipsis, and drawing.

Atlas JSON (the canonical shape, extra keys are ignored):

    {
      "height": 5,
      "glyphs": {
        "A": {"x": 0, "y": 0, "w": 3, "advance": 4},
        "g": {"x": 4, "y": 0, "w": 3, "h": 6, "advance": 4, "yOffset": 0}
      }
    }

Also accepted: "width" for "w", "xadvance" or "adv" for "advance", "yoffset" for
"yOffset", a top-level "glyphHeight", "cellHeight" or "lineHeight" for "height",
and "glyphs" as a list of objects with a "char" (or "ch") key. A glyph's "h"
defaults to the font height and "advance" to its width plus one. Without a
space glyph, a space advances by "spaceAdvance" or the most common advance.

Glyph pixels are the atlas pixels with alpha of at least 128; they are drawn in
the colour the layout asks for, so an atlas can be drawn in any colour.
"""

from __future__ import annotations

import json
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

ALPHA_THRESHOLD = 128

# Typography a blog title may carry, mapped to what a tiny ASCII font has.
_REPLACEMENTS = {
    "\u2018": "'",
    "\u2019": "'",
    "\u201a": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u201e": '"',
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": "-",
    "\u2212": "-",
    "\u0141": "L",
    "\u0142": "l",
    "\u00d8": "O",
    "\u00f8": "o",
    "\u00df": "ss",
}


# Kept as is: fonts may draw it as one glyph (layout_title swaps in "..." when they do not).
_KEEP = {"\u2026"}


def normalize_text(text: str) -> str:
    """Plain single-spaced text: smart punctuation and diacritics folded to ASCII-ish."""
    out = []
    for ch in text:
        if ch in _KEEP:
            out.append(ch)
            continue
        for part in unicodedata.normalize("NFKD", _REPLACEMENTS.get(ch, ch)):
            if not unicodedata.combining(part):
                out.append(" " if part.isspace() else part)
    return " ".join("".join(out).split())


@dataclass(frozen=True)
class Glyph:
    x: int
    y: int
    w: int
    h: int
    advance: int
    y_offset: int = 0


def _pick(d: dict, *keys: str, default=None):
    for key in keys:
        if key in d:
            return d[key]
    return default


class Font:
    def __init__(self, atlas: Image.Image, glyphs: dict[str, Glyph], height: int, space_advance: int):
        self.height = height
        self.glyphs = glyphs
        self.space_advance = space_advance
        alpha = atlas.convert("RGBA").getchannel("A")
        mask = alpha.point(lambda a: 255 if a >= ALPHA_THRESHOLD else 0)
        self._masks = {
            ch: mask.crop((g.x, g.y, g.x + g.w, g.y + g.h)) for ch, g in glyphs.items() if g.w > 0 and g.h > 0
        }
        widths = Counter(g.w for ch, g in glyphs.items() if ch != " " and g.w > 0)
        self.cell_width = widths.most_common(1)[0][0] if widths else max(1, height // 2)

    @classmethod
    def load(cls, png_path: Path, json_path: Path) -> Font:
        meta = json.loads(json_path.read_text(encoding="utf-8"))
        raw = meta.get("glyphs")
        if isinstance(raw, list):
            items = [(_pick(g, "char", "ch", "c"), g) for g in raw]
        elif isinstance(raw, dict):
            items = list(raw.items())
        else:
            raise ValueError(f"{json_path.name}: expected a 'glyphs' object or list")
        declared = _pick(meta, "height", "glyphHeight", "cellHeight", "lineHeight")
        parsed: dict[str, dict] = {}
        for ch, g in items:
            if not isinstance(ch, str) or len(ch) != 1:
                raise ValueError(f"{json_path.name}: glyph key {ch!r} is not a single character")
            w = int(_pick(g, "w", "width"))
            parsed[ch] = {
                "x": int(g["x"]),
                "y": int(g["y"]),
                "w": w,
                "h": _pick(g, "h", "height"),
                "advance": int(_pick(g, "advance", "xadvance", "adv", default=w + 1)),
                "y_offset": int(_pick(g, "yOffset", "yoffset", "dy", default=0)),
            }
        if not parsed:
            raise ValueError(f"{json_path.name}: no glyphs")
        height = int(declared if declared is not None else max(int(g["h"] or 0) for g in parsed.values()))
        if height <= 0:
            raise ValueError(f"{json_path.name}: no font height (set 'height')")
        glyphs = {ch: Glyph(**{**g, "h": int(g["h"] if g["h"] is not None else height)}) for ch, g in parsed.items()}
        advances = Counter(g.advance for ch, g in glyphs.items() if ch != " ")
        if " " in glyphs:
            space = glyphs[" "].advance
        else:
            space = int(meta.get("spaceAdvance", advances.most_common(1)[0][0] if advances else height // 2 + 1))
        with Image.open(png_path) as atlas:
            return cls(atlas, glyphs, height, space)

    def resolve(self, ch: str) -> str | None:
        """The atlas key drawn for `ch`: itself, the other case, or '?'. None draws nothing."""
        if ch == " ":
            return " " if " " in self.glyphs else None
        for candidate in (ch, ch.swapcase(), "?"):
            if candidate in self.glyphs:
                return candidate
        return None

    def advance(self, ch: str) -> int:
        key = self.resolve(ch)
        return self.glyphs[key].advance if key else self.space_advance

    def pen_width(self, text: str) -> int:
        """Where the pen ends after `text`: the sum of advances."""
        return sum(self.advance(ch) for ch in text)

    def ink_width(self, text: str) -> int:
        """Pixels `text` covers: its advances, minus the gap after the last glyph."""
        if not text:
            return 0
        key = self.resolve(text[-1])
        last_w = self.glyphs[key].w if key else 0
        return self.pen_width(text) - (self.advance(text[-1]) - last_w)

    def ellipsis(self) -> str:
        return "\u2026" if "\u2026" in self.glyphs else "..."

    def draw(self, layer: Image.Image, xy: tuple[int, int], text: str, color: tuple[int, int, int]) -> None:
        """Draw `text` on an RGBA layer with its top-left at `xy`."""
        x, y = xy
        for ch in text:
            key = self.resolve(ch)
            mask = self._masks.get(key) if key else None
            if mask is not None:
                layer.paste(color + (255,), (x, y + self.glyphs[key].y_offset), mask)
            x += self.advance(ch)


SUBTITLE_SEPARATOR = ": "


@dataclass(frozen=True)
class TextBlock:
    """Laid-out text: runs of (x, y, text, role) and the cursor's top-left corner.

    The role is "prefix" for the prompt and "text" for the rest, so each can have its own colour.
    """

    runs: tuple[tuple[int, int, str, str], ...]
    cursor: tuple[int, int]

    def draw(
        self, layer: Image.Image, font: Font, colors: dict[str, tuple[int, int, int]], origin: tuple[int, int] = (0, 0)
    ) -> None:
        for x, y, text, role in self.runs:
            font.draw(layer, (origin[0] + x, origin[1] + y), text, colors[role])


def _wrap(text: str, font: Font, first_avail: int, other_avail: int) -> list[tuple[int, int]]:
    """Greedy word wrap into (start, end) spans of `text`; only a word wider than a line is split."""
    spans: list[tuple[int, int]] = []
    start, n = 0, len(text)
    while start < n:
        avail = first_avail if not spans else other_avail
        best = None
        k = start
        while True:
            space = text.find(" ", k)
            word_end = n if space == -1 else space
            if font.ink_width(text[start:word_end]) > avail:
                break
            best = word_end
            if word_end == n:
                break
            k = word_end + 1
        if best is None:
            best = start + 1
            while best < n and text[best] != " " and font.ink_width(text[start : best + 1]) <= avail:
                best += 1
        spans.append((start, best))
        start = best
        while start < n and text[start] == " ":
            start += 1
    return spans


def _ellipsize(text: str, font: Font, avail: int) -> str:
    """The longest start of `text` that, with an ellipsis after it, has a pen width within `avail`."""
    ell = font.ellipsis()
    cut = len(text)
    while cut > 0 and font.pen_width(text[:cut] + ell) > avail:
        cut -= 1
    kept = text[:cut]
    if cut < len(text) and text[cut] != " " and " " in kept:
        kept = kept[: kept.rindex(" ")]  # end on a whole word when one fits
    return kept.rstrip(" ,.:;-") + ell


def _place(
    text: str,
    font: Font,
    width: int,
    max_lines: int,
    line_height: int,
    prefix: str,
    cursor_width: int,
    hanging_indent: bool,
    ellipsize: bool,
) -> TextBlock | None:
    """Wrap `prefix + text`; None when it does not fit and `ellipsize` is off."""
    prefix_pen = font.pen_width(prefix)
    indent = prefix_pen if hanging_indent else 0
    starts = [prefix_pen] + [indent] * (max_lines - 1)
    spans = _wrap(text, font, width - prefix_pen, width - indent) or [(0, 0)]
    pieces = [text[a:b] for a, b in spans]
    last = len(pieces) - 1
    if last < max_lines and starts[last] + font.pen_width(pieces[last]) + cursor_width <= width:
        cursor_line, cursor_x = last, starts[last] + font.pen_width(pieces[last])
    elif last + 1 < max_lines:
        cursor_line, cursor_x = last + 1, indent
    elif not ellipsize:
        return None
    else:
        last = max_lines - 1
        pieces = pieces[:last] + [_ellipsize(text[spans[last][0] :], font, width - starts[last] - cursor_width)]
        cursor_line, cursor_x = last, starts[last] + font.pen_width(pieces[last])
    runs = [(0, 0, prefix, "prefix")] if prefix else []
    runs += [(starts[i], i * line_height, piece, "text") for i, piece in enumerate(pieces) if piece]
    return TextBlock(runs=tuple(runs), cursor=(cursor_x, cursor_line * line_height))


def layout_title(
    title: str,
    font: Font,
    width: int,
    max_lines: int,
    line_height: int,
    prefix: str = "",
    cursor_width: int = 0,
    hanging_indent: bool = False,
) -> TextBlock:
    """Fit a post title into `max_lines` lines of `width` pixels, trying in order:

    1. the whole title, word-wrapped with `prefix` on the first line;
    2. the title before the first ": " (the subtitle dropped);
    3. that main title, ended at a word boundary with an ellipsis on the last line.

    A word is split mid-word only when it is wider than a line. The cursor always
    fits: one pixel gap after the last glyph (the font's letter spacing), or at
    the start of the next line when one is free. Later lines start at the left
    edge, or under the text after the prefix with `hanging_indent`.
    """
    if max_lines < 1:
        raise ValueError("max_lines must be at least 1")
    text = normalize_text(title)
    if "\u2026" not in font.glyphs:
        text = text.replace("\u2026", "...")
    main = text.split(SUBTITLE_SEPARATOR, 1)[0].strip() or text
    args = (font, width, max_lines, line_height, prefix, cursor_width, hanging_indent)
    for candidate in dict.fromkeys((text, main)):
        block = _place(candidate, *args, ellipsize=False)
        if block:
            return block
    return _place(main, *args, ellipsize=True)
