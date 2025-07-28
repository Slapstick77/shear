#!/usr/bin/env python3
"""
Test script for RDR-6081AKU card reader
This script will help verify the card reader is working properly
"""

import hid
import time
import logging
from card_reader import CardReader

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_hid_detection():
    """Test if the card reader is detected as HID device"""
    print("\n=== HID Device Detection Test ===")
    
    try:
        devices = hid.enumerate()
        print(f"Found {len(devices)} HID devices:")
        
        rdr_found = False
        for i, device in enumerate(devices):
            vendor_id = device['vendor_id']
            product_id = device['product_id']
            product_string = device.get('product_string', 'Unknown')
            manufacturer = device.get('manufacturer_string', 'Unknown')
            
            print(f"{i+1}. VID: 0x{vendor_id:04x}, PID: 0x{product_id:04x}")
            print(f"   Manufacturer: {manufacturer}")
            print(f"   Product: {product_string}")
            
            # Check if this looks like our RDR-6081AKU
            if (vendor_id == 0x0c27 and product_id == 0x3bfa) or 'RFIDeas' in manufacturer:
                print("   *** This appears to be the RDR-6081AKU card reader! ***")
                rdr_found = True
            print()
        
        return rdr_found
        
    except Exception as e:
        print(f"Error enumerating HID devices: {e}")
        return False

def test_card_reader_connection():
    """Test connecting to the card reader"""
    print("\n=== Card Reader Connection Test ===")
    
    def on_card_read(card_data):
        """Callback function for card reads"""
        print(f"\n*** CARD DETECTED! ***")
        print(f"Card ID: {card_data.get('card_id', 'Unknown')}")
        print(f"Raw Data: {card_data.get('raw_data', 'None')}")
        print(f"ASCII Data: {card_data.get('ascii_data', 'None')}")
        print(f"Timestamp: {time.ctime(card_data.get('timestamp', time.time()))}")
        print(f"Reader: {card_data.get('reader_id', 'Unknown')}")
        print("*** END CARD DATA ***\n")
    
    # Create card reader instance with RFIDeas vendor ID
    reader = CardReader(on_card_read=on_card_read, vendor_id=0x0c27, product_id=0x3bfa)
    
    try:
        print("Attempting to connect to card reader...")
        if reader.connect():
            print("✓ Successfully connected to card reader!")
            
            # Get device info
            device_info = reader.get_device_info()
            if device_info:
                print(f"Device Info:")
                print(f"  Manufacturer: {device_info.get('manufacturer', 'Unknown')}")
                print(f"  Product: {device_info.get('product', 'Unknown')}")
                print(f"  Serial: {device_info.get('serial', 'Unknown')}")
            
            return reader
        else:
            print("✗ Failed to connect to card reader")
            return None
            
    except Exception as e:
        print(f"✗ Error connecting to card reader: {e}")
        return None

def test_card_reading(reader, duration=30):
    """Test reading cards for a specified duration"""
    print(f"\n=== Card Reading Test ({duration} seconds) ===")
    print("Please scan cards now...")
    
    try:
        reader.start_monitoring()
        print(f"Monitoring for {duration} seconds. Scan some cards!")
        
        start_time = time.time()
        while time.time() - start_time < duration:
            time.sleep(1)
            remaining = int(duration - (time.time() - start_time))
            if remaining % 5 == 0:  # Print every 5 seconds
                print(f"Still monitoring... {remaining} seconds remaining")
        
        print("Monitoring period complete.")
        reader.stop_monitoring()
        
    except KeyboardInterrupt:
        print("\nTest interrupted by user")
        reader.stop_monitoring()
    except Exception as e:
        print(f"Error during card reading test: {e}")
        reader.stop_monitoring()

def manual_read_test(reader):
    """Manual test - read data when Enter is pressed"""
    print("\n=== Manual Read Test ===")
    print("Press Enter to read card data (or 'q' to quit):")
    
    try:
        while True:
            user_input = input().strip().lower()
            if user_input == 'q':
                break
            
            print("Reading card data...")
            card_data = reader.read_card_data()
            if card_data:
                print(f"Card ID: {card_data.get('card_id', 'Unknown')}")
                print(f"Raw Data: {card_data.get('raw_data', 'None')}")
                print(f"ASCII Data: {card_data.get('ascii_data', 'None')}")
            else:
                print("No card data detected")
            
            print("\nPress Enter to read again (or 'q' to quit):")
            
    except KeyboardInterrupt:
        print("\nManual test interrupted")

def main():
    """Main test function"""
    print("RDR-6081AKU Card Reader Test Script")
    print("=" * 40)
    
    # Test 1: HID Detection
    if not test_hid_detection():
        print("⚠️  RDR-6081AKU not detected in HID devices")
        print("   Make sure the device is plugged in and recognized by the system")
        return
    
    # Test 2: Connection
    reader = test_card_reader_connection()
    if not reader:
        print("❌ Cannot proceed with tests - card reader connection failed")
        return
    
    try:
        # Test 3: Automatic card reading
        test_card_reading(reader, duration=20)
        
        # Test 4: Manual reading (optional)
        print("\nWould you like to try manual reading? (y/n): ", end="")
        if input().strip().lower() == 'y':
            manual_read_test(reader)
        
        print("\n✓ All tests completed!")
        
    finally:
        # Cleanup
        if reader:
            reader.stop_monitoring()
            reader.disconnect()
        print("Test script finished.")

if __name__ == "__main__":
    main()
