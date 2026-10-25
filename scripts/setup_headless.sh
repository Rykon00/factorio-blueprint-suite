#!/usr/bin/env bash
# Download the Factorio headless server (free, no login needed) into ./.factorio
# Usage: scripts/setup_headless.sh [version]   (default: stable)
set -euo pipefail
VERSION="${1:-stable}"
DEST="${FBS_HEADLESS_DIR:-.factorio-install}"
mkdir -p "$DEST"
URL="https://factorio.com/get-download/${VERSION}/headless/linux64"
echo "Downloading $URL"
curl -fSL "$URL" -o "$DEST/headless.tar.xz"
tar -xJf "$DEST/headless.tar.xz" -C "$DEST"
rm "$DEST/headless.tar.xz"
ln -sfn "$DEST/factorio" .factorio
./.factorio/bin/x64/factorio --version | head -1
echo "Headless installed. fbs finds it via ./.factorio (or set FBS_FACTORIO)."
