#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
V86DIR="$SCRIPT_DIR/v86"
BUILD_DIR="$V86DIR/buildv86vm"
V86FILES="$V86DIR/v86files"
OUTDIR="$SCRIPT_DIR/output"
ROOTFS_TAR="$SCRIPT_DIR/rootfs-v86.tar"

RED=$(tput setaf 1)
GREEN=$(tput setaf 2)
YELLOW=$(tput setaf 3)
RESET=$(tput sgr0)

# only after tput
set -euo pipefail

echo "${GREEN}packaging v86 build${RESET}"

if [[ ! -f "$ROOTFS_TAR" ]]; then
    echo "${RED}[ERR]${RESET} rootfs-v86.tar not found. Run mkmelinux.sh TYPE=V86 first." >&2
    exit 1
fi

echo "${GREEN}[INFO]${RESET} Cleaning old output files..."
rm -rf "$OUTDIR"
mkdir -p "$OUTDIR/rootfs-flat"

echo "${GREEN}[1/5]${RESET} Generating filesystem JSON manifest..."
python3 "$BUILD_DIR/fs2json.py" --zstd --out "$OUTDIR/rootfs-fs.json" "$ROOTFS_TAR"

echo "${GREEN}[2/5]${RESET} Copying files to content-addressed store (zstd compressed)..."
python3 "$BUILD_DIR/copy-to-sha256.py" --zstd "$ROOTFS_TAR" "$OUTDIR/rootfs-flat"

echo "${GREEN}[3/5]${RESET} Copying v86 runtime files..."
cp "$V86FILES/libv86.js"   "$OUTDIR/"
cp "$V86FILES/libv86.mjs"  "$OUTDIR/"
cp "$V86FILES/v86.wasm"    "$OUTDIR/"
cp "$V86FILES/seabios.bin" "$OUTDIR/"
cp "$V86FILES/vgabios.bin" "$OUTDIR/"

echo "${GREEN}[4/5]${RESET} Generating save state (booting VM - this takes a minute or two)..."
node "$BUILD_DIR/build-state.js" "$OUTDIR"

echo "${GREEN}[5/5]${RESET} Writing index.html..."
HOSTNAME=$(grep -oP 'GENERATE_HOSTNAME=\K\S+' "$SCRIPT_DIR/arguments.txt" 2>/dev/null || echo "mylinux")
sed "s/{{HOSTNAME}}/$HOSTNAME/g" "$BUILD_DIR/index.html.template" > "$OUTDIR/index.html"

echo ""
echo "${GREEN}[INFO]${RESET} Build completed."
echo "Output directory: $OUTDIR"
echo ""
echo "To test locally, serve the output directory over HTTP:"
echo "  python3 -m http.server --directory $OUTDIR 8080"
echo "Then open: http://localhost:8080"
