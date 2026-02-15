"""
MySigen Battery Monitor - Pure YAML Platform
No config entries, no coordinator - simple polling platform
"""

import logging
import requests
import base64
import time
from datetime import timedelta
from typing import Dict, Any, Optional

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.const import PERCENTAGE, UnitOfPower, UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=30)

# API URLs
API_BASE = "https://api-aus.sigencloud.com"
AUTH_URL = f"{API_BASE}/auth/oauth/token"
STATION_URL = f"{API_BASE}/device/owner/station/home"
ENERGY_URL = f"{API_BASE}/device/sigen/station/energyflow/async"
STATS_URL = f"{API_BASE}/data-process/sigen/station/statistics/gains"


class MySigenData:
    """Shared data handler for all MySigen sensors."""
    
    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.access_token = None
        self.station_id = None
        self.data = {}
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "*/*",
            "Origin": "https://app-aus.sigencloud.com",
            "Referer": "https://app-aus.sigencloud.com/",
            "Lang": "en_US",
            "Sg-Bui": "1",
            "Sg-Env": "1",
            "Sg-Pkg": "sigen_app",
            "Version": "RELEASE",
            "Client-Server": "aus",
        })
    
    def authenticate(self) -> bool:
        """Get access token."""
        try:
            device_id = str(int(time.time() * 1000))
            client_creds = base64.b64encode(b"sigen:sigen").decode("utf-8")
            
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {client_creds}",
                "Auth-Client-Id": "sigen",
                "Sg-V": "3.4.0",
                "Sg-Ts": str(int(time.time() * 1000)),
            }
            
            data = {
                "scope": "server",
                "grant_type": "password",
                "userDeviceId": device_id,
                "username": self.username,
                "password": self.password,
            }
            
            response = self.session.post(AUTH_URL, data=data, headers=headers, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                if result.get("code") == 0:
                    self.access_token = result["data"]["access_token"]
                    _LOGGER.info("MySigen authenticated successfully")
                    return True
            
            _LOGGER.error("Auth failed: %s", response.text)
            return False
            
        except Exception as e:
            _LOGGER.error("Auth error: %s", e)
            return False
    
    def update(self):
        """Fetch fresh data."""
        if not self.access_token and not self.authenticate():
            return
        
        try:
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "TENANT-ID": "1",
                "Auth-Client-Id": "sigen",
                "Sg-V": "3.4.0",
                "Sg-Ts": str(int(time.time() * 1000)),
            }
            
            # Get station info if needed
            if not self.station_id:
                resp = self.session.get(STATION_URL, headers=headers, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("code") == 0:
                        self.station_id = str(data["data"]["stationId"])
            
            if not self.station_id:
                return
            
            # Get energy flow
            params = {"id": self.station_id, "refreshFlag": "true"}
            resp = self.session.get(ENERGY_URL, headers=headers, params=params, timeout=10)
            if resp.status_code == 200:
                result = resp.json()
                if result.get("code") == 0:
                    self.data["energy_flow"] = result["data"]
            
            # Get statistics
            params = {"stationId": self.station_id}
            resp = self.session.get(STATS_URL, headers=headers, params=params, timeout=10)
            if resp.status_code == 200:
                result = resp.json()
                if result.get("code") == 0:
                    self.data["statistics"] = result["data"]
                    
        except Exception as e:
            _LOGGER.error("Update error: %s", e)


def setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    discovery_info: Optional[DiscoveryInfoType] = None,
) -> None:
    """Set up MySigen sensors (SYNC version to avoid config entry)."""
    
    username = config.get("username")
    password = config.get("password")
    
    if not username or not password:
        _LOGGER.error("Username and password required")
        return
    
    # Create shared data handler
    data_handler = MySigenData(username, password)
    
    # Authenticate
    if not data_handler.authenticate():
        _LOGGER.error("Authentication failed")
        return
    
    # Initial update
    data_handler.update()
    
    # Create sensors
    sensors = [
        MySigenBatterySoC(data_handler),
        MySigenBatteryPower(data_handler),
        MySigenPVPower(data_handler),
        MySigenGridPower(data_handler),
        MySigenLoadPower(data_handler),
        MySigenDayGeneration(data_handler),
        MySigenMonthGeneration(data_handler),
        MySigenYearGeneration(data_handler),
        MySigenLifetimeGeneration(data_handler),
    ]
    
    add_entities(sensors, True)
    _LOGGER.info("MySigen: Loaded %d sensors", len(sensors))


class MySigenSensor(SensorEntity):
    """Base MySigen sensor."""
    
    def __init__(self, data_handler: MySigenData, name: str):
        self._data_handler = data_handler
        self._attr_name = f"MySigen {name}"
        self._attr_unique_id = f"mysigen_battery_{name.lower().replace(' ', '_')}"
        
        # Add device info to group all sensors under one device
        self._attr_device_info = {
            "identifiers": {("mysigen_battery", "sigenstor_battery")},
            "name": "Sigenstor Battery",
            "manufacturer": "Sigen Energy",
            "model": "Battery System",
        }
    
    def update(self):
        """Update sensor."""
        self._data_handler.update()


class MySigenBatterySoC(MySigenSensor):
    """Battery SoC sensor."""
    
    def __init__(self, data_handler):
        super().__init__(data_handler, "Battery SoC")
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_device_class = SensorDeviceClass.BATTERY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._last_valid_value = None  # Store last known value
    
    @property
    def native_value(self):
        """Return battery SoC, keeping last value if API returns None."""
        current_value = self._data_handler.data.get("energy_flow", {}).get("batterySoc")
        
        # If we got a valid value, store it
        if current_value is not None:
            self._last_valid_value = current_value
            return current_value
        
        # If API returns None but we have a previous value, keep showing it
        return self._last_valid_value


class MySigenBatteryPower(MySigenSensor):
    """Battery power sensor."""
    
    def __init__(self, data_handler):
        super().__init__(data_handler, "Battery Discharge Power")
        self._attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
        self._attr_device_class = SensorDeviceClass.POWER
        self._attr_state_class = SensorStateClass.MEASUREMENT
    
    @property
    def native_value(self):
        power = self._data_handler.data.get("energy_flow", {}).get("batteryPower")
        if power is not None:
            return round(power / 1000, 2) if abs(power) > 100 else power
        return None


class MySigenPVPower(MySigenSensor):
    """PV power sensor."""
    
    def __init__(self, data_handler):
        super().__init__(data_handler, "Current PV Power")
        self._attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
        self._attr_device_class = SensorDeviceClass.POWER
        self._attr_state_class = SensorStateClass.MEASUREMENT
    
    @property
    def native_value(self):
        power = self._data_handler.data.get("energy_flow", {}).get("pvPower")
        if power is not None:
            return round(power / 1000, 2) if abs(power) > 100 else power
        return None


class MySigenGridPower(MySigenSensor):
    """Grid power sensor."""
    
    def __init__(self, data_handler):
        super().__init__(data_handler, "Current Grid Power")
        self._attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
        self._attr_device_class = SensorDeviceClass.POWER
        self._attr_state_class = SensorStateClass.MEASUREMENT
    
    @property
    def native_value(self):
        power = self._data_handler.data.get("energy_flow", {}).get("buySellPower")
        if power is not None:
            return round(power / 1000, 2) if abs(power) > 100 else power
        return None


class MySigenLoadPower(MySigenSensor):
    """Load power sensor."""
    
    def __init__(self, data_handler):
        super().__init__(data_handler, "Current Load Power")
        self._attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
        self._attr_device_class = SensorDeviceClass.POWER
        self._attr_state_class = SensorStateClass.MEASUREMENT
    
    @property
    def native_value(self):
        power = self._data_handler.data.get("energy_flow", {}).get("loadPower")
        if power is not None:
            return round(power / 1000, 2) if abs(power) > 100 else power
        return None


class MySigenDayGeneration(MySigenSensor):
    """Day generation sensor."""
    
    def __init__(self, data_handler):
        super().__init__(data_handler, "Today PV Generation")
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
    
    @property
    def native_value(self):
        return self._data_handler.data.get("statistics", {}).get("dayGeneration")


class MySigenMonthGeneration(MySigenSensor):
    """Month generation sensor."""
    
    def __init__(self, data_handler):
        super().__init__(data_handler, "This Months PV Generation")
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL
    
    @property
    def native_value(self):
        return self._data_handler.data.get("statistics", {}).get("monthGeneration")


class MySigenYearGeneration(MySigenSensor):
    """Year generation sensor."""
    
    def __init__(self, data_handler):
        super().__init__(data_handler, "This Years PV Generation")
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL
    
    @property
    def native_value(self):
        return self._data_handler.data.get("statistics", {}).get("yearGeneration")


class MySigenLifetimeGeneration(MySigenSensor):
    """Lifetime generation sensor."""
    
    def __init__(self, data_handler):
        super().__init__(data_handler, "Lifetime PV Generation")
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
    
    @property
    def native_value(self):
        return self._data_handler.data.get("statistics", {}).get("lifetimeGeneration")