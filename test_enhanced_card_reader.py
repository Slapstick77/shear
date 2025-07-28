#!/usr/bin/env python3
"""
Enhanced test script for RDR-6081AKU card reader
This script will collect a complete card read sequence and parse it properly
"""

import hid
import time
import logging
from collections import defaultdict

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class RDRCardReader:
    """Enhanced RDR-6081AKU card reader"""
    
    def __init__(self):
        self.device = None
        self.card_buffer = []
        self.last_read_time = 0
        self.card_timeout = 0.5  # 500ms timeout between card reads
        
    def connect(self):
        """Connect to the RDR-6081AKU"""
        try:
            self.device = hid.device()
            # RFIDeas RDR-6081AKU vendor/product ID
            self.device.open(0x0c27, 0x3bfa)
            self.device.set_nonblocking(1)
            logger.info("Connected to RDR-6081AKU")
            return True
        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            return False
    
    def read_card_sequence(self, timeout=5):
        """Read complete card sequence"""
        print(f"Reading card for {timeout} seconds. Please scan a card...")
        
        self.card_buffer = []
        start_time = time.time()
        last_data_time = 0
        
        while time.time() - start_time < timeout:
            try:
                data = self.device.read(64)
                if data:
                    current_time = time.time()
                    
                    # If it's been more than card_timeout since last data, start new card
                    if current_time - last_data_time > self.card_timeout and self.card_buffer:
                        # Process previous card
                        card_id = self.process_card_buffer()
                        if card_id:
                            print(f"\n*** CARD READ COMPLETE ***")
                            print(f"Card ID: {card_id}")
                            print(f"Raw sequence: {[hex(b) for b in self.card_buffer]}")
                            return card_id
                        
                        # Clear buffer for new card
                        self.card_buffer = []
                    
                    # Add non-zero bytes to buffer
                    for byte in data:
                        if byte != 0:
                            self.card_buffer.append(byte)
                            print(f"Received byte: 0x{byte:02x} ({chr(byte) if 32 <= byte <= 126 else '?'})")
                    
                    last_data_time = current_time
                
                time.sleep(0.01)  # Small delay
                
            except Exception as e:
                logger.error(f"Error reading: {e}")
                break
        
        # Process any remaining data
        if self.card_buffer:
            card_id = self.process_card_buffer()
            if card_id:
                print(f"\n*** CARD READ COMPLETE ***")
                print(f"Card ID: {card_id}")
                print(f"Raw sequence: {[hex(b) for b in self.card_buffer]}")
                return card_id
        
        print("No complete card read detected")
        return None
    
    def process_card_buffer(self):
        """Process the collected card buffer into a card ID"""
        if not self.card_buffer:
            return None
        
        # Method 1: Check if it's all ASCII printable characters
        ascii_chars = ''.join([chr(b) for b in self.card_buffer if 32 <= b <= 126])
        if len(ascii_chars) >= 3:
            # Remove spaces and special characters, keep alphanumeric
            clean_id = ''.join([c for c in ascii_chars if c.isalnum()])
            if clean_id:
                return clean_id
        
        # Method 2: Convert to hex string
        hex_string = ''.join([f"{b:02x}" for b in self.card_buffer])
        if len(hex_string) >= 6:
            return hex_string.upper()
        
        # Method 3: Try to extract numeric patterns
        numbers = ''.join([chr(b) for b in self.card_buffer if 48 <= b <= 57])  # ASCII digits
        if len(numbers) >= 3:
            return numbers
        
        # Fallback: use raw hex
        return ''.join([f"{b:02x}" for b in self.card_buffer]).upper()
    
    def disconnect(self):
        """Disconnect from device"""
        if self.device:
            self.device.close()
            logger.info("Disconnected from RDR-6081AKU")

def main():
    """Main test function"""
    print("Enhanced RDR-6081AKU Card Reader Test")
    print("=" * 40)
    
    reader = RDRCardReader()
    
    if not reader.connect():
        print("Failed to connect to card reader")
        return
    
    try:
        for i in range(3):
            print(f"\n--- Test {i+1} ---")
            card_id = reader.read_card_sequence(timeout=10)
            if card_id:
                print(f"Successfully read card: {card_id}")
            else:
                print("No card detected")
            
            if i < 2:
                input("Press Enter for next test...")
    
    finally:
        reader.disconnect()

if __name__ == "__main__":
    main()
