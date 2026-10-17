import contextlib
import io
import itertools
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

import build
from moonphase import PHASES
from scene import parse_color
from solar import SKIES
from tests import synthetic as syn

LIVING = Path(__file__).resolve().parents[1]
REAL_LAYERS = LIVING / "layers"


def run(*argv: str) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        assert build.main(list(argv)) == 0
    return out.getvalue()


class BuildCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.layers = syn.make_layers(self.tmp / "layers")
        env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_TOKEN", "LIVING_README_TOKEN")}
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self._tmp.cleanup()

    def build(self, name="profile.gif", *extra: str) -> Path:
        out = self.tmp / name
        run("--layers", str(self.layers), "--out", str(out), *extra)
        return out


class BuildTest(BuildCase):
    FIXED = ("--sky", "night", "--moon", "full", "--title", "Taming 12 Terminals", "--number", "12")

    def test_gif_has_ten_frames_with_the_layout_durations_at_4x(self):
        gif = self.build("a.gif", *self.FIXED)
        im = Image.open(gif)
        self.assertEqual(im.size, (640, 360))
        self.assertEqual(im.n_frames, 10)
        self.assertEqual(im.info["loop"], 0)
        durations = []
        for i in range(im.n_frames):
            im.seek(i)
            durations.append(im.info["duration"])
        self.assertEqual(durations, syn.DURATIONS)

    def test_frames_match_the_composed_scene(self):
        gif = self.build("a.gif", *self.FIXED)
        expected = build.Scene(self.layers).compose("night", "full", "Taming 12 Terminals", 12)
        im = Image.open(gif)
        for i, frame in enumerate(expected):
            im.seek(i)
            self.assertEqual(im.convert("RGB").tobytes(), frame.resize((640, 360), Image.Resampling.NEAREST).tobytes())

    def test_identical_frames_are_not_merged(self):
        # With a day sky the synthetic frames 2 and 3 are pixel-identical.
        gif = self.build("day.gif", "--sky", "day", "--moon", "new", "--title", "x", "--number", "1")
        self.assertEqual(Image.open(gif).n_frames, 10)

    def test_same_inputs_give_identical_bytes(self):
        a = self.build("a.gif", *self.FIXED).read_bytes()
        b = self.build("b.gif", *self.FIXED).read_bytes()
        self.assertEqual(a, b)
        other = self.build("c.gif", *self.FIXED[:-1], "13").read_bytes()
        self.assertNotEqual(a, other)

    def test_now_picks_sky_and_moon(self):
        out = run(
            "--layers", str(self.layers), "--out", str(self.tmp / "x.gif"), "--now", "2026-12-24T22:00", "--offline"
        )
        self.assertIn("sky=night moon=full", out)
        out = run(
            "--layers", str(self.layers), "--out", str(self.tmp / "x.gif"), "--now", "2026-06-21T12:00", "--offline"
        )
        self.assertIn("sky=day", out)

    def test_missing_layers_build_nothing_and_succeed(self):
        out = run("--layers", str(self.tmp / "nothing"), "--out", str(self.tmp / "none.gif"))
        self.assertIn("nothing to build", out)
        self.assertFalse((self.tmp / "none.gif").exists())


class StateTest(BuildCase):
    def write_state(self, **data) -> Path:
        path = self.tmp / "state-in.json"
        path.write_text(json.dumps(data))
        return path

    def test_offline_uses_the_remembered_title_and_todays_number(self):
        state_in = self.write_state(title="Remembered", number=7, numberDate="2026-10-17")
        state_out = self.tmp / "state-out.json"
        out = run(
            "--layers",
            str(self.layers),
            "--out",
            str(self.tmp / "s.gif"),
            "--now",
            "2026-10-17T20:00",
            "--offline",
            "--state-in",
            str(state_in),
            "--state-out",
            str(state_out),
        )
        self.assertIn("number=7 (state)", out)
        self.assertIn("title='Remembered' (state)", out)
        self.assertEqual(
            json.loads(state_out.read_text()), {"title": "Remembered", "number": 7, "numberDate": "2026-10-17"}
        )

    def test_a_number_from_another_day_is_not_reused(self):
        state_in = self.write_state(title="T", number=7, numberDate="2026-10-16")
        out = run(
            "--layers",
            str(self.layers),
            "--out",
            str(self.tmp / "s.gif"),
            "--now",
            "2026-10-17T20:00",
            "--offline",
            "--state-in",
            str(state_in),
        )
        self.assertIn("number=0 (state)", out)

    def test_feed_failure_falls_back_to_the_state_title(self):
        state_in = self.write_state(title="Last known title")
        with mock.patch("blogfeed.fetch_feed", side_effect=OSError("down")):
            out = run(
                "--layers",
                str(self.layers),
                "--out",
                str(self.tmp / "s.gif"),
                "--number",
                "3",
                "--state-in",
                str(state_in),
            )
        self.assertIn("title='Last known title' (fallback)", out)

    def test_api_failure_falls_back_to_the_remembered_number(self):
        state_in = self.write_state(title="T", number=5, numberDate="2026-10-17")
        with (
            mock.patch.dict(os.environ, {"GITHUB_TOKEN": "tok"}),
            mock.patch("build.activity_number", side_effect=RuntimeError("Resource not accessible by integration")),
        ):
            out = run(
                "--layers",
                str(self.layers),
                "--out",
                str(self.tmp / "s.gif"),
                "--title",
                "x",
                "--now",
                "2026-10-17T12:00",
                "--state-in",
                str(state_in),
            )
        self.assertIn("number=5 (state)", out)

    def test_number_from_the_api_is_clamped(self):
        with (
            mock.patch.dict(os.environ, {"GITHUB_TOKEN": "tok"}),
            mock.patch("build.activity_number", return_value=4321),
        ):
            out = run("--layers", str(self.layers), "--out", str(self.tmp / "s.gif"), "--title", "x")
        self.assertIn("number=999 (github)", out)

    def test_optional_pat_wins_over_github_token(self):
        seen = []

        def fake(now, tz, login, token, post=None):
            seen.append(token)
            return 1

        with (
            mock.patch.dict(os.environ, {"GITHUB_TOKEN": "app", "LIVING_README_TOKEN": "pat"}),
            mock.patch("build.activity_number", side_effect=fake),
        ):
            run("--layers", str(self.layers), "--out", str(self.tmp / "s.gif"), "--title", "x")
        self.assertEqual(seen, ["pat"])

    def test_unreadable_state_is_ignored(self):
        path = self.tmp / "broken.json"
        path.write_text("{not json")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(build.State.read(path), build.State())


class ScriptMetadataTest(unittest.TestCase):
    def test_build_and_test_scripts_declare_the_same_dependencies(self):
        def metadata(path: Path) -> str:
            return re.search(r"# /// script\n(.*?)# ///", path.read_text(), re.S).group(1)

        self.assertEqual(metadata(LIVING / "build.py"), metadata(LIVING / "test.py"))


@unittest.skipUnless((REAL_LAYERS / "layout.json").exists(), "the real layers are not in living/layers")
class RealLayersTest(unittest.TestCase):
    """The committed art: every state composes, in the art's own palette."""

    @classmethod
    def setUpClass(cls):
        cls.scene = build.Scene(REAL_LAYERS)
        raw = json.loads((REAL_LAYERS / "layout.json").read_text(encoding="utf-8"))
        cls.palette = {parse_color(c) for c in raw["palette"]}

    def test_every_sky_and_moon_uses_only_palette_colours(self):
        title = "Green Is Not Evidence: How I Keep AI-Written Code Honest"
        for sky, moon in itertools.product(SKIES, PHASES):
            frames = self.scene.compose(sky, moon, title, 123)
            colors = set().union(*({c for _, c in f.getcolors(256)} for f in frames))
            with self.subTest(sky=sky, moon=moon):
                self.assertEqual(len(frames), 10)
                self.assertLessEqual(colors, self.palette)

    def test_default_build_writes_the_portrait(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "profile.gif"
            run(
                "--out", str(out), "--sky", "night", "--moon", "full", "--title", "Taming 12 Terminals", "--number", "7"
            )
            im = Image.open(out)
            self.assertEqual((im.size, im.n_frames), ((640, 360), 10))


if __name__ == "__main__":
    unittest.main()
