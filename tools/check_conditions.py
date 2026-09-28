"""Checks that no <Condition> in a watchface.xml can have two <Compare> branches true at once.

The Watch Face Format docs say a Compare's tree is shown when its expression is true and the
Default when none is "activated"; they do not promise that the first true Compare wins. A face
that relies on first-match ordering can show the wrong branch (or the Default) on a real watch.
This brute-forces every minute of a week, 12h/24h, and a spread of battery / weather / heart-rate
/ complication states, and reports any Condition where more than one Compare is true.

    python3 check_conditions.py path/to/watchface.xml
"""
import datetime as dt
import itertools
import os
import sys

from lxml import etree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wffrender import Env, truthy  # noqa: E402

DATA_VARIANTS = [
    {"BATTERY_PERCENT": 76, "BATTERY_CHARGING_STATUS": False, "BATTERY_IS_LOW": False,
     "HEART_RATE": 72, "WEATHER.IS_AVAILABLE": True, "WEATHER.UV_INDEX": uv,
     "STEP_COUNT": 6832, "STEP_GOAL": 10000, "STEP_PERCENT": 68}
    for uv in range(0, 13)
] + [
    {"BATTERY_PERCENT": 12, "BATTERY_CHARGING_STATUS": False, "BATTERY_IS_LOW": True, "HEART_RATE": 0,
     "WEATHER.IS_AVAILABLE": False, "WEATHER.UV_INDEX": 0, "STEP_COUNT": 0, "STEP_GOAL": 10000, "STEP_PERCENT": 0},
    {"BATTERY_PERCENT": 40, "BATTERY_CHARGING_STATUS": True, "BATTERY_IS_LOW": False, "HEART_RATE": 130,
     "WEATHER.IS_AVAILABLE": True, "WEATHER.UV_INDEX": 11, "STEP_COUNT": 15000, "STEP_GOAL": 10000,
     "STEP_PERCENT": 100},
]
ICON = object()  # any non-null image stands in for a complication icon
COMPLICATION_VARIANTS = [
    {k: v for k, v in zip(("MONOCHROMATIC_IMAGE", "TEXT", "TITLE"), combo)}
    for combo in itertools.product((None, ICON), (None, "6,832"), (None, "BPM"))
]


def conditions(root):
    for cond in root.iter("Condition"):
        exprs = {e.get("name"): (e.text or "") for e in cond.find("Expressions")}
        compares = [c.get("expression") for c in cond.findall("Compare")]
        in_complication = any(a.tag == "Complication" for a in cond.iterancestors())
        yield cond.sourceline, exprs, compares, in_complication


def main(path):
    root = etree.parse(path).getroot()
    week = [dt.datetime(2026, 9, 27) + dt.timedelta(days=d) for d in range(7)]  # Sun..Sat
    minutes = range(0, 24 * 60)
    problems = 0
    total = 0
    for line, exprs, compares, in_comp in conditions(root):
        total += 1
        if len(compares) < 2:
            continue
        worst = None
        comp_variants = COMPLICATION_VARIANTS if in_comp else [None]
        for day in week:
            for m in minutes:
                when = day + dt.timedelta(minutes=m)
                for is24 in (False, True):
                    for data in DATA_VARIANTS if m % 60 == 25 else DATA_VARIANTS[:1]:
                        for comp in comp_variants:
                            env = Env(dt=when, is24h=is24, extra=dict(data), complication=comp)
                            hits = [n for n in compares if truthy(env.eval(exprs[n]))]
                            if len(hits) > 1:
                                worst = (when, is24, comp, hits)
                                break
                        if worst:
                            break
                    if worst:
                        break
                if worst:
                    break
            if worst:
                break
        if worst:
            problems += 1
            when, is24, comp, hits = worst
            desc = when.strftime("%a %H:%M") + (" 24h" if is24 else " 12h")
            if comp is not None:
                desc += " complication=" + ",".join(k for k, v in comp.items() if v is not None)
            print(f"line {line}: {len(hits)} branches true at once ({desc}): {', '.join(hits)}")
    print(f"{total} Condition elements checked, {problems} with overlapping branches")
    return problems


if __name__ == "__main__":
    sys.exit(1 if main(sys.argv[1]) else 0)
