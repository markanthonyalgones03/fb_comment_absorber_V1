#!/usr/bin/env bash
# Facebook Comment Collector • macOS Launcher
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "=========================================================="
echo "  Facebook Comment Collector • Starting on macOS"
echo "=========================================================="

# 1. Check Python 3
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python 3 is not installed or not in your PATH."
    echo "Please download and install Python 3 from: https://www.python.org/downloads/mac-osx/"
    echo "or run: brew install python python-tk"
    exit 1
fi

# 2. Check or create virtual environment
VENV_DIR="$DIR/.venv_mac"
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment in $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
fi

# 3. Activate virtual environment
source "$VENV_DIR/bin/activate"

# 4. Install / verify dependencies
echo "Verifying required packages..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# 5. Launch Application
echo "Launching Facebook Comment Collector..."
python3 run.py
