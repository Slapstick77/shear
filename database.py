import sqlite3
from datetime import datetime
from typing import Optional, List, Dict, Any

DB_PATH = 'shear_app.db'

def get_db():
    return sqlite3.connect(DB_PATH)

def init_db():
    """Initialize the database with all required tables"""
    with get_db() as conn:
        c = conn.cursor()
        
        # Users table
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            card_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            department TEXT,
            shift TEXT,
            access_level TEXT DEFAULT 'user',
            active INTEGER DEFAULT 1,
            created_date TEXT,
            last_access TEXT,
            notes TEXT
        )''')
        
        # Scan events table - logs every card scan
        c.execute('''CREATE TABLE IF NOT EXISTS scan_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            card_id TEXT,
            event_type TEXT,
            user_name TEXT,
            result TEXT,
            details TEXT
        )''')
        
        # Pending requests table
        c.execute('''CREATE TABLE IF NOT EXISTS pending_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_id TEXT,
            first_name TEXT,
            last_name TEXT,
            department TEXT,
            shift TEXT,
            request_time TEXT,
            status TEXT DEFAULT 'pending',
            UNIQUE(card_id)
        )''')
        
        # Departments table
        c.execute('''CREATE TABLE IF NOT EXISTS departments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE
        )''')
        
        # Shifts table
        c.execute('''CREATE TABLE IF NOT EXISTS shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE
        )''')
        
        # Add default departments and shifts
        default_departments = ['Production', 'Maintenance', 'Quality', 'Engineering', 'Administration', 'N/A']
        for dept in default_departments:
            c.execute('INSERT OR IGNORE INTO departments (name) VALUES (?)', (dept,))
        
        default_shifts = ['Day Shift', 'Night Shift', 'Weekend', 'N/A']
        for shift in default_shifts:
            c.execute('INSERT OR IGNORE INTO shifts (name) VALUES (?)', (shift,))
        
        conn.commit()

# Scan Events Functions
def log_scan_event(card_id: str, event_type: str = 'scan', user_name: str = None, result: str = None, details: str = None):
    """Log any scan event (scan, unlock, lock, etc.)"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''INSERT INTO scan_events 
                     (timestamp, card_id, event_type, user_name, result, details) 
                     VALUES (?, ?, ?, ?, ?, ?)''',
                  (datetime.now().isoformat(), card_id, event_type, user_name, result, details))
        conn.commit()

def get_scan_events(limit: int = 100) -> List[Dict]:
    """Get recent scan events"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''SELECT id, timestamp, card_id, event_type, user_name, result, details 
                     FROM scan_events ORDER BY timestamp DESC LIMIT ?''', (limit,))
        rows = c.fetchall()
        return [{'id': row[0], 'timestamp': row[1], 'card_id': row[2], 
                'event_type': row[3], 'user_name': row[4], 'result': row[5], 'details': row[6]} 
                for row in rows]

# User Management Functions
def get_user(card_id: str) -> Optional[Dict]:
    """Get user by card ID"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE card_id = ?', (card_id,))
        row = c.fetchone()
        if row:
            return {
                'card_id': row[0], 'name': row[1], 'department': row[2], 'shift': row[3],
                'access_level': row[4], 'active': bool(row[5]), 'created_date': row[6],
                'last_access': row[7], 'notes': row[8]
            }
        return None

def add_user(card_id: str, name: str, department: str = '', shift: str = '', 
             access_level: str = 'user', notes: str = '') -> bool:
    """Add a new user"""
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute('''INSERT INTO users 
                         (card_id, name, department, shift, access_level, active, created_date, notes)
                         VALUES (?, ?, ?, ?, ?, 1, ?, ?)''',
                      (card_id, name, department, shift, access_level, datetime.now().isoformat(), notes))
            conn.commit()
            return True
    except sqlite3.IntegrityError:
        return False

def update_user_last_access(card_id: str):
    """Update user's last access time"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('UPDATE users SET last_access = ? WHERE card_id = ?',
                  (datetime.now().isoformat(), card_id))
        conn.commit()

def get_all_users() -> List[Dict]:
    """Get all users"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM users ORDER BY name')
        rows = c.fetchall()
        return [{'card_id': row[0], 'name': row[1], 'department': row[2], 'shift': row[3],
                'access_level': row[4], 'active': bool(row[5]), 'created_date': row[6],
                'last_access': row[7], 'notes': row[8]} for row in rows]

# Pending Requests Functions
def get_pending_request(card_id: str) -> Optional[Dict]:
    """Get pending request by card ID"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM pending_requests WHERE card_id = ?', (card_id,))
        row = c.fetchone()
        if row:
            return {
                'id': row[0], 'card_id': row[1], 'first_name': row[2], 'last_name': row[3],
                'department': row[4], 'shift': row[5], 'request_time': row[6], 'status': row[7]
            }
        return None

def add_pending_request(card_id: str, first_name: str, last_name: str, 
                       department: str = '', shift: str = '') -> bool:
    """Add a new pending request"""
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute('''INSERT INTO pending_requests 
                         (card_id, first_name, last_name, department, shift, request_time)
                         VALUES (?, ?, ?, ?, ?, ?)''',
                      (card_id, first_name, last_name, department, shift, datetime.now().isoformat()))
            conn.commit()
            return True
    except sqlite3.IntegrityError:
        return False

def get_all_pending_requests() -> List[Dict]:
    """Get all pending requests"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM pending_requests WHERE status = "pending" ORDER BY request_time')
        rows = c.fetchall()
        return [{'id': row[0], 'card_id': row[1], 'first_name': row[2], 'last_name': row[3],
                'department': row[4], 'shift': row[5], 'request_time': row[6], 'status': row[7]}
                for row in rows]

def remove_pending_request(card_id: str) -> bool:
    """Remove a pending request"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('DELETE FROM pending_requests WHERE card_id = ?', (card_id,))
        conn.commit()
        return c.rowcount > 0

# Department and Shift Functions
def get_departments() -> List[str]:
    """Get all departments"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT name FROM departments ORDER BY name')
        return [row[0] for row in c.fetchall()]

def add_department(name: str) -> bool:
    """Add a new department"""
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute('INSERT INTO departments (name) VALUES (?)', (name,))
            conn.commit()
            return True
    except sqlite3.IntegrityError:
        return False

def get_shifts() -> List[str]:
    """Get all shifts"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT name FROM shifts ORDER BY name')
        return [row[0] for row in c.fetchall()]

def add_shift(name: str) -> bool:
    """Add a new shift"""
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute('INSERT INTO shifts (name) VALUES (?)', (name,))
            conn.commit()
            return True
    except sqlite3.IntegrityError:
        return False

def clear_all_pending_requests():
    """Clear all pending requests and return count of deleted requests"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM pending_requests')
        count = c.fetchone()[0]
        c.execute('DELETE FROM pending_requests')
        conn.commit()
        return count

if __name__ == '__main__':
    init_db()
    print('Database initialized.')

def get_all_users():
    """Get all users from the database"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM users ORDER BY name')
        rows = c.fetchall()
        
        users = []
        for row in rows:
            users.append({
                'card_id': row[0],
                'name': row[1],
                'department': row[2],
                'shift': row[3],
                'access_level': row[4],
                'active': row[5],
                'created_date': row[6],
                'last_access': row[7],
                'notes': row[8]
            })
        return users


def get_all_users():
    """Get all users from the database"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM users ORDER BY name')
        rows = c.fetchall()
        
        users = []
        for row in rows:
            users.append({
                'card_id': row[0],
                'name': row[1],
                'department': row[2],
                'shift': row[3],
                'access_level': row[4],
                'active': row[5],
                'created_date': row[6],
                'last_access': row[7],
                'notes': row[8]
            })
        return users


def update_user(card_id, name, department, shift, access_level):
    """Update an existing user"""
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute('''UPDATE users 
                        SET name = ?, department = ?, shift = ?, access_level = ?
                        WHERE card_id = ?''', 
                     (name, department, shift, access_level, card_id))
            conn.commit()
            return c.rowcount > 0
    except Exception as e:
        print(f'Error updating user: {e}')
        return False

def delete_user(card_id):
    """Delete a user"""
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute('DELETE FROM users WHERE card_id = ?', (card_id,))
            conn.commit()
            return c.rowcount > 0
    except Exception as e:
        print(f'Error deleting user: {e}')
        return False

