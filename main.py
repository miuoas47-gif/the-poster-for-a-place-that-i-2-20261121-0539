#!/usr/bin/env python3
"""NEREVIA -- a travel poster for a place that isn't there.

A pure-stdlib Python program. It draws, pixel by pixel, a 1024x1024
travel poster for Nerevia: a white cliff town and a lighthouse on a
headland above a golden lagoon at dusk, the low sun on the horizon,
a sailboat on the water, and the island's name set large across the
sky.

No network, no files read, no randomness, no third-party code:
two runs write a byte-identical PNG.
"""

import math
import os
import struct
import zlib

W = 1024
H = 1024
HORIZON = 600

# ---- palette (r, g, b) ----
SKY_TOP = (14, 38, 72)
SKY_MID = (34, 88, 120)
SKY_LOW = (226, 138, 82)
SUN_CORE = (255, 216, 132)
SUN_GLOW = (255, 178, 96)
SEA_TOP = (238, 150, 84)
SEA_MID = (26, 84, 102)
SEA_BOT = (10, 38, 52)
CLIFF = (16, 44, 50)
CLIFF_LIT = (30, 66, 66)
HOUSE = (246, 238, 220)
WINDOW = (255, 190, 90)
TOWER = (244, 236, 222)
TOWER_BAND = (168, 52, 44)
CREAM = (244, 230, 198)
INK = (12, 30, 40)
BEAM = (255, 214, 130)

# 5x7 bitmap letters, only the ones NEREVIA needs.
GLYPHS = {
    "N": ("#...#",
          "##..#",
          "#.#.#",
          "#..##",
          "#...#",
          "#...#",
          "#...#"),
    "E": ("#####",
          "#....",
          "#....",
          "####.",
          "#....",
          "#....",
          "#####"),
    "R": ("####.",
          "#...#",
          "#...#",
          "####.",
          "#.#..",
          "#..#.",
          "#...#"),
    "V": ("#...#",
          "#...#",
          "#...#",
          "#...#",
          "#...#",
          ".#.#.",
          "..#.."),
    "I": ("#####",
          "..#..",
          "..#..",
          "..#..",
          "..#..",
          "..#..",
          "#####"),
    "A": ("..#..",
          ".#.#.",
          "#...#",
          "#...#",
          "#####",
          "#...#",
          "#...#"),
}


def lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def blend(dst, src, alpha):
    """Blend src colour over dst colour, alpha 0..1."""
    return tuple(int(round(dst[i] + (src[i] - dst[i]) * alpha)) for i in range(3))


class Canvas:
    def __init__(self, w, h):
        self.w = w
        self.h = h
        self.px = bytearray(w * h * 3)

    def set(self, x, y, color):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            self.px[i] = color[0]
            self.px[i + 1] = color[1]
            self.px[i + 2] = color[2]

    def get(self, x, y):
        i = (y * self.w + x) * 3
        return (self.px[i], self.px[i + 1], self.px[i + 2])

    def blend_px(self, x, y, color, alpha):
        if 0 <= x < self.w and 0 <= y < self.h and alpha > 0:
            if alpha >= 1:
                self.set(x, y, color)
            else:
                self.set(x, y, blend(self.get(x, y), color, alpha))

    def fill_rect(self, x0, y0, x1, y1, color):
        x0 = max(0, x0)
        y0 = max(0, y0)
        x1 = min(self.w, x1)
        y1 = min(self.h, y1)
        for y in range(y0, y1):
            base = (y * self.w + x0) * 3
            for x in range(x0, x1):
                i = base + (x - x0) * 3
                self.px[i] = color[0]
                self.px[i + 1] = color[1]
                self.px[i + 2] = color[2]

    def fill_disc(self, cx, cy, r, color):
        for y in range(max(0, cy - r), min(self.h, cy + r + 1)):
            dy = y - cy
            dx = int(math.sqrt(max(0, r * r - dy * dy)))
            self.fill_rect(cx - dx, y, cx + dx + 1, y + 1, color)

    def glow_disc(self, cx, cy, r, color, peak):
        """Soft radial glow: alpha falls from peak at centre to 0 at r."""
        for y in range(max(0, cy - r), min(self.h, cy + r + 1)):
            dy = y - cy
            for x in range(max(0, cx - r), min(self.w, cx + r + 1)):
                dx = x - cx
                d = math.sqrt(dx * dx + dy * dy)
                if d < r:
                    t = 1.0 - d / r
                    self.blend_px(x, y, color, peak * t * t)

    def fill_polygon(self, points, color):
        """Even-odd scanline fill for a simple polygon."""
        ys = [p[1] for p in points]
        for y in range(max(0, min(ys)), min(self.h, max(ys) + 1)):
            xs = []
            n = len(points)
            for i in range(n):
                x0, y0 = points[i]
                x1, y1 = points[(i + 1) % n]
                if (y0 <= y < y1) or (y1 <= y < y0):
                    t = (y - y0) / (y1 - y0)
                    xs.append(x0 + t * (x1 - x0))
            xs.sort()
            for j in range(0, len(xs) - 1, 2):
                self.fill_rect(int(math.ceil(xs[j])), y,
                               int(math.floor(xs[j + 1])) + 1, y + 1, color)

    def line(self, x0, y0, x1, y1, color, thick=1):
        steps = max(abs(x1 - x0), abs(y1 - y0), 1)
        for s in range(steps + 1):
            t = s / steps
            x = int(round(x0 + (x1 - x0) * t))
            y = int(round(y0 + (y1 - y0) * t))
            self.fill_rect(x - thick // 2, y - thick // 2,
                           x + thick // 2 + 1, y + thick // 2 + 1, color)

    def ellipse_soft(self, cx, cy, rx, ry, color, alpha):
        for y in range(max(0, cy - ry), min(self.h, cy + ry + 1)):
            dy = (y - cy) / ry
            for x in range(max(0, cx - rx), min(self.w, cx + rx + 1)):
                dx = (x - cx) / rx
                d = dx * dx + dy * dy
                if d < 1.0:
                    self.blend_px(x, y, color, alpha * (1.0 - d))


def draw_text(canvas, text, x, y, scale, color, outline=None):
    """Draw text from the 5x7 bitmap font. Returns the width drawn."""
    cx = x
    for ch in text:
        glyph = GLYPHS.get(ch)
        if glyph is None:
            cx += 6 * scale
            continue
        if outline is not None:
            for ox, oy in ((-3, 0), (3, 0), (0, -3), (0, 3),
                           (-3, -3), (3, -3), (-3, 3), (3, 3)):
                for row in range(7):
                    for col in range(5):
                        if glyph[row][col] == "#":
                            canvas.fill_rect(cx + ox + col * scale,
                                             y + oy + row * scale,
                                             cx + ox + (col + 1) * scale,
                                             y + oy + (row + 1) * scale,
                                             outline)
        for row in range(7):
            for col in range(5):
                if glyph[row][col] == "#":
                    canvas.fill_rect(cx + col * scale, y + row * scale,
                                     cx + (col + 1) * scale,
                                     y + (row + 1) * scale, color)
        cx += 6 * scale
    return cx - x - scale


def text_width(text, scale):
    return len(text) * 6 * scale - scale


def draw_poster():
    c = Canvas(W, H)

    # ---- sky: vertical gradient through four stops ----
    stops = [(0.0, SKY_TOP), (0.34, SKY_MID), (0.52, (120, 110, 110)),
             (0.585, SKY_LOW)]
    for y in range(HORIZON):
        t = y / HORIZON
        col = stops[0][1]
        for i in range(len(stops) - 1):
            t0, c0 = stops[i]
            t1, c1 = stops[i + 1]
            if t0 <= t <= t1:
                col = lerp(c0, c1, (t - t0) / (t1 - t0))
                break
        c.fill_rect(0, y, W, y + 1, col)

    # ---- soft clouds ----
    c.ellipse_soft(210, 300, 190, 26, (244, 214, 178), 0.28)
    c.ellipse_soft(760, 210, 220, 24, (244, 214, 178), 0.22)
    c.ellipse_soft(560, 420, 150, 20, (250, 200, 150), 0.20)

    # ---- sun glow and disc, low on the horizon ----
    sun_x, sun_y, sun_r = 370, 578, 56
    c.glow_disc(sun_x, sun_y, 300, SUN_GLOW, 0.55)
    c.fill_disc(sun_x, sun_y, sun_r, SUN_CORE)
    c.fill_disc(sun_x, sun_y, sun_r - 8, (255, 228, 160))

    # ---- sea: gradient from bright horizon to deep teal ----
    for y in range(HORIZON, H):
        t = (y - HORIZON) / (H - HORIZON)
        col = lerp(SEA_TOP, SEA_BOT, t * t * 0.9 + t * 0.1)
        c.fill_rect(0, y, W, y + 1, col)

    # ---- sun reflection: shimmering dashes down the water ----
    for y in range(HORIZON + 6, H - 30, 7):
        depth = (y - HORIZON) / (H - HORIZON)
        half = int(95 * (0.35 + depth))
        for x in range(sun_x - half, sun_x + half + 1, 4):
            wob = math.sin(x * 0.11 + y * 0.35) + math.sin(x * 0.031 - y * 0.12)
            if wob > 0.55:
                a = 0.55 * (1.0 - depth * 0.75)
                c.blend_px(x, y, (255, 205, 120), a)
                c.blend_px(x + 1, y, (255, 205, 120), a * 0.8)

    # ---- lighthouse beam: a wedge of light sweeping up-left ----
    lamp_x, lamp_y = 878, 402
    beam_top = 296
    beam_bot = 448
    beam_left = 120
    for y in range(beam_top, beam_bot + 1):
        # right edge of the wedge at this row: on the lamp->top line
        # above the lamp, on the lamp->bottom line below it
        if y <= lamp_y:
            x_right = beam_left + (lamp_x - beam_left) * (y - beam_top) / (lamp_y - beam_top)
        else:
            x_right = beam_left + (lamp_x - beam_left) * (beam_bot - y) / (beam_bot - lamp_y)
        # soften near the wedge's top and bottom edges
        edge = min((y - beam_top) / 36.0, (beam_bot - y) / 36.0, 1.0)
        for x in range(beam_left, int(x_right) + 1):
            # brighter near the lamp, fading toward the far end
            fade = (x - beam_left) / max(1, (lamp_x - beam_left))
            a = 0.20 * edge * (0.35 + 0.65 * fade)
            c.blend_px(x, y, BEAM, a)

    # ---- headland: dark cliff on the right, down to the bottom ----
    cliff = [(700, 648), (782, 566), (884, 548), (962, 566),
             (1024, 582), (1024, 1024), (700, 1024)]
    c.fill_polygon(cliff, CLIFF)
    # lit cliff edge along the top
    c.line(700, 648, 782, 566, CLIFF_LIT, 3)
    c.line(782, 566, 884, 548, CLIFF_LIT, 3)
    c.line(884, 548, 962, 566, CLIFF_LIT, 3)
    c.line(962, 566, 1024, 582, CLIFF_LIT, 3)
    # strata lines across the cliff face, and one lit hut on the slope
    for sy, sx0, sx1 in ((700, 762, 1024), (800, 724, 1024), (900, 702, 1024)):
        c.line(sx0, sy, sx1, sy + 12, (24, 60, 64), 2)
    c.fill_rect(758, 700, 778, 718, (40, 70, 66))
    c.fill_polygon([(756, 700), (768, 690), (780, 700)], TOWER_BAND)
    c.fill_rect(764, 705, 772, 713, WINDOW)

    # ---- white cliff town along the headland top ----
    houses = [(712, 606, 46, 34), (764, 596, 40, 44), (810, 600, 44, 36),
              (920, 592, 42, 40), (966, 600, 44, 34)]
    for hx, hy, hw, hh in houses:
        c.fill_rect(hx, hy, hx + hw, hy + hh, HOUSE)
        # pitched roof
        c.fill_polygon([(hx - 3, hy), (hx + hw // 2, hy - 14),
                        (hx + hw + 3, hy)], TOWER_BAND)
        # warm windows
        for wx in range(hx + 8, hx + hw - 8, 14):
            c.fill_rect(wx, hy + 12, wx + 6, hy + 20, WINDOW)

    # ---- lighthouse: tapered white tower, red bands, glowing lamp ----
    tower = [(866, 560), (892, 560), (886, 412), (872, 412)]
    c.fill_polygon(tower, TOWER)
    c.fill_rect(870, 500, 888, 516, TOWER_BAND)
    c.fill_rect(872, 452, 886, 466, TOWER_BAND)
    # gallery and lamp room
    c.fill_rect(866, 404, 892, 412, INK)
    c.fill_rect(872, 384, 886, 404, (60, 60, 58))
    c.fill_rect(876, 388, 882, 400, (255, 226, 140))
    c.fill_polygon([(870, 384), (888, 384), (879, 372)], TOWER_BAND)
    c.glow_disc(879, 394, 60, (255, 220, 130), 0.5)

    # ---- sailboat on the lagoon ----
    bx, by = 430, 742
    c.fill_polygon([(bx - 34, by), (bx + 34, by), (bx + 22, by + 14),
                    (bx - 22, by + 14)], INK)
    c.line(bx, by, bx, by - 52, INK, 3)
    c.fill_polygon([(bx + 3, by - 50), (bx + 3, by - 4), (bx + 30, by - 4)],
                   (250, 244, 228))
    c.fill_polygon([(bx - 3, by - 44), (bx - 3, by - 4), (bx - 26, by - 4)],
                   (232, 196, 150))
    # its reflection
    for y in range(by + 16, by + 40, 4):
        c.blend_px(bx, y, (255, 205, 120), 0.25)

    # a second, distant sailboat near the horizon for depth
    dx, dy = 580, 648
    c.fill_polygon([(dx - 16, dy), (dx + 16, dy), (dx + 10, dy + 7),
                    (dx - 10, dy + 7)], INK)
    c.line(dx, dy, dx, dy - 26, INK, 2)
    c.fill_polygon([(dx + 2, dy - 25), (dx + 2, dy - 2), (dx + 15, dy - 2)],
                   (250, 244, 228))

    # ---- birds ----
    for bx0, by0, s in ((180, 380, 14), (240, 350, 11), (660, 330, 12)):
        c.line(bx0 - s, by0, bx0, by0 - 7, INK, 2)
        c.line(bx0, by0 - 7, bx0 + s, by0, INK, 2)

    # ---- foreground rocks, bottom-left ----
    c.fill_polygon([(0, 1024), (0, 968), (90, 952), (180, 972),
                    (240, 1000), (240, 1024)], CLIFF)

    # ---- the name: NEREVIA, large cream letters across the sky ----
    scale = 20
    name = "NEREVIA"
    tw = text_width(name, scale)
    nx = (W - tw) // 2
    ny = 108
    draw_text(c, name, nx, ny, scale, CREAM, outline=INK)
    # thin rule beneath the name, with a diamond at its centre
    c.fill_rect((W - 420) // 2, ny + 7 * scale + 26,
                (W + 420) // 2, ny + 7 * scale + 30, CREAM)
    d = 9
    cx, cy = W // 2, ny + 7 * scale + 28
    c.fill_polygon([(cx, cy - d), (cx + d, cy), (cx, cy + d), (cx - d, cy)],
                   CREAM)

    # ---- cream frame ----
    c.fill_rect(26, 26, W - 26, 31, CREAM)
    c.fill_rect(26, H - 31, W - 26, H - 26, CREAM)
    c.fill_rect(26, 26, 31, H - 26, CREAM)
    c.fill_rect(W - 31, 26, W - 26, H - 26, CREAM)

    return c


def write_png(canvas, path):
    raw = bytearray()
    for y in range(canvas.h):
        raw.append(0)  # filter: none
        start = y * canvas.w * 3
        raw += canvas.px[start:start + canvas.w * 3]
    data = zlib.compress(bytes(raw), 9)

    def chunk(kind, payload):
        out = struct.pack(">I", len(payload)) + kind + payload
        out += struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        return out

    ihdr = struct.pack(">IIBBBBB", canvas.w, canvas.h, 8, 2, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", data) + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)
    return len(png)


def output_path():
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"
    try:
        os.makedirs(out_dir, exist_ok=True)
        return os.path.join(out_dir, "entry.png"), out_dir
    except OSError:
        out_dir = os.path.join(os.getcwd(), "output")
        os.makedirs(out_dir, exist_ok=True)
        return os.path.join(out_dir, "entry.png"), out_dir


def main():
    canvas = draw_poster()
    path, out_dir = output_path()
    size = write_png(canvas, path)
    try:
        os.chmod(out_dir, 0o777)
    except OSError:
        pass
    try:
        os.chmod(path, 0o666)
    except OSError:
        pass
    print("wrote %s (%dx%d, %d bytes)" % (path, W, H, size))


if __name__ == "__main__":
    main()
