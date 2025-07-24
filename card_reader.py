"""
Card Reader Module
Handles USB HID card reader communication
"""

import hid
import threading
import time
import logging
from typing import Optional, Callable, Dict, Any

logger = logging.getLogger(__name__)

class CardReader:
    """USB HID Card Reader handler"""
    
    def __init__(self, on_card_read: Optional[Callable] = None, vendor_id: Optional[int] = None, product_id: Optional[int] = None):
        self.on_card_read = on_card_read
        self.vendor_id = vendor_id
        self.product_id = product_id
        self.device = None
        self.running = False
        self.monitor_thread = None
        
    def find_card_reader(self) -> Optional[Dict[str, Any]]:
        """Find connected card reader device"""
        try:
            # List all HID devices
            devices = hid.enumerate()
            
            # If specific vendor/product ID provided, look for that
            if self.vendor_id and self.product_id:
                for device_info in devices:
                    if (device_info['vendor_id'] == self.vendor_id and 
                        device_info['product_id'] == self.product_id):
                        return device_info
            
            # Look for RDR-6081AKU specifically (HID Global devices often use vendor ID 0x076b)
            rdr_6081_patterns = [
                {'vendor_id': 0x076b, 'product_name_contains': ['rdr', '6081']},  # HID Global
                {'vendor_id': 0x0c27, 'product_name_contains': ['rdr', '6081']},  # Alternative vendor
                {'vendor_id': 0x08f2, 'product_name_contains': ['rdr', '6081']},  # Another common vendor
            ]
            
            for device_info in devices:
                product_name = device_info.get('product_string', '').lower()
                manufacturer = device_info.get('manufacturer_string', '').lower()
                
                # Check for specific RDR-6081AKU patterns
                for pattern in rdr_6081_patterns:
                    if device_info['vendor_id'] == pattern['vendor_id']:
                        for name_part in pattern['product_name_contains']:
                            if name_part in product_name:
                                logger.info(f"Found RDR-6081AKU card reader: {device_info}")
                                return device_info
            
            # Otherwise, look for common card reader patterns
            card_reader_keywords = ['card', 'reader', 'rfid', 'proximity', 'hid', 'rdr']
            
            for device_info in devices:
                product_name = device_info.get('product_string', '').lower()
                manufacturer = device_info.get('manufacturer_string', '').lower()
                
                for keyword in card_reader_keywords:
                    if keyword in product_name or keyword in manufacturer:
                        logger.info(f"Found potential card reader: {device_info}")
                        return device_info
            
            # If no specific card reader found, list available devices for debugging
            logger.info("Available HID devices:")
            for device_info in devices:
                logger.info(f"  VID: {device_info['vendor_id']:04x}, "
                          f"PID: {device_info['product_id']:04x}, "
                          f"Product: {device_info.get('product_string', 'Unknown')}")
            
            return None
            
        except Exception as e:
            logger.error(f"Error finding card reader: {e}")
            return None
    
    def connect(self) -> bool:
        """Connect to card reader"""
        try:
            device_info = self.find_card_reader()
            if not device_info:
                logger.warning("No card reader found")
                return False
            
            self.device = hid.device()
            self.device.open(device_info['vendor_id'], device_info['product_id'])
            
            # Set non-blocking mode
            self.device.set_nonblocking(1)
            
            logger.info(f"Connected to card reader: {device_info.get('product_string', 'Unknown')}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to card reader: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from card reader"""
        try:
            if self.device:
                self.device.close()
                self.device = None
            logger.info("Disconnected from card reader")
        except Exception as e:
            logger.error(f"Error disconnecting card reader: {e}")
    
    def is_connected(self) -> bool:
        """Check if card reader is connected"""
        return self.device is not None
    
    def get_device_info(self) -> Optional[Dict[str, Any]]:
        """Get device information"""
        if not self.device:
            return None
        
        try:
            return {
                'manufacturer': self.device.get_manufacturer_string(),
                'product': self.device.get_product_string(),
                'serial': self.device.get_serial_number_string()
            }
        except Exception as e:
            logger.error(f"Error getting device info: {e}")
            return None
    
    def read_card_data(self) -> Optional[Dict[str, Any]]:
        """Read data from card reader"""
        if not self.device:
            return None
        
        try:
            # Read data from device (adjust buffer size as needed)
            data = self.device.read(64)
            
            if data:
                # Parse the raw data based on your card reader's protocol
                card_data = self.parse_card_data(data)
                return card_data
            
            return None
            
        except Exception as e:
            logger.error(f"Error reading card data: {e}")
            return None
    
    def parse_card_data(self, raw_data: bytes) -> Dict[str, Any]:
        """Parse raw card data into structured format for RDR-6081AKU"""
        try:
            # RDR-6081AKU typically sends proximity card data in specific formats
            # Common formats:
            # - 26-bit Wiegand format
            # - Raw facility code + card number
            # - ASCII encoded numbers
            
            # Convert to hex string
            hex_data = raw_data.hex().upper()
            
            # Remove null bytes and clean up
            clean_data = bytes([b for b in raw_data if b != 0])
            
            # Try to extract card ID using different methods
            card_id = None
            
            # Method 1: Look for ASCII digits (common with RDR-6081AKU)
            ascii_data = ''.join([chr(b) for b in clean_data if 32 <= b <= 126])
            if ascii_data.isdigit() and len(ascii_data) >= 3:
                card_id = ascii_data
                logger.info(f"Extracted ASCII card ID: {card_id}")
            
            # Method 2: Parse Wiegand 26-bit format (if applicable)
            elif len(clean_data) >= 3:
                # Try to parse as 26-bit Wiegand
                if len(clean_data) == 3:
                    # 3-byte format: facility code (1 byte) + card number (2 bytes)
                    facility_code = clean_data[0]
                    card_number = (clean_data[1] << 8) | clean_data[2]
                    card_id = f"{facility_code:03d}{card_number:05d}"
                    logger.info(f"Extracted Wiegand card ID: {card_id} (Facility: {facility_code}, Card: {card_number})")
                elif len(clean_data) == 4:
                    # 4-byte format
                    card_number = int.from_bytes(clean_data, byteorder='big')
                    card_id = str(card_number)
                    logger.info(f"Extracted 4-byte card ID: {card_id}")
            
            # Method 3: Use hex representation as fallback
            if not card_id and len(hex_data) > 4:
                # Remove leading zeros and use hex
                card_id = hex_data.lstrip('0') or '0'
                logger.info(f"Using hex card ID: {card_id}")
            
            # Method 4: Last resort - use full hex
            if not card_id:
                card_id = hex_data
                logger.warning(f"Using raw hex as card ID: {card_id}")
            
            return {
                'card_id': card_id,
                'raw_data': hex_data,
                'ascii_data': ascii_data,
                'facility_code': getattr(self, '_last_facility_code', None),
                'card_number': getattr(self, '_last_card_number', None),
                'timestamp': time.time(),
                'reader_id': 'RDR-6081AKU',
                'card_type': 'proximity'
            }
            
        except Exception as e:
            logger.error(f"Error parsing card data: {e}")
            return {
                'card_id': raw_data.hex().upper(),
                'raw_data': raw_data.hex().upper(),
                'timestamp': time.time(),
                'reader_id': 'RDR-6081AKU',
                'card_type': 'proximity',
                'parse_error': str(e)
            }
    
    def monitor_loop(self):
        """Main monitoring loop"""
        logger.info("Card reader monitoring started")
        
        while self.running:
            try:
                if not self.is_connected():
                    # Try to reconnect
                    if self.connect():
                        logger.info("Card reader reconnected")
                    else:
                        time.sleep(5)  # Wait before retry
                        continue
                
                # Read card data
                card_data = self.read_card_data()
                
                if card_data and self.on_card_read:
                    self.on_card_read(card_data)
                
                time.sleep(0.1)  # Small delay to prevent excessive CPU usage
                
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
                time.sleep(1)
        
        logger.info("Card reader monitoring stopped")
    
    def start_monitoring(self):
        """Start monitoring for card reads"""
        if self.running:
            logger.warning("Card reader monitoring already running")
            return
        
        if not self.connect():
            logger.error("Failed to connect to card reader")
            return
        
        self.running = True
        self.monitor_thread = threading.Thread(target=self.monitor_loop, daemon=True)
        self.monitor_thread.start()
        logger.info("Card reader monitoring thread started")
    
    def stop_monitoring(self):
        """Stop monitoring for card reads"""
        self.running = False
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=5)
        self.disconnect()
        logger.info("Card reader monitoring stopped")
