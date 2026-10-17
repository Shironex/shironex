"""A small, exact GIF89a writer for pixel art.

Why not Pillow's GIF encoder: it merges consecutive identical frames (adding
their durations), may build per-frame palettes, and its output can change
between Pillow versions. This writer always emits:

- one global colour table holding exactly the colours used, sorted by RGB;
- every frame, with its own delay, never merged or dithered;
- the first frame in full, later frames cropped to the area that changed
  (disposal "do not dispose", so the previous frame shows through);
- a NETSCAPE2.0 block that loops forever.

The same input always gives the same bytes.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence

MAX_COLORS = 256
_MAX_CODE = 4096


def build_palette(frames: Sequence[bytes]) -> list[bytes]:
    """The sorted, unique RGB triplets used across all frames."""
    colors = set()
    for data in frames:
        colors.update(data[i : i + 3] for i in range(0, len(data), 3))
    if len(colors) > MAX_COLORS:
        raise ValueError(f"the frames use {len(colors)} colours; a GIF palette holds {MAX_COLORS}")
    return sorted(colors)


def _index_frame(data: bytes, lut: dict[bytes, int]) -> bytes:
    return bytes(lut[data[i : i + 3]] for i in range(0, len(data), 3))


def _changed_box(prev: bytes, cur: bytes, width: int, height: int) -> tuple[int, int, int, int] | None:
    """(left, top, right, bottom) of the pixels that differ, or None when the frames match."""
    top = bottom = left = right = None
    for y in range(height):
        a, b = prev[y * width : (y + 1) * width], cur[y * width : (y + 1) * width]
        if a == b:
            continue
        first = next(x for x in range(width) if a[x] != b[x])
        last = next(x for x in range(width - 1, -1, -1) if a[x] != b[x])
        top = y if top is None else top
        bottom = y + 1
        left = first if left is None else min(left, first)
        right = last + 1 if right is None else max(right, last + 1)
    return None if top is None else (left, top, right, bottom)


def _scaled_region(indices: bytes, width: int, box: tuple[int, int, int, int], scale: int) -> bytes:
    left, top, right, bottom = box
    out = bytearray()
    for y in range(top, bottom):
        row = indices[y * width + left : y * width + right]
        wide = bytearray(len(row) * scale)
        for k in range(scale):
            wide[k::scale] = row
        out += bytes(wide) * scale
    return bytes(out)


def lzw_encode(indices: bytes, min_code_size: int) -> bytes:
    """GIF-flavoured LZW: variable-width codes, packed least significant bit first."""
    clear = 1 << min_code_size
    end = clear + 1
    out = bytearray()
    bits = 0
    nbits = 0
    code_size = min_code_size + 1
    next_code = end + 1
    table: dict[int, int] = {}

    def emit(code: int) -> None:
        nonlocal bits, nbits
        bits |= code << nbits
        nbits += code_size
        while nbits >= 8:
            out.append(bits & 0xFF)
            bits >>= 8
            nbits -= 8

    emit(clear)
    if not indices:
        emit(end)
    else:
        prefix = indices[0]
        for byte in indices[1:]:
            key = (prefix << 8) | byte
            code = table.get(key)
            if code is not None:
                prefix = code
                continue
            emit(prefix)
            # The decoder widens its codes one entry behind us, when its next free
            # code reaches 2**code_size; mirror that before emitting the next code.
            if next_code == (1 << code_size) and code_size < 12:
                code_size += 1
            if next_code < _MAX_CODE:
                table[key] = next_code
                next_code += 1
            else:
                emit(clear)
                table.clear()
                code_size = min_code_size + 1
                next_code = end + 1
            prefix = byte
        emit(prefix)
        if next_code == (1 << code_size) and code_size < 12:
            code_size += 1
        emit(end)
    if nbits:
        out.append(bits & 0xFF)
    return bytes(out)


def _sub_blocks(data: bytes) -> bytes:
    out = bytearray()
    for i in range(0, len(data), 255):
        chunk = data[i : i + 255]
        out.append(len(chunk))
        out += chunk
    out.append(0)
    return bytes(out)


def encode_gif(
    frames: Sequence[bytes],
    width: int,
    height: int,
    durations_ms: Sequence[int],
    scale: int = 1,
    loop: int = 0,
) -> bytes:
    """Encode RGB frames (width * height * 3 bytes each) as an animated GIF, scaled by `scale`."""
    if not frames:
        raise ValueError("no frames")
    if len(durations_ms) != len(frames):
        raise ValueError(f"{len(frames)} frames but {len(durations_ms)} durations")
    if any(len(f) != width * height * 3 for f in frames):
        raise ValueError("every frame must be width * height RGB bytes")
    if scale < 1:
        raise ValueError("scale must be at least 1")

    palette = build_palette(frames)
    lut = {color: i for i, color in enumerate(palette)}
    indexed = [_index_frame(f, lut) for f in frames]
    table_bits = max(1, (len(palette) - 1).bit_length())
    min_code_size = max(2, table_bits)
    color_table = b"".join(palette) + b"\0\0\0" * ((1 << table_bits) - len(palette))

    out = bytearray(b"GIF89a")
    out += struct.pack("<HHBBB", width * scale, height * scale, 0x80 | 0x70 | (table_bits - 1), 0, 0)
    out += color_table
    out += b"\x21\xff\x0bNETSCAPE2.0" + struct.pack("<BBHB", 3, 1, loop, 0)

    for i, (indices, duration) in enumerate(zip(indexed, durations_ms, strict=True)):
        if i == 0:
            box = (0, 0, width, height)
        else:
            box = _changed_box(indexed[i - 1], indices, width, height) or (0, 0, 1, 1)
        left, top, right, bottom = box
        delay = round(duration / 10)
        # Graphic control: disposal 1 (leave in place), no transparency.
        out += b"\x21\xf9\x04" + struct.pack("<BHBB", 1 << 2, delay, 0, 0)
        out += b"\x2c" + struct.pack(
            "<HHHHB", left * scale, top * scale, (right - left) * scale, (bottom - top) * scale, 0
        )
        out.append(min_code_size)
        out += _sub_blocks(lzw_encode(_scaled_region(indices, width, box, scale), min_code_size))

    out.append(0x3B)
    return bytes(out)
