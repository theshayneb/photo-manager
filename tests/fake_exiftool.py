"""A stand-in for exiftool used by the tests.

Speaks the same -stay_open protocol as the real thing and keeps each file's
tags in a sidecar "<file>.fake.json", so the app can be exercised end to end
without ExifTool installed. It only understands the arguments the app sends.
"""

import json
import os
import sys

VALUE_OPTIONS = {"-charset", "-api", "-echo4", "-stay_open", "-@", "-common_args"}
TAG_MAP = {
    "XMP-dc:Subject": "XMP:Subject",
    "XMP-xmp:Label": "XMP:Label",
    "FileCreateDate": "File:FileCreateDate",
    "FileModifyDate": "File:FileModifyDate",
}
IGNORED = {"IPTC:CodedCharacterSet"}


def sidecar(path):
    return path + ".fake.json"


def load(path):
    try:
        with open(sidecar(path), encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return {}


def save(path, tags):
    with open(sidecar(path), "w", encoding="utf-8") as f:
        json.dump(tags, f)


def run(args, out, err):
    files, writes, echo = [], [], []
    i = 0
    while i < len(args):
        a = args[i]
        if a in VALUE_OPTIONS:
            if a == "-echo4":
                echo.append(args[i + 1])
            i += 2
            continue
        if a.startswith("-") and "=" in a:
            writes.append(a[1:])
        elif not a.startswith("-"):
            files.append(a)
        elif a == "-ver":
            out.write("13.00\n")
        i += 1
    if "-j" in args:
        result = []
        for f in files:
            tags = load(f)
            tags["SourceFile"] = f.replace("\\", "/")
            result.append(tags)
        out.write(json.dumps(result) + "\n")
    elif writes:
        for f in files:
            if not os.path.exists(f):
                err.write(f"Error: File not found - {f}\n")
                out.write("    0 image files updated\n    1 files weren't updated due to errors\n")
                continue
            tags = load(f)
            for w in writes:
                op = "+=" if "+=" in w else "-=" if "-=" in w else "="
                name, value = w.split(op, 1)
                if name in IGNORED:
                    continue
                if name == "AllDates":
                    for t in ("EXIF:DateTimeOriginal", "EXIF:CreateDate", "EXIF:ModifyDate"):
                        tags[t] = value
                    continue
                name = TAG_MAP.get(name, name)
                if op == "=":
                    if value:
                        tags[name] = value
                    else:
                        tags.pop(name, None)
                else:
                    current = tags.get(name, [])
                    current = current if isinstance(current, list) else [current]
                    if op == "+=":
                        current.append(value)
                    else:
                        current = [c for c in current if c != value]
                    if current:
                        tags[name] = current
                    else:
                        tags.pop(name, None)
            save(f, tags)
            out.write("    1 image files updated\n")
    for e in echo:
        err.write(e + "\n")


def main():
    argv = sys.argv[1:]
    common = argv[argv.index("-common_args") + 1 :] if "-common_args" in argv else []
    stdin = sys.stdin.buffer
    out, err = sys.stdout, sys.stderr
    args = []
    while True:
        line = stdin.readline()
        if not line:
            return
        line = line.decode("utf-8").rstrip("\r\n")
        if line.startswith("-execute"):
            run(args + common, out, err)
            out.write("{ready" + line[len("-execute"):] + "}\n")
            out.flush()
            err.flush()
            args = []
        elif args and args[-1] == "-stay_open" and line == "False":
            return
        else:
            args.append(line)


if __name__ == "__main__":
    main()
