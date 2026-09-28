"""Build static, subset, renamed instances of Google Sans Flex (SIL OFL 1.1) for the watch face.

Each instance pins every variation axis, optionally swaps the default digits for the
tabular (.tf) figures so the clock never jitters, subsets to the characters the face can
show, and renames the family so the result is a clearly modified version of the font.
"""
import sys, os, copy
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
from fontTools import subset

SRC = os.environ.get("GSF_SRC", "/home/claude/vendor/gfonts/ofl/googlesansflex/GoogleSansFlex[GRAD,ROND,opsz,slnt,wdth,wght].ttf")

DIGIT_NAMES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]

LABEL_EXTRA = "•·°%‰–—‘’“”…€£¥←↑→↓−×÷"


def label_codepoints():
    cps = set(range(0x20, 0x7F)) | set(range(0xA0, 0x180))
    cps |= {ord(c) for c in LABEL_EXTRA}
    return cps


def equalize_advances(font, reference_path, chars):
    """Give `chars` the same advance widths as in the reference font, centring each outline in
    its new advance, so two weights of the clock occupy exactly the same space."""
    ref = TTFont(reference_path)
    rcmap, cmap = ref.getBestCmap(), font.getBestCmap()
    glyf, hmtx = font["glyf"], font["hmtx"]
    for ch in chars:
        cp = ord(ch)
        if cp not in cmap or cp not in rcmap:
            continue
        gname = cmap[cp]
        target = ref["hmtx"][rcmap[cp]][0]
        adv, lsb = hmtx[gname]
        dx = int(round((target - adv) / 2))
        g = glyf[gname]
        if g.isComposite():
            for comp in g.components:
                comp.x += dx
        elif g.numberOfContours > 0:
            coords = g.coordinates
            coords.translate((dx, 0))
        g.recalcBounds(glyf)
        hmtx[gname] = (target, getattr(g, "xMin", 0))


def make_instance(out_path, family, style, axes, codepoints, tabular=False, weight_class=None,
                  match_advances_of=None):
    font = TTFont(SRC)
    inst = instancer.instantiateVariableFont(font, axes, inplace=False, updateFontNames=False)
    if tabular:
        for table in inst["cmap"].tables:
            if not table.isUnicode():
                continue
            for i, name in enumerate(DIGIT_NAMES):
                cp = 0x30 + i
                if cp in table.cmap and f"{name}.tf" in inst.getGlyphOrder():
                    table.cmap[cp] = f"{name}.tf"
    avail = set(inst.getBestCmap().keys())
    keep = sorted(cp for cp in codepoints if cp in avail)
    opts = subset.Options()
    opts.layout_features = ["kern", "liga", "calt", "ccmp", "locl", "mark", "mkmk"]
    opts.name_IDs = ["*"]
    opts.name_languages = ["*"]
    opts.notdef_outline = True
    opts.glyph_names = False
    opts.hinting = False
    opts.desubroutinize = True
    sub = subset.Subsetter(opts)
    sub.populate(unicodes=keep)
    sub.subset(inst)
    # Rename: this is a modified version of the font, so it gets its own name.
    full = f"{family} {style}"
    ps = f"{family.replace(' ', '')}-{style.replace(' ', '')}"
    name = inst["name"]
    for rec in list(name.names):
        if rec.nameID in (1, 2, 3, 4, 6, 16, 17, 21, 22, 25):
            name.removeNames(nameID=rec.nameID)
    for nid, val in ((1, family), (2, "Regular"), (3, f"{ps};modified-from-GoogleSansFlex"), (4, full),
                     (6, ps), (16, family), (17, style)):
        name.setName(val, nid, 3, 1, 0x409)
    if match_advances_of:
        equalize_advances(inst, match_advances_of, "".join(chr(c) for c in keep))
    if weight_class:
        inst["OS/2"].usWeightClass = weight_class
    inst["OS/2"].fsSelection = (inst["OS/2"].fsSelection & ~0b1100001) | 0b1000000  # REGULAR bit, not bold/italic
    inst["head"].macStyle = 0
    inst.save(out_path)
    return out_path, len(keep)


if __name__ == "__main__":
    import json
    spec = json.loads(sys.argv[1])
    outdir = sys.argv[2]
    os.makedirs(outdir, exist_ok=True)
    for item in spec:
        cps = set(map(ord, item["chars"])) if item.get("chars") else label_codepoints()
        path, n = make_instance(os.path.join(outdir, item["file"]), item["family"], item["style"],
                                item["axes"], cps, tabular=item.get("tabular", False),
                                match_advances_of=(os.path.join(outdir, item["match"]) if item.get("match") else None))
        f = TTFont(path)
        print(f"{item['file']}: {os.path.getsize(path)} bytes, {n} chars, glyphs={len(f.getGlyphOrder())}, "
              f"wght-class={f['OS/2'].usWeightClass}")
