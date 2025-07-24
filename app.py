#!/usr/bin/env python3
"""
Shear App - USB HID Card Access Server
Handles card reader events and controls access to shear equipment
"""

from flask import Flask, request, jsonify, render_template
import threading
import requests
import json
import logging
from datetime import datetime
import os
from card_reader import CardReader
from labjack_u3 import LabJackU3
from card_manager import CardManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('shear_app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# Add datetime filter for Jinja2 templates
@app.template_filter('datetime')
def datetime_filter(timestamp):
    """Format datetime for template display"""
    if timestamp == 'now':
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    elif isinstance(timestamp, str):
        try:
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except:
            return timestamp
    return str(timestamp)

# Global instances
card_reader = None
labjack_u3 = None
card_manager = None

def initialize_components():
    """Initialize card reader and LabJack components"""
    global card_reader, labjack_u3, card_manager
    
    try:
        # Initialize card manager
        card_manager = CardManager()
        
        # Initialize card reader
        card_reader = CardReader(on_card_read=handle_card_read)
        
        # Initialize LabJack U3
        labjack_u3 = LabJackU3(on_input_change=handle_labjack_input_change)
        if labjack_u3:
            connection_success = labjack_u3.connect()
            if connection_success:
                logger.info("LabJack U3 connected successfully")
                # Start monitoring loop for FIO4 and FIO5 states
                threading.Thread(target=labjack_u3.monitor_inputs, daemon=True).start()
                logger.info("Started LabJack U3 input monitoring loop")
            else:
                logger.warning("LabJack U3 connection failed - device may not be connected or driver not installed")
        
        logger.info("Components initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize components: {e}")

def handle_card_read(card_data):
    """Handle card read event"""
    try:
        card_id = card_data.get('card_id', '').strip()
        logger.info(f"Card read: {card_id}")
        
        # Validate card using card manager
        validation_result = card_manager.validate_card(card_id) if card_manager else {
            'valid': False, 'access_granted': False, 'reason': 'Card manager not available'
        }
        
        # Check shear sensor and motion detection via LabJack
        shear_locked = labjack_u3.read_shear_sensor() if labjack_u3 and labjack_u3.is_connected() else True
        motion_detected = labjack_u3.read_motion_sensor() if labjack_u3 and labjack_u3.is_connected() else False
        temperature = labjack_u3.read_temperature_sensor() if labjack_u3 and labjack_u3.is_connected() else None
        
        # Control shear and LEDs based on access decision
        if validation_result['access_granted'] and labjack_u3 and labjack_u3.is_connected():
            # Grant access
            labjack_u3.trigger_shear_unlock(duration=3.0)  # Unlock for 3 seconds
            labjack_u3.set_status_led('green', True)  # Green LED on
            # Turn off green LED after 2 seconds
            threading.Timer(2.0, lambda: labjack_u3.set_status_led('green', False)).start()
            logger.info(f"Access GRANTED for card {card_id}: {validation_result['reason']}")
        else:
            # Deny access
            if labjack_u3 and labjack_u3.is_connected():
                labjack_u3.set_status_led('red', True)  # Red LED on
                # Turn off red LED after 1 second
                threading.Timer(1.0, lambda: labjack_u3.set_status_led('red', False)).start()
            logger.warning(f"Access DENIED for card {card_id}: {validation_result['reason']}")
        
    except Exception as e:
        logger.error(f"Error handling card read: {e}")

def handle_labjack_input_change(change_data):
    """Handle LabJack input changes"""
    try:
        logger.info(f"LabJack input change: {change_data}")
        
        # Add context for specific sensors
        if change_data['channel'] == 'FIO4':  # Shear sensor (U3 uses FIO4 for inputs)
            logger.info(f"Shear sensor change: {'locked' if change_data.get('state') else 'unlocked'}")
        elif change_data['channel'] == 'FIO5':  # Motion sensor
            logger.info(f"Motion sensor change: {'detected' if change_data.get('state') else 'clear'}")
        elif change_data['channel'] == 'AIN0':  # Temperature sensor
            logger.info(f"Temperature sensor change: {change_data.get('value')}°C")
        
    except Exception as e:
        logger.error(f"Error handling LabJack input change: {e}")

@app.route('/')
def index():
    """Main dashboard"""
    return render_template('index.html', 
                         reader_status=card_reader.is_connected() if card_reader else False,
                         labjack_status=labjack_u3.is_connected() if labjack_u3 else False)

@app.route('/api/status')
def api_status():
    """API endpoint to check system status"""
    status = {
        'timestamp': datetime.now().isoformat(),
        'card_reader': {
            'connected': card_reader.is_connected() if card_reader else False,
            'device_info': card_reader.get_device_info() if card_reader and card_reader.is_connected() else None
        },
        'labjack_u3': {
            'connected': labjack_u3.is_connected() if labjack_u3 else False,
            'device_info': labjack_u3.get_device_info() if labjack_u3 and labjack_u3.is_connected() else None,
            'all_states': labjack_u3.get_all_states() if labjack_u3 and labjack_u3.is_connected() else None
        }
    }
    return jsonify(status)

@app.route('/api/card-events', methods=['GET'])
def get_card_events():
    """Get recent card events (from log or database)"""
    # This would typically read from a database or log file
    # For now, return mock data
    events = [
        {
            'timestamp': '2025-07-17T10:30:00',
            'card_id': 'CARD001',
            'access_granted': True
        },
        {
            'timestamp': '2025-07-17T10:25:00',
            'card_id': 'CARD002',
            'access_granted': True
        }
    ]
    return jsonify(events)

@app.route('/api/labjack/control', methods=['POST'])
def labjack_control():
    """Control LabJack outputs"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data provided'}), 400
        
        if not labjack_u3 or not labjack_u3.is_connected():
            return jsonify({'success': False, 'message': 'LabJack U3 not connected'}), 500
        
        action = data.get('action')
        
        if action == 'unlock_shear':
            duration = data.get('duration', 3.0)
            success = labjack_u3.trigger_shear_unlock(duration)
            return jsonify({'success': success, 'message': f'Shear unlock triggered for {duration}s'})
        
        elif action == 'lock_shear':
            success = labjack_u3.force_shear_lock()
            return jsonify({'success': success, 'message': 'Shear force locked'})
        
        elif action == 'set_led':
            color = data.get('color')
            state = data.get('state', True)
            success = labjack_u3.set_status_led(color, state)
            return jsonify({'success': success, 'message': f'{color} LED set to {"ON" if state else "OFF"}'})
        
        elif action == 'set_digital_output':
            channel = data.get('channel')
            state = data.get('state', False)
            success = labjack_u3.set_digital_output(channel, state)
            return jsonify({'success': success, 'message': f'{channel} set to {"HIGH" if state else "LOW"}'})
        
        elif action == 'set_analog_output':
            channel = data.get('channel')
            voltage = data.get('voltage', 0.0)
            success = labjack_u3.set_analog_output(channel, voltage)
            return jsonify({'success': success, 'message': f'{channel} set to {voltage}V'})
        
        else:
            return jsonify({'success': False, 'message': 'Unknown action'}), 400
    
    except Exception as e:
        logger.error(f"Error in LabJack control: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/labjack/sensors', methods=['GET'])
def labjack_sensors():
    """Get sensor readings"""
    try:
        if not labjack_u3 or not labjack_u3.is_connected():
            return jsonify({'success': False, 'message': 'LabJack U3 not connected'}), 500
        
        sensors = {
            'timestamp': datetime.now().isoformat(),
            'shear_locked': labjack_u3.read_shear_sensor(),
            'motion_detected': labjack_u3.read_motion_sensor(),
            'temperature': labjack_u3.read_temperature_sensor(),
            'digital_inputs': labjack_u3.read_digital_inputs(),
            'analog_inputs': labjack_u3.read_analog_inputs()
        }

        # Add debugging logs
        logger.debug(f"Sensor data being sent to frontend: {sensors}")

        return jsonify({'success': True, 'sensors': sensors})
    
    except Exception as e:
        logger.error(f"Error reading LabJack sensors: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/cards', methods=['GET'])
def get_cards():
    """Get all cards in access list"""
    try:
        if not card_manager:
            return jsonify({'success': False, 'message': 'Card manager not available'}), 500
        
        cards = card_manager.get_all_cards()
        stats = card_manager.get_access_stats()
        
        return jsonify({
            'success': True,
            'cards': cards,
            'stats': stats
        })
    
    except Exception as e:
        logger.error(f"Error getting cards: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/cards/<card_id>', methods=['GET'])
def get_card(card_id):
    """Get specific card information"""
    try:
        if not card_manager:
            return jsonify({'success': False, 'message': 'Card manager not available'}), 500
        
        card_info = card_manager.get_card_info(card_id)
        if card_info:
            return jsonify({'success': True, 'card': card_info})
        else:
            return jsonify({'success': False, 'message': 'Card not found'}), 404
    
    except Exception as e:
        logger.error(f"Error getting card {card_id}: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/cards', methods=['POST'])
def add_card():
    """Add a new card to access list"""
    try:
        if not card_manager:
            return jsonify({'success': False, 'message': 'Card manager not available'}), 500
        
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data provided'}), 400
        
        card_id = data.get('card_id', '').strip()
        name = data.get('name', '').strip()
        department = data.get('department', '').strip()
        access_level = data.get('access_level', 'limited')
        notes = data.get('notes', '').strip()
        
        if not card_id or not name:
            return jsonify({'success': False, 'message': 'Card ID and name are required'}), 400
        
        success = card_manager.add_card(card_id, name, department, access_level, notes)
        if success:
            return jsonify({'success': True, 'message': f'Card {card_id} added successfully'})
        else:
            return jsonify({'success': False, 'message': 'Failed to add card (may already exist)'}), 400
    
    except Exception as e:
        logger.error(f"Error adding card: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/cards/<card_id>', methods=['DELETE'])
def remove_card(card_id):
    """Remove a card from access list"""
    try:
        if not card_manager:
            return jsonify({'success': False, 'message': 'Card manager not available'}), 500
        
        success = card_manager.remove_card(card_id)
        if success:
            return jsonify({'success': True, 'message': f'Card {card_id} removed successfully'})
        else:
            return jsonify({'success': False, 'message': 'Card not found'}), 404
    
    except Exception as e:
        logger.error(f"Error removing card {card_id}: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/cards/<card_id>/activate', methods=['POST'])
def activate_card(card_id):
    """Activate a card"""
    try:
        if not card_manager:
            return jsonify({'success': False, 'message': 'Card manager not available'}), 500
        
        success = card_manager.activate_card(card_id)
        if success:
            return jsonify({'success': True, 'message': f'Card {card_id} activated'})
        else:
            return jsonify({'success': False, 'message': 'Card not found'}), 404
    
    except Exception as e:
        logger.error(f"Error activating card {card_id}: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/cards/<card_id>/deactivate', methods=['POST'])
def deactivate_card(card_id):
    """Deactivate a card"""
    try:
        if not card_manager:
            return jsonify({'success': False, 'message': 'Card manager not available'}), 500
        
        success = card_manager.deactivate_card(card_id)
        if success:
            return jsonify({'success': True, 'message': f'Card {card_id} deactivated'})
        else:
            return jsonify({'success': False, 'message': 'Card not found'}), 404
    
    except Exception as e:
        logger.error(f"Error deactivating card {card_id}: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/cards/validate/<card_id>', methods=['POST'])
def validate_card_api(card_id):
    """Validate a card (for testing purposes)"""
    try:
        if not card_manager:
            return jsonify({'success': False, 'message': 'Card manager not available'}), 500
        
        validation_result = card_manager.validate_card(card_id)
        return jsonify({'success': True, 'validation': validation_result})
    
    except Exception as e:
        logger.error(f"Error validating card {card_id}: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/cards/search', methods=['GET'])
def search_cards():
    """Search for cards"""
    try:
        if not card_manager:
            return jsonify({'success': False, 'message': 'Card manager not available'}), 500
        
        query = request.args.get('q', '').strip()
        if not query:
            return jsonify({'success': False, 'message': 'Search query required'}), 400
        
        results = card_manager.search_cards(query)
        return jsonify({'success': True, 'results': results, 'count': len(results)})
    
    except Exception as e:
        logger.error(f"Error searching cards: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

def start_card_reader():
    """Start card reader in background thread"""
    if card_reader:
        card_reader.start_monitoring()

def start_labjack():
    """Start LabJack U3 in background thread"""
    if labjack_u3:
        labjack_u3.start_monitoring()

if __name__ == '__main__':
    # Initialize components
    initialize_components()
    
    # Start card reader in background thread
    if card_reader:
        reader_thread = threading.Thread(target=start_card_reader, daemon=True)
        reader_thread.start()
        logger.info("Card reader thread started")
    
    # Start LabJack U3 in background thread
    if labjack_u3:
        labjack_thread = threading.Thread(target=start_labjack, daemon=True)
        labjack_thread.start()
        logger.info("LabJack U3 thread started")
    
    # Get configuration from environment
    host = os.environ.get('FLASK_HOST', '0.0.0.0')
    port = int(os.environ.get('FLASK_PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    
    logger.info(f"Starting Shear App server on {host}:{port}")
    app.run(host=host, port=port, debug=debug)
