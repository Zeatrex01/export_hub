"""Package Export Hub into a Blender-installable zip:  python package.py

The file list is a WHITELIST on purpose: a blacklist would quietly start shipping every new doc, board file or
scratch note that lands in this folder; a whitelist can only ship what is named here.

Blender needs the add-on folder at the root of the archive (export_hub/__init__.py, ...), and every entry name must
use forward slashes: an archive written with backslashes (Windows PowerShell 5.1's Compress-Archive does that)
installs on Windows but leaves loose files named "export_hub\\__init__.py" on macOS and Linux, where the add-on
never appears. The archive is therefore written with zipfile here and checked before the script reports success.
"""
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
PACKAGE = "export_hub"
FILES = ["__init__.py", "config.py", "operators.py", "properties.py", "templates.py", "ui.py", "updates.py",
         "validate.py"]
OPTIONAL = ["README.md", "LICENSE", "LICENSE.txt"]


def version():
    with open(os.path.join(ROOT, "__init__.py"), encoding="utf-8") as f:
        m = re.search(r'"version"\s*:\s*\((\d+)\s*,\s*(\d+)\s*,\s*(\d+)\)', f.read())
    if not m:
        sys.exit("ERROR: could not read the version tuple from __init__.py")
    return ".".join(m.groups())


def build(out_dir=None):
    """Writes <out_dir>/export_hub-<version>.zip; returns (path, entry names). Exits on a missing required file."""
    out_dir = out_dir or os.path.join(ROOT, "build")
    missing = [f for f in FILES if not os.path.isfile(os.path.join(ROOT, f))]
    if missing:
        sys.exit("ERROR: required file missing: " + ", ".join(missing))
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "%s-%s.zip" % (PACKAGE, version()))
    names = FILES + [f for f in OPTIONAL if os.path.isfile(os.path.join(ROOT, f))]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name in names:
            z.write(os.path.join(ROOT, name), PACKAGE + "/" + name)
    with zipfile.ZipFile(path) as z:
        entries = z.namelist()
    bad = [e for e in entries if "\\" in e or not e.startswith(PACKAGE + "/")]
    if bad:
        os.remove(path)
        sys.exit("ERROR: archive entries with a backslash or outside %s/: %s" % (PACKAGE, bad))
    return path, entries


if __name__ == "__main__":
    zip_path, entries = build()
    print("Packaging Export Hub %s" % version())
    for e in entries:
        print("    " + e)
    print("Done: " + zip_path)
    print("Install in Blender: Edit > Preferences > Add-ons > (dropdown) Install from Disk...")
