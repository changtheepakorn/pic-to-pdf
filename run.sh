#!/usr/bin/env bash
# ไม่รกจอ Pic to PDF by Chang - Launcher for macOS & Linux

# Move to the script's directory
cd "$(dirname "$0")"

echo "========================================================"
echo "         ไม่รกจอ Pic to PDF by Chang (macOS/Linux)"
echo "========================================================"
echo "Starting server..."
echo ""

# Check for uv
if command -v uv &> /dev/null; then
    echo "[OK] Using uv..."
    uv run python app.py
elif [ -f "$HOME/.local/bin/uv" ]; then
    echo "[OK] Using uv from ~/.local/bin..."
    "$HOME/.local/bin/uv" run python app.py
elif [ -f ".venv/bin/python" ]; then
    echo "[OK] Using virtual environment python..."
    .venv/bin/python app.py
elif command -v python3 &> /dev/null; then
    echo "[OK] Using system python3..."
    python3 app.py
else
    echo "[ERROR] Python 3 or uv was not found."
    echo "Please install uv: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi
