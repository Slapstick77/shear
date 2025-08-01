#!/usr/bin/env python3
"""
Card ID Fixer Utility
Helps identify and fix duplicate card ID issues in the database
"""

import database as db
import sqlite3
import os

def analyze_card_data():
    """Analyze current card data for potential duplicates"""
    
    print("=== CARD DATABASE ANALYSIS ===")
    
    # Get all users and pending requests
    users = db.get_all_users()
    pending = db.get_all_pending_requests()
    
    print(f"\nFound {len(users)} users and {len(pending)} pending requests")
    
    # Check for exact duplicates
    user_cards = [u['card_id'] for u in users]
    pending_cards = [p['card_id'] for p in pending]
    
    duplicates = set(user_cards) & set(pending_cards)
    if duplicates:
        print(f"\n🚨 DUPLICATE CARD IDs FOUND: {duplicates}")
        
        for dup_id in duplicates:
            user = next((u for u in users if u['card_id'] == dup_id), None)
            pend = next((p for p in pending if p['card_id'] == dup_id), None)
            
            print(f"  Card ID: {dup_id}")
            if user:
                print(f"    USER: {user['name']} ({user['role']})")
            if pend:
                print(f"    PENDING: {pend['first_name']} {pend['last_name']}")
    else:
        print("\n✅ No exact duplicate card IDs found")
    
    # Look for potential format variations
    print(f"\n=== POTENTIAL FORMAT VARIATIONS ===")
    
    all_ids = user_cards + pending_cards
    hex_ids = [id for id in all_ids if all(c in '0123456789ABCDEF' for c in id.upper()) and len(id) > 6]
    numeric_ids = [id for id in all_ids if id.isdigit()]
    ascii_ids = [id for id in all_ids if not id.isdigit() and not all(c in '0123456789ABCDEF' for c in id.upper())]
    
    print(f"Hex format IDs: {len(hex_ids)}")
    for id in hex_ids[:5]:  # Show first 5
        print(f"  {id}")
    if len(hex_ids) > 5:
        print(f"  ... and {len(hex_ids) - 5} more")
    
    print(f"Numeric format IDs: {len(numeric_ids)}")
    for id in numeric_ids[:5]:  # Show first 5
        print(f"  {id}")
    if len(numeric_ids) > 5:
        print(f"  ... and {len(numeric_ids) - 5} more")
        
    print(f"ASCII format IDs: {len(ascii_ids)}")
    for id in ascii_ids[:5]:  # Show first 5
        print(f"  {id}")
    if len(ascii_ids) > 5:
        print(f"  ... and {len(ascii_ids) - 5} more")

def remove_duplicates():
    """Remove duplicate card entries (keep user, remove pending)"""
    
    users = db.get_all_users()
    pending = db.get_all_pending_requests()
    
    user_cards = [u['card_id'] for u in users]
    pending_cards = [p['card_id'] for p in pending]
    
    duplicates = set(user_cards) & set(pending_cards)
    
    if not duplicates:
        print("No duplicates to remove")
        return
    
    print(f"Removing {len(duplicates)} duplicate pending requests...")
    
    for dup_id in duplicates:
        # Remove from pending_requests table
        result = db.remove_pending_request(dup_id)
        if result:
            print(f"✅ Removed pending request for card: {dup_id}")
        else:
            print(f"❌ Failed to remove pending request for card: {dup_id}")

def complete_user_removal(card_id):
    """Completely remove a user and verify the removal"""
    
    print(f"=== COMPLETE USER REMOVAL: {card_id} ===")
    
    # Remove user
    result = db.remove_user(card_id)
    if result:
        print(f"✅ User removal command executed successfully")
    else:
        print(f"❌ User removal command failed")
        return
    
    # Verify removal
    verification = db.verify_user_removal(card_id)
    
    print(f"\n--- VERIFICATION RESULTS ---")
    print(f"Card ID: {verification['card_id']}")
    print(f"Status: {verification['status']}")
    print(f"Users remaining: {verification['users_remaining']}")
    print(f"Pending requests remaining: {verification['pending_requests_remaining']}")
    print(f"Audit logs preserved: {verification['audit_logs_preserved']}")
    
    if verification['completely_removed']:
        print(f"✅ User {card_id} has been COMPLETELY REMOVED from operational tables")
        print(f"📊 {verification['audit_logs_preserved']} audit log entries preserved for historical tracking")
    else:
        print(f"❌ INCOMPLETE REMOVAL - some operational data may remain")

def purge_all_operational_data():
    """Purge all operational data while preserving audit logs"""
    
    print('=== PURGING ALL OPERATIONAL DATA ===')
    
    # Get counts before deletion
    users = db.get_all_users()
    pending = db.get_all_pending_requests()
    
    print(f'Before purge:')
    print(f'  Users: {len(users)}')
    print(f'  Pending requests: {len(pending)}')
    
    # Clear operational tables only
    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM users')
        users_deleted = cursor.rowcount
        
        cursor.execute('DELETE FROM pending_requests') 
        pending_deleted = cursor.rowcount
        
        # Get scan events count (NOT deleted)
        cursor.execute('SELECT COUNT(*) FROM scan_events')
        scans_preserved = cursor.fetchone()[0]
        
        conn.commit()
        conn.close()
        
        print(f'Purge complete:')
        print(f'  Users deleted: {users_deleted}')
        print(f'  Pending requests deleted: {pending_deleted}')
        print(f'  Scan events preserved: {scans_preserved}')
        print(f'✅ OPERATIONAL DATA PURGED - AUDIT LOGS PRESERVED')
        
    except Exception as e:
        print(f'❌ Error during purge: {e}')

def list_all_entries():
    """List all current database entries"""
    
    print("=== ALL DATABASE ENTRIES ===")
    
    users = db.get_all_users()
    pending = db.get_all_pending_requests()
    
    print(f"\n--- USERS ({len(users)}) ---")
    for user in users:
        print(f"Card ID: {user['card_id']} | Name: {user['name']} | Role: {user['role']}")
    
    print(f"\n--- PENDING REQUESTS ({len(pending)}) ---")
    for req in pending:
        print(f"Card ID: {req['card_id']} | Name: {req['first_name']} {req['last_name']} | Dept: {req['department']}")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 card_id_fixer.py analyze              - Analyze card data for issues")
        print("  python3 card_id_fixer.py list                 - List all entries")
        print("  python3 card_id_fixer.py remove-dups          - Remove duplicate entries")
        print("  python3 card_id_fixer.py remove-user <card_id> - Completely remove a user")
        print("  python3 card_id_fixer.py purge-all            - Purge all operational data (keep audit logs)")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "analyze":
        analyze_card_data()
    elif command == "list":
        list_all_entries()
    elif command == "remove-dups":
        remove_duplicates()
    elif command == "remove-user":
        if len(sys.argv) < 3:
            print("Error: Please provide card_id")
            print("Usage: python3 card_id_fixer.py remove-user <card_id>")
        else:
            complete_user_removal(sys.argv[2])
    elif command == "purge-all":
        purge_all_operational_data()
    else:
        print(f"Unknown command: {command}")
