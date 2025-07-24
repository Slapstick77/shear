#!/usr/bin/env python3
"""
Shear App - USB HID Card Access Server
Handles card reader events and controls access to shear equipment
"""

from flask import Flask, request, jsonify, render_template, redirect, url_for, session, send_file
import threading
import requests
import json
import logging
from datetime import datetime
import os
import csv
import io
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

# Authentication credentials
AUTH_CREDENTIALS = {
    'admin': 'admin',
    'manager': 'Manager'
}

# Session data
session_logs = []
last_card_read = None

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
    global last_card_read, session_logs
    try:
        card_id = card_data.get('card_id', '').strip()
        logger.info(f"Card read: {card_id}")
        last_card_read = card_id
        
        # Add to session logs
        log_entry = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'message': f"Card scanned: {card_id}"
        }
        session_logs.append(log_entry)
        
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
            
            log_entry = {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'message': f"Access granted for card: {card_id}"
            }
        else:
            # Deny access
            if labjack_u3 and labjack_u3.is_connected():
                labjack_u3.set_status_led('red', True)  # Red LED on
                # Turn off red LED after 2 seconds
                threading.Timer(2.0, lambda: labjack_u3.set_status_led('red', False)).start()
            
            log_entry = {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'message': f"Access denied for card: {card_id} - {validation_result.get('reason', 'Unknown')}"
            }
        
        session_logs.append(log_entry)
        
        # Keep only last 100 log entries
        if len(session_logs) > 100:
            session_logs = session_logs[-100:]
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
    """Main operating page"""
    return render_template('operating.html')

@app.route('/technical')
def technical():
    """Technical dashboard (requires admin access)"""
    if 'user_role' not in session or session['user_role'] != 'admin':
        return redirect(url_for('login', role='admin'))
    
    return render_template('index.html', 
                         reader_status=card_reader.is_connected() if card_reader else False,
                         labjack_status=labjack_u3.is_connected() if labjack_u3 else False)

@app.route('/login')
def login():
    """Login page"""
    role = request.args.get('role', 'manager')
    if role not in ['admin', 'manager']:
        role = 'manager'
    return render_template('login.html', role=role)

@app.route('/login', methods=['POST'])
def login_post():
    """Handle login form submission"""
    role = request.args.get('role', 'manager')
    password = request.form.get('password', '')
    
    if role in AUTH_CREDENTIALS and AUTH_CREDENTIALS[role] == password:
        session['user_role'] = role
        if role == 'admin':
            return redirect(url_for('admin'))
        else:
            return redirect(url_for('manager'))
    else:
        return render_template('login.html', role=role, error='Invalid password')

@app.route('/manager')
def manager():
    """Manager dashboard - accessible via card scan or existing session"""
    # Check if user has manager or admin access
    if 'user_role' not in session or session['user_role'] not in ['manager', 'admin']:
        return redirect(url_for('index'))
    
    return render_template('manager.html')

@app.route('/admin')
def admin():
    """Admin dashboard - accessible via card scan or password login"""
    # Check if user has admin access
    if 'user_role' not in session or session['user_role'] != 'admin':
        return redirect(url_for('index'))
    
    return render_template('admin.html')

@app.route('/logout')
def logout():
    """Logout and clear session"""
    global last_card_read
    session.clear()
    last_card_read = None  # Clear the last card read to prevent auto re-login
    return redirect(url_for('index'))

@app.route('/api/card-access/<card_id>')
def api_card_access(card_id):
    """Check card access level and grant access if valid"""
    try:
        if not card_manager:
            return jsonify({'success': False, 'message': 'Card manager not available'}), 500
        
        # Get card info directly from the access list
        card_info = card_manager.get_card_info(card_id)
        
        if card_info:
            access_level = card_info.get('access_level', 'user')
            
            # Validate card through normal validation process
            validation_result = card_manager.validate_card(card_id)
            
            # Ensure validation_result is a dictionary
            if isinstance(validation_result, dict) and validation_result.get('access_granted'):
                # Set session for manager/admin access
                if access_level in ['admin', 'manager']:
                    session['user_role'] = access_level
                    session['user_name'] = card_info.get('name')
                    session['card_id'] = card_id
                
                return jsonify({
                    'success': True,
                    'access_level': access_level,
                    'user_name': card_info.get('name'),
                    'card_id': card_id
                })
            else:
                # Handle both dict and string responses
                if isinstance(validation_result, dict):
                    reason = validation_result.get('reason', 'Access denied')
                else:
                    reason = str(validation_result) if validation_result else 'Access denied'
                
                return jsonify({
                    'success': False,
                    'message': reason
                })
        else:
            return jsonify({
                'success': False,
                'message': 'Card not found'
            })
    
    except Exception as e:
        logger.error(f"Error checking card access: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/simulate-card-read', methods=['POST'])
def api_simulate_card_read():
    """Simulate a card read for testing purposes"""
    global last_card_read, session_logs
    try:
        data = request.get_json()
        card_id = data.get('card_id', '')
        
        if not card_id:
            return jsonify({'success': False, 'message': 'Card ID required'}), 400
        
        # Simulate the card read by updating the global variable
        last_card_read = card_id
        
        # Add to session logs
        log_entry = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'message': f"[TEST] Card scanned: {card_id}"
        }
        session_logs.append(log_entry)
        
        # Also trigger the normal card handling process
        if card_manager:
            validation_result = card_manager.validate_card(card_id)
            
            if validation_result.get('access_granted'):
                log_entry = {
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'message': f"[TEST] Access granted for card: {card_id}"
                }
            else:
                log_entry = {
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'message': f"[TEST] Access denied for card: {card_id} - {validation_result.get('reason', 'Unknown')}"
                }
            
            session_logs.append(log_entry)
        
        # Keep only last 100 log entries
        if len(session_logs) > 100:
            session_logs = session_logs[-100:]
        
        return jsonify({'success': True, 'message': f'Card {card_id} simulated successfully'})
    
    except Exception as e:
        logger.error(f"Error simulating card read: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/admin-login', methods=['POST'])
def api_admin_login():
    """Handle admin login via password"""
    try:
        data = request.get_json()
        password = data.get('password', '')
        
        if password == AUTH_CREDENTIALS['admin']:
            session['user_role'] = 'admin'
            return jsonify({'success': True, 'message': 'Admin login successful'})
        else:
            return jsonify({'success': False, 'message': 'Invalid password'})
    
    except Exception as e:
        logger.error(f"Error during admin login: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/last-card-read')
def api_last_card_read():
    """Get the last card read"""
    global last_card_read
    return jsonify({
        'success': True,
        'card_id': last_card_read,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/users')
def api_users():
    """Get all users"""
    try:
        if not card_manager:
            return jsonify({'success': False, 'message': 'Card manager not available'}), 500
        
        users_dict = card_manager.get_all_cards()
        formatted_users = []
        for card_id, card_info in users_dict.items():
            formatted_users.append({
                'card_id': card_id,
                'name': card_info.get('name'),
                'access_level': card_info.get('access_level', 'user'),
                'department': card_info.get('department', ''),
                'active': card_info.get('active', False)
            })
        
        return jsonify({'success': True, 'users': formatted_users})
    except Exception as e:
        logger.error(f"Error getting users: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/users', methods=['POST'])
def api_add_user():
    """Add a new user"""
    try:
        if not card_manager:
            return jsonify({'success': False, 'message': 'Card manager not available'}), 500
        
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data provided'}), 400
        
        card_id = data.get('card_id', '').strip()
        user_name = data.get('user_name', '').strip()
        access_level = data.get('access_level', 'user')
        
        if not card_id or not user_name:
            return jsonify({'success': False, 'message': 'Card ID and user name are required'}), 400
        
        success = card_manager.add_card(card_id, user_name, '', access_level, '')
        if success:
            return jsonify({'success': True, 'message': f'User {user_name} added successfully'})
        else:
            return jsonify({'success': False, 'message': 'Failed to add user (card may already exist)'}), 400
    
    except Exception as e:
        logger.error(f"Error adding user: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/users/<card_id>', methods=['PUT'])
def api_update_user(card_id):
    """Update an existing user"""
    try:
        if not card_manager:
            return jsonify({'success': False, 'message': 'Card manager not available'}), 500
        
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data provided'}), 400
        
        user_name = data.get('user_name', '').strip()
        access_level = data.get('access_level', 'user')
        department = data.get('department', '').strip()
        
        if not user_name:
            return jsonify({'success': False, 'message': 'User name is required'}), 400
        
        # Get current card info using the card manager method
        card_info = card_manager.get_card_info(card_id)
        
        if not card_info:
            return jsonify({'success': False, 'message': 'Card not found'}), 404
        
        # Update the card info
        if hasattr(card_manager, 'access_list') and card_id in card_manager.access_list:
            card_manager.access_list[card_id]['name'] = user_name
            card_manager.access_list[card_id]['access_level'] = access_level
            card_manager.access_list[card_id]['department'] = department
            card_manager.save_access_list()
            
            return jsonify({'success': True, 'message': f'User {user_name} updated successfully'})
        else:
            return jsonify({'success': False, 'message': 'Failed to update user'}), 400
    
    except Exception as e:
        logger.error(f"Error updating user: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/users/<card_id>', methods=['DELETE'])
def api_remove_user(card_id):
    """Remove a user"""
    try:
        if not card_manager:
            return jsonify({'success': False, 'message': 'Card manager not available'}), 500
        
        success = card_manager.remove_card(card_id)
        if success:
            return jsonify({'success': True, 'message': f'User removed successfully'})
        else:
            return jsonify({'success': False, 'message': 'User not found'}), 404
    
    except Exception as e:
        logger.error(f"Error removing user: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/logs')
def api_logs():
    """Get system logs"""
    global session_logs
    return jsonify({'success': True, 'logs': session_logs})

@app.route('/api/logs', methods=['DELETE'])
def api_clear_logs():
    """Clear system logs"""
    global session_logs
    session_logs = []
    return jsonify({'success': True, 'message': 'Logs cleared successfully'})

@app.route('/api/logs/download')
def api_download_logs():
    """Download logs as CSV"""
    global session_logs
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Timestamp', 'Message'])
    
    for log in session_logs:
        writer.writerow([log['timestamp'], log['message']])
    
    output.seek(0)
    
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'shear_logs_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    )

@app.route('/api/usage-stats')
def api_usage_stats():
    """Get usage statistics"""
    global session_logs
    
    # Calculate stats from logs
    cards_today = len([log for log in session_logs if 'Card scanned:' in log['message']])
    access_attempts = len([log for log in session_logs if 'Access' in log['message']])
    granted = len([log for log in session_logs if 'Access granted' in log['message']])
    
    success_rate = (granted / access_attempts * 100) if access_attempts > 0 else 100
    last_activity = session_logs[-1]['timestamp'] if session_logs else 'None'
    
    return jsonify({
        'success': True,
        'cards_today': cards_today,
        'access_attempts': access_attempts,
        'success_rate': round(success_rate, 1),
        'last_activity': last_activity
    })

@app.route('/api/usage-report/download')
def api_download_usage_report():
    """Download usage report as CSV"""
    global session_logs
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Timestamp', 'Action', 'Card ID', 'Result'])
    
    for log in session_logs:
        message = log['message']
        if 'Card scanned:' in message:
            card_id = message.split('Card scanned: ')[1] if 'Card scanned: ' in message else ''
            writer.writerow([log['timestamp'], 'Card Scan', card_id, 'Scanned'])
        elif 'Access granted' in message:
            card_id = message.split('card: ')[1] if 'card: ' in message else ''
            writer.writerow([log['timestamp'], 'Access Request', card_id, 'Granted'])
        elif 'Access denied' in message:
            card_id = message.split('card: ')[1].split(' -')[0] if 'card: ' in message else ''
            writer.writerow([log['timestamp'], 'Access Request', card_id, 'Denied'])
    
    output.seek(0)
    
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'usage_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    )

@app.route('/api/settings', methods=['POST'])
def api_save_settings():
    """Save system settings (admin only)"""
    try:
        data = request.get_json()
        # In a real implementation, save settings to a config file or database
        return jsonify({'success': True, 'message': 'Settings saved successfully'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/hardware/restart', methods=['POST'])
def api_restart_hardware():
    """Restart hardware connections (admin only)"""
    try:
        # Reinitialize components
        initialize_components()
        return jsonify({'success': True, 'message': 'Hardware restarted successfully'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/emergency-stop', methods=['POST'])
def api_emergency_stop():
    """Emergency stop (admin only)"""
    try:
        if labjack_u3 and labjack_u3.is_connected():
            labjack_u3.force_shear_lock()
            labjack_u3.set_status_led('red', True)
        return jsonify({'success': True, 'message': 'Emergency stop activated'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/database/backup')
def api_backup_database():
    """Backup database (admin only)"""
    try:
        # In a real implementation, create a database backup
        return jsonify({'success': True, 'message': 'Database backup created'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/database/reset', methods=['POST'])
def api_reset_database():
    """Reset database (admin only)"""
    try:
        if card_manager:
            # In a real implementation, clear the database
            pass
        return jsonify({'success': True, 'message': 'Database reset successfully'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/factory-reset', methods=['POST'])
def api_factory_reset():
    """Factory reset (admin only)"""
    global session_logs
    try:
        session_logs = []
        if card_manager:
            # In a real implementation, reset everything to factory defaults
            pass
        return jsonify({'success': True, 'message': 'Factory reset completed'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

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
