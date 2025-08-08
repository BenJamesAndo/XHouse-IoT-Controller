import appdaemon.plugins.hass.hassapi as hass
import requests
import time
import hmac
import hashlib
import json
from datetime import datetime

class XHouseController(hass.Hass):
    """AppDaemon app to control XHouse devices from Home Assistant"""
    
    # API constants
    API_BASE_URL = "http://47.52.111.184:9010/xhouseAppEncapsulation"
    HMAC_SECRET_KEY = "juge2020@giigleiot"
    SAAS_CODE = "JUJIANG"
    PLATFORM_CODE = "giigle"
    APP_TYPE = "android"
    
    def initialize(self):
        """Initialize the AppDaemon app"""
        self.log("XHouse Controller initializing")
        
        # Get credentials from app config
        self.email = self.args.get("email")
        self.password = self.args.get("password")
        self.refresh_interval = int(self.args.get("refresh_interval", 300))  # Default 5 minutes
        self.debug_mode = bool(self.args.get("debug_mode", False))  # Default debug off
        
        # Initialize session variables
        self.session = requests.Session()
        self.user_id = None
        self.token = None
        self.devices = {}
        self.token_valid = False
        
        # Schedule first login and device discovery
        self.run_in(self.login_and_discover, 10)  # Run 10 seconds after startup
        
        # Listen to switch events
        self.listen_event(self.switch_event_handler, "call_service", 
                         domain="switch", 
                         service="turn_on")
        self.listen_event(self.switch_event_handler, "call_service", 
                         domain="switch", 
                         service="turn_off")
        self.listen_event(self.switch_event_handler, "call_service", 
                         domain="switch", 
                         service="toggle")
        
        # Listen to cover events
        self.listen_event(self.cover_event_handler, "call_service", 
                         domain="cover", 
                         service="open_cover")
        self.listen_event(self.cover_event_handler, "call_service", 
                         domain="cover", 
                         service="close_cover")
        self.listen_event(self.cover_event_handler, "call_service", 
                         domain="cover", 
                         service="toggle")
        
        self.log("XHouse Controller initialized with event listeners")
        
    def debug(self, message):
        """Log debug messages if debug mode is on"""
        if self.debug_mode:
            self.log(f"DEBUG: {message}")
    
    def login_and_discover(self, kwargs):
        """Login to XHouse and discover devices"""
        if self.login():
            self.log("Successfully logged in to XHouse")
            self.discover_devices()
            # Schedule regular refresh
            self.run_every(self.refresh_devices, "now", self.refresh_interval)
        else:
            self.log("Failed to login to XHouse, will retry in 60 seconds", level="WARNING")
            self.run_in(self.login_and_discover, 60)
    
    def generate_signature(self):
        """Generate timestamp and HMAC-MD5 signature for API authentication"""
        timestamp = str(int(time.time()))
        data_to_sign = "giigle" + timestamp
        signature = hmac.new(
            self.HMAC_SECRET_KEY.encode('utf-8'),
            data_to_sign.encode('utf-8'),
            hashlib.md5
        ).hexdigest()
        return signature, timestamp
        
    def login(self):
        """Authenticate and get session token and user ID"""
        self.log(f"Logging in to XHouse as {self.email}...")
        
        signature, timestamp = self.generate_signature()
        api_url = f"{self.API_BASE_URL}/clientUser/login"
        
        headers = {
            "apptype": self.APP_TYPE.lower(), 
            "l": "EN", 
            "platformcode": self.PLATFORM_CODE,
            "saascode": self.SAAS_CODE, 
            "timestamp": timestamp, 
            "signature": signature,
            "content-type": 'application/json; charset=utf-8', 
            "user-agent": "okhttp/4.2.0",
            "host": "47.52.111.184:9010", 
            "connection": "Keep-Alive",
        }
        
        body_dict = {
            "saasCode": self.SAAS_CODE, 
            "type": "EMAIL", 
            "email": self.email,
            "password": self.password, 
            "appType": self.APP_TYPE.upper()
        }
        
        body_string = json.dumps(body_dict, separators=(',', ':'))
        headers["content-length"] = str(len(body_string.encode('utf-8')))
        
        try:
            response = self.session.post(api_url, headers=headers, data=body_string, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get("code") == "0":
                self.user_id = data["result"]["userId"]
                self.token = data["result"]["token"]
                self.token_valid = True
                self.log(f"Login successful! User ID: {self.user_id}")
                return True
            else:
                self.token_valid = False
                self.log(f"Login failed: {data.get('msg')}", level="ERROR")
                return False
                
        except Exception as e:
            self.token_valid = False
            self.log(f"An error occurred during login: {e}", level="ERROR")
            return False
    
    def discover_devices(self):
        """Discover XHouse devices and create entities in Home Assistant"""
        self.log("Discovering XHouse devices...")
        
        if not self.token_valid:
            self.log("Not logged in. Cannot discover devices.", level="WARNING")
            if self.login():
                self.log("Re-login successful, continuing with device discovery")
            else:
                return
            
        signature, timestamp = self.generate_signature()
        api_url = f"{self.API_BASE_URL}/group/queryGroupDevices"
        phonetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        headers = {
            "apptype": self.APP_TYPE.lower(), 
            "l": "EN", 
            "phonetime": phonetime,
            "platformcode": self.PLATFORM_CODE, 
            "saascode": self.SAAS_CODE, 
            "timestamp": timestamp,
            "token": self.token, 
            "userid": self.user_id, 
            "signature": signature,
            "content-type": 'application/json; charset=utf-8', 
            "user-agent": "okhttp/4.2.0",
            "host": "47.52.111.184:9010", 
            "connection": "Keep-Alive",
        }
        
        body_dict = {
            "userId": int(self.user_id),
            "groupId": 0  # 0 appears to return all devices
        }
        
        body_string = json.dumps(body_dict, separators=(',', ':'))
        headers["content-length"] = str(len(body_string.encode('utf-8')))
        
        try:
            response = self.session.post(api_url, headers=headers, data=body_string, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get("code") == "0":
                devices = data.get("result", {}).get("deviceInfos", [])
                if not devices:
                    self.log("No XHouse devices found.", level="WARNING")
                    return
                
                self.log(f"Found {len(devices)} XHouse devices")
                
                for device in devices:
                    device_id = device.get("id")
                    device_id_str = str(device_id)  # Make sure it's a string
                    
                    self.debug(f"Device found - ID: {device_id}, ID as string: {device_id_str}")
                        
                    # Get device info
                    alias = device.get("alias", f"XHouse Device {device_id}")
                    model = device.get("model", "Unknown")
                    device_type = device.get("deviceType", "Unknown")
                    
                    # Store the original alias before any overrides
                    original_alias = alias
                    
                    # Determine device type and device class
                    is_gate = False
                    is_garage = False
                    device_class = "switch"
                    
                    # XH-SGC01 models are gates (not garage door openers)
                    if "XH-SGC01" in model:
                        is_gate = True
                        device_class = "gate"
                        # Override the name for XH-SGC01 models
                        alias = "Gate Opener"
                    # Check for other gate keywords
                    elif any(keyword in alias.lower() for keyword in ["gate"]) or "gate" in model.lower():
                        is_gate = True
                        device_class = "gate"
                    # Check for garage door keywords
                    elif any(keyword in alias.lower() for keyword in ["garage", "door"]) or "garage" in model.lower():
                        is_garage = True
                        device_class = "garage"
                    
                    is_cover = is_gate or is_garage
                    
                    # Create entity ID based on device type (cover for gates/garage doors, switch for others)
                    if is_cover:
                        entity_id = f"cover.xhouse_{device_id_str}"
                    else:
                        entity_id = f"switch.xhouse_{device_id_str}"
                    
                    # Store device info
                    self.devices[entity_id] = {
                        "id": device_id,
                        "name": alias,
                        "original_name": original_alias,  # Store original for reference
                        "model": model,
                        "type": device_type,
                        "device_class": device_class,
                        "is_cover": is_cover
                    }
                    
                    self.debug(f"Mapped entity {entity_id} to device {device_id} with class {device_class}")
                    
                    # Try to get switch status from properties
                    is_on = False
                    for prop in device.get("properties", []):
                        if prop.get("key") == "Switch_1":
                            is_on = prop.get("value") == "1"
                            break
                    
                    # Create/update entity in Home Assistant
                    if is_cover:
                        # For gates/garage doors, use cover entity with open/closed states
                        self.set_state(entity_id, 
                                     state="open" if is_on else "closed",
                                     attributes={
                                         "friendly_name": alias,
                                         "device_class": device_class,
                                         "device_id": device_id_str,
                                         "model": model,
                                         "device_type": device_type,
                                         "supported_features": 3,  # SUPPORT_OPEN + SUPPORT_CLOSE
                                     })
                        self.log(f"Created/updated cover entity {entity_id} as {device_class} for {alias}")
                    else:
                        # For regular devices, use switch entity with on/off states
                        self.set_state(entity_id, 
                                     state="on" if is_on else "off",
                                     attributes={
                                         "friendly_name": alias,
                                         "device_class": "switch",
                                         "device_id": device_id_str,
                                         "model": model,
                                         "device_type": device_type,
                                         "icon": "mdi:power-socket"
                                     })
                        self.log(f"Created/updated switch entity {entity_id} for {alias}")
                
                return True
            else:
                if "token invalid" in data.get("msg", "").lower():
                    self.token_valid = False
                    self.log("Token invalidated, attempting to re-login", level="WARNING")
                    if self.login():
                        # Try discovery again after successful login
                        return self.discover_devices()
                else:
                    self.log(f"Failed to get devices: {data.get('msg')}", level="ERROR")
                return False
                
        except Exception as e:
            self.log(f"An error occurred discovering devices: {e}", level="ERROR")
            return False
    
    def refresh_devices(self, kwargs=None):
        """Refresh device states"""
        # Only log refresh messages in debug mode
        self.debug("Refreshing XHouse device states...")
        
        # First check if we need to re-login
        if not self.token_valid:
            self.log("Session expired, logging in again...")
            if not self.login():
                return
        
        # Update each device state
        for entity_id, device_info in self.devices.items():
            device_id = device_info["id"]
            self.get_device_state(device_id, entity_id)
        
    def get_device_state(self, device_id, entity_id=None):
        """Get the current state of a device and update Home Assistant"""
        if not self.token_valid:
            self.log("Not logged in. Cannot get device state.", level="WARNING")
            if not self.login():
                return None
        
        self.debug(f"Getting state for device {device_id}")    
        signature, timestamp = self.generate_signature()
        api_url = f"{self.API_BASE_URL}/wifi/getWifiProperties"
        phonetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        headers = {
            "apptype": self.APP_TYPE.lower(), 
            "l": "EN", 
            "phonetime": phonetime,
            "platformcode": self.PLATFORM_CODE, 
            "saascode": self.SAAS_CODE, 
            "timestamp": timestamp,
            "token": self.token, 
            "userid": self.user_id, 
            "signature": signature,
            "content-type": 'application/json; charset=utf-8', 
            "user-agent": "okhttp/4.2.0",
            "host": "47.52.111.184:9010", 
            "connection": "Keep-Alive",
        }
        
        body_dict = {
            "userId": int(self.user_id),
            "deviceId": int(device_id)
        }
        
        body_string = json.dumps(body_dict, separators=(',', ':'))
        headers["content-length"] = str(len(body_string.encode('utf-8')))
        
        try:
            response = self.session.post(api_url, headers=headers, data=body_string, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get("code") == "0":
                properties = data.get("result", {}).get("properties", [])
                
                # Look for Switch_1 property
                is_on = False
                for prop in properties:
                    if prop.get("key") == "Switch_1":
                        is_on = prop.get("value") == "1"
                        break
                
                # Update entity in Home Assistant if entity_id is provided
                if entity_id:
                    # Check if this is a cover or regular switch
                    is_cover = entity_id.startswith("cover.")
                    
                    if is_cover:
                        # For covers, use open/closed states
                        self.set_state(entity_id, state="open" if is_on else "closed")
                        self.debug(f"Updated {entity_id} state to {'open' if is_on else 'closed'}")
                    else:
                        # For switches, use on/off states
                        self.set_state(entity_id, state="on" if is_on else "off")
                        self.debug(f"Updated {entity_id} state to {'on' if is_on else 'off'}")
                
                return is_on
            else:
                if "token invalid" in data.get("msg", "").lower():
                    self.token_valid = False
                    self.log("Token invalidated, attempting to re-login", level="WARNING")
                    if self.login():
                        # Try again after successful login
                        return self.get_device_state(device_id, entity_id)
                else:
                    self.log(f"Failed to get device state: {data.get('msg')}", level="WARNING")
                return None
                
        except Exception as e:
            self.log(f"An error occurred getting device state: {e}", level="ERROR")
            return None
    
    def control_device(self, entity_id, turn_on=True):
        """Control a device (turn on/off or open/close)"""
        if not self.token_valid:
            self.log("Not logged in. Cannot control device.", level="WARNING")
            if not self.login():
                return False
        
        # Find the device info
        if entity_id not in self.devices:
            self.log(f"Unknown device entity: {entity_id}", level="ERROR")
            return False
            
        device_info = self.devices[entity_id]
        device_id = device_info["id"]  # Use the numeric ID
        is_cover = entity_id.startswith("cover.")
            
        # Set action text based on device type
        if is_cover:
            state = "Open" if turn_on else "Close"
        else:
            state = "On" if turn_on else "Off"
            
        self.log(f"Sending '{state}' command to device {device_id} ({device_info['name']})")
        
        signature, timestamp = self.generate_signature()
        api_url = f"{self.API_BASE_URL}/wifi/sendWifiCode"
        phonetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        headers = {
            "apptype": self.APP_TYPE.lower(), 
            "l": "EN", 
            "phonetime": phonetime,
            "platformcode": self.PLATFORM_CODE, 
            "saascode": self.SAAS_CODE, 
            "timestamp": timestamp,
            "token": self.token, 
            "userid": self.user_id, 
            "signature": signature,
            "content-type": 'application/json; charset=utf-8', 
            "user-agent": "okhttp/4.2.0",
            "host": "47.52.111.184:9010", 
            "connection": "Keep-Alive",
        }
        
        body_dict = {
            "deviceId": int(device_id), 
            "userId": int(self.user_id),
            "propertyValue": {"Switch_1": 1 if turn_on else 0},
            "action": "On" if turn_on else "Off"  # API always uses On/Off
        }
        
        self.debug(f"Control request body: {json.dumps(body_dict)}")
        
        body_string = json.dumps(body_dict, separators=(',', ':'))
        headers["content-length"] = str(len(body_string.encode('utf-8')))
        
        try:
            response = self.session.post(api_url, headers=headers, data=body_string, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            self.debug(f"Control response: {response.status_code} - {json.dumps(data)}")
            
            if data.get("code") == "0":
                self.log(f"Successfully sent {state.lower()} command to device {device_id}")
                
                # Update entity in Home Assistant immediately (optimistic update)
                if is_cover:
                    # For covers, use open/closed states
                    self.set_state(entity_id, state="open" if turn_on else "closed")
                else:
                    # For switches, use on/off states
                    self.set_state(entity_id, state="on" if turn_on else "off")
                
                return True
            else:
                if "token invalid" in data.get("msg", "").lower():
                    self.token_valid = False
                    self.log("Token invalidated, attempting to re-login", level="WARNING")
                    if self.login():
                        # Try again after successful login
                        return self.control_device(entity_id, turn_on)
                else:
                    self.log(f"Failed to control device: {data.get('msg')}", level="ERROR")
                return False
                
        except Exception as e:
            self.log(f"An error occurred controlling device: {e}", level="ERROR")
            return False
    
    # Switch event handler
    def switch_event_handler(self, event_name, data, kwargs):
        """Handle switch events"""
        service = data.get("service")
        entity_id = data.get("service_data", {}).get("entity_id")
        
        if not entity_id:
            return
        
        # Handle both single entity and lists
        entities = entity_id if isinstance(entity_id, list) else [entity_id]
        
        for entity in entities:
            # Check if this is one of our switches
            if not entity.startswith("switch.xhouse_"):
                continue
                
            self.debug(f"Switch event: {service} for {entity}")
            
            if service == "turn_on":
                self.control_device(entity, turn_on=True)
            elif service == "turn_off":
                self.control_device(entity, turn_on=False)
            elif service == "toggle":
                current_state = self.get_state(entity)
                self.control_device(entity, turn_on=(current_state != "on"))
    
    # Cover event handler
    def cover_event_handler(self, event_name, data, kwargs):
        """Handle cover events"""
        service = data.get("service")
        entity_id = data.get("service_data", {}).get("entity_id")
        
        if not entity_id:
            return
        
        # Handle both single entity and lists
        entities = entity_id if isinstance(entity_id, list) else [entity_id]
        
        for entity in entities:
            # Check if this is one of our covers
            if not entity.startswith("cover.xhouse_"):
                continue
                
            self.debug(f"Cover event: {service} for {entity}")
            
            if service == "open_cover":
                self.control_device(entity, turn_on=True)
            elif service == "close_cover":
                self.control_device(entity, turn_on=False)
            elif service == "toggle":
                current_state = self.get_state(entity)
                self.control_device(entity, turn_on=(current_state != "open"))