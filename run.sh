#!/bin/bash
# ========================================
#  Video Compressor Pro++ - Local Runner
#  Runs on your Mac with Cloudflare tunnel
#  Auto-installs everything if needed
# ========================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "🎬 Video Compressor Pro++"
echo "========================="
echo ""

# ---- Check Python ----
if ! command -v python3 &>/dev/null; then
    echo "❌ Python3 not found. Install from https://python.org"
    exit 1
fi

# ---- Check ffmpeg ----
if ! command -v ffmpeg &>/dev/null; then
    echo "❌ ffmpeg not found. Install with: brew install ffmpeg"
    echo "   (or: sudo apt install ffmpeg on Linux)"
    exit 1
fi

echo "✅ Python3: $(python3 --version)"
echo "✅ ffmpeg:  $(ffmpeg -version 2>&1 | head -1 | cut -d' ' -f3)"

# ---- Virtual Env ----
if [ ! -d "venv" ]; then
    echo ""
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate

# ---- Install Dependencies ----
echo ""
echo "📦 Installing Python packages..."
pip install -q flask gunicorn 2>&1 | tail -1

# ---- Install Cloudflared (if needed) ----
if ! command -v cloudflared &>/dev/null; then
    echo ""
    echo "📦 Installing cloudflared..."
    if [[ "$(uname)" == "Darwin" ]]; then
        brew install cloudflare/cloudflare/cloudflared 2>/dev/null || {
            echo "⚠️  Install cloudflared manually: brew install cloudflare/cloudflare/cloudflared"
            echo "   Or download from: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/"
            exit 1
        }
    elif [[ "$(uname)" == "Linux" ]]; then
        curl -sL 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64' -o /tmp/cloudflared
        chmod +x /tmp/cloudflared
        CLOUDFLARED="/tmp/cloudflared"
    fi
fi

CLOUDFLARED="${CLOUDFLARED:-cloudflared}"
echo "✅ cloudflared: ready"

# ---- Start Flask ----
echo ""
echo "🚀 Starting Flask server on port 5000..."
python3 app.py &
FLASK_PID=$!

# Wait for Flask to be ready
echo -n "   Waiting for Flask..."
for i in $(seq 1 15); do
    if curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/ 2>/dev/null | grep -q 200; then
        echo " READY!"
        break
    fi
    echo -n "."
    sleep 1
done

# ---- Start Cloudflare Tunnel ----
echo ""
echo "🌐 Starting Cloudflare tunnel..."
$CLOUDFLARED tunnel --url http://localhost:5000 2>&1 &
CF_PID=$!

sleep 6

# Grab the tunnel URL
TUNNEL_URL=$(grep -o 'https://[a-z0-9.-]*\.trycloudflare\.com' /proc/$CF_PID/fd/1 2>/dev/null || \
             $CLOUDFLARED tunnel --url http://localhost:5000 2>&1 | grep -o 'https://[a-z0-9.-]*\.trycloudflare\.com' | head -1)

echo ""
echo "=========================================="
echo "  ✅ SERVER IS RUNNING!"
echo ""
echo "  🌐 Public URL: $TUNNEL_URL"
echo "  🏠 Local URL:  http://localhost:5000"
echo ""
echo "  Press Ctrl+C to stop"
echo "=========================================="

# Cleanup on exit
cleanup() {
    echo ""
    echo "🛑 Shutting down..."
    kill $FLASK_PID 2>/dev/null
    kill $CF_PID 2>/dev/null
    echo "Goodbye!"
}

trap cleanup EXIT

# Keep running
wait
