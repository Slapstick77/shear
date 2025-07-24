"""
Card Management Module
Handles card validation, access lists, and user management
"""

import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import os

logger = logging.getLogger(__name__)

class CardManager:
    """Manages card access lists and validation"""
    
    def __init__(self, access_list_file: str = 'access_list.json'):
        self.access_list_file = access_list_file
        self.access_list = {}
        self.load_access_list()
    
    def load_access_list(self):
        """Load access list from JSON file"""
        try:
            if os.path.exists(self.access_list_file):
                with open(self.access_list_file, 'r') as f:
                    self.access_list = json.load(f)
                logger.info(f"Loaded {len(self.access_list)} cards from access list")
            else:
                # Create default access list
                self.create_default_access_list()
                logger.info("Created default access list")
        except Exception as e:
            logger.error(f"Error loading access list: {e}")
            self.create_default_access_list()
    
    def save_access_list(self):
        """Save access list to JSON file"""
        try:
            with open(self.access_list_file, 'w') as f:
                json.dump(self.access_list, f, indent=2, default=str)
            logger.info("Access list saved successfully")
        except Exception as e:
            logger.error(f"Error saving access list: {e}")
    
    def create_default_access_list(self):
        """Create a default access list with sample cards"""
        self.access_list = {
            "001": {
                "name": "Test Admin",
                "department": "Administration",
                "access_level": "admin",
                "active": True,
                "created_date": datetime.now().isoformat(),
                "last_access": None,
                "access_times": None,  # No time restrictions - 24/7 access
                "notes": "Test admin card - full access"
            },
            "002": {
                "name": "Test Manager",
                "department": "Management",
                "access_level": "manager",
                "active": True,
                "created_date": datetime.now().isoformat(),
                "last_access": None,
                "access_times": None,  # No time restrictions - 24/7 access
                "notes": "Test manager card"
            },
            "003": {
                "name": "Test User",
                "department": "Operations",
                "access_level": "user",
                "active": True,
                "created_date": datetime.now().isoformat(),
                "last_access": None,
                "access_times": None,  # No time restrictions - 24/7 access
                "notes": "Test user card - basic access"
            },
            "004": {
                "name": "Test User 2",
                "department": "Operations",
                "access_level": "user",
                "active": True,
                "created_date": datetime.now().isoformat(),
                "last_access": None,
                "access_times": None,  # No time restrictions - 24/7 access
                "notes": "Test user card - basic access"
            },
            "345678": {
                "name": "Bob Johnson",
                "department": "Maintenance",
                "access_level": "user",
                "active": False,
                "created_date": datetime.now().isoformat(),
                "last_access": None,
                "access_times": {
                    "monday": {"start": "09:00", "end": "17:00"},
                    "tuesday": {"start": "09:00", "end": "17:00"},
                    "wednesday": {"start": "09:00", "end": "17:00"},
                    "thursday": {"start": "09:00", "end": "17:00"},
                    "friday": {"start": "09:00", "end": "17:00"},
                    "saturday": None,
                    "sunday": None
                },
                "notes": "Access temporarily disabled"
            }
        }
        self.save_access_list()
    
    def validate_card(self, card_id: str) -> Dict[str, Any]:
        """Validate a card and return access decision"""
        result = {
            'valid': False,
            'access_granted': False,
            'user_info': None,
            'reason': 'Unknown card',
            'timestamp': datetime.now().isoformat()
        }
        
        # Clean card ID (remove whitespace, convert to string)
        card_id = str(card_id).strip()
        
        if not card_id:
            result['reason'] = 'Empty card ID'
            return result
        
        # Check if card exists in access list
        if card_id not in self.access_list:
            result['reason'] = f'Card {card_id} not found in access list'
            logger.warning(f"Unknown card attempted access: {card_id}")
            return result
        
        user = self.access_list[card_id]
        result['valid'] = True
        result['user_info'] = user.copy()
        
        # Check if card is active
        if not user.get('active', False):
            result['reason'] = f'Card {card_id} is deactivated'
            logger.warning(f"Deactivated card attempted access: {card_id} ({user.get('name', 'Unknown')})")
            return result
        
        # Check time-based access
        if not self._check_time_access(user):
            result['reason'] = f'Access denied - outside allowed hours'
            logger.info(f"Time-based access denied for {card_id} ({user.get('name', 'Unknown')})")
            return result
        
        # Access granted
        result['access_granted'] = True
        result['reason'] = 'Access granted'
        
        # Update last access time
        self.access_list[card_id]['last_access'] = datetime.now().isoformat()
        self.save_access_list()
        
        logger.info(f"Access granted for {card_id} ({user.get('name', 'Unknown')})")
        return result
    
    def _check_time_access(self, user: Dict[str, Any]) -> bool:
        """Check if current time is within allowed access hours"""
        try:
            access_times = user.get('access_times')
            
            # If access_times is None, allow 24/7 access
            if access_times is None:
                return True
            
            now = datetime.now()
            current_day = now.strftime('%A').lower()
            current_time = now.strftime('%H:%M')
            
            day_access = access_times.get(current_day)
            
            # If no access defined for this day, deny access
            if day_access is None:
                return False
            
            # If day access is set but empty, deny access
            if not day_access:
                return False
            
            start_time = day_access.get('start')
            end_time = day_access.get('end')
            
            if not start_time or not end_time:
                return False
            
            # Convert times to datetime objects for comparison
            start_dt = datetime.strptime(start_time, '%H:%M').time()
            end_dt = datetime.strptime(end_time, '%H:%M').time()
            current_dt = datetime.strptime(current_time, '%H:%M').time()
            
            # Handle overnight access (e.g., 22:00 to 06:00)
            if start_dt > end_dt:
                return current_dt >= start_dt or current_dt <= end_dt
            else:
                return start_dt <= current_dt <= end_dt
                
        except Exception as e:
            logger.error(f"Error checking time access: {e}")
            # Default to allow access if there's an error
            return True
    
    def add_card(self, card_id: str, name: str, department: str = "", 
                 access_level: str = "limited", notes: str = "") -> bool:
        """Add a new card to the access list"""
        try:
            card_id = str(card_id).strip()
            
            if card_id in self.access_list:
                logger.warning(f"Card {card_id} already exists")
                return False
            
            self.access_list[card_id] = {
                "name": name,
                "department": department,
                "access_level": access_level,
                "active": True,
                "created_date": datetime.now().isoformat(),
                "last_access": None,
                "access_times": {
                    "monday": {"start": "08:00", "end": "18:00"},
                    "tuesday": {"start": "08:00", "end": "18:00"},
                    "wednesday": {"start": "08:00", "end": "18:00"},
                    "thursday": {"start": "08:00", "end": "18:00"},
                    "friday": {"start": "08:00", "end": "18:00"},
                    "saturday": None,
                    "sunday": None
                },
                "notes": notes
            }
            
            self.save_access_list()
            logger.info(f"Added new card: {card_id} ({name})")
            return True
            
        except Exception as e:
            logger.error(f"Error adding card: {e}")
            return False
    
    def remove_card(self, card_id: str) -> bool:
        """Remove a card from the access list"""
        try:
            card_id = str(card_id).strip()
            
            if card_id not in self.access_list:
                logger.warning(f"Card {card_id} not found")
                return False
            
            user_name = self.access_list[card_id].get('name', 'Unknown')
            del self.access_list[card_id]
            self.save_access_list()
            logger.info(f"Removed card: {card_id} ({user_name})")
            return True
            
        except Exception as e:
            logger.error(f"Error removing card: {e}")
            return False
    
    def activate_card(self, card_id: str) -> bool:
        """Activate a card"""
        return self._set_card_status(card_id, True)
    
    def deactivate_card(self, card_id: str) -> bool:
        """Deactivate a card"""
        return self._set_card_status(card_id, False)
    
    def _set_card_status(self, card_id: str, active: bool) -> bool:
        """Set card active status"""
        try:
            card_id = str(card_id).strip()
            
            if card_id not in self.access_list:
                logger.warning(f"Card {card_id} not found")
                return False
            
            self.access_list[card_id]['active'] = active
            self.save_access_list()
            
            user_name = self.access_list[card_id].get('name', 'Unknown')
            status = "activated" if active else "deactivated"
            logger.info(f"Card {status}: {card_id} ({user_name})")
            return True
            
        except Exception as e:
            logger.error(f"Error setting card status: {e}")
            return False
    
    def get_all_cards(self) -> Dict[str, Any]:
        """Get all cards in the access list"""
        return self.access_list.copy()
    
    def get_card_info(self, card_id: str) -> Optional[Dict[str, Any]]:
        """Get information for a specific card"""
        card_id = str(card_id).strip()
        return self.access_list.get(card_id)
    
    def get_access_stats(self) -> Dict[str, Any]:
        """Get access statistics"""
        total_cards = len(self.access_list)
        active_cards = sum(1 for card in self.access_list.values() if card.get('active', False))
        inactive_cards = total_cards - active_cards
        
        # Count by access level
        access_levels = {}
        for card in self.access_list.values():
            level = card.get('access_level', 'unknown')
            access_levels[level] = access_levels.get(level, 0) + 1
        
        return {
            'total_cards': total_cards,
            'active_cards': active_cards,
            'inactive_cards': inactive_cards,
            'access_levels': access_levels
        }
    
    def search_cards(self, query: str) -> Dict[str, Any]:
        """Search for cards by name, department, or card ID"""
        query = query.lower().strip()
        results = {}
        
        for card_id, user in self.access_list.items():
            if (query in card_id.lower() or 
                query in user.get('name', '').lower() or 
                query in user.get('department', '').lower()):
                results[card_id] = user
        
        return results
