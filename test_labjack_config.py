#!/usr/bin/env python3
"""
LabJack U3 Configuration Test Script
Configures the U3 according to specifications:
- FIO0-FIO3 as analog inputs
- FIO4 & FIO5 as digital inputs
- FIO6 & FIO7 as digital outputs
"""

import time
import u3

def configure_labjack_u3():
    """Configure LabJack U3 with specified pin assignments"""
    try:
        # Connect to LabJack U3
        lj = u3.U3()
        print(f"Connected to LabJack U3 (SN: {lj.serialNumber})")
        print(f"Firmware Version: {lj.firmwareVersion}")
        print(f"Hardware Version: {lj.hardwareVersion}")
        
        # Configure I/O using configIO
        # FIOAnalog bitmask: 1=analog, 0=digital
        # FIO0-FIO3 = analog (bits 0-3 = 1), FIO4-FIO7 = digital (bits 4-7 = 0)
        # This gives us: 00001111 = 0x0F = 15
        
        # EIOAnalog bitmask: all digital (0)
        config_result = lj.configIO(
            FIOAnalog=15,     # FIO0-FIO3 analog, FIO4-FIO7 digital
            EIOAnalog=0       # All EIO pins digital
        )
        print(f"ConfigIO result: {config_result}")
        
        # Configure digital pins direction
        # FIO4 & FIO5 as inputs (direction = 0)
        lj.getFeedback(u3.BitDirWrite(4, 0))  # FIO4 as input
        lj.getFeedback(u3.BitDirWrite(5, 0))  # FIO5 as input
        print("Configured FIO4 & FIO5 as digital inputs")
        
        # FIO6 & FIO7 as outputs (direction = 1)
        lj.getFeedback(u3.BitDirWrite(6, 1))  # FIO6 as output
        lj.getFeedback(u3.BitDirWrite(7, 1))  # FIO7 as output
        print("Configured FIO6 & FIO7 as digital outputs")
        
        # Initialize outputs to LOW
        lj.getFeedback(u3.BitStateWrite(6, 0))  # FIO6 = LOW
        lj.getFeedback(u3.BitStateWrite(7, 0))  # FIO7 = LOW
        print("Initialized FIO6 & FIO7 to LOW state")
        
        # Configure pull-down resistors for digital inputs to prevent floating
        try:
            lj.writeRegister(5004, 0)  # FIO4 pull-down
            lj.writeRegister(5005, 0)  # FIO5 pull-down
            print("Configured pull-down resistors for FIO4 & FIO5")
        except Exception as e:
            print(f"Warning: Could not configure pull-down resistors: {e}")
        
        return lj
        
    except Exception as e:
        print(f"Error configuring LabJack U3: {e}")
        return None

def test_configuration(lj):
    """Test the configured LabJack U3"""
    if not lj:
        return
    
    print("\n--- Testing Configuration ---")
    
    # Test analog inputs (FIO0-FIO3 -> AIN0-AIN3)
    print("\nAnalog Inputs (FIO0-FIO3):")
    for i in range(4):
        try:
            voltage = lj.getAIN(i)
            print(f"  AIN{i} (FIO{i}): {voltage:.3f}V")
        except Exception as e:
            print(f"  AIN{i} (FIO{i}): Error - {e}")
    
    # Test digital inputs (FIO4 & FIO5)
    print("\nDigital Inputs:")
    for pin in [4, 5]:
        try:
            state = lj.getFeedback(u3.BitStateRead(pin))[0]
            print(f"  FIO{pin}: {'HIGH' if state else 'LOW'}")
        except Exception as e:
            print(f"  FIO{pin}: Error - {e}")
    
    # Test digital outputs (FIO6 & FIO7)
    print("\nTesting Digital Outputs:")
    for pin in [6, 7]:
        try:
            # Set HIGH
            lj.getFeedback(u3.BitStateWrite(pin, 1))
            time.sleep(0.1)
            state_high = lj.getFeedback(u3.BitStateRead(pin))[0]
            
            # Set LOW
            lj.getFeedback(u3.BitStateWrite(pin, 0))
            time.sleep(0.1)
            state_low = lj.getFeedback(u3.BitStateRead(pin))[0]
            
            print(f"  FIO{pin}: HIGH={state_high}, LOW={state_low} - {'OK' if state_high and not state_low else 'FAIL'}")
        except Exception as e:
            print(f"  FIO{pin}: Error - {e}")

def main():
    """Main function"""
    print("LabJack U3 Configuration Test")
    print("=" * 40)
    
    # Configure the LabJack
    lj = configure_labjack_u3()
    
    if lj:
        # Test the configuration
        test_configuration(lj)
        
        # Close connection
        lj.close()
        print("\nLabJack U3 connection closed")
    else:
        print("Failed to configure LabJack U3")

if __name__ == "__main__":
    main()
