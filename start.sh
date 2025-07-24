#!/bin/bash

# Start Shear App server
echo "🔐 Starting Shear App server"

# Navigate to the correct directory
cd "$(dirname "$0")"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "❌ Virtual environment not found. Please run setup first."
    echo "Run: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# Check if port 5000 is in use
if lsof -i:5000 &>/dev/null; then
    echo "❌ Port 5000 is already in use. Please stop the process using it or use a different port."
    exit 1
fi

# Kill any existing Flask processes
echo "🔄 Stopping any existing processes..."
pkill -f "python.*app.py" 2>/dev/null
sleep 2

# Check LabJack U3 connection
if ! lsusb | grep -q "LabJack"; then
    echo "⚠️  LabJack U3 device not found. Please connect the device."
fi

# Check card reader connection
if ! lsusb | grep -q "Card Reader"; then
    echo "⚠️  No card reader found. Please connect the card reader."
fi

# Start Flask app
echo "🚀 Starting Flask app..."
source venv/bin/activate
python app.py

echo "🎉 Shear App started!"
echo ""
echo "📍 Local URL: http://localhost:5000"
echo ""
echo "Press Ctrl+C to stop the server"
