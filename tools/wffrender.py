"""A small Watch Face Format (WFF) renderer for previews.

It interprets the subset of WFF used by this project (Scene, Group, PartDraw with
Arc/Ellipse/Rectangle/RoundRectangle/Line, PartText with Text/Font/Template/Upper,
PartImage, ComplicationSlot/Complication, Condition, BooleanConfiguration,
ListConfiguration, Variant (ambient), Transform) and draws it with Pillow at 4x
supersampling. It is not the Wear OS runtime; it exists so the design can be checked
and the in-APK preview image is rendered from the very same XML that ships.
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from typing import Any

from lxml import etree
from PIL import Image, ImageDraw, ImageFont, ImageChops

# ----------------------------------------------------------------------------------------
# Expressions
# ----------------------------------------------------------------------------------------
_TOKEN_RE = re.compile(
    r"\s*(?:"
    r"(?P<num>\d+\.\d*|\.\d+|\d+)"
    r"|(?P<str>\"(?:[^\"\\]|\\.)*\")"
    r"|(?P<src>\[[^\]]+\])"
    r"|(?P<id>[A-Za-z_][A-Za-z0-9_]*)"
    r"|(?P<op>\|\||&&|==|!=|<=|>=|[-+*/%()!~|&<>?:,])"
    r")"
)


class ExprError(Exception):
    pass


def tokenize(s: str):
    pos, out = 0, []
    s = s.strip()
    while pos < len(s):
        m = _TOKEN_RE.match(s, pos)
        if not m or m.end() == pos:
            raise ExprError(f"bad token at {pos} in {s!r}")
        pos = m.end()
        kind = m.lastgroup
        out.append((kind, m.group(kind)))
    return out


class Parser:
    def __init__(self, tokens, env):
        self.t, self.i, self.env = tokens, 0, env

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self, val=None):
        tok = self.peek()
        if val is not None and tok[1] != val:
            raise ExprError(f"expected {val!r}, got {tok}")
        self.i += 1
        return tok

    def parse(self):
        v = self.ternary()
        if self.i != len(self.t):
            raise ExprError(f"trailing tokens {self.t[self.i:]}")
        return v

    def ternary(self):
        cond = self.lor()
        if self.peek()[1] == "?":
            self.take("?")
            a = self.ternary()
            self.take(":")
            b = self.ternary()
            return a if truthy(cond) else b
        return cond

    def lor(self):
        v = self.land()
        while self.peek()[1] == "||":
            self.take()
            r = self.land()
            v = truthy(v) or truthy(r)
        return v

    def land(self):
        v = self.bor()
        while self.peek()[1] == "&&":
            self.take()
            r = self.bor()
            v = truthy(v) and truthy(r)
        return v

    def bor(self):
        v = self.band()
        while self.peek()[1] == "|":
            self.take()
            v = int(v) | int(self.band())
        return v

    def band(self):
        v = self.eq()
        while self.peek()[1] == "&":
            self.take()
            v = int(v) & int(self.eq())
        return v

    def eq(self):
        v = self.rel()
        while self.peek()[1] in ("==", "!="):
            op = self.take()[1]
            r = self.rel()
            same = _equal(v, r)
            v = same if op == "==" else not same
        return v

    def rel(self):
        v = self.add()
        while self.peek()[1] in ("<", "<=", ">", ">="):
            op = self.take()[1]
            r = self.add()
            a, b = num(v), num(r)
            v = {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
        return v

    def add(self):
        v = self.mul()
        while self.peek()[1] in ("+", "-"):
            op = self.take()[1]
            r = self.mul()
            if op == "+" and (isinstance(v, str) or isinstance(r, str)):
                v = f"{fmt(v)}{fmt(r)}"
            else:
                v = num(v) + num(r) if op == "+" else num(v) - num(r)
        return v

    def mul(self):
        v = self.unary()
        while self.peek()[1] in ("*", "/", "%"):
            op = self.take()[1]
            r = self.unary()
            a, b = num(v), num(r)
            if op == "*":
                v = a * b
            elif op == "/":
                v = 0 if b == 0 else a / b
            else:
                v = 0 if b == 0 else math.fmod(a, b)
        return v

    def unary(self):
        tok = self.peek()
        if tok[1] in ("!", "~", "-", "+"):
            self.take()
            v = self.unary()
            if tok[1] == "!":
                return not truthy(v)
            if tok[1] == "~":
                return ~int(v)
            if tok[1] == "-":
                return -num(v)
            return num(v)
        return self.primary()

    def primary(self):
        kind, val = self.take()
        if kind == "num":
            return float(val) if "." in val else int(val)
        if kind == "str":
            return bytes(val[1:-1], "utf-8").decode("unicode_escape")
        if kind == "src":
            return self.env.source(val[1:-1])
        if kind == "id":
            if val == "null":
                return None
            if val in ("true", "TRUE"):
                return True
            if val in ("false", "FALSE"):
                return False
            self.take("(")
            args = []
            if self.peek()[1] != ")":
                args.append(self.ternary())
                while self.peek()[1] == ",":
                    self.take()
                    args.append(self.ternary())
            self.take(")")
            return call_fn(val, args, self.env)
        if val == "(":
            v = self.ternary()
            self.take(")")
            return v
        raise ExprError(f"unexpected {val!r}")


def _equal(a, b):
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, str) or isinstance(b, str):
        return fmt(a) == fmt(b)
    return num(a) == num(b)


def truthy(v):
    if v is None:
        return False
    if isinstance(v, str):
        return v not in ("", "0", "false", "FALSE")
    return bool(v)


def num(v):
    if v is None:
        return 0
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return v
    try:
        return float(v) if "." in v else int(v)
    except (TypeError, ValueError):
        return 0


def fmt(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def call_fn(name, a, env):
    f = {
        "round": lambda x: int(math.floor(num(x) + 0.5)),
        "floor": lambda x: math.floor(num(x)),
        "ceil": lambda x: math.ceil(num(x)),
        "fract": lambda x: num(x) - math.floor(num(x)),
        "sin": lambda x: math.sin(num(x)),
        "cos": lambda x: math.cos(num(x)),
        "tan": lambda x: math.tan(num(x)),
        "asin": lambda x: math.asin(num(x)),
        "acos": lambda x: math.acos(num(x)),
        "atan": lambda x: math.atan(num(x)),
        "abs": lambda x: abs(num(x)),
        "clamp": lambda x, lo, hi: min(max(num(x), num(lo)), num(hi)),
        "log": lambda x: math.log(num(x)),
        "log10": lambda x: math.log10(num(x)),
        "sqrt": lambda x: math.sqrt(num(x)),
        "exp": lambda x: math.exp(num(x)),
        "deg": lambda x: math.degrees(num(x)),
        "rad": lambda x: math.radians(num(x)),
        "pow": lambda x, y: math.pow(num(x), num(y)),
        "textLength": lambda s: len(fmt(s)),
        "subText": lambda s, i, j: fmt(s)[int(num(i)):int(num(j))],
        "colorRgb": lambda r, g, b: "#FF%02X%02X%02X" % (int(num(r)), int(num(g)), int(num(b))),
        "colorArgb": lambda al, r, g, b: "#%02X%02X%02X%02X" % (int(num(al)), int(num(r)), int(num(g)), int(num(b))),
    }.get(name)
    if f is None:
        raise ExprError(f"function {name}() not supported by preview renderer")
    return f(*a)


# ----------------------------------------------------------------------------------------
# Environment (data sources)
# ----------------------------------------------------------------------------------------
DAYS_S = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DAYS_F = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTHS_S = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@dataclass
class Env:
    dt: Any                                   # datetime.datetime
    millis: int = 0
    ambient: bool = False
    is24h: bool = False
    config: dict = field(default_factory=dict)        # id -> option id (or 'TRUE'/'FALSE')
    color_configs: dict = field(default_factory=dict)  # id -> {option id: [colors]}
    extra: dict = field(default_factory=dict)          # other data sources
    complication: dict | None = None                   # data for the complication being drawn
    strings: dict = field(default_factory=dict)

    def source(self, name: str):
        if name.startswith("CONFIGURATION."):
            parts = name.split(".")
            cid = parts[1]
            if cid in self.color_configs:
                colors = self.color_configs[cid][self.config[cid]]
                if len(parts) > 2:
                    return colors[int(parts[2])]
                return " ".join(colors)
            return self.config.get(cid)
        if name.startswith("COMPLICATION."):
            key = name.split(".", 1)[1]
            return (self.complication or {}).get(key)
        if name in self.extra:
            return self.extra[name]
        d = self.dt
        h24, m, s = d.hour, d.minute, d.second
        h12 = h24 % 12
        sm = s + self.millis / 1000.0
        table = {
            "SECOND": s, "SECOND_Z": f"{s:02d}", "SECOND_MILLISECOND": sm,
            "MINUTE": m, "MINUTE_Z": f"{m:02d}", "MINUTE_SECOND": m + sm / 60.0,
            "HOUR_0_11": h12, "HOUR_0_11_Z": f"{h12:02d}", "HOUR_0_11_MINUTE": h12 + m / 60.0 + sm / 3600.0,
            "HOUR_1_12": h12 or 12, "HOUR_1_12_Z": f"{(h12 or 12):02d}",
            "HOUR_0_23": h24, "HOUR_0_23_Z": f"{h24:02d}", "HOUR_0_23_MINUTE": h24 + m / 60.0,
            "HOUR_1_24": h24 or 24, "HOUR_1_24_Z": f"{(h24 or 24):02d}",
            "DAY": d.day, "DAY_Z": f"{d.day:02d}", "MONTH": d.month, "MONTH_Z": f"{d.month:02d}",
            "MONTH_S": MONTHS_S[d.month - 1], "YEAR": d.year,
            "DAY_OF_WEEK": (d.weekday() + 1) % 7 + 1, "DAY_OF_WEEK_S": DAYS_S[d.weekday()],
            "DAY_OF_WEEK_F": DAYS_F[d.weekday()], "IS_24_HOUR_MODE": 1 if self.is24h else 0,
            "AMPM_STATE": 0 if h24 < 12 else 1, "SECONDS_IN_DAY": h24 * 3600 + m * 60 + s,
        }
        if name in table:
            return table[name]
        raise ExprError(f"unknown source [{name}]")

    def eval(self, expr: str):
        return Parser(tokenize(expr), self).parse()


# ----------------------------------------------------------------------------------------
# Colours and geometry helpers
# ----------------------------------------------------------------------------------------
def parse_color(v) -> tuple:
    s = fmt(v).strip()
    if not s.startswith("#"):
        raise ValueError(f"not a colour: {v!r}")
    h = s[1:]
    if len(h) == 6:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)
    if len(h) == 8:
        return (int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16), int(h[0:2], 16))
    raise ValueError(f"bad colour {v!r}")


def with_alpha(c, a):
    return (c[0], c[1], c[2], int(round(c[3] * a)))


def _paste(parent, img, x, y):
    """alpha_composite that tolerates parts hanging off the parent's edges."""
    x0, y0 = max(0, -x), max(0, -y)
    x1, y1 = min(img.width, parent.width - x), min(img.height, parent.height - y)
    if x1 <= x0 or y1 <= y0:
        return
    if (x0, y0, x1, y1) != (0, 0, img.width, img.height):
        img = img.crop((x0, y0, x1, y1))
    parent.alpha_composite(img, (x + x0, y + y0))


class Renderer:
    def __init__(self, xml_path: str, res_dir: str, scale: int = 4, fallback_font: str | None = None,
                 font_overrides: dict | None = None, images: dict | None = None):
        self.xml_path, self.res_dir, self.S = xml_path, res_dir, scale
        self.tree = etree.parse(xml_path)
        self.root = self.tree.getroot()
        self.fallback_font = fallback_font
        self.font_overrides = font_overrides or {}
        self.images = images or {}
        self._font_cache: dict = {}
        self.W = float(self.root.get("width"))
        self.H = float(self.root.get("height"))
        self.color_configs = {}
        self.config_defaults = {}
        uc = self.root.find("UserConfigurations")
        if uc is not None:
            for cc in uc:
                if cc.tag == "ColorConfiguration":
                    self.color_configs[cc.get("id")] = {o.get("id"): o.get("colors").split() for o in cc}
                if cc.get("id"):
                    self.config_defaults[cc.get("id")] = cc.get("defaultValue")

    # -- fonts -----------------------------------------------------------------------------
    def font(self, family: str, size: float, weight: str = "NORMAL"):
        key = (family, round(size * self.S, 2), weight)
        if key in self._font_cache:
            return self._font_cache[key]
        path = None
        if family in self.font_overrides:
            path = self.font_overrides[family]
        else:
            for ext in (".ttf", ".otf"):
                p = os.path.join(self.res_dir, "font", family + ext)
                if os.path.exists(p):
                    path = p
                    break
        if path is None:
            path = self.fallback_font
        f = ImageFont.truetype(path, size=max(1, int(round(size * self.S))), layout_engine=ImageFont.Layout.RAQM)
        try:
            axes = f.get_variation_axes()
            wmap = {"THIN": 100, "ULTRA_LIGHT": 150, "EXTRA_LIGHT": 200, "LIGHT": 300, "NORMAL": 400,
                    "MEDIUM": 500, "SEMI_BOLD": 600, "BOLD": 700, "ULTRA_BOLD": 750, "EXTRA_BOLD": 800,
                    "BLACK": 900, "EXTRA_BLACK": 1000}
            vals = []
            for a in axes:
                nm = a["name"]
                nm = nm.decode() if isinstance(nm, bytes) else nm
                vals.append(wmap.get(weight, 400) if nm == "Weight" else a["default"])
            f.set_variation_by_axes(vals)
        except Exception:
            pass
        from fontTools.ttLib import TTFont
        tt = TTFont(path, lazy=True)
        upm = tt["head"].unitsPerEm
        asc, desc = tt["hhea"].ascent / upm, -tt["hhea"].descent / upm
        self._font_cache[key] = (f, asc, desc)
        return self._font_cache[key]

    # -- attribute helpers ---------------------------------------------------------------
    def attrs(self, el, env: Env) -> dict:
        a = dict(el.attrib)
        if env.ambient:
            for v in el.findall("Variant"):
                if v.get("mode") == "AMBIENT":
                    a[v.get("target")] = fmt(env.eval(v.get("value")))
        for t in el.findall("Transform"):
            a[t.get("target")] = fmt(env.eval(t.get("value")))
        return a

    def fnum(self, a, key, default=0.0, env=None):
        v = a.get(key)
        if v is None:
            return default
        try:
            return float(v)
        except ValueError:
            return float(num(env.eval(v)))

    def color(self, v, env):
        if v is None:
            return None
        v = v.strip()
        if v.startswith("#"):
            return parse_color(v)
        return parse_color(env.eval(v))

    # -- entry point ---------------------------------------------------------------------
    def render(self, env: Env, out_size: int | None = None) -> Image.Image:
        env.color_configs = self.color_configs
        for k, v in self.config_defaults.items():
            env.config.setdefault(k, v)
        S = self.S
        scene = self.root.find("Scene")
        sa = self.attrs(scene, env)
        bg = self.color(sa.get("backgroundColor", "#FF000000"), env)
        canvas = Image.new("RGBA", (int(self.W * S), int(self.H * S)), bg)
        self.children(scene, canvas, env)
        img = canvas
        if out_size:
            img = img.resize((out_size, out_size), Image.LANCZOS)
        return img

    def children(self, el, layer: Image.Image, env: Env):
        for ch in el:
            if not isinstance(ch.tag, str):
                continue
            tag = ch.tag
            if tag == "Group":
                self.group(ch, layer, env)
            elif tag == "PartDraw":
                self.part(ch, layer, env, self.draw_part)
            elif tag == "PartText":
                self.part(ch, layer, env, self.text_part)
            elif tag == "PartImage":
                self.part(ch, layer, env, self.image_part)
            elif tag == "ComplicationSlot":
                self.complication_slot(ch, layer, env)
            elif tag == "Condition":
                self.condition(ch, layer, env)
            elif tag in ("BooleanConfiguration", "ListConfiguration"):
                sel = env.config.get(ch.get("id"))
                for opt in ch:
                    if isinstance(opt.tag, str) and opt.get("id") == sel:
                        self.children(opt, layer, env)
            elif tag in ("Variant", "Transform", "Launch", "ScreenReader", "Localization", "Gyro",
                         "Reference", "BoundingBox", "BoundingOval", "BoundingRoundBox", "BoundingArc",
                         "DefaultProviderPolicy", "Complication"):
                continue
            else:
                raise NotImplementedError(f"preview renderer: <{tag}>")

    def condition(self, el, layer, env):
        exprs = {e.get("name"): (e.text or "") for e in el.find("Expressions")}
        compares = el.findall("Compare")
        if env.extra.get("__exactly_one__"):
            # Emulates a runtime that only shows a Compare when it is the ONLY true one
            # (otherwise the Default) - the behaviour seen on the watch.
            hits = [c for c in compares if truthy(env.eval(exprs[c.get("expression")]))]
            if len(hits) == 1:
                self.children(hits[0], layer, env)
                return
            compares = []
        for c in compares:
            if truthy(env.eval(exprs[c.get("expression")])):
                self.children(c, layer, env)
                return
        d = el.find("Default")
        if d is not None:
            self.children(d, layer, env)

    # -- compositing ------------------------------------------------------------------------
    def composite(self, parent: Image.Image, sub: Image.Image, a: dict, env: Env):
        S = self.S
        x, y = self.fnum(a, "x", env=env), self.fnum(a, "y", env=env)
        w, h = self.fnum(a, "width", env=env), self.fnum(a, "height", env=env)
        alpha = self.fnum(a, "alpha", 255, env=env) / 255.0
        angle = self.fnum(a, "angle", 0, env=env)
        tint = self.color(a.get("tintColor"), env) if a.get("tintColor") else None
        if tint is not None:
            r, g, b, ta = tint
            al = sub.getchannel("A")
            if ta < 255:
                al = al.point(lambda v: v * ta // 255)
            # tint multiplies colour: white content -> tint colour
            rgb = ImageChops.multiply(sub.convert("RGB"), Image.new("RGB", sub.size, (r, g, b)))
            sub = Image.merge("RGBA", (*rgb.split(), al))
        if alpha < 1.0:
            sub = sub.copy()
            sub.putalpha(sub.getchannel("A").point(lambda v: int(v * alpha)))
        ox, oy = int(round(x * S)), int(round(y * S))
        if abs(angle) > 1e-6:
            # Rotate about the pivot on a canvas big enough to hold the whole rotated part, so
            # nothing is cropped (the runtime rotates the canvas, it does not clip corners).
            px = int(round(self.fnum(a, "pivotX", 0.5, env=env) * w * S))
            py = int(round(self.fnum(a, "pivotY", 0.5, env=env) * h * S))
            sw, sh = sub.size
            R = int(math.ceil(max(math.hypot(px, py), math.hypot(sw - px, py), math.hypot(px, sh - py),
                                  math.hypot(sw - px, sh - py)))) + 2
            big = Image.new("RGBA", (2 * R, 2 * R), (0, 0, 0, 0))
            big.paste(sub, (R - px, R - py))
            sub = big.rotate(-angle, resample=Image.BICUBIC, center=(R, R))
            ox, oy = ox + px - R, oy + py - R
        _paste(parent, sub, ox, oy)

    def new_layer(self, a, env):
        w = max(1, int(round(self.fnum(a, "width", env=env) * self.S)))
        h = max(1, int(round(self.fnum(a, "height", env=env) * self.S)))
        return Image.new("RGBA", (w, h), (0, 0, 0, 0))

    def group(self, el, parent, env):
        a = self.attrs(el, env)
        if self.fnum(a, "alpha", 255, env=env) <= 0:
            return
        sub = self.new_layer(a, env)
        self.children(el, sub, env)
        self.composite(parent, sub, a, env)

    def part(self, el, parent, env, fn):
        a = self.attrs(el, env)
        if self.fnum(a, "alpha", 255, env=env) <= 0:
            return
        sub = self.new_layer(a, env)
        fn(el, sub, a, env)
        self.composite(parent, sub, a, env)

    def complication_slot(self, el, parent, env):
        a = self.attrs(el, env)
        data = (env.extra.get("__complications__") or {}).get(el.get("slotId"))
        ctype = data["type"] if data else "EMPTY"
        comp = None
        for c in el.findall("Complication"):
            if c.get("type") == ctype:
                comp = c
        if comp is None:
            return
        sub = self.new_layer(a, env)
        prev = env.complication
        env.complication = data or {}
        self.children(comp, sub, env)
        env.complication = prev
        self.composite(parent, sub, a, env)

    # -- PartDraw ------------------------------------------------------------------------
    def draw_part(self, el, layer, a, env):
        for shape in el:
            if not isinstance(shape.tag, str) or shape.tag in ("Transform", "Variant", "Launch", "Gyro",
                                                                 "ScreenReader", "Reference"):
                continue
            sa = self.attrs(shape, env)
            fill = shape.find("Fill")
            stroke = shape.find("Stroke")
            if shape.tag == "Arc":
                if stroke is not None:
                    self.draw_arc(layer, sa, self.attrs(stroke, env), env)
                continue
            if shape.tag == "Line":
                if stroke is not None:
                    self.draw_line(layer, sa, self.attrs(stroke, env), env)
                continue
            if fill is not None:
                self.fill_shape(layer, shape.tag, sa, self.color(self.attrs(fill, env)["color"], env), env)
            if stroke is not None:
                self.stroke_shape(layer, shape.tag, sa, self.attrs(stroke, env), env)

    def _paint(self, layer, mask, color):
        if color is None or color[3] == 0:
            return
        solid = Image.new("RGBA", layer.size, color[:3] + (255,))
        m = mask if color[3] == 255 else mask.point(lambda v: v * color[3] // 255)
        solid.putalpha(m)
        layer.alpha_composite(solid)

    def _shape_mask(self, layer, tag, sa, env, inset=0.0):
        S = self.S
        m = Image.new("L", layer.size, 0)
        d = ImageDraw.Draw(m)
        x, y = self.fnum(sa, "x", env=env) * S, self.fnum(sa, "y", env=env) * S
        w, h = self.fnum(sa, "width", env=env) * S, self.fnum(sa, "height", env=env) * S
        box = [x + inset, y + inset, x + w - inset, y + h - inset]
        if box[2] <= box[0] or box[3] <= box[1]:
            return m
        if tag == "Ellipse":
            d.ellipse(box, fill=255)
        elif tag == "Rectangle":
            d.rectangle(box, fill=255)
        elif tag == "RoundRectangle":
            r = min(self.fnum(sa, "cornerRadiusX", env=env) * S - inset, (box[2] - box[0]) / 2, (box[3] - box[1]) / 2)
            d.rounded_rectangle(box, radius=max(0, r), fill=255)
        return m

    def fill_shape(self, layer, tag, sa, color, env):
        self._paint(layer, self._shape_mask(layer, tag, sa, env), color)

    def stroke_shape(self, layer, tag, sa, st, env):
        t = self.fnum(st, "thickness", env=env) * self.S
        outer = self._shape_mask(layer, tag, sa, env, inset=-t / 2)
        inner = self._shape_mask(layer, tag, sa, env, inset=t / 2)
        self._paint(layer, ImageChops.subtract(outer, inner), self.color(st["color"], env))

    def draw_arc(self, layer, sa, st, env):
        S = self.S
        cx, cy = self.fnum(sa, "centerX", env=env) * S, self.fnum(sa, "centerY", env=env) * S
        rx, ry = self.fnum(sa, "width", env=env) * S / 2, self.fnum(sa, "height", env=env) * S / 2
        a0, a1 = self.fnum(sa, "startAngle", env=env), self.fnum(sa, "endAngle", env=env)
        if sa.get("direction", "CLOCKWISE") == "COUNTER_CLOCKWISE":
            a0, a1 = a1, a0
        if a1 < a0:
            a0, a1 = a1, a0
        t = self.fnum(st, "thickness", env=env) * S
        cap = st.get("cap", "BUTT")
        sweep = a1 - a0
        if sweep <= 0 and cap == "BUTT":
            return
        n = max(8, int(abs(sweep) * 2))
        outer, inner = [], []
        for i in range(n + 1):
            ang = math.radians(a0 + sweep * i / n)
            sx, cy_ = math.sin(ang), -math.cos(ang)
            outer.append((cx + (rx + t / 2) * sx, cy + (ry + t / 2) * cy_))
            inner.append((cx + (rx - t / 2) * sx, cy + (ry - t / 2) * cy_))
        m = Image.new("L", layer.size, 0)
        d = ImageDraw.Draw(m)
        if sweep > 0:
            d.polygon(outer + inner[::-1], fill=255)
        if cap == "ROUND":
            for ang in (a0, a1):
                r = math.radians(ang)
                px, py = cx + rx * math.sin(r), cy - ry * math.cos(r)
                d.ellipse([px - t / 2, py - t / 2, px + t / 2, py + t / 2], fill=255)
        self._paint(layer, m, self.color(st["color"], env))

    def draw_line(self, layer, sa, st, env):
        S = self.S
        x0, y0 = self.fnum(sa, "startX", env=env) * S, self.fnum(sa, "startY", env=env) * S
        x1, y1 = self.fnum(sa, "endX", env=env) * S, self.fnum(sa, "endY", env=env) * S
        t = self.fnum(st, "thickness", env=env) * S
        m = Image.new("L", layer.size, 0)
        d = ImageDraw.Draw(m)
        d.line([x0, y0, x1, y1], fill=255, width=max(1, int(round(t))))
        if st.get("cap", "BUTT") == "ROUND":
            for px, py in ((x0, y0), (x1, y1)):
                d.ellipse([px - t / 2, py - t / 2, px + t / 2, py + t / 2], fill=255)
        self._paint(layer, m, self.color(st["color"], env))

    # -- PartText ------------------------------------------------------------------------
    def text_content(self, font_el, env) -> str:
        out = []
        if font_el.text:
            out.append(font_el.text)
        for ch in font_el:
            if not isinstance(ch.tag, str):
                if ch.tail:
                    out.append(ch.tail)
                continue
            if ch.tag == "Template":
                out.append(self.template(ch, env))
            elif ch.tag == "Upper":
                out.append(self.text_content(ch, env).upper())
            elif ch.tag == "Lower":
                out.append(self.text_content(ch, env).lower())
            if ch.tail:
                out.append(ch.tail)
        return re.sub(r"\s*\n\s*", "", "".join(out)).strip()

    def template(self, tpl, env) -> str:
        fmt_str = (tpl.text or "")
        params = []
        for p in tpl.findall("Parameter"):
            params.append(env.eval(p.get("expression")))
            if p.tail:
                fmt_str += p.tail
        vals = [fmt(v) for v in params]
        out, vi, i = [], 0, 0
        while i < len(fmt_str):
            if fmt_str[i] == "%" and i + 1 < len(fmt_str):
                if fmt_str[i + 1] == "s":
                    out.append(vals[vi] if vi < len(vals) else "")
                    vi += 1
                    i += 2
                    continue
                if fmt_str[i + 1] == "%":
                    out.append("%")
                    i += 2
                    continue
            out.append(fmt_str[i])
            i += 1
        return "".join(out).strip()

    def text_part(self, el, layer, a, env):
        S = self.S
        text_el = el.find("Text")
        font_el = text_el.find("Font")
        fa = self.attrs(font_el, env)
        size = float(fa["size"])
        color = self.color(fa.get("color", "#FFFFFFFF"), env)
        s = self.text_content(font_el, env)
        if not s:
            return
        ls = float(fa.get("letterSpacing", 0) or 0)
        W, H = layer.size
        auto = text_el.get("isAutoSize", "FALSE").upper() == "TRUE"
        while True:
            f, asc, desc = self.font(fa["family"], size, fa.get("weight", "NORMAL"))
            widths = [f.getlength(c) for c in s]
            spacing = ls * size * S
            total = (f.getlength(s) if ls == 0 else sum(widths) + spacing * (len(s) - 1))
            if not auto or total <= W or size <= 12:
                break
            size -= 0.5
        if text_el.get("ellipsis", "FALSE").upper() == "TRUE" and total > W:
            while s and (f.getlength(s + "…") > W):
                s = s[:-1]
            s = s.rstrip() + "…"
            widths = [f.getlength(c) for c in s]
            total = f.getlength(s)
        align = text_el.get("align", "CENTER")
        x = 0 if align == "START" else (W - total if align == "END" else (W - total) / 2)
        line_h = (asc + desc) * size * S
        baseline = (H - line_h) / 2 + asc * size * S
        d = ImageDraw.Draw(layer)
        if ls == 0:
            d.text((x, baseline), s, font=f, fill=color, anchor="ls")
        else:
            for c, wch in zip(s, widths):
                d.text((x, baseline), c, font=f, fill=color, anchor="ls")
                x += wch + spacing

    # -- PartImage -----------------------------------------------------------------------
    def image_part(self, el, layer, a, env):
        img_el = el.find("Image")
        res = img_el.get("resource")
        if res.startswith("["):
            im = env.eval(res)
        else:
            im = self.images.get(res)
            if im is None:
                for folder in ("drawable-nodpi", "drawable"):
                    p = os.path.join(self.res_dir, folder, res + ".png")
                    if os.path.exists(p):
                        im = Image.open(p).convert("RGBA")
                        break
        if im is None:
            return
        layer.alpha_composite(im.convert("RGBA").resize(layer.size, Image.LANCZOS))
