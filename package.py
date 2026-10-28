"""Package Export Hub for installation:  python package.py

Writes two archives to build/:

* export_hub-<version>.zip — the classic add-on zip (Edit > Preferences > Add-ons >
  Install from Disk...). Works in every supported Blender, 3.6 and newer, and is the one to
  use when upgrading an install of 1.7 or earlier: the module stays "export_hub", so saved
  projects, presets and history carry over.
* export_hub-<version>-extension.zip — the Blender 4.2+ extension package (blender_manifest.toml
  at the root). Installed this way the add-on runs as bl_ext.<repository>.export_hub, which
  Blender treats as a different add-on: export the config to JSON first when switching.

The file list is a WHITELIST on purpose: a blacklist would quietly start shipping every new doc, board file or
scratch note that lands in this folder; a whitelist can only ship what is named here.

Every entry name must use forward slashes: an archive written with backslashes (Windows PowerShell 5.1's
Compress-Archive does that) installs on Windows but leaves loose files named "export_hub\\__init__.py" on macOS and
Linux, where the add-on never appears. The archives are therefore written with zipfile here and checked before the
script reports success.
"""
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
PACKAGE = "export_hub"
MANIFEST = "blender_manifest.toml"
FILES = ["__init__.py", "config.py", "operators.py", "properties.py", "templates.py", "ui.py", "updates.py",
         "validate.py"]
OPTIONAL = ["README.md", "LICENSE", "LICENSE.txt"]


def version():
    """The version in bl_info, after checking blender_manifest.toml says the same."""
    with open(os.path.join(ROOT, "__init__.py"), encoding="utf-8") as f:
        m = re.search(r'"version"\s*:\s*\((\d+)\s*,\s*(\d+)\s*,\s*(\d+)\)', f.read())
    if not m:
        sys.exit("ERROR: could not read the version tuple from __init__.py")
    found = ".".join(m.groups())
    with open(os.path.join(ROOT, MANIFEST), encoding="utf-8") as f:
        m = re.search(r'^version\s*=\s*"([^"]+)"', f.read(), re.MULTILINE)
    if not m or m.group(1) != found:
        sys.exit("ERROR: %s says version %s but bl_info says %s"
                 % (MANIFEST, m.group(1) if m else "nothing", found))
    return found


def _write(path, names, prefix):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name in names:
            z.write(os.path.join(ROOT, name), prefix + name)
    with zipfile.ZipFile(path) as z:
        entries = z.namelist()
    bad = [e for e in entries if "\\" in e or not e.startswith(prefix)]
    if bad:
        os.remove(path)
        sys.exit("ERROR: archive entries with a backslash or outside %s: %s" % (prefix or "the root", bad))
    return entries


def build(out_dir=None):
    """Writes <out_dir>/export_hub-<version>.zip; returns (path, entry names). Exits on a missing required file."""
    out_dir = out_dir or os.path.join(ROOT, "build")
    missing = [f for f in FILES + [MANIFEST] if not os.path.isfile(os.path.join(ROOT, f))]
    if missing:
        sys.exit("ERROR: required file missing: " + ", ".join(missing))
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "%s-%s.zip" % (PACKAGE, version()))
    names = FILES + [f for f in OPTIONAL if os.path.isfile(os.path.join(ROOT, f))]
    # No manifest in the classic zip: Blender 4.2+ would install it as an extension, under a
    # different module name, and an upgrade from 1.7 would lose its saved projects.
    return path, _write(path, names, PACKAGE + "/")


def build_extension(out_dir=None):
    """Writes <out_dir>/export_hub-<version>-extension.zip; returns (path, entry names)."""
    out_dir = out_dir or os.path.join(ROOT, "build")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "%s-%s-extension.zip" % (PACKAGE, version()))
    names = [MANIFEST] + FILES + [f for f in OPTIONAL if os.path.isfile(os.path.join(ROOT, f))]
    return path, _write(path, names, "")


if __name__ == "__main__":
    print("Packaging Export Hub %s" % version())
    for builder in (build, build_extension):
        zip_path, entries = builder()
        for e in entries:
            print("    " + e)
        print("Done: " + zip_path)
    print("Install in Blender: Edit > Preferences > Add-ons > (dropdown) Install from Disk...")
