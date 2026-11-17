"""
qr.py - tiny QR code generator (pure Python, no internet, no libraries).

Used to show the share link as a QR code, so phones can just scan it.
Supports byte mode, error-correction level M, versions 1-9 (up to ~180 characters).

Fun CN link: QR codes use Reed-Solomon error correction - the same family of
error-correcting codes used in CDs, DSL and satellite links. Level M can
recover ~15% damaged modules.
"""

# Level M table: version -> (EC codewords per block, [data codewords of each block])
_TABLE_M = {
    1: (10, [16]),
    2: (16, [28]),
    3: (26, [44]),
    4: (18, [32, 32]),
    5: (24, [43, 43]),
    6: (16, [27, 27, 27, 27]),
    7: (18, [31, 31, 31, 31]),
    8: (22, [38, 38, 39, 39]),
    9: (22, [36, 36, 36, 37, 37]),
}
_ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34],
          7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46]}
_FORMAT_BITS_M = 0  # ECC level M is encoded as 00 in the format info


# ---------------- Reed-Solomon over GF(256) ----------------
def _gf_mul(x, y):
    z = 0
    for i in range(7, -1, -1):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(degree):
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(len(result)):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < len(result):
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 0x02)
    return result


def _rs_remainder(data, divisor):
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _gf_mul(coef, factor)
    return result


# ---------------- building the symbol ----------------
class _Matrix:
    def __init__(self, version):
        self.version = version
        self.size = version * 4 + 17
        self.mod = [[False] * self.size for _ in range(self.size)]
        self.func = [[False] * self.size for _ in range(self.size)]

    def set_func(self, x, y, dark):
        self.mod[y][x] = dark
        self.func[y][x] = True

    def draw_function_patterns(self):
        n = self.size
        for i in range(n):                          # timing patterns
            self.set_func(6, i, i % 2 == 0)
            self.set_func(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):   # finder patterns (the 3 big squares)
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < n and 0 <= y < n:
                        self.set_func(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        pos = _ALIGN[self.version]                  # alignment patterns
        last = len(pos) - 1
        for i, ax in enumerate(pos):
            for j, ay in enumerate(pos):
                if (i, j) in ((0, 0), (0, last), (last, 0)):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.set_func(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)
        self.draw_format(0)                         # reserve format area
        if self.version >= 7:
            rem = self.version
            for _ in range(12):
                rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
            bits = self.version << 12 | rem
            for i in range(18):
                bit = (bits >> i) & 1 == 1
                a, b = n - 11 + i % 3, i // 3
                self.set_func(a, b, bit)
                self.set_func(b, a, bit)

    def draw_format(self, mask):
        data = _FORMAT_BITS_M << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        bit = lambda i: (bits >> i) & 1 == 1
        n = self.size
        for i in range(6):
            self.set_func(8, i, bit(i))
        self.set_func(8, 7, bit(6))
        self.set_func(8, 8, bit(7))
        self.set_func(7, 8, bit(8))
        for i in range(9, 15):
            self.set_func(14 - i, 8, bit(i))
        for i in range(8):
            self.set_func(n - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self.set_func(8, n - 15 + i, bit(i))
        self.set_func(8, n - 8, True)               # always-dark module

    def draw_codewords(self, data):
        n, i = self.size, 0
        total = len(data) * 8
        right = n - 1
        while right >= 1:                           # zig-zag in 2-column strips, bottom-right first
            if right == 6:
                right = 5
            for vert in range(n):
                for j in range(2):
                    x = right - j
                    upward = ((right + 1) & 2) == 0
                    y = n - 1 - vert if upward else vert
                    if not self.func[y][x] and i < total:
                        self.mod[y][x] = (data[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
            right -= 2

    def apply_mask(self, mask):
        f = [
            lambda x, y: (x + y) % 2 == 0,
            lambda x, y: y % 2 == 0,
            lambda x, y: x % 3 == 0,
            lambda x, y: (x + y) % 3 == 0,
            lambda x, y: (x // 3 + y // 2) % 2 == 0,
            lambda x, y: x * y % 2 + x * y % 3 == 0,
            lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
            lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
        ][mask]
        for y in range(self.size):
            for x in range(self.size):
                if not self.func[y][x] and f(x, y):
                    self.mod[y][x] = not self.mod[y][x]

    def penalty(self):
        """Lower = easier to scan. Standard QR rules 1-4."""
        m, n, score = self.mod, self.size, 0
        lines = [row for row in m] + [[m[y][x] for y in range(n)] for x in range(n)]
        pat1 = [True, False, True, True, True, False, True, False, False, False, False]
        pat2 = pat1[::-1]
        for line in lines:
            run = 1
            for i in range(1, n + 1):
                if i < n and line[i] == line[i - 1]:
                    run += 1
                else:
                    if run >= 5:
                        score += 3 + (run - 5)
                    run = 1
            for i in range(n - 10):
                seg = line[i:i + 11]
                if seg == pat1 or seg == pat2:
                    score += 40
        for y in range(n - 1):
            for x in range(n - 1):
                c = m[y][x]
                if c == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    score += 3
        dark = sum(sum(row) for row in m)
        score += 10 * (abs(dark * 100 // (n * n) - 50) // 5)
        return score


def make(text, mask=None):
    """Return the QR code for `text` as a square list of rows (True = dark)."""
    data = text.encode("utf-8")
    for version in range(1, 10):
        ec_len, blocks = _TABLE_M[version]
        capacity = sum(blocks)
        if 4 + 8 + len(data) * 8 <= capacity * 8:
            break
    else:
        raise ValueError("Text too long for QR code")

    # Bit stream: mode (0100 = byte) + length + data + terminator + padding
    bits = [0, 1, 0, 0] + [(len(data) >> i) & 1 for i in range(7, -1, -1)]
    for b in data:
        bits += [(b >> i) & 1 for i in range(7, -1, -1)]
    bits += [0] * min(4, capacity * 8 - len(bits))
    bits += [0] * (-len(bits) % 8)
    codewords = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = 0xEC
    while len(codewords) < capacity:
        codewords.append(pad)
        pad ^= 0xEC ^ 0x11

    # Split into blocks, add Reed-Solomon error-correction bytes, interleave
    divisor = _rs_divisor(ec_len)
    data_blocks, ec_blocks, k = [], [], 0
    for size in blocks:
        blk = codewords[k:k + size]
        k += size
        data_blocks.append(blk)
        ec_blocks.append(_rs_remainder(blk, divisor))
    final = []
    for i in range(max(blocks)):
        for blk in data_blocks:
            if i < len(blk):
                final.append(blk[i])
    for i in range(ec_len):
        for blk in ec_blocks:
            final.append(blk[i])

    best, best_score = None, None
    for m in ([mask] if mask is not None else range(8)):
        qr = _Matrix(version)
        qr.draw_function_patterns()
        qr.draw_codewords(final)
        qr.apply_mask(m)
        qr.draw_format(m)
        s = qr.penalty()
        if best is None or s < best_score:
            best, best_score = qr, s
    return best.mod


def to_svg(matrix, border=4):
    n = len(matrix) + border * 2
    path = "".join(f"M{x + border},{y + border}h1v1h-1z"
                   for y, row in enumerate(matrix) for x, dark in enumerate(row) if dark)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n} {n}" shape-rendering="crispEdges">'
            f'<rect width="{n}" height="{n}" fill="#fff"/><path d="{path}" fill="#000"/></svg>')


def to_terminal(matrix, border=2):
    """Draw the QR with half-block characters (2 rows per text line).
    Light modules are printed as white blocks, so it scans on a dark console."""
    n = len(matrix)
    light = lambda x, y: not (0 <= x < n and 0 <= y < n and matrix[y][x])
    lines = []
    for y in range(-border, n + border, 2):
        line = ""
        for x in range(-border, n + border):
            top, bottom = light(x, y), light(x, y + 1)
            line += "█" if top and bottom else "▀" if top else "▄" if bottom else " "
        lines.append(line)
    return "\n".join(lines)


if __name__ == "__main__":
    print(to_terminal(make("http://192.168.137.1:8000")))
