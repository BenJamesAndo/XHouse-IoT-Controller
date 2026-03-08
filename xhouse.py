import appdaemon.plugins.hass.hassapi as hass
import requests
import time
import hmac
import hashlib
import json
from datetime import datetime


class XHouseController(hass.Hass):
    """AppDaemon app to control XHouse IOT devices from Home Assistant."""

    API_BASE_URL = "http://47.52.111.184:9010/xhouseAppEncapsulation"
    HMAC_SECRET_KEY = "juge2020@giigleiot"
    SAAS_CODE = "JUJIANG"
    PLATFORM_CODE = "giigle"
    APP_TYPE = "android"

    # Known models get specialised entity handling (cover with open/close)
    KNOWN_MODELS = ["XH-SGC01"]

    # Property keys that are config/metadata, not device controls
    NON_CONTROL_PROPERTIES = {"VoiceControl", "bleCode", "wifiName"}

    # ── Initialisation ──────────────────────────────────────────────────

    def initialize(self):
        self.log("XHouse Controller initializing")

        self.email = self.args.get("email")
        self.password = self.args.get("password")
        self.refresh_interval = int(self.args.get("refresh_interval", 300))
        self.debug_mode = bool(self.args.get("debug_mode", False))

        self.session = requests.Session()
        self.user_id = None
        self.token = None
        self.devices = {}  # entity_id -> device info dict
        self.token_valid = False

        self.run_in(self._login_and_discover, 10)

        for domain, services in [
            ("switch", ["turn_on", "turn_off", "toggle"]),
            ("cover", ["open_cover", "close_cover", "toggle"]),
        ]:
            for service in services:
                self.listen_event(
                    self._handle_service_call, "call_service",
                    domain=domain, service=service,
                )

        self.log("XHouse Controller initialized")

    # ── Logging helpers ─────────────────────────────────────────────────

    def _debug(self, message):
        if self.debug_mode:
            self.log(f"DEBUG: {message}")

    def _debug_response(self, label, data):
        if self.debug_mode:
            self.log(f"DEBUG: === {label} ===")
            self.log(f"DEBUG: {json.dumps(data, indent=2)}")

    # ── API helpers ─────────────────────────────────────────────────────

    def _generate_signature(self):
        timestamp = str(int(time.time()))
        signature = hmac.new(
            self.HMAC_SECRET_KEY.encode(),
            (self.PLATFORM_CODE + timestamp).encode(),
            hashlib.md5,
        ).hexdigest()
        return signature, timestamp

    def _build_headers(self, *, authenticated=True):
        signature, timestamp = self._generate_signature()
        headers = {
            "apptype": self.APP_TYPE,
            "l": "EN",
            "platformcode": self.PLATFORM_CODE,
            "saascode": self.SAAS_CODE,
            "timestamp": timestamp,
            "signature": signature,
            "content-type": "application/json; charset=utf-8",
            "user-agent": "okhttp/4.2.0",
            "host": "47.52.111.184:9010",
            "connection": "Keep-Alive",
        }
        if authenticated:
            headers["token"] = self.token
            headers["userid"] = self.user_id
            headers["phonetime"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return headers

    def _api_post(self, endpoint, body, *, authenticated=True):
        """POST to the XHouse API. Returns parsed JSON or None on error."""
        headers = self._build_headers(authenticated=authenticated)
        body_string = json.dumps(body, separators=(",", ":"))
        headers["content-length"] = str(len(body_string.encode()))
        url = f"{self.API_BASE_URL}/{endpoint}"
        try:
            resp = self.session.post(url, headers=headers, data=body_string, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            self.log(f"API request to {endpoint} failed: {e}", level="ERROR")
            return None

    def _ensure_logged_in(self):
        """Return True if we have a valid session, re-logging in if needed."""
        if self.token_valid:
            return True
        self.log("Session expired, logging in again...")
        return self._login()

    def _handle_token_error(self, data, retry_func, *args):
        """If *data* contains a token error, re-login and retry.

        Returns the retry result on token error, or False if not a token error.
        """
        msg = (data or {}).get("msg", "").lower()
        if "token invalid" in msg:
            self.token_valid = False
            self.log("Token invalidated, re-logging in", level="WARNING")
            if self._login():
                return retry_func(*args)
            return None
        return False

    # ── Entity helpers ──────────────────────────────────────────────────

    def _entities_for_device(self, device_id):
        """Yield (entity_id, info) for all entities belonging to a device."""
        device_id_str = str(device_id)
        for eid, info in self.devices.items():
            if str(info["id"]) == device_id_str:
                yield eid, info

    def _update_entity(self, entity_id, state, extra_attrs=None):
        """Set entity state in HA, preserving existing attributes."""
        attrs = dict((self.get_state(entity_id, attribute="all") or {}).get("attributes", {}))
        if extra_attrs:
            attrs.update(extra_attrs)
        self.set_state(entity_id, state=state, attributes=attrs)

    def _state_for_value(self, entity_id, is_on):
        """Return the correct HA state string for a boolean value."""
        if entity_id.startswith("cover."):
            return "open" if is_on else "closed"
        return "on" if is_on else "off"

    def _mark_device_offline(self, device_id):
        for eid, info in self._entities_for_device(device_id):
            info["connection_state"] = "offline"
            self._update_entity(eid, "unavailable", {"connection_state": "offline"})
        self.log(f"Device {device_id} is offline, marked as unavailable")

    def _online_device_ids(self):
        """Return a set of unique device IDs that are currently online."""
        return {
            info["id"] for info in self.devices.values()
            if info["connection_state"] == "online"
        }

    # ── Auth ────────────────────────────────────────────────────────────

    def _login_and_discover(self, kwargs):
        if self._login():
            self.log("Successfully logged in to XHouse")
            self._discover_devices()
            if self.debug_mode:
                self._debug("Fetching device states for all online devices...")
                for device_id in self._online_device_ids():
                    self._get_device_state(device_id)
            self.run_every(self._refresh_devices, "now", self.refresh_interval)
        else:
            self.log("Failed to login, retrying in 60s", level="WARNING")
            self.run_in(self._login_and_discover, 60)

    def _login(self):
        self.log("Logging in to XHouse...")
        body = {
            "saasCode": self.SAAS_CODE,
            "type": "EMAIL",
            "email": self.email,
            "password": self.password,
            "appType": self.APP_TYPE.upper(),
        }
        data = self._api_post("clientUser/login", body, authenticated=False)
        if data is None:
            self.token_valid = False
            return False

        if self.debug_mode:
            safe = json.loads(json.dumps(data))
            result = safe.get("result") or {}
            if "token" in result:
                result["token"] = "***REDACTED***"
            for key in ("email", "nickName", "phone"):
                client = result.get("clientUser") or {}
                if client.get(key):
                    client[key] = "***REDACTED***"
            self._debug_response("LOGIN RESPONSE", safe)

        if data.get("code") == "0":
            self.user_id = data["result"]["userId"]
            self.token = data["result"]["token"]
            self.token_valid = True
            self.log(f"Login successful! User ID: {self.user_id}")
            return True

        self.token_valid = False
        self.log(f"Login failed: {data.get('msg')}", level="ERROR")
        return False

    # ── Discovery ───────────────────────────────────────────────────────

    def _discover_devices(self):
        self.log("Discovering XHouse devices...")
        if not self._ensure_logged_in():
            return

        data = self._api_post(
            "group/queryGroupDevices",
            {"userId": int(self.user_id), "groupId": 0},
        )
        if data is None:
            return
        self._debug_response("DISCOVER DEVICES RESPONSE", data)

        if data.get("code") != "0":
            handled = self._handle_token_error(data, self._discover_devices)
            if handled is False:
                self.log(f"Failed to get devices: {data.get('msg')}", level="ERROR")
            return

        devices = (data.get("result") or {}).get("deviceInfos") or []
        if not devices:
            self.log("No XHouse devices found.", level="WARNING")
            return

        self.log(f"Found {len(devices)} XHouse device(s)")
        for device in devices:
            is_known = any(m in device.get("model", "") for m in self.KNOWN_MODELS)
            if is_known:
                self._register_known_device(device)
            else:
                self._register_generic_device(device)

    def _device_common(self, device):
        """Extract common fields from an API device dict."""
        return {
            "device_id": device.get("id"),
            "device_id_str": str(device.get("id")),
            "alias": device.get("alias", f"XHouse Device {device.get('id')}"),
            "model": device.get("model", "Unknown"),
            "device_type": device.get("deviceType", "Unknown"),
            "online": device.get("status", 0) == 1,
            "connection_state": "online" if device.get("status", 0) == 1 else "offline",
        }

    def _register_entity(self, entity_id, *, device_id, name, original_name, model,
                         device_type, device_class, is_cover, property_key,
                         connection_state, state, attributes):
        """Store device info and create/update the HA entity."""
        last_good = state if state != "unavailable" else ("closed" if is_cover else "off")
        self.devices[entity_id] = {
            "id": device_id,
            "name": name,
            "original_name": original_name,
            "model": model,
            "type": device_type,
            "device_class": device_class,
            "is_cover": is_cover,
            "property_key": property_key,
            "connection_state": connection_state,
            "last_good_state": last_good,
        }
        self.set_state(entity_id, state=state, attributes=attributes)
        kind = "cover" if is_cover else "switch"
        self.log(f"Created {kind} entity {entity_id} for {name} ({connection_state})")

    def _register_known_device(self, device):
        """Register entities for a known/supported model (e.g. SGC01)."""
        c = self._device_common(device)
        did, did_str = c["device_id"], c["device_id_str"]
        alias, model = c["alias"], c["model"]

        alias_lower, model_lower = alias.lower(), model.lower()
        if "XH-SGC01" in model:
            device_class, is_cover, alias = "gate", True, "Gate Opener"
        elif "gate" in alias_lower or "gate" in model_lower:
            device_class, is_cover = "gate", True
        elif any(k in alias_lower for k in ("garage", "door")) or "garage" in model_lower:
            device_class, is_cover = "garage", True
        else:
            device_class, is_cover = "switch", False

        is_on = any(
            p.get("value") == "1"
            for p in device.get("properties", [])
            if p.get("key") == "Switch_1"
        )

        entity_id = f"{'cover' if is_cover else 'switch'}.xhouse_{did_str}"
        state = "unavailable" if not c["online"] else self._state_for_value(entity_id, is_on)

        attrs = {
            "friendly_name": alias,
            "device_class": device_class,
            "device_id": did_str,
            "model": model,
            "device_type": c["device_type"],
            "connection_state": c["connection_state"],
        }
        if is_cover:
            attrs["supported_features"] = 3  # OPEN + CLOSE
        else:
            attrs["icon"] = "mdi:power-socket"

        self._register_entity(
            entity_id, device_id=did, name=alias, original_name=c["alias"],
            model=model, device_type=c["device_type"], device_class=device_class,
            is_cover=is_cover, property_key="Switch_1",
            connection_state=c["connection_state"], state=state, attributes=attrs,
        )

    def _register_generic_device(self, device):
        """Register a switch entity for each INT property on an unknown device."""
        c = self._device_common(device)
        did, did_str = c["device_id"], c["device_id_str"]

        int_props = [
            p for p in device.get("properties", [])
            if p.get("type") == "INT" and p.get("key") not in self.NON_CONTROL_PROPERTIES
        ]

        if not int_props:
            self.log(
                f"Device {did} ({c['model']}) has no controllable properties",
                level="WARNING",
            )
            return

        for prop in int_props:
            key = prop["key"]
            name = prop.get("name", key)
            is_on = prop.get("value") == "1"

            entity_id = f"switch.xhouse_{did_str}_{key.lower()}"
            friendly = f"{c['alias']} {name}" if name != key else f"{c['alias']} {key}"
            state = "unavailable" if not c["online"] else ("on" if is_on else "off")

            attrs = {
                "friendly_name": friendly,
                "device_class": "switch",
                "device_id": did_str,
                "model": c["model"],
                "device_type": c["device_type"],
                "property_key": key,
                "icon": "mdi:toggle-switch",
                "connection_state": c["connection_state"],
            }

            self._register_entity(
                entity_id, device_id=did, name=friendly, original_name=c["alias"],
                model=c["model"], device_type=c["device_type"], device_class="switch",
                is_cover=False, property_key=key,
                connection_state=c["connection_state"], state=state, attributes=attrs,
            )

    # ── Refresh ─────────────────────────────────────────────────────────

    def _refresh_devices(self, kwargs=None):
        self._debug("Refreshing device states...")
        if not self._ensure_logged_in():
            return
        self._update_connection_states()
        for device_id in self._online_device_ids():
            self._get_device_state(device_id)

    def _update_connection_states(self):
        if not self._ensure_logged_in():
            return

        data = self._api_post(
            "group/queryGroupDevices",
            {"userId": int(self.user_id), "groupId": 0},
        )
        if data is None:
            return
        self._debug_response("CONNECTION STATE RESPONSE", data)

        if data.get("code") != "0":
            handled = self._handle_token_error(data, self._update_connection_states)
            if handled is False:
                self.log(f"Failed to get connection states: {data.get('msg')}", level="WARNING")
            return

        for device in (data.get("result") or {}).get("deviceInfos") or []:
            device_id = device.get("id")
            new_conn = "online" if device.get("status", 0) == 1 else "offline"
            need_fetch = False

            for eid, info in self._entities_for_device(device_id):
                prev = info["connection_state"]
                info["connection_state"] = new_conn

                if prev == new_conn:
                    if new_conn == "offline" and self.get_state(eid) != "unavailable":
                        self._update_entity(eid, "unavailable", {"connection_state": "offline"})
                    continue

                if new_conn == "offline":
                    self.log(f"{eid} is now offline")
                    self._update_entity(eid, "unavailable", {"connection_state": "offline"})
                else:
                    restore = info.get("last_good_state") or (
                        "closed" if info["is_cover"] else "off"
                    )
                    self.log(f"{eid} is now online, restoring to {restore}")
                    self._update_entity(eid, restore, {"connection_state": "online"})
                    need_fetch = True

            if need_fetch:
                self._get_device_state(device_id)

    # ── Device state ────────────────────────────────────────────────────

    def _get_device_state(self, device_id):
        if not self._ensure_logged_in():
            return
        self._debug(f"Getting state for device {device_id}")

        data = self._api_post(
            "wifi/getWifiProperties",
            {"userId": int(self.user_id), "deviceId": int(device_id)},
        )
        if data is None:
            return
        self._debug_response(f"DEVICE STATE RESPONSE (device {device_id})", data)

        if data.get("code") == "0":
            prop_values = {
                p["key"]: p.get("value")
                for p in (data.get("result") or {}).get("properties") or []
            }
            for eid, info in self._entities_for_device(device_id):
                is_on = prop_values.get(info.get("property_key", "Switch_1")) == "1"
                new_state = self._state_for_value(eid, is_on)
                self._update_entity(eid, new_state)
                info["last_good_state"] = new_state
                self._debug(f"Updated {eid} to {new_state}")
            return

        handled = self._handle_token_error(data, self._get_device_state, device_id)
        if handled is not False:
            return
        if "device offline" in (data.get("msg") or "").lower():
            self._mark_device_offline(device_id)
        else:
            self.log(f"Failed to get device state: {data.get('msg')}", level="WARNING")

    # ── Device control ──────────────────────────────────────────────────

    def control_device(self, entity_id, turn_on=True):
        if not self._ensure_logged_in():
            return False

        if entity_id not in self.devices:
            self.log(f"Unknown entity: {entity_id}", level="ERROR")
            return False

        info = self.devices[entity_id]
        device_id = info["id"]
        is_cover = entity_id.startswith("cover.")

        if info.get("connection_state") == "offline":
            self._update_entity(entity_id, "unavailable", {"connection_state": "offline"})
            self.log(f"Cannot control {entity_id}: device is offline", level="WARNING")
            return False

        action = ("Open" if turn_on else "Close") if is_cover else ("On" if turn_on else "Off")
        self.log(f"Sending '{action}' to device {device_id} ({info['name']})")

        prop_key = info.get("property_key", "Switch_1")
        body = {
            "deviceId": int(device_id),
            "userId": int(self.user_id),
            "propertyValue": {prop_key: 1 if turn_on else 0},
            "action": "On" if turn_on else "Off",
        }
        self._debug(f"Control body: {json.dumps(body)}")

        data = self._api_post("wifi/sendWifiCode", body)
        if data is None:
            return False
        self._debug_response(f"CONTROL RESPONSE (device {device_id})", data)

        if data.get("code") == "0":
            self.log(f"Successfully sent {action.lower()} to device {device_id}")
            new_state = self._state_for_value(entity_id, turn_on)
            info["connection_state"] = "online"
            info["last_good_state"] = new_state
            self._update_entity(entity_id, new_state, {"connection_state": "online"})
            return True

        handled = self._handle_token_error(data, self.control_device, entity_id, turn_on)
        if handled is not False:
            return bool(handled)
        if "device offline" in (data.get("msg") or "").lower():
            info["connection_state"] = "offline"
            self._update_entity(entity_id, "unavailable", {"connection_state": "offline"})
            self.log(f"Cannot control {entity_id}: device is offline", level="WARNING")
        else:
            self.log(f"Failed to control device: {data.get('msg')}", level="ERROR")
        return False

    # ── Event handler ───────────────────────────────────────────────────

    def _handle_service_call(self, event_name, data, kwargs):
        """Unified handler for both switch and cover service calls."""
        service = data.get("service")
        raw_ids = data.get("service_data", {}).get("entity_id")
        if not raw_ids:
            return

        entities = raw_ids if isinstance(raw_ids, list) else [raw_ids]

        for entity in entities:
            if not (entity.startswith("switch.xhouse_") or entity.startswith("cover.xhouse_")):
                continue

            self._debug(f"Service call: {service} for {entity}")

            if self.get_state(entity) == "unavailable":
                self.log(f"Cannot control {entity}: unavailable", level="WARNING")
                continue

            if service in ("turn_on", "open_cover"):
                self.control_device(entity, turn_on=True)
            elif service in ("turn_off", "close_cover"):
                self.control_device(entity, turn_on=False)
            elif service == "toggle":
                is_cover = entity.startswith("cover.")
                current = self.get_state(entity)
                currently_on = current == ("open" if is_cover else "on")
                self.control_device(entity, turn_on=not currently_on)
