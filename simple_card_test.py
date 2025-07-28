#!/usr/bin/env python3
"""
Simple card reader test to debug the RDR-6081AKU data format
"""

import hid
import time
import logging

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def simple_card_test():
    """Simple test to see raw data from RDR-6081AKU"""
    print("Simple RDR-6081AKU Card Reader Test")
    print("=" * 40)
    
    try:
        # Connect directly to the card reader
        device = hid.device()
        device.open(0x0c27, 0x3bfa)  # RFIDeas vendor/product ID
        device.set_nonblocking(1)
        
        print("✓ Connected to card reader")
        print("Waiting for card scan... (Press Ctrl+C to exit)")
        print()
        
        scan_count = 0
        while True:
            try:
                # Read raw data
                data = device.read(64)
                
                if data:
                    scan_count += 1
                    print(f"\n--- Scan #{scan_count} ---")
                    print(f"Raw data type: {type(data)}")
                    print(f"Raw data length: {len(data)}")
                    print(f"Raw data: {data}")
                    
                    # Convert to bytes if it's a list
                    if isinstance(data, list):
                        byte_data = bytes(data)
                        print(f"As bytes: {byte_data}")
                        print(f"As hex: {byte_data.hex().upper()}")
                        
                        # Remove null bytes
                        clean_data = bytes([b for b in data if b != 0])
                        print(f"Clean data: {clean_data}")
                        if clean_data:
                            print(f"Clean hex: {clean_data.hex().upper()}")
                            
                            # Try to interpret as ASCII
                            try:
                                ascii_data = clean_data.decode('ascii')
                                print(f"ASCII: '{ascii_data}'")
                            except:
                                print("Cannot decode as ASCII")
                                
                            # Try individual bytes as characters
                            chars = []
                            for b in clean_data:
                                if 32 <= b <= 126:  # Printable ASCII
                                    chars.append(chr(b))
                                else:
                                    chars.append(f"[{b:02x}]")
                            print(f"Character interpretation: {''.join(chars)}")
                    
                    print("---" * 10)
                
                time.sleep(0.1)
                
            except KeyboardInterrupt:
                print("\nTest interrupted by user")
                break
                
        device.close()
        print("Device disconnected")
        
    except Exception as e:
        print(f"Error: {e}")
        
if __name__ == "__main__":
    simple_card_test()
