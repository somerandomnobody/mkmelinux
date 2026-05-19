#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

RED=$(tput setaf 1 2>/dev/null || true)
GREEN=$(tput setaf 2 2>/dev/null || true)
YELLOW=$(tput setaf 3 2>/dev/null || true)
RESET=$(tput sgr0 2>/dev/null || true)

echo "${GREEN}=== mkmelinux host-setup ===${RESET}"

# Check KVM
if [ -c /dev/kvm ]; then
    echo "${GREEN}[ OK ]${RESET} KVM acceleration is available."
else
    echo "${YELLOW}[WARN]${RESET} KVM acceleration is not available — HARDDISK builds may be slow or fail."
fi

# Check Python 3
if ! command -v python3 &>/dev/null; then
    echo "${RED}[ERR]${RESET} python3 not found. Please install Python 3.8+ and re-run this script." >&2
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "${GREEN}[ OK ]${RESET} Found Python ${PYTHON_VERSION}"

# Check Podman
if ! command -v podman &>/dev/null; then
    echo "${YELLOW}[WARN]${RESET} podman not found. Builds will not work until Podman is installed."
    echo "       On Debian/Ubuntu:  sudo apt install podman"
    echo "       On Arch:           sudo pacman -S podman"
    echo "       On Fedora:         sudo dnf install podman"
else
    echo "${GREEN}[ OK ]${RESET} Found $(podman --version)"
fi

# Create venv if it doesn't exist
if [[ ! -d "$VENV_DIR" ]]; then
    echo "${GREEN}[...]${RESET} Creating virtual environment at ./venv ..."
    python3 -m venv "$VENV_DIR"
else
    echo "${GREEN}[ OK ]${RESET} Virtual environment already exists at ./venv"
fi

# Install/upgrade dependencies
echo "${GREEN}[...]${RESET} Installing dependencies (textual)..."
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet textual

echo "${GREEN}[ OK ]${RESET} Dependencies installed."
echo ""
echo "${GREEN}=== Launching distrobuilder ===${RESET}"
exec "$VENV_DIR/bin/python3" "$SCRIPT_DIR/distrobuilder.py"
