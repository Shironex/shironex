import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from scene import Layout, Scene, clamp_number, parse_color
from tests import synthetic as syn


class SceneCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.dir = syn.make_layers(Path(cls._tmp.name) / "layers")
        cls.scene = Scene(cls.dir)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()


class ComposeTest(SceneCase):
    def compose(self, sky="night", moon="full", title="Hello", number=7):
        return self.scene.compose(sky, moon, title, number)

    def test_frame_count_size_and_mode(self):
        frames = self.compose()
        self.assertEqual(len(frames), 10)
        self.assertTrue(all(f.size == syn.SIZE and f.mode == "RGB" for f in frames))

    def test_sky_and_stars_follow_the_time_of_day(self):
        star = (12 + 1, 12)
        sky_px = (20, 30)
        for sky, color in syn.SKY_COLORS.items():
            first = self.compose(sky=sky)[0]
            with self.subTest(sky=sky):
                self.assertEqual(first.getpixel(sky_px), color)
                self.assertEqual(first.getpixel(star) == syn.STAR, sky == "night")

    def test_moon_is_full_at_night_faint_at_dawn_and_hidden_by_day(self):
        lit, unlit = syn.MOON_LIT_PX, syn.MOON_UNLIT_PX
        night = self.compose(sky="night", moon="full")[0]
        self.assertEqual((night.getpixel(lit), night.getpixel(unlit)), (syn.MOON_COLORS["full"], syn.MOON_UNLIT))
        day = self.compose(sky="day", moon="full")[0]
        self.assertEqual((day.getpixel(lit), day.getpixel(unlit)), (syn.SKY_COLORS["day"], syn.SKY_COLORS["day"]))
        # moonFaint: the unlit disc is dropped and every other moon pixel is one flat colour, no blending.
        for sky in ("dawn", "dusk"):
            faint = self.compose(sky=sky, moon="waxing_gibbous")[0]
            with self.subTest(sky=sky):
                self.assertEqual(faint.getpixel(lit), syn.MOON_FAINT)
                self.assertEqual(faint.getpixel(unlit), syn.SKY_COLORS[sky])

    def test_without_a_moon_faint_rule_a_partial_moon_fades(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = syn.layout_dict()
            del layout["moonFaint"]
            scene = Scene(syn.make_layers(Path(tmp), layout))
            faint = scene.compose("dawn", "full", "x", 1)[0].getpixel(syn.MOON_LIT_PX)
        sky, moon = syn.SKY_COLORS["dawn"], syn.MOON_COLORS["full"]
        for s, m, f in zip(sky, moon, faint, strict=True):
            self.assertAlmostEqual(f, s + (m - s) * 0.4, delta=2)

    def test_each_moon_phase_uses_its_layer(self):
        for phase, color in syn.MOON_COLORS.items():
            with self.subTest(phase=phase):
                self.assertEqual(self.compose(moon=phase)[0].getpixel(syn.MOON_LIT_PX), color)

    def test_prompt_has_its_own_colour(self):
        x, y, _, _ = syn.SCREEN
        frame = self.compose(title="Hello")[0]
        self.assertEqual(frame.getpixel((x, y)), parse_color(syn.PREFIX))  # top-left pixel of ">"
        self.assertEqual(frame.getpixel((x + 8, y)), parse_color(syn.TEXT))  # top-left pixel of "H"

    def test_no_title_or_number_leaves_the_screen_and_note_blank(self):
        frames = self.compose(title=None, number=None)
        for rect, background in ((syn.SCREEN, syn.SCREEN_BG), (syn.NOTE, syn.NOTE_BG)):
            x, y, w, h = rect
            for frame in frames:
                colors = {c for _, c in frame.crop((x, y, x + w, y + h)).getcolors()}
                self.assertEqual(colors, {background})

    def test_cursor_blinks_on_the_listed_frames(self):
        cursor = self.scene.layout.screen.cursor_color
        x, y, _, _ = syn.SCREEN
        cx = x + 8 + 5 * 4  # after "> Hello"
        frames = self.compose(title="Hello")
        shown = [i + 1 for i, f in enumerate(frames) if f.getpixel((cx, y)) == cursor]
        self.assertEqual(shown, syn.CURSOR_FRAMES)

    def test_screen_text_stays_inside_its_rect(self):
        x, y, w, h = syn.SCREEN
        text = parse_color(syn.TEXT)
        frame = self.compose(title="Green Is Not Evidence: How I Keep AI-Written Code Honest")[0]
        hits = [(px, py) for px in range(syn.SIZE[0]) for py in range(syn.SIZE[1]) if frame.getpixel((px, py)) == text]
        self.assertTrue(hits)
        self.assertTrue(all(x <= px < x + w and y <= py < y + h for px, py in hits))

    def test_note_number_is_centred_and_clamped(self):
        x, y, w, h = syn.NOTE

        def ink(number):
            frame = self.compose(number=number)[0]
            return {
                (px, py) for px in range(x, x + w) for py in range(y, y + h) if frame.getpixel((px, py)) == ink_color
            }

        ink_color = parse_color(syn.NOTE_INK)
        # A 3x5 glyph in a 14x9 note: (14 - 3) // 2 = 5 px from the left, (9 - 5) // 2 = 2 px from the top.
        seven = ink(7)
        self.assertIn((x + 5, y + 2), seven)  # the synthetic font always inks a glyph's top-left pixel
        self.assertTrue(all(x + 5 <= px < x + 8 and y + 2 <= py < y + 7 for px, py in seven))
        self.assertEqual(ink(5000), ink(999))
        self.assertNotEqual(ink(99), ink(999))
        self.assertEqual(clamp_number(-3), 0)
        self.assertEqual(clamp_number(1234), 999)
        self.assertEqual(clamp_number(42), 42)

    def test_unknown_sky_or_moon_is_an_error(self):
        with self.assertRaises(ValueError):
            self.compose(sky="noon")
        with self.assertRaises(ValueError):
            self.compose(moon="blue")


class ValidationTest(unittest.TestCase):
    def test_contract_placeholder_values_are_rejected(self):
        bad = syn.layout_dict(moonVisible={"night": 1.0, "dawn": "faint or 0", "day": 0, "dusk": 0})
        with self.assertRaisesRegex(ValueError, "moonVisible.dawn"):
            Layout.from_dict(bad)

    def test_unknown_layer_names_are_rejected(self):
        bad = syn.layout_dict(layerOrder=["sky", "clouds", "base"])
        with self.assertRaisesRegex(ValueError, "clouds"):
            Layout.from_dict(bad)

    def test_cursor_frames_must_exist(self):
        bad = syn.layout_dict()
        bad["screenText"] = {**bad["screenText"], "cursorBlinkFrames": [0, 11]}
        with self.assertRaises(ValueError):
            Layout.from_dict(bad)

    def test_missing_and_wrong_sized_layers_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = syn.make_layers(Path(tmp))
            (d / "stars_f03.png").unlink()
            with self.assertRaisesRegex(FileNotFoundError, "stars_f03.png"):
                Scene(d)
        with tempfile.TemporaryDirectory() as tmp:
            d = syn.make_layers(Path(tmp))
            Image.new("RGBA", (10, 10)).save(d / "sky_day.png")
            with self.assertRaisesRegex(ValueError, "sky_day.png"):
                Scene(d)

    def test_a_single_file_stands_in_for_a_layer_that_does_not_animate(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = syn.make_layers(Path(tmp))
            (d / "screen_blank_f01.png").rename(d / "screen_blank.png")
            for i in range(2, 11):
                (d / f"screen_blank_f{i:02d}.png").unlink()
            self.assertEqual(len(Scene(d).compose("day", "new", "x", 1)), 10)

    def test_note_clamps_to_the_layout_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = syn.layout_dict()
            layout["noteText"] = {**layout["noteText"], "clampTo": 99}
            scene = Scene(syn.make_layers(Path(tmp), layout))
            self.assertEqual(scene.compose("day", "new", "x", 150)[0], scene.compose("day", "new", "x", 99)[0])

    def test_digits_font_is_optional(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = syn.make_layers(Path(tmp))
            (d / "font_digits.json").unlink()
            scene = Scene(d)
            self.assertIs(scene.digits, scene.font)

    def test_layout_round_trips_the_contract_example_keys(self):
        layout = Layout.from_dict(json.loads(json.dumps(syn.layout_dict())))
        self.assertEqual(layout.frame_count, 10)
        self.assertEqual(layout.moon_visible["dawn"], 0.4)
        self.assertEqual(layout.stars_visible, {"night": True, "dawn": False, "day": False, "dusk": False})


if __name__ == "__main__":
    unittest.main()
