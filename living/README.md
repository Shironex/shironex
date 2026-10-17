# Living README portrait

The portrait at the top of the profile README is rebuilt every hour by
`.github/workflows/living-readme.yml`:

- the **window** shows the time of day in Warsaw (night, dawn, day or dusk) and, at night, the real moon phase;
- the **monitor** shows the newest [shirone.blog](https://shirone.blog/rss.xml) post title with a blinking cursor;
- the **sticky note** shows my GitHub contributions today.

The art is drawn once in Aseprite and exported as flat PNG layers into `living/layers/` (the contract lives with
the art, in `aseprite-demo/living/CONTRACT.md`). `build.py` stacks the layers, draws the text with the pixel font,
and writes `profile.gif` at 4x. The Action force-pushes it, with a small `state.json`, to the `living-output` branch as a
single commit, only when the bytes change. The README links
`https://raw.githubusercontent.com/Shironex/shironex/living-output/profile.gif`; raw.githubusercontent.com and GitHub's
image proxy cache it for about 5 minutes, so a new picture can take that long to show.

If `living/layers/layout.json` is missing, the build prints a notice and publishes nothing.

## Preview locally

Needs [uv](https://docs.astral.sh/uv/); it installs Python 3.12+ and Pillow for the scripts.

```sh
uv run living/build.py                          # live data, writes living/out/profile.gif
uv run living/build.py --offline                # no network: title and number from --state-in
uv run living/build.py --sky dusk --moon waning_crescent --title "Taming 12 Terminals" --number 42
uv run living/build.py --now 2026-12-24T22:00   # what Christmas Eve will look like (Warsaw time)
GITHUB_TOKEN=$(gh auth token) uv run living/build.py   # with the real contribution count
uv run living/test.py                           # tests (add -v for names)
```

Flags: `--sky night|dawn|day|dusk`, `--moon <phase>`, `--title`, `--number`, `--now`, `--out`, `--layers`,
`--scale`, `--state-in`, `--state-out`, `--offline`. Run `uv run living/build.py --help` for details.

## How each part is decided

| Part | Source | Fallback |
|---|---|---|
| Sky | Sun elevation for Warsaw (NOAA solar calculator equations, `solar.py`) | none needed |
| Moon | Mean synodic month from the 2000-01-06 new moon, in eighths (`moonphase.py`) | none needed |
| Title | Newest item of `https://shirone.blog/rss.xml` by `pubDate` (`blogfeed.py`) | last title in `state.json` |
| Number | GitHub contribution calendar, today's Warsaw date (`activity.py`) | today's number in `state.json`, else 0 |

Sky boundaries: **night** below -6 degrees (civil twilight); **dawn** from civil dawn until 45 minutes after
sunrise; **day** until 45 minutes before sunset; **dusk** from then until civil dusk. Sunrise and sunset are at
-0.833 degrees. They land within about a minute of the USNO tables.

At dawn and dusk the moon follows the layout's `moonFaint` rule (only its lit pixels, in one flat grey); stars show
only at night.

The feed is not sorted by date, so the newest item wins by `pubDate`; two posts on the same date go to the one
listed last.

The screen holds about 10 characters on each of 5 lines, so a title is fitted in this order (`pixelfont.py`):

1. the whole title, word-wrapped, with the amber `> ` prompt on line 1;
2. the title before the first `: ` (the subtitle dropped);
3. that main title, ended at a word boundary with `…` on the last line.

A word is cut mid-word only when it is wider than a line. The cursor sits 1 px after the last glyph, or at the start
of the next line when one is free.

## Change the number on the note

Edit `activity_number()` in `living/activity.py`; it is the only place that decides the metric. It gets the time,
the Warsaw time zone, the login and a token, and returns an int (the note clamps it to 0..999).

The default metric works with the Action's own `GITHUB_TOKEN`: it reads the same contribution calendar as the
public profile, which includes private contributions because the profile shows them. A metric that needs private
data the profile does not show (for example per-repository counts in private repos) needs a token of mine: add a
fine-grained personal access token as the repository secret `LIVING_README_TOKEN` and it is used instead.

## Change the schedule

Edit the `cron` line in `.github/workflows/living-readme.yml` (UTC, minutes off the top of the hour, which is when
scheduled runs queue up). GitHub turns off scheduled workflows in a public repository after 60 days without
activity in it; if that happens, turn it back on in the Actions tab or push a commit.

## Fonts

`font_tiny.json` (the screen) and `font_digits.json` (the note) describe a glyph atlas:

```json
{ "cellHeight": 6, "spaceAdvance": 2, "glyphs": { "A": { "x": 0, "y": 0, "w": 3, "h": 6, "advance": 4 } } }
```

Per glyph: `x`, `y`, `w` (or `width`), optional `h`, `advance` (default `w + 1`) and `yOffset`. Glyph pixels are the
atlas pixels with alpha 128 or more, drawn in the layout's colour. Missing letters fall back to the other case, then
`?`; curly quotes, dashes and accents in titles are folded to plain ASCII first.
