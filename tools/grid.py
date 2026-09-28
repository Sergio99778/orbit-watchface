"""Contact sheets: themes, clock edge cases, complication types."""
import datetime as dt, os, sys
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design
from preview import renderer, render, round_mask, OUT

LABEL = ImageFont.truetype(os.path.join(design.RES, "font", "orbit_label.ttf"), 22)

def sheet(items, cols, name, cell=450, bezel=True):
    tiles = []
    for label, img in items:
        t = round_mask(img, bezel=bezel)
        canvas = Image.new("RGBA", (t.size[0], t.size[1] + 40), (18, 18, 20, 255))
        canvas.alpha_composite(t, (0, 0))
        ImageDraw.Draw(canvas).text((t.size[0] / 2, t.size[1] + 18), label, font=LABEL, fill=(200, 200, 200), anchor="mm")
        tiles.append(canvas)
    tw, th = tiles[0].size
    rows = (len(tiles) + cols - 1) // cols
    out = Image.new("RGBA", (cols * tw, rows * th), (18, 18, 20, 255))
    for i, t in enumerate(tiles):
        out.alpha_composite(t, ((i % cols) * tw, (i // cols) * th))
    out.convert("RGB").save(os.path.join(OUT, name))
    return out

if __name__ == "__main__":
    design.write_all()
    r = renderer()
    what = sys.argv[1] if len(sys.argv) > 1 else "themes"
    if what == "themes":
        sheet([(label, render(r, theme=tid)) for tid, label, *_ in design.THEMES], 3, "themes.png")
    elif what == "clock":
        cases = [("9:41 (12h)", dt.datetime(2026, 9, 28, 9, 41, 5), False),
                 ("12:00 (12h)", dt.datetime(2026, 9, 28, 12, 0, 45), False),
                 ("1:11 (12h)", dt.datetime(2026, 9, 28, 13, 11, 20), False),
                 ("21:41 (24h)", dt.datetime(2026, 9, 28, 21, 41, 50), True),
                 ("07:05 (24h)", dt.datetime(2026, 9, 28, 7, 5, 12), True),
                 ("00:59 (24h)", dt.datetime(2026, 9, 28, 0, 59, 58), True)]
        sheet([(l, render(r, when=w, is24h=h)) for l, w, h in cases], 3, "clock_cases.png")
    elif what == "comps":
        sheet([("steps + battery", render(r, comps="default")), ("heart + weather", render(r, comps="alt")),
               ("goal + text/title", render(r, comps="goal")), ("empty slots", render(r, comps="empty")),
               ("seconds off", render(r, seconds="off")), ("ambient", render(r, ambient=True))], 3, "complications.png")
