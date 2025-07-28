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
        self.vendor_id = vendor_id or 0x0c27  # Default to RFIDeas RDR-6081AKU
        self.product_id = product_id or 0x3bfa
        self.device = None
        self.running = False
        self.monitor_thread = None
        self.card_buffer = []
        self.last_read_time = 0
        self.card_timeout = 0.5  # 500ms timeout between complete card reads
        
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
                logger.debug(f"Raw card data received: {data} (type: {type(data)})")
                # Print raw card data to console for debugging
                print(f"[CARD READER] Raw data: {data}")
                print(f"[CARD READER] Data type: {type(data)}")
                if isinstance(data, list):
                    print(f"[CARD READER] Hex data: {' '.join([f'{b:02x}' for b in data])}")
                else:
                    print(f"[CARD READER] Hex data: {data.hex()}")
                
                # Convert list to bytes if needed (hid.device.read() returns a list)
                if isinstance(data, list):
                    data = bytes(data)
                # Parse the raw data based on your card reader's protocol
                card_data = self.parse_card_data(data)
                return card_data
            
            return None
            
        except Exception as e:
            logger.error(f"Error reading card data: {e}")
            return None
    
    def parse_card_data(self, raw_data) -> Dict[str, Any]:
        """Parse raw card data into structured format for RDR-6081AKU"""
        try:
            # Convert list to bytes if needed
            if isinstance(raw_data, list):
                raw_data = bytes(raw_data)
            
            current_time = time.time()
            
            # Add non-zero bytes to buffer
            new_bytes = [b for b in raw_data if b != 0]
            if new_bytes:
                # If it's been too long since last read, start new card
                if current_time - self.last_read_time > self.card_timeout and self.card_buffer:
                    # Process previous card first
                    previous_card = self.process_card_buffer()
                    if previous_card:
                        # Clear buffer for new card
                        self.card_buffer = new_bytes
                        self.last_read_time = current_time
                        return previous_card
                    
                # Add to current buffer
                self.card_buffer.extend(new_bytes)
                self.last_read_time = current_time
                
                # Check if we have enough data for a complete card (minimum 4 bytes)
                if len(self.card_buffer) >= 4:
                    # Try to process the current buffer
                    card_result = self.process_card_buffer()
                    if card_result:
                        # Reset buffer for next card
                        self.card_buffer = []
                        return card_result
            
            return None  # No complete card yet
            
        except Exception as e:
            logger.error(f"Error parsing card data: {e}")
            # Handle the case where raw_data might be a list
            if isinstance(raw_data, list):
                raw_data = bytes(raw_data)
            
            return {
                'card_id': raw_data.hex().upper(),
                'raw_data': raw_data.hex().upper(),
                'timestamp': time.time(),
                'reader_id': 'RDR-6081AKU',
                'card_type': 'proximity',
                'parse_error': str(e)
            }
    
    def process_card_buffer(self) -> Optional[Dict[str, Any]]:
        """Process the collected card buffer into a card data dictionary"""
        if not self.card_buffer:
            return None
        
        try:
            # Create hex string from buffer
            hex_data = ''.join([f"{b:02x}" for b in self.card_buffer]).upper()
            
            # Method 1: Use hex as card ID (most reliable for RDR-6081AKU)
            card_id = hex_data
            
            # Method 2: Check if it contains readable ASCII
            ascii_data = ''.join([chr(b) for b in self.card_buffer if 32 <= b <= 126])
            
            # Method 3: Extract any numeric patterns
            numeric_data = ''.join([chr(b) for b in self.card_buffer if 48 <= b <= 57])
            
            logger.info(f"Card processed - ID: {card_id}, ASCII: '{ascii_data}', Numeric: '{numeric_data}'")
            
            # Print card processing info to console
            print(f"[CARD READER] ========== CARD PROCESSED ==========")
            print(f"[CARD READER] Card ID: {card_id}")
            print(f"[CARD READER] Raw hex: {hex_data}")
            print(f"[CARD READER] ASCII data: '{ascii_data}'")
            print(f"[CARD READER] Numeric data: '{numeric_data}'")
            print(f"[CARD READER] Buffer length: {len(self.card_buffer)} bytes")
            print(f"[CARD READER] =====================================")
            
            return {
                'card_id': card_id,
                'raw_data': hex_data,
                'ascii_data': ascii_data,
                'numeric_data': numeric_data,
                'facility_code': None,  # RDR-6081AKU doesn't typically separate facility code
                'card_number': None,
                'timestamp': time.time(),
                'reader_id': 'RDR-6081AKU',
                'card_type': 'proximity',
                'buffer_length': len(self.card_buffer)
            }
            
        except Exception as e:
            logger.error(f"Error processing card buffer: {e}")
            return None
    
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
