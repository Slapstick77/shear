#!/bin/bash

# Shear App Setup Script

echo "🔐 Shear App - Setup Script"
echo "Setting up USB HID Card Reader + LabJack T7 Access Control System"
echo ""

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3.8 or later."
    exit 1
fi

echo "✅ Python 3 found: $(python3 --version)"

# Check if pip is installed
if ! command -v pip3 &> /dev/null; then
    echo "❌ pip3 is not installed. Please install pip3."
    exit 1
fi

echo "✅ pip3 found"

# Install system dependencies
echo ""
echo "📦 Installing system dependencies..."

# Check if we're on a Debian/Ubuntu system
if command -v apt &> /dev/null; then
    echo "Detected Debian/Ubuntu system"
    
    # Update package list
    sudo apt update
    
    # Install Python venv support
    sudo apt install -y python3-venv python3-dev
    
    # Install USB development libraries
    sudo apt install -y libusb-1.0-0-dev libudev-dev
    
    # Install LabJack dependencies for U3
    echo "Installing LabJack U3 dependencies..."
    
    # Install libusb for LabJack U3
    sudo apt install -y libusb-1.0-0-dev
    
    echo "LabJack U3 will use the LabJackPython library (installed via pip)"
    
elif command -v yum &> /dev/null; then
    echo "Detected Red Hat/CentOS system"
    sudo yum install -y python3-devel libusb1-devel systemd-devel
else
    echo "⚠️  Unknown Linux distribution. You may need to install dependencies manually:"
    echo "   - Python 3 development headers"
    echo "   - libusb development libraries"
    echo "   - LabJack U3 Python library from https://labjack.com/support/software/examples/ud/labjackpython"
fi

# Create virtual environment
echo ""
echo "🐍 Creating Python virtual environment..."
if [ -d "venv" ]; then
    echo "Virtual environment already exists"
else
    python3 -m venv venv
    echo "Virtual environment created"
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install Python dependencies
echo ""
echo "📦 Installing Python dependencies..."
pip install -r requirements.txt

# Create configuration file
echo ""
echo "⚙️  Setting up configuration..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "Created .env configuration file from template"
    echo ""
    echo "⚠️  IMPORTANT: Please edit the .env file with your settings:"
    echo "   - Set your POWERAPP_WEBHOOK_URL"
    echo "   - Change the SECRET_KEY for production use"
    echo "   - Configure other settings as needed"
else
    echo ".env file already exists"
fi

# Set up udev rules for USB devices
echo ""
echo "🔌 Setting up USB device permissions..."

# Create udev rules for common card readers and LabJack devices
sudo tee /etc/udev/rules.d/99-shear-app.rules > /dev/null << 'EOF'
# LabJack devices (U3)
SUBSYSTEM=="usb", ATTRS{idVendor}=="0cd5", ATTRS{idProduct}=="0009", MODE="0666", GROUP="plugdev"

# Common HID card readers
SUBSYSTEM=="usb", ATTRS{idVendor}=="ffff", MODE="0666", GROUP="plugdev"
SUBSYSTEM=="usb", ATTRS{idVendor}=="08f2", MODE="0666", GROUP="plugdev"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0c27", MODE="0666", GROUP="plugdev"

# Generic HID devices (be careful with this rule)
KERNEL=="hidraw*", ATTRS{idVendor}=="*", MODE="0666", GROUP="plugdev"
EOF

# Reload udev rules
sudo udevadm control --reload-rules
sudo udevadm trigger

echo "USB device permissions configured"

# Add user to plugdev group
if ! groups $USER | grep -q plugdev; then
    echo "Adding user to plugdev group..."
    sudo usermod -a -G plugdev $USER
    echo "⚠️  You may need to log out and back in for group changes to take effect"
fi

# Make start script executable
chmod +x start.sh

echo ""
echo "✅ Setup complete!"
echo ""
echo "📋 Next steps:"
echo "1. Edit the .env file with your configuration"
echo "2. Connect your USB HID card reader"
echo "2. Connect your LabJack U3 via USB"
echo "4. Run: ./start.sh"
echo ""
echo "🌐 The web dashboard will be available at: http://localhost:5000"
echo ""
echo "📖 For more information, see README.md"
