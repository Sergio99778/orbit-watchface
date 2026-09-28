"""Renders the bitmap resources that ship in the APK: the picker preview and the app icon."""
import datetime as dt
import math
import os
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import design  # noqa: E402
from preview import renderer, render  # noqa: E402

DRAWABLE = os.path.join(design.RES, "drawable-nodpi")


def hexrgb(argb):
    h = argb.lstrip("#")[-6:]
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def app_icon(size=192):
    ss = 4
    n = size * ss
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse([0, 0, n - 1, n - 1], fill=(0, 0, 0, 255))
    _, _, hour, minute, second = design.THEMES[0]
    c = n / 2
    rings = [(0.40, hour, 300), (0.30, minute, 60), (0.20, second, 190)]
    for rf, col, ang in rings:
        r = rf * n
        rgb = hexrgb(col)
        w = int(0.012 * n)
        d.ellipse([c - r, c - r, c + r, c + r], outline=rgb + (90,), width=w)
    for (rf, col, ang), pd in zip(rings, (0.13, 0.10, 0.07)):
        r = rf * n
        rgb = hexrgb(col)
        a = math.radians(ang)
        x, y = c + r * math.sin(a), c - r * math.cos(a)
        pr = pd * n / 2
        d.ellipse([x - pr * 1.9, y - pr * 1.9, x + pr * 1.9, y + pr * 1.9], fill=rgb + (45,))
        d.ellipse([x - pr, y - pr, x + pr, y + pr], fill=rgb + (255,))
    return im.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    os.makedirs(DRAWABLE, exist_ok=True)
    design.write_all()
    r = renderer()
    preview = render(r, when=dt.datetime(2026, 9, 27, 10, 8, 32))
    preview.convert("RGB").save(os.path.join(DRAWABLE, "preview.png"), optimize=True)
    app_icon().save(os.path.join(DRAWABLE, "ic_launcher.png"), optimize=True)
    for f in sorted(os.listdir(DRAWABLE)):
        p = os.path.join(DRAWABLE, f)
        print(f, Image.open(p).size, os.path.getsize(p), "bytes")
