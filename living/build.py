# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow==12.3.0"]
# ///
"""Compose the living README portrait and write profile.gif.

    uv run living/build.py                       # live data, writes living/out/profile.gif
    uv run living/build.py --sky dusk --moon full --title "Hello" --number 42
    uv run living/build.py --now 2026-12-24T22:00 --offline

Live data: the Warsaw sky and moon phase for --now (default: the current time),
the newest shirone.blog title, and GitHub contributions today. Every input has
an override flag, and the state file keeps the last good title and number so a
failing feed or API never fails the build.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from activity import activity_number  # noqa: E402
from blogfeed import latest_title  # noqa: E402
from gifwriter import encode_gif  # noqa: E402
from moonphase import PHASES, moon_phase  # noqa: E402
from scene import Scene, clamp_number  # noqa: E402
from solar import SKIES, time_of_day  # noqa: E402

TZ = ZoneInfo("Europe/Warsaw")
LATITUDE, LONGITUDE = 52.2297, 21.0122  # Warsaw
FEED_URL = "https://shirone.blog/rss.xml"
GITHUB_LOGIN = "Shironex"
DEFAULT_TITLE = "shirone.blog"
SCALE = 4


@dataclass(frozen=True)
class State:
    """What the last build knew, kept on the living-output branch for fallbacks."""

    title: str = DEFAULT_TITLE
    number: int = 0
    number_date: str = ""

    @classmethod
    def read(cls, path: Path | None) -> State:
        if not path or not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                title=str(raw.get("title") or DEFAULT_TITLE),
                number=int(raw.get("number", 0)),
                number_date=str(raw.get("numberDate", "")),
            )
        except (ValueError, TypeError, AttributeError) as exc:
            warn(f"ignoring unreadable state {path}: {exc!r}")
            return cls()

    def write(self, path: Path) -> None:
        data = {"title": self.title, "number": self.number, "numberDate": self.number_date}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def warn(message: str) -> None:
    prefix = "::warning::" if os.environ.get("GITHUB_ACTIONS") == "true" else "warning: "
    print(f"{prefix}{message}", file=sys.stderr)


def parse_now(text: str | None) -> datetime:
    if not text:
        return datetime.now(UTC)
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=TZ)


def resolve_number(args: argparse.Namespace, now: datetime, state: State) -> tuple[int, str]:
    if args.number is not None:
        return clamp_number(args.number), "flag"
    today = now.astimezone(TZ).date().isoformat()
    remembered = state.number if state.number_date == today else 0
    token = os.environ.get("LIVING_README_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if args.offline or not token:
        if not args.offline:
            warn("no LIVING_README_TOKEN or GITHUB_TOKEN; using the remembered number")
        return clamp_number(remembered), "state"
    try:
        return clamp_number(activity_number(now, TZ, GITHUB_LOGIN, token)), "github"
    except Exception as exc:  # any failure falls back: the API must never break the build
        warn(f"could not read GitHub activity: {exc!r}")
        return clamp_number(remembered), "state"


def resolve_title(args: argparse.Namespace, state: State) -> tuple[str, str]:
    if args.title is not None:
        return args.title, "flag"
    if args.offline:
        return state.title, "state"
    return latest_title(FEED_URL, state.title)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--sky", choices=SKIES, help="window sky (default: from --now in Warsaw)")
    p.add_argument("--moon", choices=PHASES, help="moon phase (default: from --now)")
    p.add_argument("--title", help="monitor text (default: newest shirone.blog title)")
    p.add_argument("--number", type=int, help="sticky note number, clamped to 0..999 (default: contributions today)")
    p.add_argument("--now", help="ISO time to render, e.g. 2026-12-24T22:00 (Warsaw time unless it has an offset)")
    p.add_argument("--out", type=Path, default=HERE / "out" / "profile.gif", help="where to write the GIF")
    p.add_argument("--layers", type=Path, default=HERE / "layers", help="directory with the exported layers")
    p.add_argument("--scale", type=int, default=SCALE, help="pixel scale of the GIF (default: 4)")
    p.add_argument("--state-in", type=Path, help="state.json from the last build, for fallbacks")
    p.add_argument("--state-out", type=Path, help="where to write the new state.json")
    p.add_argument("--offline", action="store_true", help="never touch the network; use the state for title and number")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not (args.layers / "layout.json").exists():
        print(f"No layers in {args.layers} yet (layout.json is missing); nothing to build.")
        return 0

    now = parse_now(args.now)
    state = State.read(args.state_in)
    scene = Scene(args.layers)

    sky = args.sky or time_of_day(now, LATITUDE, LONGITUDE)
    moon = args.moon or moon_phase(now)
    title, title_source = resolve_title(args, state)
    number, number_source = resolve_number(args, now, state)

    frames = scene.compose(sky, moon, title, number)
    width, height = scene.layout.size
    durations = scene.layout.frame_durations_ms
    gif = encode_gif([f.tobytes() for f in frames], width, height, durations, scale=args.scale)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(gif)

    if args.state_out:
        today = now.astimezone(TZ).date().isoformat()
        State(title=title, number=number, number_date=today).write(args.state_out)

    print(
        f"{now.astimezone(TZ):%Y-%m-%d %H:%M %Z}: sky={sky} moon={moon} "
        f"number={number} ({number_source}) title={title!r} ({title_source}) "
        f"-> {args.out} ({len(gif)} bytes)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
