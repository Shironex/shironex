import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from pixelfont import Font, layout_title, normalize_text
from tests.synthetic import FONT_CHARS, write_font

ADVANCE = 4  # synthetic glyphs are 3 px wide with a 1 px gap
LAYERS = Path(__file__).resolve().parents[1] / "layers"
ELLIPSIS = "\u2026"


def texts(block):
    return [(x, y, text) for x, y, text, role in block.runs if role == "text"]


class SyntheticFontCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls._tmp.name)
        write_font(cls.dir, "font", FONT_CHARS)
        cls.font = Font.load(cls.dir / "font.png", cls.dir / "font.json")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def layout(self, text, width=44, lines=3, prefix="> ", cursor=3, **kwargs):
        return layout_title(text, self.font, width, lines, 6, prefix, cursor, **kwargs)

    def assert_fits(self, block, width, lines, cursor=3):
        for x, y, text, _ in block.runs:
            self.assertLessEqual(x + self.font.ink_width(text), width, text)
            self.assertLess(y // 6, lines)
        cx, cy = block.cursor
        self.assertLessEqual(cx + cursor, width)
        self.assertLess(cy // 6, lines)


class NormalizeTest(unittest.TestCase):
    def test_folds_typography_and_diacritics(self):
        self.assertEqual(normalize_text("\u201cQuote\u201d \u2014 it\u2019s fine"), '"Quote" - it\'s fine')
        self.assertEqual(
            normalize_text("Za\u017c\u00f3\u0142\u0107 g\u0119\u015bl\u0105 ja\u017a\u0144"), "Zazolc gesla jazn"
        )
        self.assertEqual(normalize_text("  tabs\tand\nnew\u00a0lines  "), "tabs and new lines")

    def test_keeps_the_ellipsis_for_fonts_that_have_it(self):
        self.assertEqual(normalize_text("wait" + ELLIPSIS), "wait" + ELLIPSIS)


class FontTest(SyntheticFontCase):
    def test_widths(self):
        self.assertEqual(self.font.height, 5)
        self.assertEqual(self.font.cell_width, 3)
        self.assertEqual(self.font.pen_width("ab"), 2 * ADVANCE)
        self.assertEqual(self.font.ink_width("ab"), 2 * ADVANCE - 1)
        self.assertEqual(self.font.ink_width(""), 0)

    def test_missing_glyphs_fall_back_to_the_other_case_then_question_mark(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_font(Path(tmp), "upper", [chr(c) for c in range(65, 91)] + ["?"])
            font = Font.load(Path(tmp) / "upper.png", Path(tmp) / "upper.json")
        self.assertEqual(font.resolve("a"), "A")
        self.assertEqual(font.resolve("~"), "?")
        self.assertEqual(font.advance("~"), font.advance("?"))

    def test_list_schema_and_aliases_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_font(d, "list", ["A", "B"], as_list=True, with_space=False)
            font = Font.load(d / "list.png", d / "list.json")
            self.assertEqual(sorted(font.glyphs), ["A", "B"])
            self.assertEqual(font.advance(" "), ADVANCE)  # most common advance without a space glyph

            Image.new("RGBA", (8, 6), (255, 255, 255, 255)).save(d / "alias.png")
            glyph = {"x": 0, "y": 0, "width": 4, "xadvance": 5, "yoffset": 1}
            (d / "alias.json").write_text(json.dumps({"glyphHeight": 6, "glyphs": {"x": glyph}}))
            alias = Font.load(d / "alias.png", d / "alias.json")
            self.assertEqual((alias.glyphs["x"].w, alias.glyphs["x"].h, alias.glyphs["x"].advance), (4, 6, 5))
            self.assertEqual(alias.glyphs["x"].y_offset, 1)

    def test_bad_schema_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            Image.new("RGBA", (4, 4)).save(d / "bad.png")
            (d / "bad.json").write_text(json.dumps({"frames": []}))
            with self.assertRaises(ValueError):
                Font.load(d / "bad.png", d / "bad.json")

    def test_draw_uses_the_requested_colour_only(self):
        layer = Image.new("RGBA", (20, 8), (0, 0, 0, 0))
        self.font.draw(layer, (1, 1), "AB", (1, 2, 3))
        colors = {c for _, c in layer.getcolors()}
        self.assertEqual(colors, {(0, 0, 0, 0), (1, 2, 3, 255)})


class SyntheticLayoutTest(SyntheticFontCase):
    """Policy rules, with a fixed-width fake font so the arithmetic is easy to follow."""

    def test_prompt_and_text_are_separate_runs(self):
        block = self.layout("Hello")
        self.assertEqual(block.runs, ((0, 0, "> ", "prefix"), (8, 0, "Hello", "text")))
        self.assertEqual(block.cursor, (8 + 5 * ADVANCE, 0))

    def test_later_lines_start_at_the_left_edge_or_under_the_text(self):
        self.assertEqual(texts(self.layout("Taming 12 Terminals")), [(8, 0, "Taming 12"), (0, 6, "Terminals")])
        hanging = self.layout("Taming 12 Terminals", hanging_indent=True)
        self.assertEqual(texts(hanging), [(8, 0, "Taming 12"), (8, 6, "Terminals")])

    def test_ellipsis_prefers_a_word_boundary(self):
        def last(text, width):
            return texts(layout_title(text, self.font, width, 1, 6))[-1][2]

        self.assertEqual(last("aaaa bbbb cccccccccccc", 48), "aaaa bbbb...")
        self.assertEqual(last("aaaa bbbb cccccccccccc", 40), "aaaa...")  # not "aaaa bb..."
        self.assertEqual(last("Evidence, How it went", 48), "Evidence...")  # trailing punctuation goes

    def test_a_word_longer_than_a_line_is_split(self):
        block = self.layout("Supercalifragilistic")
        self.assertEqual("".join(t for _, _, t in texts(block)), "Supercalifragilistic")
        self.assert_fits(block, 44, 3)

    def test_cursor_moves_to_a_free_line_when_the_last_one_is_full(self):
        block = self.layout("123456789")  # 9 glyphs fill the 36 px after the prompt
        self.assertEqual(texts(block), [(8, 0, "123456789")])
        self.assertEqual(block.cursor, (0, 6))

    def test_without_a_free_line_the_text_makes_room_for_the_cursor(self):
        block = self.layout("123456789", lines=1)
        self.assertTrue(texts(block)[-1][2].endswith("..."))
        self.assert_fits(block, 44, 1)

    def test_empty_title_shows_the_prompt_and_cursor(self):
        block = self.layout("   ")
        self.assertEqual(block.runs, ((0, 0, "> ", "prefix"),))
        self.assertEqual(block.cursor, (8, 0))

    def test_ellipsis_falls_back_to_dots_without_the_glyph(self):
        self.assertNotIn(ELLIPSIS, self.font.glyphs)
        block = self.layout("one two three four five six seven eight nine ten eleven", lines=2)
        self.assertTrue(texts(block)[-1][2].endswith("..."))


@unittest.skipUnless((LAYERS / "font_tiny.json").exists(), "the real font is not in living/layers")
class RealFontTitleTest(unittest.TestCase):
    """The title policy with the real font and the real screen: 40 x 30 px, 5 lines of 6 px."""

    @classmethod
    def setUpClass(cls):
        cls.font = Font.load(LAYERS / "font_tiny.png", LAYERS / "font_tiny.json")
        layout = json.loads((LAYERS / "layout.json").read_text(encoding="utf-8"))["screenText"]
        cls.width, cls.lines, cls.line_height = layout["rect"][2], layout["lines"], layout["lineHeight"]
        cls.prefix, cls.cursor = layout["prefix"], layout["cursorSize"][0]

    def layout(self, title):
        return layout_title(title, self.font, self.width, self.lines, self.line_height, self.prefix, self.cursor)

    def assert_fits(self, block):
        for x, y, text, _ in block.runs:
            self.assertLessEqual(x + self.font.ink_width(text), self.width, text)
            self.assertLess(y // self.line_height, self.lines)
        cx, cy = block.cursor
        self.assertLessEqual(cx + self.cursor, self.width)
        self.assertLess(cy // self.line_height, self.lines)

    def test_font_metrics(self):
        self.assertEqual(self.font.height, 6)
        self.assertEqual(self.font.pen_width("> "), 6)
        self.assertEqual(self.font.ellipsis(), ELLIPSIS)

    def test_short_title_fits_whole(self):
        block = self.layout("Taming 12 Terminals")
        self.assertEqual(texts(block), [(6, 0, "Taming 12"), (0, 6, "Terminals")])
        self.assertEqual(block.cursor, (self.font.pen_width("Terminals"), 6))
        self.assert_fits(block)

    def test_subtitle_is_dropped_when_the_whole_title_does_not_fit(self):
        block = self.layout("Green Is Not Evidence: How I Keep AI-Written Code Honest")
        self.assertEqual(texts(block), [(6, 0, "Green Is"), (0, 6, "Not"), (0, 12, "Evidence")])
        self.assertEqual(block.cursor, (self.font.pen_width("Evidence"), 12))  # 1 px after the last glyph
        self.assert_fits(block)
        same = self.layout("Taming 12 Terminals: How I Stopped the UI from Freezing")
        self.assertEqual(texts(same), [(6, 0, "Taming 12"), (0, 6, "Terminals")])

    def test_a_main_title_that_still_does_not_fit_ends_on_a_word_with_an_ellipsis(self):
        block = self.layout("Building an Activity Feed Without Opening a Single Port")
        lines = [t for _, _, t in texts(block)]
        self.assertEqual(lines, ["Building", "an Activity", "Feed", "Without", "Opening" + ELLIPSIS])
        self.assert_fits(block)
        self.assertEqual(block.cursor[1], 4 * self.line_height)

    def test_every_title_on_the_blog_fits(self):
        titles = [
            "Swapping the Engine Mid-Flight: Shiranami 2 and a 186k-Line Merge",
            "The asar Trap: When Your AI Agent Works in Dev but Dies in Production",
            "I Put a Browser Inside Electron (and Rewrote It Twice)",
            "Your Electron App Is Leaking Secrets (and How I Fixed It)",
            "7 Pitfalls I Predicted (and All 7 Happened)",
            "Hello, World",
        ]
        for title in titles:
            with self.subTest(title=title):
                self.assert_fits(self.layout(title))


if __name__ == "__main__":
    unittest.main()
