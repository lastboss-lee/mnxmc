#!/bin/bash

set -e

RPM_FILE="storcli2-008.0016.0000.0011-1.x86_64.rpm"

echo "===================================="
echo " StorCLI2 Install Script"
echo "===================================="

# root 확인
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root"
    exit 1
fi

echo "[1/6] Checking RPM file..."

if [ ! -f "$RPM_FILE" ]; then
    echo "ERROR: $RPM_FILE not found"
    exit 1
fi

echo "[2/6] Installing required packages..."

apt update -y
apt install -y alien

echo "[3/6] Converting RPM to DEB..."

DEB_FILE=$(alien -k "$RPM_FILE" | awk '{print $NF}')

echo "Generated DEB: $DEB_FILE"

echo "[4/6] Installing StorCLI2..."

dpkg -i "$DEB_FILE"

echo "[5/6] Creating symlink..."

STORCLI_PATH="/opt/MegaRAID/storcli2/storcli2"

if [ -f "$STORCLI_PATH" ]; then
    ln -sf "$STORCLI_PATH" /usr/local/sbin/storcli
    chmod +x /usr/local/sbin/storcli
else
    echo "ERROR: storcli2 binary not found at $STORCLI_PATH"
    exit 1
fi

echo "[6/6] Verifying installation..."

storcli show || true

echo "===================================="
echo " StorCLI installation completed"
echo "===================================="
echo "Command available:"
echo "  storcli show"
echo "  storcli /c0 show"
echo "===================================="
