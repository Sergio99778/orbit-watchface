"""Render previews of the generated watch face from its own watchface.xml."""
from __future__ import annotations

import datetime as dt
import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import design  # noqa: E402
from wffrender import Env, Renderer  # noqa: E402

PROJECT = design.PROJECT
OUT = os.path.join(PROJECT, "previews")
SYMBOLS = os.environ.get(
    "SYMBOLS_FONT", "/home/claude/vendor/mdi/variablefont/MaterialSymbolsRounded[FILL,GRAD,opsz,wght].ttf")
SYSTEM_FONT = os.path.join(HERE, "_system_font.ttf")

ICON_CODEPOINTS = {"steps": 0xF87D, "battery": 0xF0A0, "heart": 0xE87E, "weather": 0xF172, "bolt": 0xEA0B,
                   "event": 0xE878}


def ensure_system_font():
    """Stand-in for the watch's own font (SYNC_TO_DEVICE): Google Sans Flex at its defaults."""
    if os.path.exists(SYSTEM_FONT):
        return SYSTEM_FONT
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer
    src = "/home/claude/vendor/gfonts/ofl/googlesansflex/GoogleSansFlex[GRAD,ROND,opsz,slnt,wdth,wght].ttf"
    f = instancer.instantiateVariableFont(TTFont(src), {"opsz": 18, "wdth": 100, "wght": 400, "GRAD": 0,
                                                       "ROND": 0, "slnt": 0})
    f.save(SYSTEM_FONT)
    return SYSTEM_FONT


def icon(name, px=96, fill=1):
    f = ImageFont.truetype(SYMBOLS, px)
    axes = f.get_variation_axes()
    vals = []
    for a in axes:
        n = a["name"].decode() if isinstance(a["name"], bytes) else a["name"]
        vals.append({"Fill": fill, "Weight": 500, "Optical size": 24, "Grade": 0}.get(n, a["default"]))
    f.set_variation_by_axes(vals)
    im = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.text((px / 2, px / 2), chr(ICON_CODEPOINTS[name]), font=f, fill=(255, 255, 255, 255), anchor="mm")
    return im


def sample_complications(kind="default"):
    if kind == "default":
        return {
            "0": {"type": "SHORT_TEXT", "TEXT": "6,832", "TITLE": None, "MONOCHROMATIC_IMAGE": icon("steps")},
            "1": {"type": "RANGED_VALUE", "TEXT": "76%", "TITLE": None, "MONOCHROMATIC_IMAGE": icon("battery"),
                  "RANGED_VALUE_VALUE": 76, "RANGED_VALUE_MIN": 0, "RANGED_VALUE_MAX": 100},
        }
    if kind == "alt":
        return {
            "0": {"type": "SHORT_TEXT", "TEXT": "72", "TITLE": None, "MONOCHROMATIC_IMAGE": icon("heart")},
            "1": {"type": "SHORT_TEXT", "TEXT": "21°", "TITLE": None, "MONOCHROMATIC_IMAGE": icon("weather")},
        }
    if kind == "goal":
        return {
            "0": {"type": "GOAL_PROGRESS", "TEXT": "9,410", "TITLE": None, "MONOCHROMATIC_IMAGE": icon("steps"),
                  "GOAL_PROGRESS_VALUE": 9410, "GOAL_PROGRESS_TARGET_VALUE": 10000},
            "1": {"type": "SHORT_TEXT", "TEXT": "3:30", "TITLE": "PM", "MONOCHROMATIC_IMAGE": None},
        }
    if kind == "empty":
        return {}
    raise ValueError(kind)


def renderer():
    ensure_system_font()
    xml = os.path.join(design.RES, "raw", "watchface.xml")
    return Renderer(xml, design.RES, scale=4, fallback_font=SYSTEM_FONT)


def render(r, when=dt.datetime(2026, 9, 27, 10, 8, 32), millis=0, ambient=False, theme=None, seconds="smooth",
           comps="default", is24h=False, size=450):
    cfg = {"seconds": seconds}
    if theme:
        cfg["theme"] = theme
    env = Env(dt=when, millis=millis, ambient=ambient, is24h=is24h, config=cfg,
              extra={"__complications__": sample_complications(comps)})
    return r.render(env, out_size=size)


def round_mask(img, bezel=True):
    """Clip to the round display and put it in a simple bezel, like it sits on the wrist."""
    n = img.size[0]
    pad = int(n * 0.07) if bezel else 0
    out = Image.new("RGBA", (n + 2 * pad, n + 2 * pad), (0, 0, 0, 0))
    ss = 4
    m = Image.new("L", (n * ss, n * ss), 0)
    ImageDraw.Draw(m).ellipse([0, 0, n * ss - 1, n * ss - 1], fill=255)
    m = m.resize((n, n), Image.LANCZOS)
    if bezel:
        big = (n + 2 * pad) * ss
        b = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        d = ImageDraw.Draw(b)
        d.ellipse([0, 0, big - 1, big - 1], fill=(38, 40, 44, 255))
        e = int(pad * ss * 0.35)
        d.ellipse([e, e, big - 1 - e, big - 1 - e], fill=(10, 10, 12, 255))
        b = b.resize((n + 2 * pad, n + 2 * pad), Image.LANCZOS)
        out.alpha_composite(b)
    face = img.copy()
    face.putalpha(m)
    out.alpha_composite(face, (pad, pad))
    return out


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    design.write_all()
    r = renderer()
    img = render(r)
    img.save(os.path.join(OUT, "interactive.png"))
    render(r, ambient=True).save(os.path.join(OUT, "ambient.png"))
    print("ok")
