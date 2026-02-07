from dataclasses import dataclass
from enum import Enum
from typing import Optional

class DeviceStatus(Enum):
    OFFLINE = "offline"
    ONLINE = "online"
    LIVING = "living"      # Đang phát LIVE
    FARMING = "farming"    # Đang đi tương tác
    ERROR = "error"
    COOLDOWN = "cooldown"  # Nghỉ cho máy mát

@dataclass
class DeviceState:
    udid: str
    status: DeviceStatus = DeviceStatus.OFFLINE
    battery_level: int = 0
    is_charging: bool = False
    temperature_state: str = "Normal" # Normal, Warm, Hot
    current_task: str = "Idle"
    last_active: float = 0.0
    ip_address: str = "Unknown"
    
    # Affiliate Stats
    products_pinned: int = 0
    live_duration: int = 0