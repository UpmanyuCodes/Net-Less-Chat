"""Draw the app icon (blue rounded square + white chat bubble) and save assets/icon.ico.
Pure Python, no image libraries. Run once: python assets/make_icon.py"""

import os
import struct
import zlib

N = 256


def inside_round_rect(x, y, x0, y0, x1, y1, r):
    cx = min(max(x, x0 + r), x1 - r)
    cy = min(max(y, y0 + r), y1 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def pixel(x, y):
    # background: rounded square with a diagonal blue gradient
    if not inside_round_rect(x, y, 0, 0, N - 1, N - 1, 60):
        return (0, 0, 0, 0)
    t = (x + y) / (2 * N)
    bg = (int(106 + (59 - 106) * t), int(163 + (111 - 163) * t), int(255 + (224 - 255) * t), 255)
    # chat bubble + its tail
    bubble = inside_round_rect(x, y, 56, 56, 200, 168, 26)
    dy = y - 160
    tail = 70 <= x <= 110 and 0 <= dy <= 45 and (x - 70) >= dy * 0.9 - 2 and dy <= (110 - x) * 1.1
    if bubble or tail:
        for cx in (96, 128, 160):           # three dots
            if (x - cx) ** 2 + (y - 112) ** 2 <= 12 ** 2:
                return bg
        return (255, 255, 255, 255)
    return bg


def png_bytes():
    rows = b"".join(b"\x00" + b"".join(bytes(pixel(x, y)) for x in range(N)) for y in range(N))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", N, N, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def main():
    png = png_bytes()
    # ICO file = 6-byte header + 16-byte directory entry + PNG data (allowed since Windows Vista)
    ico = struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png), 22) + png
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
    with open(out, "wb") as f:
        f.write(ico)
    print("saved", out)


if __name__ == "__main__":
    main()
