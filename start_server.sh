#!/bin/bash

# Start Shear App server
echo "🔐 Starting Shear App server"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "❌ Virtual environment not found. Please run setup first."
    echo "Run: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# Kill any existing Flask processes
echo "🔄 Stopping any existing processes..."
pkill -f "python.*app.py" 2>/dev/null
sleep 2

# Start Flask app
echo "🚀 Starting Flask app..."
source venv/bin/activate
python app.py

echo "🎉 Shear App started!"
echo ""
echo "📍 Local URL: http://localhost:5000"
echo ""
echo "Press Ctrl+C to stop the server"
