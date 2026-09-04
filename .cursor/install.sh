#!/usr/bin/env bash
#
# Cloud Agent install step for the Export Hub Blender add-on.
#
# The add-on is pure Python that imports `bpy`, so the only real dependency of
# the development experience is Blender itself. This script downloads a pinned
# portable Blender build, installs the shared libraries the headless build needs
# to start, and links the executable onto PATH. It is idempotent: an already
# present Blender is reused and only the symlink is refreshed.

set -euo pipefail

# The add-on targets Blender 3.6 as a minimum and is compatible up to the 4.5
# LTS line. Pin to the top of that supported range so the environment exercises
# what current users run; override with BLENDER_VERSION to test another build
# (for example the 3.6 lower bound). BLENDER_SERIES is derived as major.minor.
BLENDER_VERSION="${BLENDER_VERSION:-4.5.1}"
BLENDER_SERIES="${BLENDER_SERIES:-$(printf '%s' "${BLENDER_VERSION}" | cut -d. -f1,2)}"
BLENDER_PKG="blender-${BLENDER_VERSION}-linux-x64"
BLENDER_TARBALL="${BLENDER_PKG}.tar.xz"
BLENDER_URL="https://download.blender.org/release/Blender${BLENDER_SERIES}/${BLENDER_TARBALL}"

BLENDER_HOME="${HOME}/${BLENDER_PKG}"
BIN_DIR="${HOME}/.local/bin"

echo "==> Installing system libraries required by headless Blender"
if command -v sudo >/dev/null 2>&1; then
    sudo apt-get update -y
    sudo apt-get install -y --no-install-recommends \
        xz-utils \
        zip \
        unzip \
        libgl1 \
        libglx-mesa0 \
        libxi6 \
        libxxf86vm1 \
        libxfixes3 \
        libxrender1 \
        libxkbcommon0 \
        libsm6 \
        libxext6
else
    echo "    sudo unavailable; assuming the base image already has the libraries" >&2
fi

mkdir -p "${BIN_DIR}"

if [ ! -x "${BLENDER_HOME}/blender" ]; then
    echo "==> Downloading ${BLENDER_TARBALL}"
    tmp_dir="$(mktemp -d)"
    trap 'rm -rf "${tmp_dir}"' EXIT
    curl -fSL "${BLENDER_URL}" -o "${tmp_dir}/${BLENDER_TARBALL}"
    echo "==> Extracting Blender into ${HOME}"
    tar -xJf "${tmp_dir}/${BLENDER_TARBALL}" -C "${HOME}"
    rm -rf "${tmp_dir}"
    trap - EXIT
else
    echo "==> Reusing existing Blender at ${BLENDER_HOME}"
fi

ln -sfn "${BLENDER_HOME}/blender" "${BIN_DIR}/blender"

# Also link into a directory that is on PATH for every shell (login or not) so a
# bare `blender` works. /usr/local/bin is on the default PATH; fall back quietly
# to ~/.local/bin only when it cannot be written.
if command -v sudo >/dev/null 2>&1 && [ -d /usr/local/bin ]; then
    sudo ln -sfn "${BLENDER_HOME}/blender" /usr/local/bin/blender
fi

echo "==> Blender version:"
"${BLENDER_HOME}/blender" --background --version | head -n 1

echo "==> Install complete. 'blender' resolves to ${BLENDER_HOME}/blender"
