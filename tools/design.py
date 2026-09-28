"""Generates the Orbit watch face resources (Watch Face Format v4).

Single source of truth for the design: every coordinate, colour and behaviour lives here and
is written out as res/raw/watchface.xml plus the supporting resource files. The preview
renderer reads the generated XML back, so what the previews show is what ships.
"""
from __future__ import annotations

import math
import os
import sys
from xml.sax.saxutils import escape

from fontTools.ttLib import TTFont

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
SRC = os.path.join(PROJECT, "src")
RES = os.path.join(SRC, "res")

PACKAGE = "app.orbit.watchface"
VERSION_CODE = 3
VERSION_NAME = "1.1.1"
AUTHOR = "Sergio De Lucio"
LICENSE = "CC BY-NC-SA 4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by-nc-sa/4.0/"
WFF_VERSION = 4          # Wear OS 6 (API 36) - Pixel Watch 4 ships with Wear OS 6
MIN_SDK = 36
TARGET_SDK = 36

W = H = 450
C = W / 2

# ------------------------------------------------------------------------------------------
# Design parameters
# ------------------------------------------------------------------------------------------
# Kepler's rule: the slower the body, the wider its orbit. Hours outside, seconds inside.
R_HOUR, R_MIN, R_SEC = 204, 182, 160
D_HOUR, D_MIN, D_SEC = 22, 15, 9
ORBIT_STROKE = 1.6
TAIL = {  # comet tail: degrees, stacked layers (more = smoother), alpha per layer, max width factor
    "hour": dict(length=26, layers=10, alpha=25, width=0.72),
    "min": dict(length=38, layers=10, alpha=24, width=0.72),
    "sec": dict(length=64, layers=12, alpha=22, width=0.80),
}

HALO = [(2.3, 22), (1.6, 34)]   # soft glow around each body: (diameter factor, alpha)

TIME_FONT, TIME_FONT_AOD = "orbit_time", "orbit_time_light"
LABEL_FONT = "orbit_label"
TIME_SIZE = 104
TIME_CY = 222
TIME_BOX_H = 100          # digits span ~76px; text is centred, so the box only sets the tap target
DATE_CY = 141
DATE_SIZE = 22
CHIP_W, CHIP_H, CHIP_GAP, CHIP_Y = 104, 36, 12, 283

# Colour themes: hour body, minute body, second body. Everything else is derived by tinting
# white shapes, so the palette the editor shows stays exactly these three colours.
THEMES = [
    ("aurora", "Aurora", "#FF74F0C4", "#FF7CC6FF", "#FFD9A8FF"),
    ("solar", "Solar", "#FFFFC262", "#FFFF8166", "#FFFFE4B5"),
    ("nebula", "Nebula", "#FFFF8FC9", "#FFB29DFF", "#FF8CE7FF"),
    ("glacier", "Glacier", "#FFE4EEFF", "#FF8FB9FF", "#FFFFFFFF"),
    ("lime", "Lime", "#FFD4F56B", "#FF79E6A6", "#FFFFF27A"),
    ("classic", "Classic", "#FFFFFFFF", "#FFC8C8C8", "#FFFF5A4F"),
]

HOUR_C, MIN_C, SEC_C = "[CONFIGURATION.theme.0]", "[CONFIGURATION.theme.1]", "[CONFIGURATION.theme.2]"

# Ambient-mode switch. Watch Face Format v4 would allow a fade here (duration > 0), but Wear OS 6
# has a known bug where third-party faces can freeze half-way through that fade and show the
# interactive and always-on layers on top of each other (issuetracker.google.com/452423520).
# An explicit zero duration (the v4 default is 1.0) makes the switch instant and avoids it.
FADE = 'duration="0"'


def fnum(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def white(alpha: int) -> str:
    return "#%02XFFFFFF" % max(0, min(255, alpha))


def font_metrics(family):
    f = TTFont(os.path.join(RES, "font", family + ".ttf"))
    upm = f["head"].unitsPerEm
    cmap = f.getBestCmap()
    adv = lambda ch: f["hmtx"][cmap[ord(ch)]][0] / upm
    return dict(digit=adv("0"), colon=adv(":"), asc=f["hhea"].ascent / upm, desc=-f["hhea"].descent / upm)


# ------------------------------------------------------------------------------------------
# Building blocks
# ------------------------------------------------------------------------------------------
def planet(name, radius, diameter, tint, angle_expr, tail, ambient_ring=False):
    """A body on an orbit: white shapes in one rotating PartDraw, tinted with the theme."""
    cx, cy = C, C - radius
    parts = []
    n = tail["layers"]
    for k in range(n, 0, -1):  # longest (thinnest, faintest) first
        length = tail["length"] * k / n
        width = max(1.6, diameter * tail["width"] * (1 - (k - 1) / n))
        parts.append(
            f'<Arc centerX="{fnum(C)}" centerY="{fnum(C)}" width="{fnum(2 * radius)}" height="{fnum(2 * radius)}" '
            f'startAngle="{fnum(-length)}" endAngle="0">'
            f'<Stroke color="{white(tail["alpha"])}" thickness="{fnum(width)}" cap="ROUND"/></Arc>')
    for scale, a in HALO:
        hd = diameter * scale
        parts.append(
            f'<Ellipse x="{fnum(cx - hd / 2)}" y="{fnum(cy - hd / 2)}" width="{fnum(hd)}" height="{fnum(hd)}">'
            f'<Fill color="{white(a)}"/></Ellipse>')
    parts.append(
        f'<Ellipse x="{fnum(cx - diameter / 2)}" y="{fnum(cy - diameter / 2)}" width="{diameter}" height="{diameter}">'
        f'<Fill color="#FFFFFFFF"/></Ellipse>')
    out = [
        f'<PartDraw name="{uid(name)}" x="0" y="0" width="{W}" height="{H}" pivotX="0.5" pivotY="0.5" tintColor="{tint}">',
        f'<Transform target="angle" value="{angle_expr}"/>',
        f'<Variant mode="AMBIENT" target="alpha" value="0" {FADE}/>',
        *parts,
        "</PartDraw>",
    ]
    if ambient_ring:
        d = diameter - 4
        out += [
            f'<PartDraw name="{uid(name + "_ambient")}" x="0" y="0" width="{W}" height="{H}" pivotX="0.5" pivotY="0.5" '
            f'alpha="0" tintColor="{tint}">',
            f'<Transform target="angle" value="{angle_expr}"/>',
            f'<Variant mode="AMBIENT" target="alpha" value="210" {FADE}/>',
            f'<Ellipse x="{fnum(cx - d / 2)}" y="{fnum(cy - d / 2)}" width="{d}" height="{d}">'
            f'<Stroke color="#FFFFFFFF" thickness="2.4"/></Ellipse>',
            "</PartDraw>",
        ]
    return "\n".join(out)


def orbit_ring(name, radius, tint, alpha):
    return (
        f'<PartDraw name="{uid(name)}" x="0" y="0" width="{W}" height="{H}" tintColor="{tint}" alpha="{alpha}">'
        f'<Variant mode="AMBIENT" target="alpha" value="0" {FADE}/>'
        f'<Ellipse x="{fnum(C - radius)}" y="{fnum(C - radius)}" width="{2 * radius}" height="{2 * radius}">'
        f'<Stroke color="#FFFFFFFF" thickness="{fnum(ORBIT_STROKE)}"/></Ellipse>'
        "</PartDraw>")


def hour_marks():
    dots = []
    for i in range(12):
        a = math.radians(i * 30)
        x, y = C + R_HOUR * math.sin(a), C - R_HOUR * math.cos(a)
        d = 6 if i == 0 else 4
        col = "#FFBDBDBD" if i == 0 else "#FF5E5E5E"
        dots.append(f'<Ellipse x="{fnum(x - d / 2)}" y="{fnum(y - d / 2)}" width="{d}" height="{d}">'
                    f'<Fill color="{col}"/></Ellipse>')
    return (f'<PartDraw name="hour_marks" x="0" y="0" width="{W}" height="{H}">'
            f'<Variant mode="AMBIENT" target="alpha" value="150" {FADE}/>'
            + "".join(dots) + "</PartDraw>")


# ------------------------------------------------------------------------------------------
# Conditions are always if / else-if chains: exactly one <Compare> per <Condition>, the "else"
# in <Default>. The runtime does not promise that the first true Compare wins (on the watch a
# Condition with two true branches falls back to its Default), so branches must never overlap.
# ------------------------------------------------------------------------------------------
def chain(cases, default):
    """cases: [(name, expression, body), ...] tried in order; default: body when none match."""
    if not cases:
        return default
    (name, expr, body), rest = cases[0], cases[1:]
    return (f'<Condition><Expressions><Expression name="{name}"><![CDATA[{expr}]]></Expression>'
            f'</Expressions><Compare expression="{name}">{body}</Compare>'
            f"<Default>{chain(rest, default)}</Default></Condition>")


_NAMES = {}


def uid(base):
    """Unique element names, so no two parts in the scene share one."""
    _NAMES[base] = _NAMES.get(base, 0) + 1
    return base if _NAMES[base] == 1 else f"{base}_{_NAMES[base]}"


def text(name, x, y, w, h, family, size, color, content, align="CENTER", letter_spacing=None, extra="",
         text_attrs="", part_children=""):
    ls = f' letterSpacing="{fnum(letter_spacing)}"' if letter_spacing else ""
    return (f'<PartText name="{uid(name)}" x="{int(x)}" y="{int(y)}" width="{int(w)}" height="{int(h)}"{extra}>'
            f'{part_children}'
            f'<Text align="{align}"{text_attrs}><Font family="{family}" size="{fnum(size)}" color="{color}"{ls}>'
            f'{content}</Font></Text></PartText>')


def template(fmt, *exprs):
    params = "".join(f'<Parameter expression="{escape(e, {chr(34): "&quot;"})}"/>' for e in exprs)
    return f"<Template>{escape(fmt)}{params}</Template>"


def clock(ambient: bool):
    """Digital time from tabular digits. Every run is centre-aligned in a generous box whose centre
    is computed here, so the layout is identical in left-to-right and right-to-left languages, and
    a single-digit 12-hour time ("9:41") is laid out as its own centred block."""
    fam = TIME_FONT_AOD if ambient else TIME_FONT
    m = font_metrics(TIME_FONT)          # both instances share advance widths (equalised)
    dw, cw = m["digit"] * TIME_SIZE, m["colon"] * TIME_SIZE
    box_h = TIME_BOX_H
    y = int(round(TIME_CY - box_h / 2))
    colon_color = SEC_C if not ambient else "#80FFFFFF"
    name = "time_ambient" if ambient else "time"

    def run(label, center, width, color, content, extra=""):
        x = int(round(center - width / 2))
        return text(f"{name}_{label}", x, 0, width, box_h, fam, TIME_SIZE, color, content,
                    text_attrs=' maxLines="1"', extra=extra)

    def layout(hour_digits, hour_expr):
        block = hour_digits * dw + cw + 2 * dw
        left = C - block / 2
        hours_c = left + hour_digits * dw / 2
        colon_c = left + hour_digits * dw + cw / 2
        minutes_c = left + hour_digits * dw + cw + dw
        return (run("hours", hours_c, 150, HOUR_C, template("%s", hour_expr))
                + run("colon", colon_c, 50, colon_color, ":", "" if ambient else ' alpha="235"')
                + run("minutes", minutes_c, 150, MIN_C, template("%s", "[MINUTE_Z]")))

    if ambient:
        vis, variant = ' alpha="0"', f'<Variant mode="AMBIENT" target="alpha" value="255" {FADE}/>'
    else:
        vis, variant = "", f'<Variant mode="AMBIENT" target="alpha" value="0" {FADE}/>'
    launch = "" if ambient else '<Launch target="ALARM"/>'
    def block(label, hour_digits, hour_expr):
        return (f'<Group name="{uid(name + "_" + label)}" x="0" y="0" width="{W}" height="{box_h}">'
                + layout(hour_digits, hour_expr) + "</Group>")
    body = chain([(f"{name}_24h", "[IS_24_HOUR_MODE]", block("24h", 2, "[HOUR_0_23_Z]")),
                  (f"{name}_12h_two_digits", "[HOUR_1_12] >= 10", block("12h_2", 2, "[HOUR_1_12]"))],
                 block("12h_1", 1, "[HOUR_1_12]"))
    return (f'<Group name="{name}" x="0" y="{y}" width="{W}" height="{box_h}"{vis}>{variant}{launch}'
            f"{body}</Group>")


def date_line():
    lm = font_metrics(LABEL_FONT)
    h = int(round((lm["asc"] + lm["desc"]) * DATE_SIZE)) + 4
    y = int(round(DATE_CY - h / 2))
    content = f"<Upper>{template('%s %s', '[DAY_OF_WEEK_S]', '[DAY]')}</Upper>"
    return (f'<Group name="date" x="95" y="{y}" width="260" height="{h}">'
            f'<Variant mode="AMBIENT" target="alpha" value="170" {FADE}/>'
            '<Launch target="CALENDAR"/>'
            + text("date_text", 0, 0, 260, h, LABEL_FONT, DATE_SIZE, "#FFE8E8E8", content, letter_spacing=0.12)
            + "</Group>")


# ------------------------------------------------------------------------------------------
# Complication chips
# ------------------------------------------------------------------------------------------
def chip_bg(tint, alpha=40):
    r = CHIP_H / 2
    return (f'<PartDraw name="{uid("chip_bg")}" x="0" y="0" width="{CHIP_W}" height="{CHIP_H}" tintColor="{tint}">'
            f'<Variant mode="AMBIENT" target="alpha" value="0" {FADE}/>'
            f'<RoundRectangle x="0" y="0" width="{CHIP_W}" height="{CHIP_H}" cornerRadiusX="{fnum(r)}" cornerRadiusY="{fnum(r)}">'
            f'<Fill color="{white(alpha)}"/></RoundRectangle></PartDraw>')


def chip_progress(tint, frac_expr):
    """Background fill that grows left-to-right with the value (never narrower than a circle)."""
    r = CHIP_H / 2
    width_expr = f"{CHIP_H} + ({CHIP_W - CHIP_H}) * ({frac_expr})"
    return (f'<PartDraw name="{uid("chip_progress")}" x="0" y="0" width="{CHIP_W}" height="{CHIP_H}" tintColor="{tint}">'
            f'<Variant mode="AMBIENT" target="alpha" value="0" {FADE}/>'
            f'<RoundRectangle x="0" y="0" width="{CHIP_W}" height="{CHIP_H}" cornerRadiusX="{fnum(r)}" cornerRadiusY="{fnum(r)}">'
            f'<Transform target="width" value="{width_expr}"/>'
            f'<Fill color="{white(58)}"/></RoundRectangle></PartDraw>')


def chip_icon(tint, x, size=20):
    y = int(round((CHIP_H - size) / 2))
    return (f'<PartImage name="{uid("chip_icon")}" x="{x}" y="{y}" width="{size}" height="{size}" tintColor="{tint}">'
            f'<Variant mode="AMBIENT" target="alpha" value="190" {FADE}/>'
            '<Image resource="[COMPLICATION.MONOCHROMATIC_IMAGE]"/></PartImage>')


def chip_text(x, w, fmt="%s", exprs=("[COMPLICATION.TEXT]",), size=19):
    return text("chip_text", x, 0, w, CHIP_H, LABEL_FONT, size, "#FFF4F4F4", template(fmt, *exprs),
                text_attrs=' ellipsis="TRUE" isAutoSize="TRUE"',
                part_children=f'<Variant mode="AMBIENT" target="alpha" value="190" {FADE}/>')


def chip_icon_text(tint, name_prefix):
    """Chip content for every combination a data source may send: icon+text, text+title, text,
    icon alone. Text is optional for ranged / goal types, so nothing assumes it is present."""
    icon_c = int(round((CHIP_W - 22) / 2))
    icon_only = (f'<PartImage name="{uid("chip_icon")}" x="{icon_c}" y="{int((CHIP_H - 22) / 2)}" width="22" height="22" '
                 f'tintColor="{tint}"><Variant mode="AMBIENT" target="alpha" value="190" {FADE}/>'
                 '<Image resource="[COMPLICATION.MONOCHROMATIC_IMAGE]"/></PartImage>')
    icon_text = (f'<Group name="{uid("chip_icon_text")}" x="0" y="0" width="{CHIP_W}" height="{CHIP_H}">'
                 + chip_icon(tint, 12) + chip_text(36, CHIP_W - 36 - 10) + "</Group>")
    return chain([
        (f"{name_prefix}_icon_text", "[COMPLICATION.MONOCHROMATIC_IMAGE] != null && [COMPLICATION.TEXT] != null", icon_text),
        (f"{name_prefix}_text_title", "[COMPLICATION.TEXT] != null && [COMPLICATION.TITLE] != null",
         chip_text(10, CHIP_W - 20, fmt="%s %s", exprs=("[COMPLICATION.TEXT]", "[COMPLICATION.TITLE]"))),
        (f"{name_prefix}_text", "[COMPLICATION.TEXT] != null", chip_text(10, CHIP_W - 20)),
        (f"{name_prefix}_icon", "[COMPLICATION.MONOCHROMATIC_IMAGE] != null", icon_only),
    ], f'<Group name="{uid("chip_nothing")}" x="0" y="0" width="1" height="1"/>')


def complication_slot(slot_id, name, display, x, tint, default_provider, default_type):
    ranged = ("clamp(([COMPLICATION.RANGED_VALUE_VALUE] - [COMPLICATION.RANGED_VALUE_MIN]) / "
              "([COMPLICATION.RANGED_VALUE_MAX] - [COMPLICATION.RANGED_VALUE_MIN]), 0, 1)")
    goal = "clamp([COMPLICATION.GOAL_PROGRESS_VALUE] / [COMPLICATION.GOAL_PROGRESS_TARGET_VALUE], 0, 1)"
    img = int(round((CHIP_H - 24) / 2))
    icon_only = (f'<PartImage name="{uid("chip_icon")}" x="{int((CHIP_W - 22) / 2)}" y="{int((CHIP_H - 22) / 2)}" width="22" height="22" '
                 f'tintColor="{tint}"><Variant mode="AMBIENT" target="alpha" value="190" {FADE}/>'
                 '<Image resource="[COMPLICATION.MONOCHROMATIC_IMAGE]"/></PartImage>')
    return (
        f'<ComplicationSlot name="{name}" slotId="{slot_id}" displayName="{display}" x="{x}" y="{CHIP_Y}" '
        f'width="{CHIP_W}" height="{CHIP_H}" isCustomizable="TRUE" '
        'supportedTypes="SHORT_TEXT RANGED_VALUE GOAL_PROGRESS MONOCHROMATIC_IMAGE SMALL_IMAGE EMPTY">'
        f'<DefaultProviderPolicy defaultSystemProvider="{default_provider}" defaultSystemProviderType="{default_type}"/>'
        f'<BoundingRoundBox x="0" y="0" width="{CHIP_W}" height="{CHIP_H}" cornerRadius="{fnum(CHIP_H / 2)}"/>'
        '<Complication type="SHORT_TEXT">' + chip_bg(tint) + chip_icon_text(tint, f"s{slot_id}_short") + "</Complication>"
        '<Complication type="RANGED_VALUE">' + chip_bg(tint) + chip_progress(tint, ranged)
        + chip_icon_text(tint, f"s{slot_id}_ranged") + "</Complication>"
        '<Complication type="GOAL_PROGRESS">' + chip_bg(tint) + chip_progress(tint, goal)
        + chip_icon_text(tint, f"s{slot_id}_goal") + "</Complication>"
        '<Complication type="MONOCHROMATIC_IMAGE">' + chip_bg(tint) + icon_only + "</Complication>"
        '<Complication type="SMALL_IMAGE">' + chip_bg(tint)
        + f'<PartImage name="{uid("chip_image")}" x="{int((CHIP_W - 24) / 2)}" y="{img}" width="24" height="24">'
          f'<Variant mode="AMBIENT" target="alpha" value="0" {FADE}/>'
          '<Image resource="[COMPLICATION.SMALL_IMAGE]"/></PartImage>'
        + "</Complication>"
        '<Complication type="EMPTY"/>'
        "</ComplicationSlot>")


# ------------------------------------------------------------------------------------------
# The watch face
# ------------------------------------------------------------------------------------------
def watchface_xml() -> str:
    _NAMES.clear()
    theme_opts = "\n".join(
        f'      <ColorOption id="{tid}" displayName="theme_{tid}" colors="{h} {m} {s}"/>'
        for tid, _, h, m, s in THEMES)
    left_x = int(C - CHIP_GAP / 2 - CHIP_W)
    right_x = int(C + CHIP_GAP / 2)
    def seconds_layer(angle_expr):
        return (f'<Group name="{uid("seconds_layer")}" x="0" y="0" width="450" height="450">'
                + orbit_ring("orbit_seconds", R_SEC, SEC_C, 70)
                + planet("planet_seconds", R_SEC, D_SEC, SEC_C, angle_expr, TAIL["sec"])
                + "</Group>")
    seconds = (
        '<ListConfiguration id="seconds">'
        f'<ListOption id="smooth">{seconds_layer("[SECOND_MILLISECOND] * 6")}</ListOption>'
        f'<ListOption id="tick">{seconds_layer("[SECOND] * 6")}</ListOption>'
        '<ListOption id="off"><Group name="seconds_off" x="0" y="0" width="1" height="1"/></ListOption>'
        "</ListConfiguration>")
    body = f"""<?xml version="1.0" encoding="utf-8"?>
<!--
  Orbit - a Watch Face Format (v{WFF_VERSION}) watch face.
  © 2026 {AUTHOR}. Licensed under {LICENSE} ({LICENSE_URL}).
  Fonts keep their own licenses (see TERCEROS.md).
  Hours, minutes and seconds are bodies on three orbits (the slowest on the widest orbit),
  around a large digital time. Generated by tools/design.py; edit that file, not this one.
-->
<WatchFace width="{W}" height="{H}">
  <Metadata key="CLOCK_TYPE" value="DIGITAL"/>
  <Metadata key="PREVIEW_TIME" value="10:08:32"/>
  <Metadata key="AUTHOR" value="{AUTHOR}"/>
  <Metadata key="LICENSE" value="{LICENSE} - {LICENSE_URL}"/>
  <UserConfigurations>
    <ColorConfiguration id="theme" displayName="theme_label" defaultValue="{THEMES[0][0]}">
{theme_opts}
    </ColorConfiguration>
    <ListConfiguration id="seconds" displayName="seconds_label" defaultValue="smooth">
      <ListOption id="smooth" displayName="seconds_smooth"/>
      <ListOption id="tick" displayName="seconds_tick"/>
      <ListOption id="off" displayName="seconds_off"/>
    </ListConfiguration>
  </UserConfigurations>
  <Scene backgroundColor="#FF000000">
    {orbit_ring("orbit_hours", R_HOUR, HOUR_C, 64)}
    {orbit_ring("orbit_minutes", R_MIN, MIN_C, 64)}
    {hour_marks()}
    {seconds}
    {planet("planet_minutes", R_MIN, D_MIN, MIN_C, "[MINUTE_SECOND] * 6", TAIL["min"], ambient_ring=True)}
    {planet("planet_hours", R_HOUR, D_HOUR, HOUR_C, "[HOUR_0_11_MINUTE] * 30", TAIL["hour"], ambient_ring=True)}
    {date_line()}
    {clock(ambient=False)}
    {clock(ambient=True)}
    {complication_slot(0, "left_chip", "complication_left", left_x, HOUR_C, "STEP_COUNT", "SHORT_TEXT")}
    {complication_slot(1, "right_chip", "complication_right", right_x, MIN_C, "WATCH_BATTERY", "RANGED_VALUE")}
  </Scene>
</WatchFace>
"""
    return body


def strings_xml() -> str:
    items = {
        "watch_face_name": "Orbit",
        "theme_label": "Colors",
        "seconds_label": "Seconds",
        "seconds_smooth": "Smooth",
        "seconds_tick": "Tick",
        "seconds_off": "Off",
        "complication_left": "Left",
        "complication_right": "Right",
    }
    for tid, label, *_ in THEMES:
        items[f"theme_{tid}"] = label
    rows = "\n".join(f'    <string name="{k}">{escape(v)}</string>' for k, v in items.items())
    return f'<?xml version="1.0" encoding="utf-8"?>\n<resources>\n{rows}\n</resources>\n'


def watch_face_info_xml() -> str:
    return """<?xml version="1.0" encoding="utf-8"?>
<WatchFaceInfo>
  <Preview value="@drawable/preview"/>
  <Category value="CATEGORY_EMPTY"/>
  <AvailableInRetail value="false"/>
  <MultipleInstancesAllowed value="true"/>
  <Editable value="true"/>
</WatchFaceInfo>
"""


def manifest_xml() -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="{PACKAGE}"
    android:versionCode="{VERSION_CODE}"
    android:versionName="{VERSION_NAME}">

  <uses-sdk android:minSdkVersion="{MIN_SDK}" android:targetSdkVersion="{TARGET_SDK}"/>
  <uses-feature android:name="android.hardware.type.watch"/>

  <!-- Watch Face Format watch faces are resource-only: no code is allowed. -->
  <application
      android:label="@string/watch_face_name"
      android:icon="@drawable/ic_launcher"
      android:hasCode="false">
    <meta-data android:name="com.google.android.wearable.standalone" android:value="true"/>
    <meta-data android:name="author" android:value="{AUTHOR}"/>
    <meta-data android:name="license" android:value="{LICENSE} - {LICENSE_URL}"/>
    <property android:name="com.google.wear.watchface.format.version" android:value="{WFF_VERSION}"/>
  </application>
</manifest>
"""


def pretty(xml: str) -> str:
    """Indent for readability, but keep text runs (Font and everything inside it) on one line so
    no stray whitespace can end up in rendered strings."""
    from lxml import etree
    parser = etree.XMLParser(remove_blank_text=True, strip_cdata=False)
    root = etree.fromstring(xml.encode("utf-8"), parser)
    etree.indent(root, space="  ")
    for font in root.iter("Font"):
        if font.text is not None and not font.text.strip():
            font.text = None
        for d in font.iterdescendants():
            if d.text is not None and not d.text.strip():
                d.text = None
            if d.tail is not None and not d.tail.strip():
                d.tail = None
    comment = xml.split("-->")[0].split("<!--")[1]
    return ('<?xml version="1.0" encoding="utf-8"?>\n<!--' + comment + "-->\n"
            + etree.tostring(root, encoding="unicode") + "\n")


def write_all():
    os.makedirs(os.path.join(RES, "raw"), exist_ok=True)
    os.makedirs(os.path.join(RES, "values"), exist_ok=True)
    os.makedirs(os.path.join(RES, "xml"), exist_ok=True)
    with open(os.path.join(RES, "raw", "watchface.xml"), "w") as f:
        f.write(pretty(watchface_xml()))
    with open(os.path.join(RES, "values", "strings.xml"), "w") as f:
        f.write(strings_xml())
    with open(os.path.join(RES, "xml", "watch_face_info.xml"), "w") as f:
        f.write(watch_face_info_xml())
    with open(os.path.join(SRC, "AndroidManifest.xml"), "w") as f:
        f.write(manifest_xml())


if __name__ == "__main__":
    write_all()
    print("wrote", os.path.join(RES, "raw", "watchface.xml"))
