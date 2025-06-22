#!/bin/bash

echo "🚀 Starting TokenBot..."

# Kill any existing instances
echo "🛑 Stopping existing instances..."
pkill -f "python.*main.py" 2>/dev/null || true
sleep 2

# Check if any instances are still running
if pgrep -f "python.*main.py" > /dev/null; then
    echo "⚠️  Force killing remaining instances..."
    pkill -9 -f "python.*main.py" 2>/dev/null || true
    sleep 2
fi

# Start fresh instance
echo "✅ Starting fresh bot instance..."
python3 main.py

echo "🏁 Bot stopped."
