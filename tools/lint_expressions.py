"""Checks every expression in a watchface.xml against the official WFF data-source and
function lists (the XSD validator checks structure, but not the names used inside
expressions). Also parses each expression to catch syntax errors."""
import os
import re
import sys

from lxml import etree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wffrender import tokenize  # noqa: E402

SPEC = os.environ.get("WFF_SPEC", "/home/claude/vendor/watchface/third_party/wff/specification/documents")

COMPLICATION_SOURCES = {
    "TEXT", "TITLE", "MONOCHROMATIC_IMAGE", "MONOCHROMATIC_IMAGE_AMBIENT", "SMALL_IMAGE", "SMALL_IMAGE_AMBIENT",
    "IMAGE_STYLE", "PHOTO_IMAGE", "RANGED_VALUE_MIN", "RANGED_VALUE_MAX", "RANGED_VALUE_VALUE",
    "RANGED_VALUE_COLORS", "RANGED_VALUE_COLORS_INTERPOLATE", "GOAL_PROGRESS_VALUE", "GOAL_PROGRESS_TARGET_VALUE",
    "GOAL_PROGRESS_COLORS", "GOAL_PROGRESS_COLORS_INTERPOLATE", "WEIGHTED_ELEMENTS_COLORS",
    "WEIGHTED_ELEMENTS_WEIGHTS", "WEIGHTED_ELEMENTS_BACKGROUND_COLOR",
}


REGISTRY = os.environ.get(
    "WFF_REGISTRY",
    "/home/claude/vendor/watchface/tools/dwf-validator/src/commonMain/kotlin/com/google/wear/watchface/"
    "validator/expression/VersionRegistry.kt")


def registry_lists(version):
    """Data sources and functions from Google's dwf-validator VersionRegistry (the XSD enumeration
    has typos such as WEATHER.WEATHER.UV_INDEX), filtered to those available in `version`."""
    text = open(REGISTRY).read()
    entries = re.findall(r'"([^"]+)" to VersionRange\((\d+)(?:,\s*(\d+))?\)', text)
    sources, functions = [], set()
    for name, lo, hi in entries:
        if int(lo) > version or (hi and int(hi) < version):
            continue
        if "{" in name and name.endswith("}") and name[:-1].rsplit("{", 1)[1].isdigit():
            functions.add(name.split("{")[0])
        else:
            sources.append(re.compile("^" + re.escape(name).replace(r"\{index\}", r"\d+") + "$"))
    return sources, functions


def spec_lists(version):
    if os.path.exists(REGISTRY):
        return registry_lists(version)
    base = os.path.join(SPEC, str(version), "common", "simpleTypes")
    if not os.path.isdir(base):
        base = os.path.join(SPEC, str(version), "common", "attributes")
    src = open(os.path.join(base, "sourceType.xsd")).read()
    fn = open(os.path.join(base, "arithmeticExpressionType.xsd")).read()
    sources = re.findall(r'<xs:enumeration value="([^"]+)"', src)
    patterns = [re.compile("^" + s.replace(".", r"\.").replace(r"\\.", r"\.") + "$") for s in sources]
    fn_block = fn.split('name="_functionType"')[1].split("</xs:simpleType>")[0]
    functions = {m.split("(")[0] for m in re.findall(r'<xs:enumeration value="([^"]+)"', fn_block)}
    return patterns, functions


def main(path, version):
    patterns, functions = spec_lists(version)
    root = etree.parse(path).getroot()
    color_configs, other_configs = {}, set()
    for c in root.find("UserConfigurations") if root.find("UserConfigurations") is not None else []:
        if c.tag == "ColorConfiguration":
            color_configs[c.get("id")] = min(len(o.get("colors").split()) for o in c)
        elif c.get("id"):
            other_configs.add(c.get("id"))

    expressions = []
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        for attr in ("value", "expression", "color", "tintColor", "resource", "backgroundColor"):
            v = el.get(attr)
            if v is None:
                continue
            if el.tag == "Compare" and attr == "expression":
                continue  # names an <Expression>, checked by the XSD keyref
            if el.tag in ("Metadata", "Preview", "Category") or (attr == "resource" and "[" not in v):
                continue
            if attr in ("color", "tintColor", "backgroundColor") and v.startswith("#"):
                continue
            if el.tag == "Variant" and el.get("target") in ("backgroundColor",) and v.startswith("#"):
                continue
            expressions.append((el.sourceline, el.tag, attr, v))
        if el.tag == "Expression":
            expressions.append((el.sourceline, "Expression", "text", el.text or ""))

    errors = 0
    used = set()
    for line, tag, attr, expr in expressions:
        try:
            toks = tokenize(expr)
        except Exception as e:  # noqa: BLE001
            print(f"line {line} <{tag} {attr}>: syntax: {e}")
            errors += 1
            continue
        for i, (kind, val) in enumerate(toks):
            if kind == "src":
                name = val[1:-1]
                used.add(name)
                if name.startswith("CONFIGURATION."):
                    parts = name.split(".")
                    if parts[1] in color_configs:
                        if len(parts) > 2 and int(parts[2]) >= color_configs[parts[1]]:
                            print(f"line {line}: {name}: colour index out of range")
                            errors += 1
                    elif parts[1] not in other_configs:
                        print(f"line {line}: {name}: unknown configuration")
                        errors += 1
                elif name.startswith("COMPLICATION."):
                    if name.split(".", 1)[1] not in COMPLICATION_SOURCES:
                        print(f"line {line}: {name}: unknown complication source")
                        errors += 1
                elif not any(p.match(name) for p in patterns):
                    print(f"line {line}: [{name}] is not a WFF v{version} data source")
                    errors += 1
            elif kind == "id" and val not in ("null", "true", "false", "TRUE", "FALSE"):
                nxt = toks[i + 1][1] if i + 1 < len(toks) else None
                if nxt != "(" or val not in functions:
                    print(f"line {line}: '{val}' is not a WFF v{version} function")
                    errors += 1
    print(f"{len(expressions)} expressions checked, {len(used)} distinct sources, {errors} problem(s)")
    return errors


if __name__ == "__main__":
    sys.exit(1 if main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 4) else 0)
