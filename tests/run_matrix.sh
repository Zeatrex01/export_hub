#!/usr/bin/env bash
#
# Run the Export Hub end-to-end suite against several Blender versions.
#
# The add-on supports Blender 3.6 (minimum) up to the 4.5 LTS line. This script
# verifies the suite against a list of versions, downloading any that are not
# already present next to the pinned install. Pass versions as arguments, or set
# BLENDER_VERSIONS; the default covers the 3.6 minimum, an intermediate LTS and
# the 4.5.1 ceiling.
#
#   tests/run_matrix.sh                 # default matrix
#   tests/run_matrix.sh 3.6.23 4.5.1    # explicit versions
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ "$#" -gt 0 ]; then
    VERSIONS=("$@")
else
    # Minimum (3.6), an intermediate LTS (4.2) and the 4.5.1 ceiling.
    read -r -a VERSIONS <<< "${BLENDER_VERSIONS:-3.6.23 4.2.23 4.5.1}"
fi

# Sets BLENDER_BIN to the executable for a version, downloading it if missing.
# Returns the path through a global rather than stdout so progress logging can go
# to the terminal without being captured into the path.
ensure_blender() {
    local version="$1"
    local series
    series="$(printf '%s' "${version}" | cut -d. -f1,2)"
    local home="${HOME}/blender-${version}-linux-x64"
    if [ ! -x "${home}/blender" ]; then
        local tarball="blender-${version}-linux-x64.tar.xz"
        local url="https://download.blender.org/release/Blender${series}/${tarball}"
        echo "==> Downloading Blender ${version}" >&2
        local tmp
        tmp="$(mktemp -d)"
        curl -fSL "${url}" -o "${tmp}/${tarball}"
        tar -xJf "${tmp}/${tarball}" -C "${HOME}"
        rm -rf "${tmp}"
    fi
    BLENDER_BIN="${home}/blender"
}

overall=0
declare -a RESULTS=()

for version in "${VERSIONS[@]}"; do
    ensure_blender "${version}"
    blender_bin="${BLENDER_BIN}"
    echo
    echo "############################################################"
    echo "# Blender ${version}"
    echo "############################################################"
    "${blender_bin}" --background --version | head -n 1
    if "${blender_bin}" --background --factory-startup \
        --python "${REPO_ROOT}/tests/test_export_hub.py"; then
        RESULTS+=("${version}: PASS")
    else
        RESULTS+=("${version}: FAIL")
        overall=1
    fi
done

echo
echo "==================== MATRIX RESULT ===================="
for line in "${RESULTS[@]}"; do
    echo "  ${line}"
done
echo "======================================================"
exit "${overall}"
