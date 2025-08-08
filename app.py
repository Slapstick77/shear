#!/usr/bin/env python3
"""
Shear App - USB HID Card Access Server
Handles card reader events and controls access to shear equipment
"""

from flask import Flask, request, jsonify, render_template, redirect, url_for, session, send_file, Response
import threading
import requests
import json
import time
import logging
from datetime import datetime
import os
import csv
import io
from card_reader import CardReader
from labjack_u3 import LabJackU3
import database as db

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

# Shear control settings
SHEAR_SETTINGS = {
    'unlock_timeout': 120,  # Default 2 minutes in seconds
    'shear_output_pin': 'FIO6',  # LabJack output pin for shear control
    'motion_input_pin': 'FIO4',  # LabJack input pin for motion detection
    'error_action': 'unlock',  # Options: 'unlock', 'lock', 'maintain'
}

# Session data
session_logs = []
last_card_read = None
card_scan_events = []  # Queue for card scan events to push to frontend
shear_unlock_timer = None
shear_unlocked = False
shear_unlock_timestamp = None
shear_unlock_user = None
shear_cycles = 0  # Track number of shear unlock cycles
auto_accept_enabled = False  # Auto-accept setting for new card registrations

# Output control modes - track manual/auto state for each output
output_modes = {
    'FIO6': 'auto',  # Shear control output
    'FIO7': 'auto'   # Additional output
}
manual_output_states = {
    'FIO6': False,  # Manual state when in manual mode
    'FIO7': False   # Manual state when in manual mode
}

# System data for shifts and departments
system_shifts = ["First", "Second", "Third"]
system_departments = ["Sheet Shop", "Base Shop", "Electric Shop", "Assembly", "Door Shop", "QA", "Maintenance", "Management", "Engineering", "Other"]

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

def migrate_legacy_json_data():
    """Migrate legacy access_requests.json to SQL database if it exists"""
    try:
        legacy_file = 'access_requests.json'
        if os.path.exists(legacy_file):
            logger.info(f"Found legacy {legacy_file} - migrating to SQL database")
            
            with open(legacy_file, 'r') as f:
                legacy_requests = json.load(f)
            
            migrated_count = 0
            for request in legacy_requests:
                if request.get('status') == 'pending':
                    card_id = request.get('card_id')
                    name = request.get('name', '')
                    first_name = request.get('first_name', '')
                    last_name = request.get('last_name', '')
                    email = request.get('email', '')
                    
                    # Check if already exists in database
                    if not db.get_pending_request(card_id) and not db.get_user(card_id):
                        success = db.add_pending_request(card_id, name, first_name, last_name, email, '', '')
                        if success:
                            migrated_count += 1
                            logger.info(f"Migrated pending request: {card_id} - {name}")
            
            # Move the legacy file to backup
            backup_file = f"{legacy_file}.migrated.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            os.rename(legacy_file, backup_file)
            
            logger.info(f"Migration complete: {migrated_count} requests migrated from {legacy_file}")
            logger.info(f"Legacy file backed up as: {backup_file}")
            
    except Exception as e:
        logger.error(f"Error during legacy data migration: {e}")

def initialize_components():
    """Initialize card reader and LabJack components"""
    global card_reader, labjack_u3
    
    try:
        # Initialize database
        db.init_db()
        logger.info("Database initialized successfully")
        
        # Migrate legacy JSON data if present
        migrate_legacy_json_data()
        
        # Initialize card reader
        card_reader = CardReader(on_card_read=handle_card_read)
        
        # Initialize LabJack U3
        labjack_u3 = LabJackU3(on_input_change=handle_labjack_input_change)
        if labjack_u3:
            connection_success = labjack_u3.connect()
            if connection_success:
                logger.info("LabJack U3 connected successfully")
                # Start monitoring loop for FIO4 and FIO5 states
                labjack_u3.start_monitoring()
                logger.info("Started LabJack U3 input monitoring loop")
            else:
                logger.warning("LabJack U3 connection failed - device may not be connected or driver not installed")
        
        logger.info("Components initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize components: {e}")

def handle_card_read(card_data):
    """Handle card read event - NEW SQL-based flow"""
    global last_card_read, session_logs, shear_unlock_timer, shear_unlocked, shear_unlock_user
    try:
        card_id = card_data.get('card_id', '').strip()
        logger.info(f"Card read: {card_id}")
        last_card_read = card_id
        
        # STEP 1: Log every scan to database
        db.log_scan_event(card_id, 'scan')
        
        # STEP 2: Check if card is in users table
        user = db.get_user(card_id)
        if user:
            # User exists - unlock shear
            unlock_shear(card_id, user)
            
            # Update last access time
            db.update_user_last_access(card_id)
            
            # Log the unlock event
            db.log_scan_event(card_id, 'unlock')
            
            # Push event to frontend
            event = {
                'type': 'card_scan',
                'card_id': card_id,
                'status': 'authorized',
                'user_name': user['name'],
                'message': 'Access granted'
            }
            card_scan_events.append(event)
            logger.info(f"Pushed authorized event to SSE queue: {event}")
            
            # Add to session logs for UI
            log_entry = {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'message': f"Access granted for {user['name']} (card: {card_id}) - Shear unlocked"
            }
            session_logs.append(log_entry)
            
        else:
            # STEP 3: Check if card has pending request
            pending_request = db.get_pending_request(card_id)
            if pending_request:
                # Card has pending request
                db.log_scan_event(card_id, 'pending')
                
                # Push event to frontend
                card_scan_events.append({
                    'type': 'card_scan',
                    'card_id': card_id,
                    'status': 'authorization_pending',
                    'user_name': f"{pending_request['first_name']} {pending_request['last_name']}",
                    'message': 'Admin approval required'
                })
                
                log_entry = {
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'message': f"Request pending for {pending_request['first_name']} {pending_request['last_name']} (card: {card_id}) - Admin approval required"
                }
                session_logs.append(log_entry)
                
            else:
                # STEP 4: Unknown card - log and trigger UI prompt
                db.log_scan_event(card_id, 'unknown')
                
                # Push event to frontend
                event = {
                    'type': 'card_scan',
                    'card_id': card_id,
                    'status': 'unknown',
                    'user_name': None,
                    'message': 'Unknown card'
                }
                card_scan_events.append(event)
                logger.info(f"Pushed unknown card event to SSE queue: {event}")
                
                log_entry = {
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'message': f"Unknown card scanned: {card_id} - Awaiting user information"
                }
                session_logs.append(log_entry)
        
        # Keep only last 100 log entries in memory
        if len(session_logs) > 100:
            session_logs = session_logs[-100:]
        
    except Exception as e:
        logger.error(f"Error handling card read: {e}")
        db.log_scan_event(card_id, 'error')

def unlock_shear(card_id, user_info=None):
    """Unlock shear and start monitoring"""
    global shear_unlock_timer, shear_unlocked, shear_unlock_timestamp, shear_unlock_user, shear_cycles
    
    try:
        # Cancel any existing timer
        if shear_unlock_timer:
            shear_unlock_timer.cancel()
        
        # Set shear output HIGH to unlock (only if in auto mode)
        if labjack_u3 and labjack_u3.is_connected():
            shear_pin = SHEAR_SETTINGS['shear_output_pin']
            if output_modes.get(shear_pin, 'auto') == 'auto':
                # Only control output if in auto mode
                labjack_u3.set_digital_output(shear_pin, True)
                logger.info(f"Shear output set HIGH (AUTO MODE)")
            else:
                logger.info(f"Shear output in MANUAL MODE - not changing state")
            # No LED control - just unlock the shear
        
        shear_unlocked = True
        shear_unlock_timestamp = datetime.now()
        shear_unlock_user = user_info or {}
        shear_cycles = 0  # Reset cycles when shear is unlocked
        logger.info(f"Shear unlocked for card: {card_id} (Cycles reset to 0)")
        
        # Broadcast status change via SSE
        status_event = {
            'type': 'status_change',
            'shear_unlocked': True,
            'unlock_user': user_info,
            'cycles': shear_cycles,
            'timestamp': datetime.now().isoformat()
        }
        card_scan_events.append(status_event)
        logger.info(f"Pushed shear unlock status event to SSE queue")
        
        # Start timeout timer
        start_shear_timeout_timer()
        
    except Exception as e:
        logger.error(f"Error unlocking shear: {e}")

def lock_shear():
    """Lock shear and stop monitoring"""
    global shear_unlock_timer, shear_unlocked, shear_unlock_timestamp, shear_unlock_user
    
    try:
        # Cancel timer
        if shear_unlock_timer:
            shear_unlock_timer.cancel()
            shear_unlock_timer = None
        
        # Set shear output LOW to lock (only if in auto mode)
        if labjack_u3 and labjack_u3.is_connected():
            shear_pin = SHEAR_SETTINGS['shear_output_pin']
            if output_modes.get(shear_pin, 'auto') == 'auto':
                # Only control output if in auto mode
                labjack_u3.set_digital_output(shear_pin, False)
                logger.info(f"Shear output set LOW (AUTO MODE)")
            else:
                logger.info(f"Shear output in MANUAL MODE - not changing state")
            # No LED control - just lock the shear
        
        shear_unlocked = False
        shear_unlock_timestamp = None
        shear_unlock_user = None
        logger.info("Shear locked due to timeout")
        
        # Broadcast status change via SSE
        status_event = {
            'type': 'status_change',
            'shear_unlocked': False,
            'unlock_user': None,
            'timestamp': datetime.now().isoformat()
        }
        card_scan_events.append(status_event)
        logger.info(f"Pushed shear lock status event to SSE queue")
        
        # Add to session logs
        log_entry = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'message': "Shear locked - timeout reached"
        }
        session_logs.append(log_entry)
        
    except Exception as e:
        logger.error(f"Error locking shear: {e}")

def start_shear_timeout_timer():
    """Start or restart the shear timeout timer"""
    global shear_unlock_timer, shear_unlock_timestamp
    
    # Cancel existing timer
    if shear_unlock_timer:
        shear_unlock_timer.cancel()
    
    # Reset timestamp for timer calculation
    shear_unlock_timestamp = datetime.now()
    
    # Start new timer
    timeout_seconds = SHEAR_SETTINGS['unlock_timeout']
    shear_unlock_timer = threading.Timer(timeout_seconds, lock_shear)
    shear_unlock_timer.start()
    logger.info(f"Shear timeout timer started: {timeout_seconds} seconds")

def handle_labjack_input_change(change_data):
    """Handle LabJack input changes"""
    global shear_unlocked, shear_cycles
    try:
        logger.info(f"LabJack input change: {change_data}")
        print(f"[DEBUG] LabJack input change: {change_data}")
        print(f"[DEBUG] Current shear_unlocked: {shear_unlocked}")
        print(f"[DEBUG] Motion input pin setting: {SHEAR_SETTINGS['motion_input_pin']}")
        
        # Check for motion detection while shear is unlocked
        if (change_data['channel'] == SHEAR_SETTINGS['motion_input_pin'] and shear_unlocked):
            if change_data.get('state'):
                # Motion detected (HIGH state) - reset timer and increment cycle
                logger.info("Motion detected (HIGH) - resetting shear timeout timer and incrementing cycle")
                print(f"[MOTION DETECTOR] Motion detected on {SHEAR_SETTINGS['motion_input_pin']} - Timer reset!")
                start_shear_timeout_timer()
                
                # Increment cycle counter for each motion detection
                shear_cycles += 1
                print(f"[MOTION DETECTOR] Shear cycle #{shear_cycles}")
                
                # Add to session logs
                log_entry = {
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'message': f"Motion detected on {SHEAR_SETTINGS['motion_input_pin']} - cycle #{shear_cycles}, timer reset"
                }
                session_logs.append(log_entry)
            else:
                # Motion stopped (LOW state) - just log it
                logger.info("Motion stopped (LOW) - no action taken")
                print(f"[MOTION DETECTOR] Motion stopped on {SHEAR_SETTINGS['motion_input_pin']}")
        
        # Add context for specific sensors
        if change_data['channel'] == 'FIO4':  # Motion sensor
            motion_state = 'detected' if change_data.get('state') else 'clear'
            logger.info(f"Motion sensor (FIO4) change: {motion_state}")
            print(f"[SENSOR] FIO4 Motion: {motion_state}")
        elif change_data['channel'] == 'FIO5':  # Additional input
            input_state = 'HIGH' if change_data.get('state') else 'LOW'
            logger.info(f"FIO5 input change: {input_state}")
            print(f"[SENSOR] FIO5 Input: {input_state}")
        elif change_data['channel'] == 'AIN0':  # Temperature sensor
            temp_value = change_data.get('value', 'unknown')
            logger.info(f"Temperature sensor change: {temp_value}°C")
            print(f"[SENSOR] Temperature: {temp_value}°C")
        
    except Exception as e:
        logger.error(f"Error handling LabJack input change: {e}")

@app.route('/')
def index():
    """Smart routing based on device type"""
    user_agent = request.headers.get('User-Agent', '').lower()
    
    # Enhanced device detection
    is_mobile_phone = any(keyword in user_agent for keyword in [
        'android.*mobile', 'iphone', 'ipod', 'blackberry', 'iemobile', 'opera mini'
    ])
    is_tablet = any(keyword in user_agent for keyword in [
        'ipad', 'android tablet', 'tablet'
    ]) or ('android' in user_agent and 'mobile' not in user_agent)
    
    # Route tablets to full operating dashboard, desktops to simple status page
    if is_tablet or is_mobile_phone:
        return render_template('operating.html')
    else:
        return redirect(url_for('desktop_status'))

@app.route('/operating')
def operating():
    """Full operating dashboard (for tablets/mobile)"""
    return render_template('operating.html')

@app.route('/desktop')
def desktop_status():
    """Desktop dashboard for monitoring and administration"""
    return render_template('desktop_dashboard.html')

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
    
    # Lock shear when user logs out for security
    lock_shear()
    
    # Clear session
    session.clear()
    last_card_read = None  # Clear the last card read to prevent auto re-login
    
    # Add logout log
    log_entry = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'message': 'User logged out - Shear locked for security'
    }
    session_logs.append(log_entry)
    
    return redirect(url_for('index'))

@app.route('/api/admin-login', methods=['POST'])
def api_admin_login():
    """Handle admin login via password"""
    try:
        data = request.get_json()
        password = data.get('password', '')
        
        if password == AUTH_CREDENTIALS['admin']:
            session['user_role'] = 'admin'
            session['login_method'] = 'password'  # Track how they logged in
            return jsonify({'success': True, 'message': 'Admin login successful'})
        else:
            return jsonify({'success': False, 'message': 'Invalid password'})
    
    except Exception as e:
        logger.error(f"Error during admin login: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/auth-status')
def api_auth_status():
    """Get current authentication status"""
    try:
        user_role = session.get('user_role')
        login_method = session.get('login_method')
        
        if user_role:
            return jsonify({
                'authenticated': True,
                'role': user_role,
                'login_method': login_method
            })
        else:
            return jsonify({
                'authenticated': False,
                'role': None,
                'login_method': None
            })
    
    except Exception as e:
        logger.error(f"Error checking auth status: {e}")
        return jsonify({'authenticated': False, 'role': None, 'login_method': None})

@app.route('/api/user-permissions')
def api_user_permissions():
    """Get current user's permissions"""
    try:
        user_role = session.get('user_role')
        login_method = session.get('login_method', 'card')
        
        # Define permissions based on role
        permissions = {
            'can_assign_admin': False,
            'can_assign_manager': False,
            'can_assign_user': False,
            'can_edit_all_users': False,
            'can_remove_all_users': False,
            'can_approve_requests': False,
            'user_role': user_role,
            'login_method': login_method
        }
        
        if user_role == 'admin':
            # Admin can do everything
            permissions['can_assign_admin'] = True
            permissions['can_assign_manager'] = True
            permissions['can_assign_user'] = True
            permissions['can_edit_all_users'] = True
            permissions['can_remove_all_users'] = True
            permissions['can_approve_requests'] = True
            
        elif user_role == 'manager':
            # Manager can assign user level only, edit users, and approve user-level requests
            permissions['can_assign_user'] = True
            permissions['can_edit_all_users'] = True  # Can edit, but restricted in access_level assignment
            permissions['can_remove_all_users'] = False  # Cannot remove admin/manager users
            permissions['can_approve_requests'] = True  # Can approve but only assign user level
        
        return jsonify({'success': True, 'permissions': permissions})
        
    except Exception as e:
        logger.error(f"Error getting user permissions: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/last-card-status')
def api_last_card_status():
    """Get the last card read with its status"""
    global last_card_read
    
    if not last_card_read:
        return jsonify({
            'success': True,
            'card_id': None,
            'status': 'no_card',
            'message': 'No card scanned yet'
        })
    
    card_id = last_card_read
    
    # Check if card has pending request
    pending_request = db.get_pending_request(card_id)
    
    if pending_request:
        return jsonify({
            'success': True,
            'card_id': card_id,
            'status': 'authorization_pending',
            'message': 'Authorization pending - Admin approval required',
            'user_name': pending_request.get('name', 'Unknown User')
        })
    
    # Check if card exists in access list
    user = db.get_user(card_id)
    if user:
        return jsonify({
            'success': True,
            'card_id': card_id,
            'status': 'authorized',
            'message': 'Access granted',
            'user_name': user['name']
        })
    
    return jsonify({
        'success': True,
        'card_id': card_id,
        'status': 'unknown',
        'message': 'Unknown card - Access request can be submitted'
    })

@app.route('/api/last-card-read')
def api_last_card_read():
    """Get the last card read"""
    global last_card_read
    return jsonify({
        'success': True,
        'card_id': last_card_read,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/request-access', methods=['POST'])
def api_request_access():
    """Submit an access request for a card"""
    try:
        data = request.json
        card_id = data.get('card_id')
        name = data.get('name', '').strip()
        first_name = data.get('first_name', '').strip()
        last_name = data.get('last_name', '').strip()
        email = data.get('email', '').strip()
        
        if not card_id or not name:
            return jsonify({'success': False, 'message': 'Card ID and name are required'}), 400
        
        # Check if card already has access
        existing_user = db.get_user(card_id)
        if existing_user:
            return jsonify({'success': False, 'message': 'Card already has access'}), 400
        
        # Check if access request already exists
        existing_request = db.get_pending_request(card_id)
        if existing_request:
            return jsonify({'success': False, 'message': 'Access request already exists'}), 400
        
        # Create full name from parts if provided, otherwise use name field
        if first_name and last_name:
            full_name = f"{first_name} {last_name}".strip()
        else:
            full_name = name
            # Try to split name into first/last if not provided
            if not first_name and not last_name:
                name_parts = name.split()
                if len(name_parts) >= 2:
                    first_name = name_parts[0]
                    last_name = ' '.join(name_parts[1:])
                else:
                    first_name = name
                    last_name = ''
        
        # Add pending request to database
        success = db.add_pending_request(card_id, full_name, first_name, last_name, email, '', '')
        
        if success:
            logger.info(f"Access request submitted for card {card_id} by {full_name}")
            return jsonify({'success': True, 'message': 'Access request submitted successfully'})
        else:
            return jsonify({'success': False, 'message': 'Failed to submit access request'}), 500
        
    except Exception as e:
        logger.error(f"Error processing access request: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/access-requests')
def api_get_access_requests():
    """Get all pending access requests"""
    try:
        # Get all pending requests from database
        pending_requests = db.get_all_pending_requests()
        
        return jsonify({'success': True, 'requests': pending_requests})
        
    except Exception as e:
        logger.error(f"Error getting access requests: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/access-requests/<card_id>', methods=['POST'])
def api_approve_access_request(card_id):
    """Approve an access request and create user - NEW SQL-based"""
    try:
        data = request.json
        access_level = data.get('access_level', 'user')
        department = data.get('department', '').strip()
        shift = data.get('shift', '').strip()
        
        # Check if user has permission to assign this access level
        user_role = session.get('user_role')
        
        if user_role == 'manager' and access_level not in ['user']:
            return jsonify({'success': False, 'message': 'Managers can only assign user access level'}), 403
        
        if user_role not in ['admin', 'manager']:
            return jsonify({'success': False, 'message': 'Insufficient permissions'}), 403
        
        # Get the pending request
        pending_request = db.get_pending_request(card_id)
        if not pending_request:
            return jsonify({'success': False, 'message': 'Access request not found'}), 404
        
        # Create full name
        full_name = f"{pending_request['first_name']} {pending_request['last_name']}"
        
        # Add user to database (note: department and shift from request data, not from pending_request)
        success = db.add_user(card_id, full_name, access_level, department, shift, 'active')
        
        if success:
            # Remove from pending requests
            db.remove_pending_request(card_id)
            
            # Log the approval
            db.log_scan_event(card_id, 'approved')
            
            logger.info(f"Approved access for card {card_id} - {full_name} as {access_level}")
            return jsonify({'success': True, 'message': f'Access approved for {full_name}'})
        else:
            return jsonify({'success': False, 'message': 'Failed to add user'}), 500
            
    except Exception as e:
        logger.error(f"Error approving access request: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/access-requests/<card_id>', methods=['DELETE'])
def api_deny_access_request(card_id):
    """Deny an access request - NEW SQL-based"""
    try:
        # Get the pending request for logging
        pending_request = db.get_pending_request(card_id)
        if not pending_request:
            return jsonify({'success': False, 'message': 'Access request not found'}), 404
        
        # Remove from pending requests
        success = db.remove_pending_request(card_id)
        if success:
            full_name = f"{pending_request['first_name']} {pending_request['last_name']}"
            
            # Log the denial
            db.log_scan_event(card_id, 'denied')
            
            logger.info(f"Access request denied for card {card_id} - {full_name}")
            return jsonify({'success': True, 'message': 'Access request denied'})
        else:
            return jsonify({'success': False, 'message': 'Failed to remove request'}), 500
        
    except Exception as e:
        logger.error(f"Error denying access request: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/users')
def api_users():
    """Get all users"""
    try:
        users = db.get_all_users()
        formatted_users = []
        for user in users:
            if not isinstance(user, dict):
                logger.warning(f"Unexpected user record type in get_all_users(): {type(user)} -> {user}")
                continue
            # Safely extract fields with defaults
            shift_val = ''
            try:
                shift_val = user['shift'] if user.get('shift') is not None else ''
            except Exception:
                # If even this fails, leave shift blank
                shift_val = ''
            try:
                formatted_users.append({
                    'card_id': user.get('card_id', ''),
                    'name': user.get('name', ''),
                    'access_level': user.get('access_level', ''),
                    'department': user.get('department', ''),
                    'shift': shift_val,
                    'active': user.get('status', '') == 'active'
                })
            except Exception as inner_e:
                logger.error(f"Failed to format user record {user}: {inner_e}")
        return jsonify({'success': True, 'users': formatted_users})
    except Exception as e:
        logger.error(f"Error getting users: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/users', methods=['POST'])
def api_add_user():
    """Add a new user"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data provided'}), 400
        
        card_id = data.get('card_id', '').strip()
        user_name = data.get('user_name', '').strip()
        access_level = data.get('access_level', 'user')
        department = data.get('department', '').strip()
        shift = data.get('shift', '').strip()
        
        if not card_id or not user_name:
            return jsonify({'success': False, 'message': 'Card ID and user name are required'}), 400
        
        # Check if user already exists
        existing_user = db.get_user(card_id)
        if existing_user:
            return jsonify({'success': False, 'message': 'Card already exists'}), 400
        
        # Add user to database
        success = db.add_user(card_id, user_name, access_level, department, shift, 'active')
        if success:
            return jsonify({'success': True, 'message': f'User {user_name} added successfully'})
        else:
            return jsonify({'success': False, 'message': 'Failed to add user'}), 500
    
    except Exception as e:
        logger.error(f"Error adding user: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/users/<card_id>', methods=['PUT'])
def api_update_user(card_id):
    """Update an existing user"""
    try:
        # Check authentication and permissions
        user_role = session.get('user_role')
        if user_role not in ['admin', 'manager']:
            return jsonify({'success': False, 'message': 'Insufficient permissions'}), 403
        
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data provided'}), 400
        
        user_name = data.get('user_name', '').strip()
        access_level = data.get('access_level', 'user')
        department = data.get('department', '').strip()
        shift = data.get('shift', '').strip()
        
        if not user_name:
            return jsonify({'success': False, 'message': 'User name is required'}), 400
        
        # Check if user exists
        existing_user = db.get_user(card_id)
        if not existing_user:
            return jsonify({'success': False, 'message': 'Card not found'}), 404
        
        # Permission check: managers can only edit user access level accounts and can't change access level
        if user_role == 'manager':
            if existing_user['access_level'] != 'user':
                return jsonify({'success': False, 'message': 'Managers can only edit user-level accounts'}), 403
            # Force access_level to remain 'user' for manager edits
            access_level = 'user'
        
        # Update the user
        success = db.update_user(card_id, user_name, access_level, department, shift, existing_user['status'])
        if success:
            logger.info(f"User {card_id} updated by {user_role}: {user_name} - {access_level} - {department} - {shift}")
            return jsonify({'success': True, 'message': f'User {user_name} updated successfully'})
        else:
            return jsonify({'success': False, 'message': 'Failed to update user'}), 500
    
    except Exception as e:
        logger.error(f"Error updating user: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/users/<card_id>', methods=['DELETE'])
def api_remove_user(card_id):
    """Remove a user"""
    try:
        # Check authentication and permissions
        user_role = session.get('user_role')
        if user_role not in ['admin', 'manager']:
            return jsonify({'success': False, 'message': 'Insufficient permissions'}), 403
        
        # Check if user exists
        existing_user = db.get_user(card_id)
        if not existing_user:
            return jsonify({'success': False, 'message': 'User not found'}), 404
        
        # Additional permission check: managers cannot remove admin/manager users (case-insensitive)
        if user_role == 'manager' and existing_user.get('access_level', '').lower() in ['admin', 'manager']:
            return jsonify({'success': False, 'message': 'Managers cannot remove admin or manager users'}), 403

        success = db.remove_user(card_id)
        if success:
            logger.info(f"User {card_id} ({existing_user['name']}) removed by {user_role}")
            return jsonify({'success': True, 'message': f'User removed successfully'})
        else:
            return jsonify({'success': False, 'message': 'Failed to remove user'}), 500
    
    except Exception as e:
        logger.error(f"Error removing user: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/users/search')
def api_search_users():
    """Search users by name, card ID, or department"""
    try:
        query = request.args.get('q', '').strip()
        if not query:
            return jsonify({'success': False, 'message': 'Search query is required'}), 400
            
        search_results = db.search_users(query)
        
        # Convert to the format expected by the frontend
        users = []
        for user in search_results:
            users.append({
                'card_id': user['card_id'],
                'name': user['name'],
                'access_level': user['access_level'],
                'department': user['department'],
                'active': user['status'] == 'active'
            })
        
        return jsonify({'success': True, 'users': users})
    
    except Exception as e:
        logger.error(f"Error searching users: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# Shifts and Departments Management
@app.route('/api/shifts')
def api_get_shifts():
    """Get all available shifts"""
    global system_shifts
    return jsonify({'success': True, 'shifts': system_shifts})

@app.route('/api/shifts', methods=['POST'])
def api_add_shift():
    """Add a new shift"""
    global system_shifts
    try:
        data = request.get_json()
        shift_name = data.get('name', '').strip()
        
        if not shift_name:
            return jsonify({'success': False, 'message': 'Shift name is required'}), 400
        
        if shift_name in system_shifts:
            return jsonify({'success': False, 'message': 'Shift already exists'}), 400
        
        system_shifts.append(shift_name)
        logger.info(f"Added new shift: {shift_name}")
        return jsonify({'success': True, 'message': 'Shift added successfully'})
    
    except Exception as e:
        logger.error(f"Error adding shift: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/shifts/<shift_name>', methods=['DELETE'])
def api_remove_shift(shift_name):
    """Remove a shift"""
    global system_shifts
    try:
        if shift_name not in system_shifts:
            return jsonify({'success': False, 'message': 'Shift not found'}), 404
        
        system_shifts.remove(shift_name)
        logger.info(f"Removed shift: {shift_name}")
        return jsonify({'success': True, 'message': 'Shift removed successfully'})
    
    except Exception as e:
        logger.error(f"Error removing shift: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/departments')
def api_get_departments():
    """Get all available departments"""
    global system_departments
    return jsonify({'success': True, 'departments': system_departments})

@app.route('/api/departments', methods=['POST'])
def api_add_department():
    """Add a new department"""
    global system_departments
    try:
        data = request.get_json()
        dept_name = data.get('name', '').strip()
        
        if not dept_name:
            return jsonify({'success': False, 'message': 'Department name is required'}), 400
        
        if dept_name in system_departments:
            return jsonify({'success': False, 'message': 'Department already exists'}), 400
        
        system_departments.append(dept_name)
        logger.info(f"Added new department: {dept_name}")
        return jsonify({'success': True, 'message': 'Department added successfully'})
    
    except Exception as e:
        logger.error(f"Error adding department: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/departments/<dept_name>', methods=['DELETE'])
def api_remove_department(dept_name):
    """Remove a department"""
    global system_departments
    try:
        if dept_name not in system_departments:
            return jsonify({'success': False, 'message': 'Department not found'}), 404
        
        system_departments.remove(dept_name)
        logger.info(f"Removed department: {dept_name}")
        return jsonify({'success': True, 'message': 'Department removed successfully'})
    
    except Exception as e:
        logger.error(f"Error removing department: {e}")
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

@app.route('/api/settings', methods=['GET'])
def api_get_settings():
    """Get current system settings"""
    try:
        return jsonify({
            'success': True,
            'settings': SHEAR_SETTINGS
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/settings', methods=['POST'])
def api_save_settings():
    """Save system settings (admin only)"""
    global SHEAR_SETTINGS
    try:
        data = request.get_json()
        
        # Update timeout setting if provided
        if 'unlock_timeout' in data:
            timeout_value = int(data['unlock_timeout'])
            if 10 <= timeout_value <= 3600:  # Allow 10 seconds to 1 hour
                SHEAR_SETTINGS['unlock_timeout'] = timeout_value
                logger.info(f"Shear unlock timeout updated to {timeout_value} seconds")
            else:
                return jsonify({'success': False, 'message': 'Timeout must be between 10 and 3600 seconds'}), 400
        
        # Update shear output pin if provided
        if 'shear_output_pin' in data:
            pin = data['shear_output_pin']
            if pin in ['FIO6', 'FIO7']:  # Valid output pins
                SHEAR_SETTINGS['shear_output_pin'] = pin
                logger.info(f"Shear output pin updated to {pin}")
            else:
                return jsonify({'success': False, 'message': 'Invalid output pin'}), 400
        
        # Update motion input pin if provided
        if 'motion_input_pin' in data:
            pin = data['motion_input_pin']
            if pin in ['FIO4', 'FIO5']:  # Valid input pins
                SHEAR_SETTINGS['motion_input_pin'] = pin
                logger.info(f"Motion input pin updated to {pin}")
            else:
                return jsonify({'success': False, 'message': 'Invalid input pin'}), 400
        
        # Update error action if provided
        if 'error_action' in data:
            action = data['error_action']
            if action in ['unlock', 'lock', 'maintain']:
                SHEAR_SETTINGS['error_action'] = action
                logger.info(f"Error action updated to {action}")
            else:
                return jsonify({'success': False, 'message': 'Invalid error action'}), 400
        
        return jsonify({'success': True, 'message': 'Settings saved successfully', 'settings': SHEAR_SETTINGS})
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
    global shear_unlocked, shear_unlock_timer
    try:
        # Lock shear immediately
        lock_shear()
        
        # Clear all sessions
        session.clear()
        
        # Add emergency log
        log_entry = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'message': 'EMERGENCY STOP - All systems locked'
        }
        session_logs.append(log_entry)
        
        logger.warning("Emergency stop activated")
        return jsonify({'success': True, 'message': 'Emergency stop activated'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/shear/lock', methods=['POST'])
def api_lock_shear():
    """Manually lock shear (admin only)"""
    try:
        lock_shear()
        return jsonify({'success': True, 'message': 'Shear locked successfully'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/emergency-unlock', methods=['POST'])
def api_emergency_unlock():
    """Emergency unlock due to system error"""
    global shear_unlocked
    try:
        data = request.get_json() or {}
        reason = data.get('reason', 'System error')
        
        # Check error action setting
        error_action = SHEAR_SETTINGS.get('error_action', 'unlock')
        
        if error_action == 'unlock':
            # Unlock shear for safety
            if labjack_u3 and labjack_u3.is_connected():
                labjack_u3.set_digital_output(SHEAR_SETTINGS['shear_output_pin'], True)
                shear_unlocked = True
                
            # Add emergency log
            log_entry = {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'message': f'EMERGENCY UNLOCK: {reason}'
            }
            session_logs.append(log_entry)
            
            logger.warning(f"Emergency unlock activated due to: {reason}")
            return jsonify({'success': True, 'message': f'Emergency unlock activated: {reason}'})
        elif error_action == 'lock':
            lock_shear()
            return jsonify({'success': True, 'message': f'Emergency lock activated: {reason}'})
        else:  # maintain
            return jsonify({'success': True, 'message': f'Maintaining current state: {reason}'})
            
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/authorized-unlock', methods=['POST'])
def api_authorized_unlock():
    """Unlock shear for authorized user"""
    global shear_unlocked
    try:
        data = request.get_json() or {}
        card_id = data.get('card_id', 'Unknown')
        user_name = data.get('user_name', 'Unknown User')
        
        # Trigger the unlock sequence
        unlock_shear(card_id, {'name': user_name})
        
        # Log the authorized access
        log_entry = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'message': f'AUTHORIZED ACCESS: {user_name} (Card: {card_id})'
        }
        session_logs.append(log_entry)
        
        logger.info(f"Authorized unlock for user: {user_name} (Card: {card_id})")
        return jsonify({'success': True, 'message': f'Access granted to {user_name}'})
            
    except Exception as e:
        logger.error(f"Error in authorized unlock: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/card-events')
def card_events():
    """Server-Sent Events stream for card scan events"""
    def event_stream():
        last_heartbeat = time.time()
        while True:
            try:
                # Check for new card scan events
                if card_scan_events:
                    event = card_scan_events.pop(0)
                    logger.info(f"SSE sending event: {event}")
                    yield f"data: {json.dumps(event)}\n\n"
                    last_heartbeat = time.time()
                else:
                    # Send heartbeat every 30 seconds to keep connection alive
                    if time.time() - last_heartbeat > 30:
                        yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
                        last_heartbeat = time.time()
                time.sleep(0.5)  # Check every 500ms for events
            except GeneratorExit:
                break
            except Exception as e:
                logger.error(f"Error in SSE stream: {e}")
                break
    
    return Response(event_stream(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Cache-Control',
        'X-Accel-Buffering': 'no'  # Disable nginx buffering
    })

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
        # Reset database using the database module
        db.reset_database()
        return jsonify({'success': True, 'message': 'Database reset successfully'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/factory-reset', methods=['POST'])
def api_factory_reset():
    """Factory reset (admin only)"""
    global session_logs
    try:
        session_logs = []
        # Reset database to factory defaults
        db.reset_database()
        return jsonify({'success': True, 'message': 'Factory reset completed'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/status')
def api_status():
    """API endpoint to check system status"""
    global shear_unlocked, shear_unlock_timer, shear_unlock_timestamp, shear_unlock_user, shear_cycles
    
    # Calculate remaining time if timer is active
    remaining_time = 0
    if shear_unlock_timer and shear_unlocked and shear_unlock_timestamp:
        elapsed_time = (datetime.now() - shear_unlock_timestamp).total_seconds()
        remaining_time = max(0, SHEAR_SETTINGS['unlock_timeout'] - elapsed_time)
    
    status = {
        'timestamp': datetime.now().isoformat(),
        'card_reader': {
            'connected': card_reader.is_connected() if card_reader else False,
            'device_info': card_reader.get_device_info() if card_reader and card_reader.is_connected() else None,
            'last_card': last_card_read
        },
        'labjack_u3': {
            'connected': labjack_u3.is_connected() if labjack_u3 else False,
            'device_info': labjack_u3.get_device_info() if labjack_u3 and labjack_u3.is_connected() else None,
            'all_states': labjack_u3.get_all_states() if labjack_u3 and labjack_u3.is_connected() else None
        },
        'shear': {
            'unlocked': shear_unlocked,
            'timeout_remaining': remaining_time,
            'timeout_setting': SHEAR_SETTINGS['unlock_timeout'],
            'output_pin': SHEAR_SETTINGS['shear_output_pin'],
            'motion_pin': SHEAR_SETTINGS['motion_input_pin'],
            'unlock_user': shear_unlock_user,
            'cycles': shear_cycles
        },
        'recent_logs': session_logs[-5:] if session_logs else []
    }
    return jsonify(status)

@app.route('/api/manual-lock', methods=['POST'])
def manual_lock():
    """Manually lock the shear"""
    try:
        # Lock the shear immediately
        lock_shear()
        return jsonify({'success': True, 'message': 'Shear locked manually'})
    except Exception as e:
        logger.error(f"Error in manual lock: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/pending-requests', methods=['GET'])
def get_pending_requests():
    """Get all pending access requests"""
    try:
        requests = db.get_all_pending_requests()
        return jsonify({'success': True, 'requests': requests})
    except Exception as e:
        logger.error(f"Error getting pending requests: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/approve-request', methods=['POST'])
def approve_request():
    """Approve a pending access request"""
    try:
        data = request.get_json()
        card_id = data.get('card_id')
        name = data.get('name', '').strip()
        department = data.get('department', '').strip()
        shift = data.get('shift', '').strip()
        access_level = data.get('access_level', 'user')
        
        if not card_id or not name:
            return jsonify({'success': False, 'message': 'Card ID and name are required'}), 400
        
        # Add user to access list
        success = db.add_user(card_id, name, access_level, department, shift)
        if success:
            # Remove from pending requests
            db.remove_pending_request(card_id)
            logger.info(f"Approved access for card {card_id} - {name}")
            return jsonify({'success': True, 'message': f'Access approved for {name}'})
        else:
            return jsonify({'success': False, 'message': 'Failed to add user to access list'}), 500
            
    except Exception as e:
        logger.error(f"Error approving request: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/deny-request', methods=['POST'])
def deny_request():
    """Deny a pending access request"""
    try:
        data = request.get_json()
        card_id = data.get('card_id')
        
        if not card_id:
            return jsonify({'success': False, 'message': 'Card ID is required'}), 400
        
        # Remove from pending requests
        success = db.remove_pending_request(card_id)
        if success:
            logger.info(f"Denied access for card {card_id}")
            return jsonify({'success': True, 'message': 'Access request denied'})
        else:
            return jsonify({'success': False, 'message': 'Failed to remove pending request'}), 500
        
    except Exception as e:
        logger.error(f"Error denying request: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/submit-access-request', methods=['POST'])
def submit_access_request():
    """User submits their information for access request"""
    try:
        data = request.get_json()
        card_id = data.get('card_id')
        first_name = data.get('first_name', '').strip()
        last_name = data.get('last_name', '').strip()
        department = data.get('department', '').strip()
        shift = data.get('shift', '').strip()
        
        if not card_id or not first_name or not last_name:
            return jsonify({'success': False, 'message': 'Card ID, first name, and last name are required'}), 400
        
        # Check if user already exists
        existing_user = db.get_user(card_id)
        if existing_user:
            return jsonify({'success': False, 'message': 'Card already has access'}), 400
        
        # Check if pending request already exists
        existing_request = db.get_pending_request(card_id)
        if existing_request:
            # Update existing request with user information
            full_name = f"{first_name} {last_name}".strip()
            success = db.remove_pending_request(card_id)
            if success:
                success = db.add_pending_request(card_id, full_name, first_name, last_name, '', department, shift)
        else:
            # Create new pending request
            full_name = f"{first_name} {last_name}".strip()
            success = db.add_pending_request(card_id, full_name, first_name, last_name, '', department, shift)
        
        if success:
            # If auto-accept is enabled, immediately convert to active user
            if auto_accept_enabled:
                full_name_for_user = full_name if full_name else f"{first_name} {last_name}".strip()
                # Attempt to add user directly
                added = db.add_user(card_id, full_name_for_user, 'user', department, shift, 'active')
                if added:
                    # Remove pending request if it still exists
                    db.remove_pending_request(card_id)
                    logger.info(f"Auto-accepted and added user {full_name_for_user} (card {card_id}) - dept={department} shift={shift}")
                    return jsonify({'success': True, 'auto_accepted': True, 'message': 'Access automatically granted'})
                else:
                    logger.warning(f"Auto-accept failed to add user for card {card_id}; leaving as pending")
            logger.info(f"User {first_name} {last_name} submitted access request for card {card_id}")
            return jsonify({'success': True, 'auto_accepted': False, 'message': 'Access request submitted successfully'})
        else:
            return jsonify({'success': False, 'message': 'Failed to submit access request'}), 500
        
    except Exception as e:
        logger.error(f"Error submitting access request: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/check-pending-request/<card_id>')
def check_pending_request(card_id):
    """Check if a card has a pending request that needs user info"""
    try:
        pending_request = db.get_pending_request(card_id)
        if pending_request:
            # Check if user info has been provided (first_name and last_name exist)
            has_user_info = bool(pending_request.get('first_name') and pending_request.get('last_name'))
            return jsonify({
                'success': True, 
                'has_pending': True, 
                'card_id': card_id,
                'user_info_provided': has_user_info
            })
        
        return jsonify({'success': True, 'has_pending': False})
        
    except Exception as e:
        logger.error(f"Error checking pending request: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/purge-pending-requests', methods=['POST'])
def purge_pending_requests():
    """Purge all pending requests"""
    try:
        count = db.remove_all_pending_requests()
        logger.info(f"Purged {count} pending requests")
        return jsonify({'success': True, 'message': f'Purged {count} pending requests'})
        
    except Exception as e:
        logger.error(f"Error purging pending requests: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/toggle-auto-accept', methods=['POST'])
def toggle_auto_accept():
    """Toggle auto-accept setting for new card registrations"""
    global auto_accept_enabled
    try:
        data = request.get_json()
        enabled = data.get('enabled', False)
        
        auto_accept_enabled = bool(enabled)
        logger.info(f"Auto-accept setting changed to: {auto_accept_enabled}")
        return jsonify({'success': True, 'enabled': auto_accept_enabled})
        
    except Exception as e:
        logger.error(f"Error toggling auto-accept: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/auto-accept', methods=['GET'])
def get_auto_accept_state():
    """Return current auto-accept state (admin use)."""
    try:
        return jsonify({'success': True, 'enabled': auto_accept_enabled})
    except Exception as e:
        logger.error(f"Error getting auto-accept state: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/card-events-history', methods=['GET'])
def get_card_events_history():
    """Get recent card events history (from log or database)"""
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
            
            # Check if output is in manual mode
            if output_modes.get(channel, 'auto') == 'manual':
                # In manual mode - allow full control and store manual state
                manual_output_states[channel] = state
                success = labjack_u3.set_digital_output(channel, state)
                return jsonify({'success': success, 'message': f'{channel} set to {"HIGH" if state else "LOW"} (MANUAL MODE)'})
            else:
                # In auto mode - this shouldn't typically be called directly, but allow for testing
                success = labjack_u3.set_digital_output(channel, state)
                return jsonify({'success': success, 'message': f'{channel} set to {"HIGH" if state else "LOW"} (AUTO MODE)'})
        
        elif action == 'set_output_mode':
            # New action to set manual/auto mode for an output
            channel = data.get('channel')
            mode = data.get('mode', 'auto')  # 'manual' or 'auto'
            
            if channel in output_modes:
                output_modes[channel] = mode
                
                # If switching to auto mode, restore logic state
                if mode == 'auto':
                    # Determine what the logic state should be for this output
                    if channel == SHEAR_SETTINGS['shear_output_pin']:
                        # For shear output, set based on current shear state
                        logic_state = shear_unlocked
                        labjack_u3.set_digital_output(channel, logic_state)
                        message = f'{channel} set to AUTO mode - restored to logic state: {"HIGH" if logic_state else "LOW"}'
                    else:
                        # For other outputs, default to LOW when in auto mode
                        labjack_u3.set_digital_output(channel, False)
                        message = f'{channel} set to AUTO mode - set to LOW'
                else:
                    # Manual mode - don't change output state, just enable manual control
                    message = f'{channel} set to MANUAL mode - manual control enabled'
                
                return jsonify({'success': True, 'message': message, 'mode': mode})
            else:
                return jsonify({'success': False, 'message': f'Invalid channel: {channel}'})
        
        elif action == 'get_output_modes':
            # Get current modes for all outputs
            return jsonify({'success': True, 'output_modes': output_modes, 'manual_states': manual_output_states})
        
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

@app.route('/api/debug-monitor-status', methods=['GET'])
def debug_monitor_status():
    """Debug endpoint to check monitoring thread status without restart"""
    try:
        if not labjack_u3:
            return jsonify({'success': False, 'error': 'LabJack not initialized'})
        
        status = {
            'labjack_connected': labjack_u3.is_connected(),
            'labjack_running': getattr(labjack_u3, 'running', False),
            'monitor_thread_exists': hasattr(labjack_u3, 'monitor_thread') and labjack_u3.monitor_thread is not None,
            'monitor_thread_alive': labjack_u3.monitor_thread.is_alive() if hasattr(labjack_u3, 'monitor_thread') and labjack_u3.monitor_thread else False,
            'callback_registered': labjack_u3.on_input_change is not None,
            'callback_function': str(labjack_u3.on_input_change) if labjack_u3.on_input_change else None
        }
        return jsonify({'success': True, 'status': status})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

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
