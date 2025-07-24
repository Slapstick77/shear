"""
LabJack U3 Module
Handles LabJack U3 data acquisition and I/O operations
"""

import time
import threading
import logging
from typing import Optional, Dict, Any, Callable, List
from datetime import datetime

try:
    import u3
    LABJACK_AVAILABLE = True
except ImportError:
    LABJACK_AVAILABLE = False
    u3 = None

logger = logging.getLogger(__name__)

class LabJackU3:
    """LabJack U3 handler for I/O operations and data acquisition"""
    
    def __init__(self, on_input_change: Optional[Callable] = None):
        self.device = None
        self.device_info = None
        self.running = False
        self.monitor_thread = None
        self.on_input_change = on_input_change
        
        # U3 Configuration - Based on requirements:
        # FIO0-FIO3 as analog inputs, FIO4-FIO5 as digital inputs, FIO6-FIO7 as digital outputs
        self.input_channels = ['FIO4', 'FIO5']  # Digital inputs to monitor
        self.output_channels = ['FIO6', 'FIO7']  # Digital outputs for control
        self.analog_channels = ['AIN0', 'AIN1', 'AIN2', 'AIN3']  # Analog inputs (FIO0-FIO3)
        
        # Input floating state management - assume unconnected inputs are LOW
        self.floating_inputs_as_low = True  # Treat floating/unconnected inputs as LOW
        self.stable_input_readings = {}  # Track stable readings to filter noise
        
        # Shear lock state tracking
        self.shear_unlocked = False  # Track if shear is currently unlocked
        
        # State tracking
        self.last_input_states = {}
        self.output_states = {}
        self.last_analog_values = {}
        
        if not LABJACK_AVAILABLE:
            logger.warning("LabJack U3 library not available. LabJack functionality disabled.")
    
    def connect(self) -> bool:
        """Connect to LabJack U3"""
        if not LABJACK_AVAILABLE:
            logger.error("LabJack U3 library not available")
            return False
        
        try:
            # Open first found LabJack U3
            self.device = u3.U3()
            
            # Get device info
            self.device_info = {
                'device_type': 'U3',
                'serial_number': self.device.serialNumber,
                'firmware_version': self.device.firmwareVersion,
                'hardware_version': self.device.hardwareVersion,
                'local_id': self.device.localId,
                'device_name': self.device.deviceName if hasattr(self.device, 'deviceName') else 'U3'
            }
            
            # Configure I/O channels
            self._configure_channels()
            
            logger.info(f"Connected to LabJack U3 (SN: {self.device_info['serial_number']})")
            return True
            
        except Exception as e:
            error_msg = str(e)
            if "Could not load the Exodriver driver" in error_msg:
                logger.error("LabJack U3 Exodriver not installed or not configured properly. USB connectivity requires Exodriver. Install with: sudo apt-get install liblabjackusb-dev")
            elif "Ethernet connectivity only" in error_msg:
                logger.error("LabJack U3 USB driver not available. Only Ethernet connectivity possible.")
            elif "No LabJack devices found" in error_msg:
                logger.error("No LabJack U3 devices found. Check USB connection.")
            else:
                logger.error(f"Failed to connect to LabJack U3: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from LabJack U3"""
        try:
            if self.device:
                self.device.close()
                self.device = None
                self.device_info = None
            logger.info("Disconnected from LabJack U3")
        except Exception as e:
            logger.error(f"Error disconnecting LabJack U3: {e}")
    
    def is_connected(self) -> bool:
        """Check if LabJack U3 is connected"""
        return self.device is not None and LABJACK_AVAILABLE
    
    def get_device_info(self) -> Optional[Dict[str, Any]]:
        """Get LabJack device information"""
        return self.device_info
    
    def _configure_channels(self):
        """Configure I/O channels"""
        if not self.is_connected():
            return

        try:
            # First, read the current configuration to understand the state
            current_config = self.device.configIO()
            logger.info(f"Current U3 config: {current_config}")

            # U3 pin configuration using configIO command
            # FIO0-FIO3 as analog inputs, FIO4-FIO5 as digital inputs, FIO6-FIO7 as digital outputs
            # FIOAnalog bitmask: 1=analog, 0=digital
            # FIO0-FIO3 = analog (bits 0-3 = 1), FIO4-FIO7 = digital (bits 4-7 = 0)
            # This gives us: 00001111 = 0x0F = 15

            new_config = self.device.configIO(
                FIOAnalog=15,             # FIO0-FIO3 as analog, FIO4-FIO7 as digital
                EIOAnalog=0               # All EIO pins as digital
            )

            logger.info(f"New U3 config: {new_config}")

            # Explicitly set pull-down resistors for FIO4 and FIO5 to avoid floating states
            try:
                self.device.writeRegister(5004, 0)  # FIO4 pull-down
                logger.info("Configured pull-down resistor for FIO4")
            except Exception as e:
                logger.error(f"Failed to configure pull-down resistor for FIO4: {e}")

            try:
                self.device.writeRegister(5005, 0)  # FIO5 pull-down
                logger.info("Configured pull-down resistor for FIO5")
            except Exception as e:
                logger.error(f"Failed to configure pull-down resistor for FIO5: {e}")

            try:
                self.device.writeRegister(6004, 0)  # Set FIO4 state to low
                logger.info("Forced FIO4 to low state")
            except Exception as e:
                logger.error(f"Failed to force FIO4 to low state: {e}")

            try:
                self.device.writeRegister(6005, 0)  # Set FIO5 state to low
                logger.info("Forced FIO5 to low state")
            except Exception as e:
                logger.error(f"Failed to force FIO5 to low state: {e}")
            
            # Give the configuration a moment to take effect
            time.sleep(0.1)
            
            # Now configure pins for digital I/O operations
            # Set input channels as inputs (direction = 0)
            for i, channel in enumerate(self.input_channels):
                if channel.startswith('FIO'):
                    pin_num = int(channel.replace('FIO', ''))
                elif channel.startswith('EIO'):
                    pin_num = int(channel.replace('EIO', '')) + 8  # EIO pins are offset by 8
                else:
                    continue
                    
                try:
                    self.device.getFeedback(u3.BitDirWrite(pin_num, 0))  # Set as input
                    # Initialize state tracking - floating inputs will be handled in read logic
                    self.last_input_states[channel] = False
                    logger.debug(f"Configured {channel} (pin {pin_num}) as digital input")
                except Exception as e:
                    logger.error(f"Failed to configure {channel} as input: {e}")
            
            # Set output channels as outputs (direction = 1) and initialize to low
            for i, channel in enumerate(self.output_channels):
                if channel.startswith('FIO'):
                    pin_num = int(channel.replace('FIO', ''))
                elif channel.startswith('EIO'):
                    pin_num = int(channel.replace('EIO', '')) + 8  # EIO pins are offset by 8
                else:
                    continue
                    
                try:
                    self.device.getFeedback(u3.BitDirWrite(pin_num, 1))  # Set as output
                    self.device.getFeedback(u3.BitStateWrite(pin_num, 0))  # Set low
                    self.output_states[channel] = False
                    logger.debug(f"Configured {channel} (pin {pin_num}) as digital output")
                except Exception as e:
                    logger.error(f"Failed to configure {channel} as output: {e}")
            
            # Initialize analog input tracking
            for channel in self.analog_channels:
                self.last_analog_values[channel] = 0.0
            
            logger.info("LabJack U3 channels configured successfully")
            
        except Exception as e:
            logger.error(f"Error configuring LabJack U3 channels: {e}")
    
    def read_digital_inputs(self) -> Dict[str, bool]:
        """Read all digital input states with floating input handling"""
        if not self.is_connected():
            return {}

        try:
            states = {}
            for channel in self.input_channels:
                if channel.startswith('FIO'):
                    pin_num = int(channel.replace('FIO', ''))
                elif channel.startswith('EIO'):
                    pin_num = int(channel.replace('EIO', '')) + 8  # EIO pins are offset by 8
                else:
                    continue

                # Read the pin state multiple times to filter noise from floating inputs
                readings = []
                for _ in range(3):  # Take 3 quick readings
                    result = self.device.getFeedback(u3.BitStateRead(pin_num))
                    readings.append(bool(result[0]))
                    time.sleep(0.001)  # Small delay between readings

                # If readings are inconsistent (floating), default to LOW
                if len(set(readings)) > 1:  # Inconsistent readings indicate floating
                    if self.floating_inputs_as_low:
                        stable_state = False  # Treat floating as LOW
                        logger.debug(f"{channel} appears to be floating - setting to LOW")
                    else:
                        stable_state = True   # Treat floating as HIGH
                        logger.debug(f"{channel} appears to be floating - setting to HIGH")
                else:
                    stable_state = readings[0]  # All readings consistent

                # Store stable reading for tracking
                self.stable_input_readings[channel] = stable_state
                states[channel] = stable_state

                # Add detailed logging for debugging
                logger.info(f"Channel {channel}: Readings={readings}, StableState={stable_state}, FloatingInputsAsLow={self.floating_inputs_as_low}")

            return states

        except Exception as e:
            logger.error(f"Error reading digital inputs: {e}")
            return {}
    
    def read_analog_inputs(self) -> Dict[str, float]:
        """Read all analog input values"""
        if not self.is_connected():
            return {}
        
        try:
            values = {}
            for channel in self.analog_channels:
                ain_num = int(channel.replace('AIN', ''))
                # Read single-ended voltage
                result = self.device.getAIN(ain_num)
                values[channel] = round(result, 3)
            return values
        except Exception as e:
            logger.error(f"Error reading analog inputs: {e}")
            return {}
    
    def set_digital_output(self, channel: str, state: bool) -> bool:
        """Set digital output state"""
        if not self.is_connected():
            return False
        
        if channel not in self.output_channels:
            logger.error(f"Invalid output channel: {channel}")
            return False
        
        try:
            if channel.startswith('FIO'):
                pin_num = int(channel.replace('FIO', ''))
            elif channel.startswith('EIO'):
                pin_num = int(channel.replace('EIO', '')) + 8  # EIO pins are offset by 8
            else:
                logger.error(f"Unknown channel type: {channel}")
                return False
                
            self.device.getFeedback(u3.BitStateWrite(pin_num, int(state)))
            self.output_states[channel] = state
            logger.info(f"Set {channel} to {'HIGH' if state else 'LOW'}")
            return True
        except Exception as e:
            logger.error(f"Error setting digital output: {e}")
            return False
    
    def set_analog_output(self, channel: str, voltage: float) -> bool:
        """Set analog output voltage (DAC channels)"""
        if not self.is_connected():
            return False
        
        # U3 has DAC0 and DAC1
        if channel not in ['DAC0', 'DAC1']:
            logger.error(f"Invalid analog output channel: {channel}")
            return False
        
        try:
            dac_num = int(channel.replace('DAC', ''))
            # Convert voltage to DAC value (U3 DAC is 0-5V, 10-bit resolution)
            dac_value = max(0, min(1023, int((voltage / 5.0) * 1023)))
            
            if dac_num == 0:
                self.device.getFeedback(u3.DAC0_8(dac_value >> 2))  # 8-bit mode
            else:
                self.device.getFeedback(u3.DAC1_8(dac_value >> 2))  # 8-bit mode
            
            logger.info(f"Set {channel} to {voltage}V")
            return True
        except Exception as e:
            logger.error(f"Error setting analog output: {e}")
            return False
    
    def trigger_shear_unlock(self, duration: float = 3.0) -> bool:
        """Trigger shear unlock relay for specified duration"""
        success = self.set_digital_output('EIO0', True)  # Activate unlock relay
        if success:
            self.shear_unlocked = True
            
            # Schedule turning off the relay after duration
            def turn_off_relay():
                time.sleep(duration)
                self.set_digital_output('EIO0', False)
            
            threading.Thread(target=turn_off_relay, daemon=True).start()
            
            logger.info(f"Shear unlock triggered for {duration} seconds")
        
        return success
    
    def force_shear_lock(self) -> bool:
        """Force shear to lock immediately"""
        success = self.set_digital_output('EIO0', False)  # Deactivate unlock relay
        if success:
            self.shear_unlocked = False
            logger.info("Shear force locked")
        return success
    
    def set_status_led(self, color: str, state: bool) -> bool:
        """Control status LEDs"""
        led_mapping = {
            'green': 'EIO1',
            'red': 'EIO2',
            'blue': 'EIO3'
        }
        
        if color not in led_mapping:
            logger.error(f"Invalid LED color: {color}")
            return False
        
        return self.set_digital_output(led_mapping[color], state)
    
    def read_shear_sensor(self) -> bool:
        """Read shear position sensor"""
        states = self.read_digital_inputs()
        return states.get('FIO4', False)  # Shear locked = True
    
    def read_motion_sensor(self) -> bool:
        """Read motion detection sensor"""
        states = self.read_digital_inputs()
        return states.get('FIO5', False)  # Motion detected = True
    
    def read_temperature_sensor(self) -> Optional[float]:
        """Read temperature from analog sensor"""
        values = self.read_analog_inputs()
        voltage = values.get('AIN0', 0.0)
        
        # Convert voltage to temperature (assuming TMP36 sensor)
        # TMP36: 10mV/°C, 500mV offset, so °C = (voltage - 0.5) * 100
        if voltage > 0:
            temperature = (voltage - 0.5) * 100
            return round(temperature, 1)
        return None
    
    def monitor_loop(self):
        """Main monitoring loop for input changes"""
        logger.info("LabJack U3 monitoring started")
        
        while self.running:
            try:
                if not self.is_connected():
                    # Try to reconnect
                    if self.connect():
                        logger.info("LabJack U3 reconnected")
                    else:
                        time.sleep(5)  # Wait before retry
                        continue
                
                # Read current states
                current_inputs = self.read_digital_inputs()
                current_analogs = self.read_analog_inputs()
                
                # Check for input changes
                for channel, current_state in current_inputs.items():
                    last_state = self.last_input_states.get(channel, False)
                    if current_state != last_state:
                        self.last_input_states[channel] = current_state
                        
                        change_data = {
                            'channel': channel,
                            'state': current_state,
                            'timestamp': datetime.now().isoformat(),
                            'change_type': 'digital_input'
                        }
                        
                        if self.on_input_change:
                            self.on_input_change(change_data)
                
                # Check for significant analog changes (> 0.1V)
                for channel, current_value in current_analogs.items():
                    last_value = self.last_analog_values.get(channel, 0.0)
                    if abs(current_value - last_value) > 0.1:
                        self.last_analog_values[channel] = current_value
                        
                        change_data = {
                            'channel': channel,
                            'value': current_value,
                            'timestamp': datetime.now().isoformat(),
                            'change_type': 'analog_input'
                        }
                        
                        if self.on_input_change:
                            self.on_input_change(change_data)
                
                # Continuously monitor the states of FIO4 and FIO5
                while True:
                    fio4_state = self.device.getDIState(4)  # Get digital input state for FIO4
                    fio5_state = self.device.getDIState(5)  # Get digital input state for FIO5
                    logger.info(f"FIO4 state: {fio4_state}, FIO5 state: {fio5_state}")
                    time.sleep(1)  # Log every second
                
                time.sleep(0.1)  # 100ms polling rate
                
            except Exception as e:
                logger.error(f"Error in LabJack U3 monitor loop: {e}")
                time.sleep(1)
        
        logger.info("LabJack U3 monitoring stopped")
    
    def set_floating_input_mode(self, treat_as_low: bool = True):
        """Configure how floating/unconnected inputs should be interpreted
        
        Args:
            treat_as_low (bool): If True, floating inputs read as LOW (False)
                               If False, floating inputs read as HIGH (True)
        """
        self.floating_inputs_as_low = treat_as_low
        logger.info(f"Floating inputs will be treated as {'LOW' if treat_as_low else 'HIGH'}")
    
    def start_monitoring(self):
        """Start monitoring for input changes"""
        if self.running:
            logger.warning("LabJack U3 monitoring already running")
            return
        
        if not self.connect():
            logger.error("Failed to connect to LabJack U3")
            return
        
        self.running = True
        self.monitor_thread = threading.Thread(target=self.monitor_loop, daemon=True)
        self.monitor_thread.start()
        logger.info("LabJack U3 monitoring thread started")
    
    def stop_monitoring(self):
        """Stop monitoring for input changes"""
        self.running = False
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=5)
        self.disconnect()
        logger.info("LabJack U3 monitoring stopped")
    
    def get_all_states(self) -> Dict[str, Any]:
        """Get current state of all channels"""
        return {
            'digital_inputs': self.read_digital_inputs(),
            'digital_outputs': self.output_states.copy(),
            'analog_inputs': self.read_analog_inputs(),
            'device_info': self.device_info,
            'connected': self.is_connected()
        }
    
    def get_calibration_constants(self):
        """Retrieve calibration constants from the U3 memory."""
        if not self.is_connected():
            logger.error("Device not connected. Cannot retrieve calibration constants.")
            return None

        try:
            # Example: Retrieve LV AIN SE Slope and Offset
            lv_ain_se_slope = self.device.readRegister(0)  # Address 0
            lv_ain_se_offset = self.device.readRegister(8)  # Address 8

            logger.info(f"Calibration constants retrieved: Slope={lv_ain_se_slope}, Offset={lv_ain_se_offset}")
            return {
                "lv_ain_se_slope": lv_ain_se_slope,
                "lv_ain_se_offset": lv_ain_se_offset
            }
        except Exception as e:
            logger.error(f"Failed to retrieve calibration constants: {e}")
            return None

    def read_analog_input_voltage(self, channel: str) -> Optional[float]:
        """Read and convert an analog input to voltage."""
        if not self.is_connected():
            return None

        try:
            # Read raw binary value
            channel_index = int(channel.replace('AIN', ''))
            raw_value = self.device.getAIN(channel_index)

            # Apply calibration constants
            constants = self.get_calibration_constants()
            if not constants:
                return None

            slope = constants["lv_ain_se_slope"]
            offset = constants["lv_ain_se_offset"]
            voltage = (slope * raw_value) + offset

            logger.info(f"Analog input {channel}: Raw={raw_value}, Voltage={voltage}")
            return voltage
        except Exception as e:
            logger.error(f"Failed to read analog input {channel}: {e}")
            return None

    def read_internal_temperature(self) -> Optional[float]:
        """Read and convert the internal temperature."""
        if not self.is_connected():
            return None

        try:
            # Read raw binary value from channel 30
            raw_value = self.device.getAIN(30)

            # Apply temperature calibration
            temp_slope = 0.013021  # Example slope from datasheet
            temperature_kelvin = raw_value * temp_slope

            logger.info(f"Internal temperature: Raw={raw_value}, Temp(K)={temperature_kelvin}")
            return temperature_kelvin
        except Exception as e:
            logger.error(f"Failed to read internal temperature: {e}")
            return None
