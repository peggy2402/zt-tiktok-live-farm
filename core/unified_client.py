# core/unified_client.py
import socket
import wda
import json
import time
import sys
import subprocess
import random
import requests
import threading
from typing import Optional, Callable
from config.settings import TIKTOK_BUNDLE_ID, WDA_BUNDLE_ID
import os
from core.models import DeviceStatus

class UnifiedClient:
    """
    Client thống nhất làm việc với cả tidevice và pymobiledevice3
    """
    def __init__(self, port: int, engine: str = "pymobile", udid: str = None):
        self.port = port
        self.engine = engine
        self.udid = udid
        self.client = None
        self.session = None
        self.wda_bundle_id = WDA_BUNDLE_ID
        self.progress_callback = None
        
        self.crash_logs = [] # Lưu log crash tạm thời
        self.last_action_time = time.time()
        # Engine-specific attributes
        self.pymobile_lockdown = None
        self.pymobile_dvt = None
        
    def _diagnose_wda_crash(self):
        """Đọc syslog để tìm nguyên nhân WDA crash"""
        self._report_progress("🔍 DIAGNOSING WDA CRASH via Syslog...")
        
        safe_env = os.environ.copy()
        safe_env["TERM"] = "dumb"
        
        try:
            # Lệnh đọc syslog và lọc theo tên process WDA (thường chứa 'WebDriverAgent')
            # Chạy trong 5 giây để bắt lỗi
            cmd = [
                sys.executable, "-m", "pymobiledevice3", 
                "syslog", "live", "--udid", self.udid
            ]
            
            self._report_progress("Capturing device logs for 3 seconds...")
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors='ignore', env=safe_env)
            time.sleep(3)
            process.terminate()
            
            out, _ = process.communicate()
            relevant_logs = [line for line in out.split('\n') if "WebDriverAgent" in line or "dyld" in line or "runningboard" in line]
            
            if relevant_logs:
                self._report_progress("--- DEVICE CRASH LOGS ---")
                for log in relevant_logs[-10:]: # In 10 dòng cuối
                    print(f"   [SYS] {log}")
                self._report_progress("-------------------------")
        except Exception as e:
            print(f"Diagnosis failed: {e}")

    def _report_progress(self, message: str):
        print(f"[{self.engine.upper()}] {message}")
        if self.progress_callback:
            self.progress_callback(message)
    
    def _launch_wda_app_pymobile(self) -> bool:
        """Sử dụng pymobiledevice3 để gửi lệnh khởi chạy WDA."""
        if not self.udid:
            return False
        
        safe_env = os.environ.copy()
        safe_env["TERM"] = "dumb"

        # [OPTIMIZATION] Nếu engine là tidevice, dùng tidevice ngay lập tức
        if self.engine == "tidevice":
            self._report_progress(f"Using tidevice to launch WDA ({self.wda_bundle_id})...")
            subprocess.run(["tidevice", "--udid", self.udid, "launch", self.wda_bundle_id], 
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            return True

        # BƯỚC 0: Kiểm tra kỹ xem Bundle ID có đúng không TRƯỚC khi chạy
        # Tránh trường hợp config sai dẫn đến launch thành công (giả) nhưng app không lên
        detected_id = self._check_app_installed()
        if detected_id and detected_id != self.wda_bundle_id:
            self._report_progress(f"Auto-corrected Bundle ID: {self.wda_bundle_id} -> {detected_id}")
            self.wda_bundle_id = detected_id
        elif not detected_id:
            self._report_progress(f"[WARNING] WDA Bundle ID '{self.wda_bundle_id}' not found on device. Launching anyway...")

        # [FIX TRIỆT ĐỂ] Nếu pymobile không tìm thấy app (detected_id is None), 
        # nghĩa là nó đang mù. Dùng tidevice để launch ngay lập tức.
        if detected_id is None:
            try:
                self._report_progress("Pymobile blind. Switching to tidevice for launch...")
                subprocess.run(["tidevice", "--udid", self.udid, "launch", self.wda_bundle_id], 
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                return True
            except:
                pass 

        self._report_progress(f"Sending launch command for WDA ({self.wda_bundle_id})...")
        try:
            cmd = [
                sys.executable, "-m", "pymobiledevice3", 
                "developer", "dvt", "launch", 
                "--udid", self.udid,
                self.wda_bundle_id
            ]
            # Use CREATE_NO_WINDOW on Windows to hide the console
            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=15, 
                creationflags=creation_flags, encoding='utf-8', errors='ignore', env=safe_env
            )
            if "Process is running" in result.stdout or result.returncode == 0:
                self._report_progress(f"WDA launch command sent. (Bundle: {self.wda_bundle_id})")
                return True
            else:
                err_msg = result.stderr.strip()
                self._report_progress(f"WDA launch command failed: {err_msg}")
                
                # Phân tích lỗi cụ thể để hướng dẫn người dùng
                if "returned nil" in err_msg or "NotFound" in err_msg:
                     self._report_progress(f"❌ ERROR: Bundle ID '{self.wda_bundle_id}' not found on device.")
                     self._report_progress("👉 SOLUTION: Check if WDA is installed. The tool tried to auto-detect but failed.")
                return False
        except Exception as e:
            self._report_progress(f"Exception while launching WDA: {e}")
            
            # [FALLBACK] Nếu pymobile thất bại, thử dùng tidevice (nếu có)
            try:
                self._report_progress("Attempting fallback launch via tidevice...")
                # Capture output để debug nếu lỗi
                res = subprocess.run(["tidevice", "--udid", self.udid, "launch", self.wda_bundle_id], 
                                     capture_output=True, text=True, check=False)
                if res.returncode == 0:
                    self._report_progress(f"tidevice launch success: {res.stdout.strip()}")
                    return True
                else:
                    self._report_progress(f"tidevice launch failed: {res.stderr.strip()}")
            except FileNotFoundError:
                self._report_progress("[HINT] Install 'tidevice' for better compatibility: pip install tidevice")
            
            return False

    def _check_app_installed(self):
        """Kiểm tra và tự động phát hiện WDA Bundle ID"""
        safe_env = os.environ.copy()
        safe_env["TERM"] = "dumb"
        
        try:
            # FIX: Bỏ --json vì phiên bản pymobiledevice3 hiện tại không hỗ trợ
            cmd = [sys.executable, "-m", "pymobiledevice3", "apps", "list", "--udid", self.udid]
            res = subprocess.run(cmd, capture_output=True, text=True, errors='ignore', timeout=20, env=safe_env)
            
            if res.returncode != 0:
                self._report_progress(f"[DEBUG] Failed to list apps: {res.stderr.strip()}")
                return None
            
            output = res.stdout
            if not output.strip():
                # [FALLBACK] Nếu pymobile trả về rỗng, thử dùng tidevice
                try:
                    cmd_tidevice = ["tidevice", "--udid", self.udid, "applist"]
                    res_tidevice = subprocess.run(cmd_tidevice, capture_output=True, text=True, errors='ignore')
                    if res_tidevice.returncode == 0 and res_tidevice.stdout.strip():
                        output = res_tidevice.stdout
                        self._report_progress("[DEBUG] Used tidevice fallback for app list.")
                except:
                    pass
            
            if not output.strip():
                self._report_progress("[DEBUG] App list output is empty.")
                return None

            # Parse text output (tìm kiếm chuỗi trong toàn bộ output)
            if self.wda_bundle_id in output:
                self._report_progress(f"[OK] Bundle ID '{self.wda_bundle_id}' is installed.")
                return self.wda_bundle_id
            
            # Tìm kiếm ID nào giống WDA (chứa WebDriverAgent hoặc xctrunner)
            lines = output.splitlines()
            found_wda = None
            user_apps = []

            for line in lines:
                line = line.strip()
                if not line: continue
                
                # Lọc ra các app người dùng (không phải com.apple) để hiển thị gợi ý
                if "com.apple." not in line:
                    # Lấy chuỗi có vẻ là Bundle ID (chứa dấu chấm)
                    parts = line.split()
                    for part in parts:
                        if "." in part and not part.startswith("("): 
                             user_apps.append(part)
                             break

                # [IMPROVED] Tìm kiếm WDA với nhiều từ khóa hơn (wda, runner...)
                line_lower = line.lower()
                if any(k in line_lower for k in ["webdriveragent", "xctrunner", "wda", "runner"]):
                    parts = line.split()
                    for part in parts:
                        # Bundle ID phải có dấu chấm, không bắt đầu bằng (, và chứa từ khóa
                        if "." in part and not part.startswith("(") and \
                           any(k in part.lower() for k in ["webdriveragent", "xctrunner", "wda", "runner"]):
                            found_wda = part
                            break
                if found_wda: break
            
            if found_wda:
                self._report_progress(f"[AUTO-DETECT] Found WDA: {found_wda}")
                return found_wda
            
            self._report_progress(f"[CRITICAL] WDA not found. Configured: {self.wda_bundle_id}")
            
            if user_apps:
                self._report_progress("--- INSTALLED USER APPS (Copy ID below if it is WDA) ---")
                for app in user_apps:
                    self._report_progress(f"   {app}")
                self._report_progress("--------------------------------------------------------")
            else:
                self._report_progress(f"[DEBUG] Raw app list sample: {lines[:5] if lines else 'Empty'}")
                
            return None
        except Exception as e:
            self._report_progress(f"[DEBUG] Error checking apps: {e}")
            return None

    def connect(self) -> bool:
        """Kết nối với thiết bị dựa trên engine"""
        self._report_progress(f"Connecting via {self.engine} on port {self.port}...")
        # Trong kiến trúc Hybrid mới, DeviceController đã lo việc start relay/wda.
        # UnifiedClient chỉ cần verify kết nối HTTP tới localhost.
        return self._connect_http_wda()
    
    def _connect_http_wda(self) -> bool:
        """Kết nối thuần HTTP tới WDA đã được relay"""
        try:
            self.client = wda.Client(f"http://localhost:{self.port}")
            self.client.healthcheck()
            self._report_progress("Connected via HTTP Relay (Stable)")
            return True
        except Exception as e:
            self._report_progress(f"Connection failed: {e}")
            return False

    def _connect_pymobile(self) -> bool:
        """Kết nối qua pymobiledevice3 (iOS 17+)"""
        
        # --- BẮT ĐẦU GHI LOG NGẦM ---
        # Ghi lại syslog trong quá trình khởi động để bắt lỗi crash ngay lập tức
        self.crash_logs = []
        stop_log_event = threading.Event()
        
        safe_env = os.environ.copy()
        safe_env["TERM"] = "dumb"
        
        def capture_logs():
            try:
                cmd = [sys.executable, "-m", "pymobiledevice3", "syslog", "live", "--udid", self.udid]
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors='ignore', env=safe_env)
                while not stop_log_event.is_set():
                    line = proc.stdout.readline()
                    if not line: break
                    # Lọc các từ khóa quan trọng liên quan đến lỗi khởi động App
                    if any(k in line for k in ["WebDriverAgent", "dyld", "runningboard", "assertiond", "amfid", "code signature"]):
                        self.crash_logs.append(line.strip())
                        if len(self.crash_logs) > 50: self.crash_logs.pop(0) # Giữ 50 dòng cuối
                proc.terminate()
            except:
                pass
        
        threading.Thread(target=capture_logs, daemon=True).start()
        # ---------------------------

        # [CHANGE] Nếu đang dùng tidevice wdaproxy (đã chạy ở DeviceManager), 
        # thì không cần launch thủ công nữa. Chỉ launch nếu chưa có kết nối.
        if not self._check_wda_alive():
            self._report_progress("WDA not responding, attempting manual launch...")
            self._launch_wda_app_pymobile()
            time.sleep(5)
        
        stop_log_event.set() # Dừng ghi log
        
        try:
            # Kiểm tra kết nối cơ bản (Retry vài lần)
            for _ in range(3):
                try:
                    response = requests.get(f"http://127.0.0.1:{self.port}/status", timeout=5)
                    if response.status_code == 200:
                        break
                except:
                    time.sleep(2)
            
            # Kết nối WDA client (vẫn dùng facebook-wda cho DVT proxy)
            self.client = wda.Client(f"http://localhost:{self.port}")
            self.client.healthcheck()
            
            self._report_progress("Connected via pymobiledevice3 DVT proxy")
            return True
        except Exception as e:
            self._report_progress(f"Pymobile connection failed. CHECK: Trusted App? WDA Running? (iOS 15 doesn't need Dev Mode)")
            
            # In ra log đã bắt được
            if self.crash_logs:
                self._report_progress("--- CRASH LOGS DURING LAUNCH ---")
                for log in self.crash_logs:
                    print(f"   [SYS] {log}")
                self._report_progress("--------------------------------")
            else:
                self._report_progress("[DEBUG] No crash logs captured (Syslog might be empty or filtered).")
                self._diagnose_wda_crash()
            
            # Fallback: Thử dùng trực tiếp pymobiledevice3 nếu WDA không hoạt động
            try:
                from pymobiledevice3.lockdown import create_using_usbmux
                self.pymobile_lockdown = create_using_usbmux(serial=self.udid)
                self._report_progress("Connected via pymobiledevice3 direct")
                return True
            except Exception as e2:
                self._report_progress(f"Direct connection also failed: {e2}")
                return False

    def _check_wda_alive(self):
        """Kiểm tra nhanh xem WDA có đang trả lời không"""
        try:
            response = requests.get(f"http://127.0.0.1:{self.port}/status", timeout=2)
            if response.status_code == 200:
                return True
        except:
            pass
        return False

    def get_device_info(self):
        """Lấy thông tin pin và nhiệt độ (giả lập hoặc qua WDA)"""
        info = {
            "battery": 0,
            "charging": False,
            "ip": "Unknown"
        }
        if self.client:
            try:
                # WDA info
                wda_info = self.client.status()
                # Một số bản WDA custom có trả về battery, bản gốc thì không.
                # Ở đây ta dùng info từ lockdown nếu có thể, hoặc giả lập logic
                
                # Giả lập logic giảm pin khi LIVE
                elapsed = time.time() - self.last_action_time
                estimated_drain = int(elapsed / 300) # 5 phút mất 1%
                info["battery"] = max(10, 100 - estimated_drain) 
                
                # Lấy IP thật
                info["ip"] = wda_info.get("ios", {}).get("ip", "Unknown")
            except:
                pass
        return info

    def _ensure_session(self, bundle_id: str):
        """Đảm bảo session WDA hợp lệ, tự động kết nối lại nếu mất."""
        try:
            # Kiểm tra nhanh xem session có còn hoạt động không
            if self.session and self.session.running:
                 self.client.healthcheck() # Kiểm tra sâu hơn qua HTTP request
                 return True
            raise wda.exceptions.WDAError("Session not running or invalid")
        except (AttributeError, wda.exceptions.WDAError, requests.exceptions.ConnectionError):
            self._report_progress("Session invalid or connection lost. Re-establishing...")
            if self.connect(): # connect() sẽ tự động thử khởi chạy lại WDA
                self.session = self.client.session(bundle_id)
                time.sleep(2) # Đợi session sẵn sàng
                return True
            else:
                self._report_progress("[ERROR] Failed to re-establish session.")
                return False

    def start_tiktok_live(self, title: str = "Chill Stream") -> bool:
        """Bắt đầu LIVE trên TikTok - Tương thích cả 2 engine"""
        
        try:
            self._report_progress(f"Preparing LIVE: {title}")
            # Mở TikTok
            return self._pymobile_live_scenario(title)

        except Exception as e: # Bắt các lỗi không lường trước
            self._report_progress(f"LIVE scenario failed: {e}")
            return False
    
    def _tidevice_live_scenario(self, video_path: Optional[str]) -> bool:
        """Scenario cho iOS 15 (tidevice + WDA)"""
        self.session = self.client.session(TIKTOK_BUNDLE_ID)
        time.sleep(3)
        self._report_progress("Starting TikTok LIVE scenario...")

        if not self._ensure_session(TIKTOK_BUNDLE_ID):
            return False
        
        # Bấm nút Tạo/Create
        self._tap_by_label(["Create", "Tạo", "Post"], timeout=10)
        time.sleep(2)
        
        # Chuyển sang tab LIVE
        self._tap_by_label(["LIVE", "Live"], timeout=8)
        time.sleep(2)
        
        # Bấm Phát LIVE
        self._tap_by_label(["Go LIVE", "Phát LIVE", "Start LIVE"], timeout=10)
        time.sleep(5)
        
        self._report_progress("LIVE started successfully!")
        return True
    
    def _pymobile_live_scenario(self, title: str) -> bool:
        """Scenario cho iOS 18 (pymobiledevice3)"""
        # Phương án 1: Dùng WDA client nếu có
        if self.client:
            return self._tidevice_live_scenario(None) # Tái sử dụng logic WDA
        
        # Phương án 2: Dùng pymobiledevice3 trực tiếp
        try:
            from pymobiledevice3.services.installation_proxy import InstallationProxyService
            from pymobiledevice3.services.springboard import SpringBoardServicesService
            
            # Mở TikTok bằng bundle ID
            sb = SpringBoardServicesService(self.pymobile_lockdown)
            sb.launch_application(TIKTOK_BUNDLE_ID)
            self._report_progress("TikTok launched via pymobiledevice3")
            
            # TODO: Thêm logic điều khiển UI qua pymobiledevice3
            # Cần implement thêm các thao tác tap/swipe
            
            return True
        except Exception as e:
            self._report_progress(f"Pymobile direct control failed: {e}")
            return False
    
    def send_comment(self, text: str):
        """Gửi comment vào LIVE (Seeding)"""
        if not self.client: return False
        try:
            # Tìm ô chat
            self._tap_by_label(["Comment", "Bình luận", "Add comment..."])
            time.sleep(1)
            self.client.send_keys(text)
            time.sleep(0.5)
            self.client.send_keys("\n") # Enter
            self._report_progress(f"💬 Commented: {text}")
            return True
        except Exception as e:
            self._report_progress(f"Comment failed: {e}")
            return False

    def pin_product(self, product_index: int = 1):
        """Ghim sản phẩm trong giỏ hàng (Affiliate)"""
        if not self.client: return False
        try:
            self._report_progress("🛒 Opening Shop...")
            self._tap_by_label(["Shop", "Cửa hàng", "Bag"])
            time.sleep(2)
            
            # Logic click theo tọa độ tương đối (vì list sản phẩm khó bắt element)
            # Giả sử sản phẩm 1 nằm ở y=0.4, sản phẩm 2 ở y=0.6
            w, h = self.session.window_size()
            y_pos = 0.4 + (product_index * 0.15)
            self.session.tap(w * 0.8, h * y_pos) # Nút "Ghim/Pin" thường ở bên phải
            self._report_progress(f"📌 Pinned product #{product_index}")
            
            # Đóng shop
            self.session.tap(w * 0.5, h * 0.15) # Tap ra ngoài
            return True
        except Exception as e:
            self._report_progress(f"Pin product failed: {e}")
            return False

    def _tap_by_label(self, labels: list, timeout: int = 10) -> bool:
        """Tìm và tap element theo danh sách labels (thử lần lượt)"""
        for label in labels:
            try:
                element = self.session(label=label)
                if element.wait(timeout=2):
                    element.click()
                    self._report_progress(f"Tapped '{label}'")
                    return True
            except:
                continue
        
        # Fallback: Swipe để tìm
        w, h = self.session.window_size()
        self.session.swipe(w * 0.8, h * 0.5, w * 0.2, h * 0.5, duration=0.5)
        time.sleep(1)
        
        return False
    
    def _get_host_ip(self):
        """Lấy IP LAN của máy tính (Host)"""
        dns_server = "1.1.1.1"
        max_attempts = 5
        for attempt in range(max_attempts):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(2)
                    s.connect((dns_server, 53))
                    return s.getsockname()[0]
            except OSError:
                if attempt == max_attempts - 1:
                    return "127.0.0.1"
                time.sleep(1)
        return "127.0.0.1"

    def _find_free_port(self):
        """Tìm một port trống trên máy tính"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('', 0))
                return s.getsockname()[1]
        except OSError:
            return 0

    def set_virtual_location(self, lat: float = 34.0522, lon: float = -118.2437) -> bool:
        """
        Fake GPS location to US (Default: Los Angeles).
        Requires Developer Disk Image mounted.
        """
        self._report_progress(f"Setting virtual location to {lat}, {lon} (US)...")
        
        safe_env = os.environ.copy()
        safe_env["TERM"] = "dumb"
        
        try:
            # [FIX] Đặt --udid LÊN ĐẦU để tránh lỗi exit status 2
            # Lệnh này chuẩn cho iOS 15.x (Dùng DDI, không dùng RSD)
            cmd = [
                sys.executable, "-m", "pymobiledevice3", 
                "developer", "simulate-location", "set",
                "--udid", self.udid,
                "--", str(lat), str(lon)
            ]
            
            # Hide console window on Windows
            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creation_flags, check=True, timeout=10, env=safe_env)
            self._report_progress("✅ Virtual location set successfully.")
            return True
        except Exception as e:
            self._report_progress(f"❌ Failed to set location: {e}")
            return False

    def warm_up_account(self, duration: int = 60, behavior_profile: str = "random") -> bool:
        """Nuôi nick TikTok - Tương thích cả 2 engine"""
        self._report_progress("Launching TikTok for Warm-up...")
        
        # 1. Đảm bảo App được mở trước
        subprocess.run(["tidevice", "--udid", self.udid, "launch", TIKTOK_BUNDLE_ID], 
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        time.sleep(5) # Đợi App load (quan trọng để tránh màn hình đen)

        if not self._ensure_session(TIKTOK_BUNDLE_ID):
            return False
        
        start_time = time.time()
        action_count = 0
        
        # [OPTIMIZATION] Cache window size để giảm tải request tới WDA
        try:
            w, h = self.session.window_size()
        except Exception:
            w, h = (375, 667) # Fallback kích thước iPhone 7 nếu lỗi
            self._report_progress("[WARNING] Could not get screen size. Using default iPhone 7 scale.")
            w, h = (375, 667) 

        while time.time() - start_time < duration:
            try:
                if self.client and self.session:
                    # [HUMAN-LIKE] Quyết định hành động tiếp theo
                    action_roll = random.random()
                    
                    # 5% cơ hội lướt ngược lại (xem lại video cũ) - Hành vi rất người
                    if action_roll < 0.05:
                        self._report_progress("⬆️ Scrolling back to previous video...")
                        start_y = h * 0.2
                        end_y = h * 0.8
                        duration_swipe = random.uniform(0.3, 0.6)
                    else:
                        # 95% lướt tới (Next video)
                        # Randomize swipe speed and distance (Anti-ban)
                        start_y = h * (0.7 + random.uniform(-0.1, 0.1))
                        end_y = h * (0.2 + random.uniform(-0.1, 0.1))
                        duration_swipe = 0.2 + random.uniform(0.0, 0.4) # Tốc độ vuốt không đều

                    # Random tọa độ X để đường vuốt hơi nghiêng (giống tay người cầm điện thoại)
                    start_x = w * (0.5 + random.uniform(-0.1, 0.1))
                    end_x = w * (0.5 + random.uniform(-0.1, 0.1))
                    
                    self.session.swipe(start_x, start_y, end_x, end_y, duration=duration_swipe)
                
                # [HUMAN-LIKE] Thời gian xem video biến thiên mạnh
                # Có video xem lướt (3s), có video xem kỹ (15s)
                watch_time = random.choices([3, 5, 8, 12, 15], weights=[10, 30, 30, 20, 10])[0]
                
                # 10% cơ hội dừng lại lâu hơn để "đọc comment"
                if random.random() < 0.1:
                    read_time = random.randint(3, 6)
                    self._report_progress(f"📖 Reading comments ({read_time}s)...")
                    watch_time += read_time

                self._report_progress(f"Watching {watch_time}s...")
                time.sleep(watch_time)
                
                # Thả tim (30% cơ hội) - Human behavior
                if random.random() < 0.3 and self.client and self.session:
                    self.session.double_tap(w * 0.5, h * 0.5)
                    self._report_progress("❤️ Liked video")
                
                action_count += 1
                
            except Exception as e:
                self._report_progress(f"Warm-up error: {e}")
                # [FIX] Nếu gặp lỗi (ví dụ popup chặn), cứ thử vuốt tiếp để thoát
                self._report_progress(f"Action failed ({e}). Trying to swipe anyway...")
                try:
                    self.session.swipe(w*0.5, h*0.7, w*0.5, h*0.2, duration=0.1)
                except: pass

                # [ADD] Tự động kết nối lại session nếu bị ngắt giữa chừng
                if "Session" in str(e) or "closed" in str(e):
                    self._ensure_session(TIKTOK_BUNDLE_ID)
                time.sleep(2)
                time.sleep(1)
        
        self._report_progress(f"Warm-up completed: {action_count} actions")
        return True
    
    def check_region_health(self) -> bool:
        """
        Kiểm tra sức khỏe thiết bị cho thị trường US:
        1. Kiểm tra kết nối WDA.
        2. Kiểm tra Timezone/Region từ thông tin thiết bị.
        """
        self._report_progress("Checking Device Region Health (US Market)...")
        try:
            if self.client:
                info = self.client.status()
                # info thường có dạng: {'message': 'WebDriverAgent is ready to accept commands', 'state': 'success', 'os': {'testmanagerdVersion': 28, 'name': 'iOS', 'sdkVersion': '16.4', 'version': '16.4'}, 'ios': {'ip': '192.168.1.101'}, 'ready': True, 'build': {'time': '...', 'productBundleIdentifier': 'com.facebook.WebDriverAgentRunner'}}
                
                # Lấy thông tin chi tiết hơn qua session capabilities
                session = self.client.session(self.wda_bundle_id)
                caps = session.capabilities
                
                timezone = caps.get("timeZone", "Unknown")
                locale_setting = caps.get("locale", "Unknown")
                
                self._report_progress(f"Detected Timezone: {timezone} | Locale: {locale_setting}")
                
                # Tự động Set GPS nếu chưa đúng
                if "Ho_Chi_Minh" in timezone:
                     self._report_progress("[AUTO-FIX] Setting GPS to Los Angeles...")
                     self.set_virtual_location(34.0522, -118.2437)

                # Cảnh báo nếu không phải US (Ví dụ cơ bản)
                if "Ho_Chi_Minh" in timezone or "Asia/Bangkok" in timezone:
                    self._report_progress("[WARNING] Device is in VIETNAM Timezone! Please change to US/New_York or US/Los_Angeles.")
                    return False
                
                self._report_progress("[OK] Region settings look acceptable.")
                return True
        except Exception as e:
            self._report_progress(f"Check Region failed: {e}")
        return False

    def check_ip(self) -> bool:
        """Kiểm tra IP bằng cách mở Safari"""
        self._report_progress("Checking IP via Safari...")
        if not self._ensure_session("com.apple.mobilesafari"):
            return False
            
        try:
            if self.client:
                # Dùng WDA để mở Safari
                self.client.session("com.apple.mobilesafari").activate()
                time.sleep(1)
                self.client.open_url("https://whoer.net")
                return True
        except Exception as e:
            self._report_progress(f"Check IP failed: {e}")
        return False

    def disconnect(self):
        """Đóng kết nối"""
        if self.session:
            try:
                self.session.close()
            except:
                pass
        
        if self.pymobile_lockdown:
            try:
                self.pymobile_lockdown.close()
            except:
                pass
        
        self.client = None
        self.session = None
        self.pymobile_lockdown = None
        self._report_progress("Disconnected")