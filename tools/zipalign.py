"""Minimal zipalign: rewrites a zip so every uncompressed (STORED) entry's data starts on a
4-byte boundary (what `zipalign -p 4` does for resource-only APKs), or checks that it does.

    python3 zipalign.py in.apk out.apk
    python3 zipalign.py --check file.apk
"""
import struct
import sys
import zipfile

ALIGN = 4


def data_offsets(path):
    """Yield (name, compress_type, data_offset) for every entry, read from local headers."""
    with zipfile.ZipFile(path) as z, open(path, "rb") as f:
        for info in z.infolist():
            f.seek(info.header_offset)
            hdr = f.read(30)
            sig, _, _, _, _, _, _, _, _, name_len, extra_len = struct.unpack("<IHHHHHIIIHH", hdr)
            assert sig == 0x04034B50, "bad local header"
            yield info.filename, info.compress_type, info.header_offset + 30 + name_len + extra_len


def check(path):
    bad = [(n, off) for n, ct, off in data_offsets(path) if ct == zipfile.ZIP_STORED and off % ALIGN]
    for n, off in bad:
        print(f"  misaligned: {n} @ {off}")
    stored = sum(1 for _, ct, _ in data_offsets(path) if ct == zipfile.ZIP_STORED)
    print(f"alignment: {'OK' if not bad else 'FAILED'} ({stored} stored entries checked, {ALIGN}-byte)")
    return not bad


def align(src, dst):
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            new = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            new.compress_type = info.compress_type
            new.external_attr = info.external_attr
            new.create_system = info.create_system
            extra = b""
            if info.compress_type == zipfile.ZIP_STORED:
                offset = zout.fp.tell()
                base = offset + 30 + len(info.filename.encode("utf-8"))
                pad = (ALIGN - (base + 6) % ALIGN) % ALIGN
                # 0xD935 is the Android alignment extra field: uint16 alignment + padding
                extra = struct.pack("<HHH", 0xD935, 2 + pad, ALIGN) + b"\0" * pad
            new.extra = extra
            zout.writestr(new, data)
    return check(dst)


if __name__ == "__main__":
    if sys.argv[1] == "--check":
        sys.exit(0 if check(sys.argv[2]) else 1)
    sys.exit(0 if align(sys.argv[1], sys.argv[2]) else 1)
