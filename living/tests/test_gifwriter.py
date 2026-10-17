import io
import random
import unittest

from PIL import Image

from gifwriter import build_palette, encode_gif


def gif_blocks(data: bytes):
    """Walk a GIF and return (global table size, [(GCE delay, disposal)], [local table flags])."""
    assert data[:6] == b"GIF89a"
    packed = data[10]
    pos = 13
    gct = 0
    if packed & 0x80:
        gct = 2 ** ((packed & 7) + 1)
        pos += 3 * gct
    controls, local_flags = [], []
    while True:
        tag = data[pos]
        if tag == 0x3B:
            return gct, controls, local_flags
        if tag == 0x21:
            label = data[pos + 1]
            if label == 0xF9:
                controls.append((int.from_bytes(data[pos + 4 : pos + 6], "little"), (data[pos + 3] >> 2) & 7))
            pos += 2
            while data[pos]:
                pos += data[pos] + 1
            pos += 1
        elif tag == 0x2C:
            flags = data[pos + 9]
            local_flags.append(bool(flags & 0x80))
            pos += 10
            if flags & 0x80:
                pos += 3 * 2 ** ((flags & 7) + 1)
            pos += 1  # LZW minimum code size
            while data[pos]:
                pos += data[pos] + 1
            pos += 1
        else:
            raise AssertionError(f"unexpected block 0x{tag:02x} at {pos}")


def decode(data: bytes) -> list[Image.Image]:
    im = Image.open(io.BytesIO(data))
    frames = []
    for i in range(im.n_frames):
        im.seek(i)
        frames.append(im.convert("RGB"))
    return frames


def random_frames(n, w, h, colors, seed):
    rng = random.Random(seed)
    palette = [bytes(rng.randrange(256) for _ in range(3)) for _ in range(colors)]
    return [b"".join(rng.choice(palette) for _ in range(w * h)) for _ in range(n)]


class GifWriterTest(unittest.TestCase):
    def roundtrip(self, frames, w, h, durations, scale=1):
        data = encode_gif(frames, w, h, durations, scale=scale)
        decoded = decode(data)
        self.assertEqual(len(decoded), len(frames))
        for got, raw in zip(decoded, frames, strict=True):
            want = Image.frombytes("RGB", (w, h), raw).resize((w * scale, h * scale), Image.Resampling.NEAREST)
            self.assertEqual(got.tobytes(), want.tobytes())
        return data

    def test_noise_with_many_colours_survives_lzw_table_resets(self):
        frames = random_frames(3, 97, 61, 256, seed=1)
        self.roundtrip(frames, 97, 61, [100, 200, 300])

    def test_small_palettes(self):
        for colors in (1, 2, 3, 5, 17):
            with self.subTest(colors=colors):
                self.roundtrip(random_frames(2, 13, 7, colors, seed=colors), 13, 7, [100, 100], scale=3)

    def test_identical_frames_are_kept_with_their_own_delays(self):
        a = random_frames(1, 8, 8, 4, seed=2)[0]
        durations = [150, 110, 130, 110]
        data = self.roundtrip([a, a, a, a], 8, 8, durations, scale=4)
        _, controls, _ = gif_blocks(data)
        self.assertEqual([delay for delay, _ in controls], [15, 11, 13, 11])
        im = Image.open(io.BytesIO(data))
        read = []
        for i in range(im.n_frames):
            im.seek(i)
            read.append(im.info["duration"])
        self.assertEqual(read, durations)

    def test_one_global_palette_and_no_local_tables(self):
        frames = random_frames(4, 16, 9, 6, seed=3)
        data = encode_gif(frames, 16, 9, [100] * 4, scale=2)
        gct, controls, local_flags = gif_blocks(data)
        self.assertEqual(gct, 8)  # six colours round up to a table of eight
        self.assertEqual(len(controls), 4)
        self.assertEqual(local_flags, [False] * 4)
        self.assertTrue(all(disposal == 1 for _, disposal in controls))
        self.assertEqual(data[13 : 13 + 18], b"".join(build_palette(frames)))

    def test_loops_forever(self):
        im = Image.open(io.BytesIO(encode_gif(random_frames(2, 4, 4, 2, seed=4), 4, 4, [100, 100])))
        self.assertEqual(im.info["loop"], 0)

    def test_output_is_deterministic(self):
        frames = random_frames(3, 20, 10, 30, seed=5)
        self.assertEqual(encode_gif(frames, 20, 10, [100] * 3, scale=4), encode_gif(frames, 20, 10, [100] * 3, scale=4))

    def test_too_many_colours_is_an_error(self):
        frames = random_frames(1, 30, 30, 300, seed=6)
        self.assertGreater(len(set(frames[0][i : i + 3] for i in range(0, len(frames[0]), 3))), 256)
        with self.assertRaises(ValueError):
            encode_gif(frames, 30, 30, [100])

    def test_mismatched_durations_are_an_error(self):
        with self.assertRaises(ValueError):
            encode_gif(random_frames(2, 4, 4, 2, seed=7), 4, 4, [100])


if __name__ == "__main__":
    unittest.main()
