#!/usr/bin/env bash
# start.command – macOS launcher (double-click in Finder to run)

cd "$(dirname "$0")"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "   AI Video Agent"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── Find Python ───────────────────────────────────────────────────────────────
PYTHON=""
for candidate in \
    "$HOME/miniforge3/envs/equiAI-env/bin/python" \
    "$HOME/.conda/envs/equiAI-env/bin/python" \
    "/opt/homebrew/Caskroom/miniforge/base/envs/equiAI-env/bin/python" \
    "$(conda run -n equiAI-env which python 2>/dev/null)" \
    "python3" "python"; do
    if command -v "$candidate" &>/dev/null 2>&1 || [ -f "$candidate" ]; then
        PYTHON="$candidate"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "ERROR: Python not found. Install Python 3.10+ and try again."
    read -p "Press Enter to close…"
    exit 1
fi

echo "Python: $PYTHON"

# ── Install / update Python dependencies ─────────────────────────────────────
echo "Checking Python dependencies…"
"$PYTHON" -m pip install -q -r requirements.txt

# ── Launch Adobe Premiere Pro (if installed, not already running) ─────────────
if ! pgrep -x "Adobe Premiere Pro" > /dev/null 2>&1; then
    # Try to find any installed version
    PREMIERE_APP=$(ls -d /Applications/Adobe\ Premiere\ Pro*/Adobe\ Premiere\ Pro*.app 2>/dev/null | sort -r | head -1)
    if [ -n "$PREMIERE_APP" ]; then
        echo "Launching Adobe Premiere Pro…"
        open "$PREMIERE_APP"
    else
        echo "Adobe Premiere Pro not found – skipping (Premiere features won't be available)"
    fi
else
    echo "Adobe Premiere Pro already running"
fi

# ── Start server ──────────────────────────────────────────────────────────────
echo "Starting server on http://localhost:8000 …"
"$PYTHON" server.py &
SERVER_PID=$!

# Wait for server to be ready
for i in $(seq 1 20); do
    sleep 1
    if curl -s http://localhost:8000/api/status > /dev/null 2>&1; then
        break
    fi
done

# ── Open browser ──────────────────────────────────────────────────────────────
open "http://localhost:8000"

echo ""
echo "Server running (PID $SERVER_PID)."
echo "Blender runs headlessly when needed – no need to open it."
echo "Close this window to stop the server."
echo ""

wait $SERVER_PID
