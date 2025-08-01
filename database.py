"""
Database Module
Handles SQLite database operations for the shear application
"""

import sqlite3
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
import os

logger = logging.getLogger(__name__)

DB_FILE = 'shear_app.db'

def get_connection():
    """Get database connection"""
    return sqlite3.connect(DB_FILE)

def init_db():
    """Initialize database with required tables"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Create users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                card_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                access_level TEXT DEFAULT 'user',
                department TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                created_date TEXT DEFAULT CURRENT_TIMESTAMP,
                last_access TEXT
            )
        ''')
        
        # Create pending_requests table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pending_requests (
                card_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                first_name TEXT DEFAULT '',
                last_name TEXT DEFAULT '',
                email TEXT DEFAULT '',
                department TEXT DEFAULT '',
                shift TEXT DEFAULT '',
                requested_date TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create scan_events table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scan_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id TEXT NOT NULL,
                scan_time TEXT DEFAULT CURRENT_TIMESTAMP,
                result TEXT DEFAULT 'unknown'
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully")
        
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        raise

def reset_database():
    """Reset database by dropping and recreating all tables"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Drop all tables
        cursor.execute('DROP TABLE IF EXISTS users')
        cursor.execute('DROP TABLE IF EXISTS pending_requests')
        cursor.execute('DROP TABLE IF EXISTS scan_events')
        
        conn.commit()
        conn.close()
        
        # Reinitialize with empty tables
        init_db()
        logger.info("Database reset completed")
        
    except Exception as e:
        logger.error(f"Error resetting database: {e}")
        raise

def add_user(card_id: str, name: str, access_level: str = 'user', department: str = '', status: str = 'active') -> bool:
    """Add a new user to the database"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO users (card_id, name, access_level, department, status)
            VALUES (?, ?, ?, ?, ?)
        ''', (card_id, name, access_level, department, status))
        
        conn.commit()
        conn.close()
        logger.info(f"Added user: {card_id} - {name}")
        return True
        
    except Exception as e:
        logger.error(f"Error adding user: {e}")
        return False

def get_user(card_id: str) -> Optional[Dict[str, Any]]:
    """
    Get user by card ID for AUTHORIZATION purposes
    
    IMPORTANT: This function ONLY checks the 'users' table.
    It does NOT check scan_events - those are audit logs only.
    If a user is deleted, they will NOT be found here and access will be denied.
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM users WHERE card_id = ?', (card_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'card_id': row[0],
                'name': row[1],
                'access_level': row[2],
                'department': row[3],
                'status': row[4],
                'created_date': row[5],
                'last_access': row[6]
            }
        return None
        
    except Exception as e:
        logger.error(f"Error getting user: {e}")
        return None

def get_all_users() -> List[Dict[str, Any]]:
    """Get all users"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM users ORDER BY name')
        rows = cursor.fetchall()
        conn.close()
        
        users = []
        for row in rows:
            users.append({
                'card_id': row[0],
                'name': row[1],
                'access_level': row[2],
                'department': row[3],
                'status': row[4],
                'created_date': row[5],
                'last_access': row[6]
            })
        return users
        
    except Exception as e:
        logger.error(f"Error getting all users: {e}")
        return []

def update_user(card_id: str, name: str, access_level: str, department: str, status: str) -> bool:
    """Update user information"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE users SET name = ?, access_level = ?, department = ?, status = ?
            WHERE card_id = ?
        ''', (name, access_level, department, status, card_id))
        
        conn.commit()
        conn.close()
        logger.info(f"Updated user: {card_id}")
        return True
        
    except Exception as e:
        logger.error(f"Error updating user: {e}")
        return False

def remove_user(card_id: str) -> bool:
    """
    COMPLETE USER REMOVAL - Removes user from all operational tables while preserving audit logs
    
    This function removes the user from:
    - users table (so they can't access the shear anymore)
    - pending_requests table (removes any pending access requests)
    
    This function PRESERVES:
    - scan_events table (for historical audit/usage tracking)
    
    After removal, the card will be treated as "unknown" if scanned again.
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Remove from users table (so they can't access anymore)
        cursor.execute('DELETE FROM users WHERE card_id = ?', (card_id,))
        users_removed = cursor.rowcount
        
        # Also remove any pending requests for this card
        cursor.execute('DELETE FROM pending_requests WHERE card_id = ?', (card_id,))
        pending_removed = cursor.rowcount
        
        # Note: We intentionally keep scan_events for audit purposes
        # These logs are read-only and never used for authorization
        
        conn.commit()
        conn.close()
        
        logger.info(f"User removal complete for {card_id}: {users_removed} user records, {pending_removed} pending requests removed. Audit logs preserved.")
        return True
        
    except Exception as e:
        logger.error(f"Error removing user: {e}")
        return False

def verify_user_removal(card_id: str) -> Dict[str, Any]:
    """
    Verify that a user has been completely removed from operational tables
    Returns status of removal and any remaining references
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Check users table
        cursor.execute('SELECT COUNT(*) FROM users WHERE card_id = ?', (card_id,))
        users_count = cursor.fetchone()[0]
        
        # Check pending_requests table  
        cursor.execute('SELECT COUNT(*) FROM pending_requests WHERE card_id = ?', (card_id,))
        pending_count = cursor.fetchone()[0]
        
        # Check scan_events table (these should remain for audit)
        cursor.execute('SELECT COUNT(*) FROM scan_events WHERE card_id = ?', (card_id,))
        scan_events_count = cursor.fetchone()[0]
        
        conn.close()
        
        is_completely_removed = (users_count == 0 and pending_count == 0)
        
        return {
            'card_id': card_id,
            'completely_removed': is_completely_removed,
            'users_remaining': users_count,
            'pending_requests_remaining': pending_count,
            'audit_logs_preserved': scan_events_count,
            'status': 'COMPLETELY REMOVED' if is_completely_removed else 'INCOMPLETE REMOVAL'
        }
        
    except Exception as e:
        logger.error(f"Error verifying user removal: {e}")
        return {
            'card_id': card_id,
            'completely_removed': False,
            'error': str(e)
        }

def update_user_status(card_id: str, status: str) -> bool:
    """Update user status"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute('UPDATE users SET status = ? WHERE card_id = ?', (status, card_id))
        
        conn.commit()
        conn.close()
        return True
        
    except Exception as e:
        logger.error(f"Error updating user status: {e}")
        return False

def update_user_last_access(card_id: str) -> bool:
    """Update user's last access time"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        current_time = datetime.now().isoformat()
        cursor.execute('UPDATE users SET last_access = ? WHERE card_id = ?', (current_time, card_id))
        
        conn.commit()
        conn.close()
        return True
        
    except Exception as e:
        logger.error(f"Error updating user last access: {e}")
        return False

def add_pending_request(card_id: str, name: str, first_name: str = '', last_name: str = '', 
                       email: str = '', department: str = '', shift: str = '') -> bool:
    """Add a pending access request"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO pending_requests (card_id, name, first_name, last_name, email, department, shift)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (card_id, name, first_name, last_name, email, department, shift))
        
        conn.commit()
        conn.close()
        logger.info(f"Added pending request: {card_id} - {name}")
        return True
        
    except Exception as e:
        logger.error(f"Error adding pending request: {e}")
        return False

def get_pending_request(card_id: str) -> Optional[Dict[str, Any]]:
    """
    Get pending request by card ID for ACCESS REQUEST purposes
    
    IMPORTANT: This function ONLY checks the 'pending_requests' table.
    It does NOT check scan_events - those are audit logs only.
    If a user is deleted, their pending request is also removed.
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM pending_requests WHERE card_id = ?', (card_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'card_id': row[0],
                'name': row[1],
                'first_name': row[2],
                'last_name': row[3],
                'email': row[4],
                'department': row[5],
                'shift': row[6],
                'requested_date': row[7]
            }
        return None
        
    except Exception as e:
        logger.error(f"Error getting pending request: {e}")
        return None

def get_all_pending_requests() -> List[Dict[str, Any]]:
    """Get all pending requests"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM pending_requests ORDER BY requested_date')
        rows = cursor.fetchall()
        conn.close()
        
        requests = []
        for row in rows:
            requests.append({
                'card_id': row[0],
                'name': row[1],
                'first_name': row[2],
                'last_name': row[3],
                'email': row[4],
                'department': row[5],
                'shift': row[6],
                'requested_date': row[7]
            })
        return requests
        
    except Exception as e:
        logger.error(f"Error getting pending requests: {e}")
        return []

def remove_pending_request(card_id: str) -> bool:
    """Remove pending request"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM pending_requests WHERE card_id = ?', (card_id,))
        
        conn.commit()
        conn.close()
        logger.info(f"Removed pending request: {card_id}")
        return True
        
    except Exception as e:
        logger.error(f"Error removing pending request: {e}")
        return False

def remove_all_pending_requests() -> int:
    """Remove all pending requests and return count of removed requests"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Get count first
        cursor.execute('SELECT COUNT(*) FROM pending_requests')
        count = cursor.fetchone()[0]
        
        # Delete all
        cursor.execute('DELETE FROM pending_requests')
        
        conn.commit()
        conn.close()
        logger.info(f"Removed {count} pending requests")
        return count
        
    except Exception as e:
        logger.error(f"Error removing all pending requests: {e}")
        return 0

def log_scan_event(card_id: str, result: str = 'unknown') -> bool:
    """Log a card scan event"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO scan_events (card_id, result)
            VALUES (?, ?)
        ''', (card_id, result))
        
        conn.commit()
        conn.close()
        return True
        
    except Exception as e:
        logger.error(f"Error logging scan event: {e}")
        return False

def search_users(query: str) -> List[Dict[str, Any]]:
    """Search users by name, card ID, or department"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        search_pattern = f'%{query}%'
        cursor.execute('''
            SELECT * FROM users 
            WHERE card_id LIKE ? OR name LIKE ? OR department LIKE ?
            ORDER BY name
        ''', (search_pattern, search_pattern, search_pattern))
        
        rows = cursor.fetchall()
        conn.close()
        
        users = []
        for row in rows:
            users.append({
                'card_id': row[0],
                'name': row[1],
                'access_level': row[2],
                'department': row[3],
                'status': row[4],
                'created_date': row[5],
                'last_access': row[6]
            })
        return users
        
    except Exception as e:
        logger.error(f"Error searching users: {e}")
        return []
