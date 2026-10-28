#!/usr/bin/env bash
# OM Search Engine - Linux / macOS Quick Setup Script

set -e

echo "================================================================================"
echo "                     OM SEARCH ENGINE — UNIX SETUP WIZARD"
echo "================================================================================"
echo ""

# Check for Python 3
if command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_CMD="python"
else
    echo "[!] Python is not installed. Please install Python 3.10+."
    exit 1
fi

# Run universal setup wizard
$PYTHON_CMD setup.py "$@"
