"""One image that shows the face: normal mode, always-on mode, and the six colour themes."""
import datetime as dt
import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import design  # noqa: E402
from preview import renderer, render, round_mask  # noqa: E402

BG = (14, 14, 16, 255)


def label_font(size):
    return ImageFont.truetype(os.path.join(design.RES, "font", "orbit_label.ttf"), size)


def main(out_path):
    r = renderer()
    when = dt.datetime(2026, 9, 28, 10, 8, 32)
    big = 620
    hero = round_mask(render(r, when=when, size=big))
    aod = round_mask(render(r, when=when, size=big, ambient=True))
    thumbs = []
    for tid, label, *_ in design.THEMES:
        t = round_mask(render(r, when=when, theme=tid, size=200))
        thumbs.append((label, t))

    W = 1560
    pad = 60
    H = 56 + hero.size[1] + 70 + thumbs[0][1].size[1] + 70
    im = Image.new("RGBA", (W, H), BG)
    d = ImageDraw.Draw(im)
    gap = (W - 2 * hero.size[0]) // 3
    x1, x2 = gap, 2 * gap + hero.size[0]
    y = 40
    im.alpha_composite(hero, (x1, y))
    im.alpha_composite(aod, (x2, y))
    cap = label_font(30)
    d.text((x1 + hero.size[0] / 2, y + hero.size[1] + 26), "Screen on", font=cap, fill=(225, 225, 225), anchor="mm")
    d.text((x2 + aod.size[0] / 2, y + aod.size[1] + 26), "Always-on", font=cap, fill=(160, 160, 160), anchor="mm")
    ty = y + hero.size[1] + 70
    tw = thumbs[0][1].size[0]
    tgap = (W - 2 * pad - 6 * tw) // 5
    small = label_font(24)
    for i, (label, t) in enumerate(thumbs):
        tx = pad + i * (tw + tgap)
        im.alpha_composite(t, (tx, ty))
        d.text((tx + tw / 2, ty + tw + 24), label, font=small, fill=(200, 200, 200), anchor="mm")
    im.convert("RGB").save(out_path, optimize=True)
    print(out_path, im.size)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(design.PROJECT, "previews", "orbit-showcase.png"))
