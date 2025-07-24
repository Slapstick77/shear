# Shear App - USB HID Card Access Server

A Flask-based server application that reads USB HID card reader data and controls access to shear equipment.

## Features

- **USB HID Card Reader Support**: Automatically detects and reads from USB HID card readers
- **LabJack U3 Integration**: Controls digital/analog I/O for shear locks, LEDs, sensors
- **Web Dashboard**: Real-time monitoring dashboard with status indicators and controls
- **Automatic Reconnection**: Handles device disconnections and automatically reconnects
- **Sensor Monitoring**: Temperature, shear position, motion detection
- **Access Control**: Automated shear unlock, status LEDs, security monitoring
- **Logging**: Comprehensive logging for debugging and monitoring
- **API Endpoints**: REST API for status checking and device control

## Installation

1. **Clone or create the project directory:**
   ```bash
   mkdir shear-app && cd shear-app
   ```

2. **Create and activate virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure the application:**
   ```bash
   cp .env.example .env
   # Edit .env with your settings
   ```

## Configuration

Edit the `.env` file with your specific settings:

### Required Settings
- `SECRET_KEY`: Flask secret key (generate a secure random key for production)

### Optional Settings
- `FLASK_HOST`: Server host (default: 0.0.0.0)
- `FLASK_PORT`: Server port (default: 5000)
- `ACCESS_POINT_NAME`: Identifier for this access point
- Card reader vendor/product IDs (if you have specific hardware)

## Usage

### Starting the Server

```bash
# Activate virtual environment
source venv/bin/activate

# Start the server
python app.py
```

The server will:
1. Start the Flask web server on the configured port
2. Begin monitoring for USB HID card readers
3. Automatically connect to detected card readers
4. Process card read events and control shear access

### Web Dashboard

Access the dashboard at `http://localhost:5000` to:
- Monitor card reader connection status
- Check LabJack U3 connection and I/O status
- View recent card access events
- Control shear lock and status LEDs
- View system logs

### API Endpoints

- `GET /api/status` - Get system status (card reader, LabJack U3)
- `GET /api/card-events` - Get recent card events
- `POST /api/labjack/control` - Control LabJack outputs (shear unlock, LEDs, relays)
- `GET /api/labjack/sensors` - Get current sensor readings

## Hardware Requirements

### LabJack U3
- LabJack U3 for I/O operations
- USB connection
- Digital I/O channels used:
  - FIO0: Door position sensor (input)
  - FIO1: Motion sensor (input)
  - FIO2-3: Additional digital inputs
  - FIO4: Door unlock relay (output)
  - FIO5: Green status LED (output)
  - FIO6: Red status LED (output)
  - FIO7: Blue status LED (output)
- Analog inputs:
  - AIN0: Temperature sensor (e.g., TMP36)
  - AIN1: Additional analog sensor
- Analog outputs:
  - DAC0: Analog control output (0-5V)
  - DAC1: Additional analog output (0-5V)

### Supported Card Readers
The application supports USB HID card readers. It will automatically detect devices that:
- Use the USB HID protocol
- Have product names containing keywords like "card", "reader", "rfid", or "proximity"
- Are from known card reader manufacturers

### Linux Permissions
On Linux, you may need to add udev rules for card reader access:

```bash
# Create udev rule file
sudo nano /etc/udev/rules.d/99-cardreader.rules

# Add rule (replace XXXX:YYYY with your device vendor:product ID)
SUBSYSTEM=="usb", ATTRS{idVendor}=="XXXX", ATTRS{idProduct}=="YYYY", MODE="0666"

# Reload udev rules
sudo udevadm control --reload-rules
sudo udevadm trigger
```

## Troubleshooting

### Card Reader Not Detected
1. Check if the device appears in `lsusb` output
2. Verify USB permissions (see Linux Permissions above)
3. Check the application logs for detection attempts
4. Try specifying vendor/product ID in `.env` if auto-detection fails

### LabJack U3 Issues
1. Verify LabJack U3 is connected via USB
2. Check that LabJackPython and Exodriver are installed
3. Run `lsusb` to verify the device is detected
4. Check I/O configuration and pin assignments

### General Issues
1. Check the application logs (`shear_app.log`)
2. Verify all dependencies are installed
3. Ensure virtual environment is activated
4. Check firewall settings for the Flask port

## Development

### Project Structure
```
shear-app/
├── app.py              # Main Flask application
├── card_reader.py      # USB HID card reader handler
├── labjack_u3.py       # LabJack U3 integration
├── card_manager.py     # Card access management
├── templates/
│   └── index.html     # Web dashboard
├── requirements.txt    # Python dependencies
├── .env.example       # Configuration template
└── README.md          # This file
```

### Adding New Card Reader Support
To add support for a specific card reader:
1. Identify the vendor/product ID using `lsusb`
2. Add the IDs to `.env`
3. Modify `parse_card_data()` in `card_reader.py` for device-specific data parsing

### Extending Functionality
To modify the application or add new features:
1. Add new API endpoints in `app.py`
2. Extend LabJack I/O functionality in `labjack_u3.py`
3. Update the dashboard HTML if needed

## Security Considerations

- Change the default `SECRET_KEY` in production
- Implement proper authentication for the web interface
- Consider network security for the Flask server
- Consider network security for the Flask server
- Regularly update dependencies

## License

[Add your license information here]

## Support

[Add support contact information here]
