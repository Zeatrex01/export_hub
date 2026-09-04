#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Package Export Hub into a Blender-installable zip (Linux/macOS).
#
# A POSIX counterpart to package.bat. The file list below is a WHITELIST on
# purpose: a blacklist would quietly start shipping every new note or scratch
# file that lands in this folder, while a whitelist can only ship what is named
# here.
#
# Blender needs the add-on package folder at the root of the archive, so the
# files are staged into build/export_hub/ first and that folder is zipped --
# zipping the loose .py files would produce an archive Blender refuses.
# ---------------------------------------------------------------------------
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${ROOT}/build"
STAGE="${OUT}/export_hub"

# Files that make up the add-on. Add here when a new module joins the package.
FILES=(__init__.py config.py operators.py properties.py templates.py ui.py updates.py validate.py)
# Shipped only if present.
OPTIONAL=(README.md LICENSE LICENSE.txt)

echo
echo " Packaging Export Hub"
echo " --------------------"

# --- version straight from bl_info, so the zip name can never drift from it
VERSION="$(python3 - "${ROOT}/__init__.py" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
m = re.search(r'"version"\s*:\s*\((\d+)\s*,\s*(\d+)\s*,\s*(\d+)\)', text)
print("%s.%s.%s" % m.groups() if m else "unknown")
PY
)"

if [ "${VERSION}" = "unknown" ]; then
    echo " ERROR: could not read the version tuple from __init__.py" >&2
    exit 1
fi
echo " Version: ${VERSION}"

ZIP="${OUT}/export_hub-${VERSION}.zip"

# --- clean previous build so nothing stale survives into the archive
rm -rf "${STAGE}"
rm -f "${ZIP}"
mkdir -p "${STAGE}"

# --- required files: a missing one is a build failure, not a warning
for f in "${FILES[@]}"; do
    if [ ! -f "${ROOT}/${f}" ]; then
        echo " ERROR: required file missing: ${f}" >&2
        rm -rf "${STAGE}"
        exit 1
    fi
    cp "${ROOT}/${f}" "${STAGE}/"
    echo "   + ${f}"
done

for f in "${OPTIONAL[@]}"; do
    if [ -f "${ROOT}/${f}" ]; then
        cp "${ROOT}/${f}" "${STAGE}/"
        echo "   + ${f}"
    fi
done

# --- zip the staged folder, not its contents, so export_hub/ is the archive root
(cd "${OUT}" && zip -r -q "${ZIP}" "export_hub")

rm -rf "${STAGE}"

echo
echo " Archive contents:"
unzip -Z1 "${ZIP}" | sed 's/^/    /'

echo
echo " Done: ${ZIP}"
echo " Install in Blender via Edit > Preferences > Add-ons > Install..."
