"""Report any Chinese text left in a plugin installation (or in this repo's plugin/ tree).

    python tools/verify_no_cjk.py <path-to-package>

Exit code 0 = clean, 1 = Chinese found (each hit printed as file:line).

Allow-listed on purpose: a few regexes match Chinese text produced by Blender itself
(Blender is localized, so its stderr can be Chinese regardless of this translation),
and a handful of docs may still be referenced by their original Chinese filenames.
"""
import os
import re
import sys

CJK = re.compile(r"[\u2e80-\u303f\u3400-\u4dbf\u4e00-\u9fff\uff00-\uffef]")

SKIP_DIRS = {"__pycache__", "node_modules", ".git", "tests"}
SKIP_EXT = {".png", ".jpg", ".jpeg", ".blend", ".glb", ".gltf", ".zip", ".exe", ".dll", ".pyc", ".mp4", ".map"}

# files where Chinese is intentional or out of scope
ALLOW_FILES = {
    # regexes matching Chinese text emitted by Blender itself (Blender is localized)
    "lib/runtime/core/errors.js",
    # npm metadata (description / a comment field) — never shown in tool interaction, and shipping a
    # rewritten package.json would overwrite upstream version metadata on the next plugin update
    "package.json",
}


def main():
    try:  # Windows consoles are often cp1251/cp866; never crash on the very text we report
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    total = 0
    files = 0
    for dirpath, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in names:
            if os.path.splitext(name)[1].lower() in SKIP_EXT:
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root).replace("\\", "/")
            if rel in ALLOW_FILES:
                continue
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    lines = fh.readlines()
            except (UnicodeDecodeError, OSError):
                continue
            for i, line in enumerate(lines, 1):
                if CJK.search(line):
                    total += len(CJK.findall(line))
                    files += 1
                    print(f"{rel}:{i}: {line.strip()[:140]}")
    print(f"\n{files} line(s) with Chinese, {total} character(s)")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
