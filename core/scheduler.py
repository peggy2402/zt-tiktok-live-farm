import time
import threading
from datetime import datetime
from typing import Dict, List
from core.models import DeviceState, DeviceStatus

class FarmScheduler:
    """
    Bộ não của hệ thống:
    - Quyết định máy nào LIVE giờ nào.
    - Tự động xoay tua máy để tránh nóng.
    """
    def __init__(self):
        self.schedules = {} # {udid: {"start": 8, "end": 12}} (Giờ)
        self.running = False
        self.lock = threading.Lock()
        
    def set_schedule(self, udid: str, start_hour: int, end_hour: int):
        with self.lock:
            self.schedules[udid] = {"start": start_hour, "end": end_hour}
            
    def should_be_active(self, udid: str) -> bool:
        """Kiểm tra xem giờ hiện tại máy này có được phép chạy không"""
        if udid not in self.schedules:
            return False # Không có lịch -> Không chạy
            
        now = datetime.now().hour
        sch = self.schedules[udid]
        
        # Xử lý trường hợp qua đêm (ví dụ 22h -> 06h)
        if sch["start"] <= sch["end"]:
            return sch["start"] <= now < sch["end"]
        else:
            return now >= sch["start"] or now < sch["end"]

    def get_next_action(self, device_state: DeviceState) -> str:
        """
        Trả về hành động tiếp theo dựa trên trạng thái và lịch
        """
        if not self.should_be_active(device_state.udid):
            return "STOP"
            
        if device_state.status == DeviceStatus.ERROR:
            return "RESTART_APP"
            
        if device_state.status == DeviceStatus.ONLINE:
            return "START_LIVE"
            
        # Nếu đang LIVE, kiểm tra xem có cần đổi sản phẩm không (ví dụ mỗi 30p)
        if device_state.status == DeviceStatus.LIVING:
            if time.time() - device_state.last_active > 1800: # 30 mins
                return "ROTATE_PRODUCT"
                
        return "CONTINUE"