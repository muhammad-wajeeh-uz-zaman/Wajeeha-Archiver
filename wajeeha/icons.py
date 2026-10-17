# -*- coding: utf-8 -*-
"""
Tiny dependency-free vector icon rasteriser for Wajeeha Archiver.

Every icon is described with a few shapes on a 32 x 32 design grid and rendered
to an anti-aliased RGBA PNG at any pixel size (so it stays sharp on high-DPI
screens).  Tk can load the PNG data directly:  tk.PhotoImage(data=b64)
"""
import base64
import math
import struct
import zlib

# ----------------------------------------------------------------- palette
WHITE = (255, 255, 255, 255)
INDIGO = (79, 107, 237, 255)
INDIGO_D = (52, 72, 190, 255)
INDIGO_L = (126, 148, 255, 255)
ORANGE = (255, 152, 67, 255)
GREEN = (38, 176, 106, 255)
GREEN_L = (96, 216, 152, 255)
RED = (232, 84, 84, 255)
RED_D = (196, 58, 58, 255)
BLUE = (47, 146, 224, 255)
BLUE_L = (104, 190, 246, 255)
YELLOW = (250, 196, 70, 255)
YELLOW_D = (230, 160, 36, 255)
SLATE = (150, 156, 176, 255)


class Raster:
    """Premultiplied-alpha software canvas using signed-distance shapes."""

    def __init__(self, size):
        self.n = int(size)
        self.k = self.n / 32.0
        self.px = [0.0] * (self.n * self.n * 4)

    # color may be (r,g,b,a) or ((r,g,b,a),(r,g,b,a)) = vertical gradient
    def _paint(self, bbox, sdf, color):
        n, k, px = self.n, self.k, self.px
        x0, y0, x1, y1 = bbox
        i0 = max(0, int(math.floor(x0 * k)) - 1)
        i1 = min(n, int(math.ceil(x1 * k)) + 1)
        j0 = max(0, int(math.floor(y0 * k)) - 1)
        j1 = min(n, int(math.ceil(y1 * k)) + 1)
        grad = isinstance(color[0], (tuple, list))
        if grad:
            ca, cb = color
        else:
            r, g, b, a = color
        gh = max(y1 - y0, 1e-6)
        for j in range(j0, j1):
            y = (j + 0.5) / k
            if grad:
                t = min(1.0, max(0.0, (y - y0) / gh))
                r, g, b, a = [ca[q] + (cb[q] - ca[q]) * t for q in range(4)]
            for i in range(i0, i1):
                d = sdf((i + 0.5) / k, y) * k
                cov = 0.5 - d
                if cov <= 0.0:
                    continue
                if cov > 1.0:
                    cov = 1.0
                al = cov * a / 255.0
                p = (j * n + i) * 4
                inv = 1.0 - al
                px[p] = r * al + px[p] * inv
                px[p + 1] = g * al + px[p + 1] * inv
                px[p + 2] = b * al + px[p + 2] * inv
                px[p + 3] = al + px[p + 3] * inv

    # ---------------------------------------------------------- primitives
    def circle(self, cx, cy, r, color):
        self._paint((cx - r - 1, cy - r - 1, cx + r + 1, cy + r + 1),
                    lambda x, y: math.hypot(x - cx, y - cy) - r, color)

    def ring(self, cx, cy, r, t, color):
        h = t / 2.0
        e = r + h + 1
        self._paint((cx - e, cy - e, cx + e, cy + e),
                    lambda x, y: abs(math.hypot(x - cx, y - cy) - r) - h, color)

    def rrect(self, x, y, w, h, rad, color):
        cx, cy, hw, hh = x + w / 2.0, y + h / 2.0, w / 2.0, h / 2.0
        rad = min(rad, hw, hh)

        def f(px_, py_):
            qx = abs(px_ - cx) - hw + rad
            qy = abs(py_ - cy) - hh + rad
            return math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - rad
        self._paint((x - 1, y - 1, x + w + 1, y + h + 1), f, color)

    def line(self, x1, y1, x2, y2, w, color):
        dx, dy = x2 - x1, y2 - y1
        l2 = dx * dx + dy * dy or 1e-9
        hw = w / 2.0

        def f(px_, py_):
            t = ((px_ - x1) * dx + (py_ - y1) * dy) / l2
            t = 0.0 if t < 0 else 1.0 if t > 1 else t
            return math.hypot(px_ - (x1 + t * dx), py_ - (y1 + t * dy)) - hw
        self._paint((min(x1, x2) - hw - 1, min(y1, y2) - hw - 1,
                     max(x1, x2) + hw + 1, max(y1, y2) + hw + 1), f, color)

    def polyline(self, pts, w, color):
        for a, b in zip(pts, pts[1:]):
            self.line(a[0], a[1], b[0], b[1], w, color)

    def poly(self, pts, color):
        """Convex polygon."""
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        edges = []
        for i in range(len(pts)):
            ax, ay = pts[i]
            bx, by = pts[(i + 1) % len(pts)]
            ex, ey = bx - ax, by - ay
            ln = math.hypot(ex, ey) or 1e-9
            nx, ny = ey / ln, -ex / ln
            if (cx - ax) * nx + (cy - ay) * ny > 0:
                nx, ny = -nx, -ny
            edges.append((ax, ay, nx, ny))

        def f(x, y):
            return max((x - ax) * nx + (y - ay) * ny for ax, ay, nx, ny in edges)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        self._paint((min(xs) - 1, min(ys) - 1, max(xs) + 1, max(ys) + 1), f, color)

    # -------------------------------------------------------------- export
    def to_png(self, gray=False):
        n, px = self.n, self.px
        raw = bytearray()
        for y in range(n):
            raw.append(0)
            for x in range(n):
                p = (y * n + x) * 4
                a = px[p + 3]
                if a <= 0.001:
                    raw += b"\x00\x00\x00\x00"
                    continue
                r_, g_, b_ = px[p] / a, px[p + 1] / a, px[p + 2] / a
                if gray:
                    r_ = g_ = b_ = 0.3 * r_ + 0.59 * g_ + 0.11 * b_
                    a_out = a * 0.42
                else:
                    a_out = a
                raw.append(min(255, int(r_ + 0.5)))
                raw.append(min(255, int(g_ + 0.5)))
                raw.append(min(255, int(b_ + 0.5)))
                raw.append(min(255, int(a_out * 255 + 0.5)))

        def chunk(tag, data):
            body = tag + data
            return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        return (b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 6, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
                + chunk(b"IEND", b""))


# ------------------------------------------------------------- icon designs
def _box(r, lid, body, slot):
    r.rrect(6, 11, 20, 17, 2.5, body)
    r.rrect(4, 5, 24, 8, 2.5, lid)
    r.rrect(12.5, 16.5, 7, 3, 1.5, slot)


def _add(r, fg):
    _box(r, INDIGO_D, (INDIGO_L, INDIGO), (255, 255, 255, 215))
    r.circle(24, 24, 7.6, (GREEN_L, GREEN))
    r.line(24, 20.4, 24, 27.6, 2.5, WHITE)
    r.line(20.4, 24, 27.6, 24, 2.5, WHITE)


def _extract(r, fg):
    r.poly([(16, 2.2), (25.5, 12.5), (6.5, 12.5)], ORANGE)
    r.line(16, 10, 16, 20, 4.6, ORANGE)
    r.rrect(5, 15.5, 22, 12.5, 2.5, (INDIGO_L, INDIGO))
    r.rrect(3, 13.5, 26, 5, 2.5, INDIGO_D)
    r.rrect(12.5, 21, 7, 3, 1.5, (255, 255, 255, 215))


def _test(r, fg):
    r.circle(16, 16, 13, (GREEN_L, GREEN))
    r.polyline([(9.5, 16.5), (14, 21), (22.5, 11)], 3.8, WHITE)


def _view(r, fg):
    r.rrect(6, 2.5, 20, 27, 3, SLATE)
    r.rrect(7, 3.5, 18, 25, 2.2, (250, 251, 255, 255))
    for i, w in enumerate((12, 12, 8, 12, 9)):
        r.line(10, 9 + i * 4.2, 10 + w, 9 + i * 4.2, 2, (150, 158, 190, 255))


def _delete(r, fg):
    r.rrect(11.5, 3, 9, 4.5, 1.8, RED_D)
    r.rrect(5, 6.5, 22, 4, 2, RED_D)
    r.poly([(7.6, 11), (24.4, 11), (22.6, 28.5), (9.4, 28.5)], (RED, RED_D))
    for x in (12.6, 16, 19.4):
        r.line(x, 14.5, x, 25, 1.9, (255, 255, 255, 220))


def _find(r, fg):
    r.circle(13.2, 13.2, 9.2, (190, 225, 255, 90))
    r.ring(13.2, 13.2, 8.4, 3.4, BLUE)
    r.line(19.6, 19.6, 27.2, 27.2, 4.6, INDIGO_D)


def _info(r, fg):
    r.circle(16, 16, 13, (BLUE_L, BLUE))
    r.circle(16, 9.6, 2.2, WHITE)
    r.rrect(14.1, 13.6, 3.8, 11.4, 1.6, WHITE)


def _repair(r, fg):
    r.rrect(10.5, 3.5, 11, 8, 2.5, RED_D)
    r.rrect(13, 6, 6, 4, 1.4, (0, 0, 0, 0))
    r.rrect(3.5, 8, 25, 20, 3.5, (RED, RED_D))
    r.line(16, 12.6, 16, 23.4, 3.8, WHITE)
    r.line(10.6, 18, 21.4, 18, 3.8, WHITE)


def _convert(r, fg):
    r.line(5, 10.5, 21, 10.5, 3.4, INDIGO)
    r.poly([(27, 10.5), (19, 4), (19, 17)], INDIGO)
    r.line(11, 21.5, 27, 21.5, 3.4, ORANGE)
    r.poly([(5, 21.5), (13, 15), (13, 28)], ORANGE)


def _up(r, fg):
    r.line(16, 27, 16, 10, 3.8, fg)
    r.poly([(16, 3.5), (26, 14), (6, 14)], fg)


def _gear(r, fg):
    for i in range(8):
        a = i * math.pi / 4
        r.line(16 + 9 * math.cos(a), 16 + 9 * math.sin(a),
               16 + 13 * math.cos(a), 16 + 13 * math.sin(a), 4.6, fg)
    r.ring(16, 16, 8.2, 5.6, fg)


def _folder(r, fg):
    r.rrect(3, 5.5, 13, 8, 2.5, YELLOW_D)
    r.rrect(3, 9, 26, 19, 3, (YELLOW, YELLOW_D))


def _comment(r, fg):
    r.rrect(3, 4, 26, 19, 5, (BLUE_L, BLUE))
    r.poly([(9, 21), (9, 29), (17, 21)], BLUE)
    for i in range(3):
        r.line(8, 10 + i * 4.2, 8 + (16, 16, 10)[i], 10 + i * 4.2, 2, WHITE)


def _open(r, fg):
    r.rrect(3, 5.5, 13, 8, 2.5, YELLOW_D)
    r.rrect(3, 9, 26, 19, 3, YELLOW_D)
    r.poly([(7, 28), (31, 28), (26, 14), (2, 14)], (YELLOW, YELLOW_D))


def _app(r, fg):
    r.rrect(1, 1, 30, 30, 7.5, ((104, 112, 255, 255), (150, 86, 245, 255)))
    r.rrect(8, 12.5, 16, 12.5, 2.2, (255, 255, 255, 235))
    r.rrect(6, 7, 20, 7, 2.2, WHITE)
    r.rrect(13, 17, 6, 2.8, 1.4, (118, 104, 245, 255))


ICONS = {
    "add": _add, "extract": _extract, "test": _test, "view": _view,
    "delete": _delete, "find": _find, "info": _info, "repair": _repair,
    "convert": _convert, "up": _up, "gear": _gear, "folder": _folder,
    "comment": _comment, "open": _open, "app": _app,
}

# small file-type icons: a page with a colored label
FILE_COLORS = {
    "archive": (250, 160, 60, 255),
    "image": (60, 180, 120, 255),
    "audio": (170, 100, 230, 255),
    "video": (230, 90, 110, 255),
    "text": (110, 130, 170, 255),
    "code": (60, 150, 220, 255),
    "exe": (90, 100, 120, 255),
    "pdf": (225, 70, 70, 255),
    "file": (150, 158, 186, 255),
}


def _file_icon(r, color):
    r.rrect(6, 2.5, 20, 27, 3, SLATE)
    r.rrect(7, 3.5, 18, 25, 2.2, (250, 251, 255, 255))
    r.poly([(19, 3.5), (25, 9.5), (19, 9.5)], (205, 210, 225, 255))
    r.rrect(9.5, 15.5, 13, 9, 2, color)


def render(name, px, fg=(84, 90, 112, 255), gray=False):
    """PNG bytes for icon `name` ('file:<kind>' for file-type icons)."""
    r = Raster(px)
    if name.startswith("file:"):
        _file_icon(r, FILE_COLORS.get(name[5:], FILE_COLORS["file"]))
    else:
        ICONS[name](r, fg)
    return r.to_png(gray)


def render_b64(name, px, fg=(84, 90, 112, 255), gray=False):
    return base64.b64encode(render(name, px, fg, gray))


def make_ico(path, sizes=(16, 24, 32, 48, 64, 128, 256), name="app"):
    """Write a multi-size .ico (PNG-compressed entries)."""
    images = [(s, render(name, s)) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    blobs = b""
    for s, data in images:
        entries += struct.pack("<BBBBHHII", 0 if s >= 256 else s, 0 if s >= 256 else s,
                               0, 0, 1, 32, len(data), offset + len(blobs))
        blobs += data
    with open(path, "wb") as f:
        f.write(header + entries + blobs)
    return path
