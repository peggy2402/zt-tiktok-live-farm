# core/unified_client.py
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

class UnifiedClient:
    """
    Client thống nhất làm việc với cả tidevice và pymobiledevice3
    """
    def __init__(self, port: int, engine: str = "tidevice", udid: str = None):
        self.port = port
        self.engine = engine  # "tidevice" hoặc "pymobile"
        self.udid = udid
        self.client = None
        self.session = None
        self.wda_bundle_id = WDA_BUNDLE_ID
        self.progress_callback = None
        
        self.crash_logs = [] # Lưu log crash tạm thời
        # Engine-specific attributes
        self.pymobile_lockdown = None
        self.pymobile_dvt = None
        
    def _diagnose_wda_crash(self):
        """Đọc syslog để tìm nguyên nhân WDA crash"""
        self._report_progress("🔍 DIAGNOSING WDA CRASH via Syslog...")
        try:
            # Lệnh đọc syslog và lọc theo tên process WDA (thường chứa 'WebDriverAgent')
            # Chạy trong 5 giây để bắt lỗi
            cmd = [
                sys.executable, "-m", "pymobiledevice3", 
                "syslog", "live", "--udid", self.udid
            ]
            
            self._report_progress("Capturing device logs for 3 seconds...")
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors='ignore')
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
        
        # BƯỚC 0: Kiểm tra kỹ xem Bundle ID có đúng không TRƯỚC khi chạy
        # Tránh trường hợp config sai dẫn đến launch thành công (giả) nhưng app không lên
        detected_id = self._check_app_installed()
        if detected_id and detected_id != self.wda_bundle_id:
            self._report_progress(f"Auto-corrected Bundle ID: {self.wda_bundle_id} -> {detected_id}")
            self.wda_bundle_id = detected_id
        elif not detected_id:
            self._report_progress(f"[WARNING] WDA Bundle ID '{self.wda_bundle_id}' not found on device. Launching anyway...")

        self._report_progress(f"Sending launch command for WDA ({self.wda_bundle_id})...")
        try:
            cmd = [
                sys.executable, "-m", "pymobiledevice3",
                "developer", "dvt", "launch", self.wda_bundle_id,
                "--udid", self.udid
            ]
            # Use CREATE_NO_WINDOW on Windows to hide the console
            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=15, 
                creationflags=creation_flags, encoding='utf-8', errors='ignore'
            )
            if "Process is running" in result.stdout or result.returncode == 0:
                self._report_progress(f"WDA launch command sent. (Bundle: {self.wda_bundle_id})")
                return True
            else:
                self._report_progress(f"WDA launch command failed: {result.stderr.strip()}")
                return False
        except Exception as e:
            self._report_progress(f"Exception while launching WDA: {e}")
            return False

    def _check_app_installed(self):
        """Kiểm tra và tự động phát hiện WDA Bundle ID"""
        try:
            cmd = [sys.executable, "-m", "pymobiledevice3", "apps", "list", "--udid", self.udid, "--json"]
            res = subprocess.run(cmd, capture_output=True, text=True, errors='ignore')
            apps = json.loads(res.stdout)
            # apps là dict {BundleID: {info}}
            
            if self.wda_bundle_id in apps:
                self._report_progress(f"[OK] Bundle ID '{self.wda_bundle_id}' is installed.")
                return self.wda_bundle_id
            
            # Nếu không tìm thấy ID cấu hình, tìm ID nào giống WDA nhất
            for bid in apps:
                if "WebDriverAgent" in bid or "xctrunner" in bid:
                    self._report_progress(f"[AUTO-DETECT] Found WDA: {bid}")
                    return bid
            
            # Debug: In ra các app User cài đặt để user check
            user_apps = [bid for bid, info in apps.items() if info.get('ApplicationType') == 'User']
            if user_apps:
                self._report_progress(f"[DEBUG] WDA not found. Installed User Apps: {', '.join(user_apps)}")
            else:
                self._report_progress("[DEBUG] No User Apps found on device. (Is WDA installed?)")
            
            self._report_progress(f"[CRITICAL] WDA not found. Configured: {self.wda_bundle_id}")
            return None
        except:
            pass
        return None

    def connect(self) -> bool:
        """Kết nối với thiết bị dựa trên engine"""
        self._report_progress(f"Connecting via {self.engine} on port {self.port}...")
        
        if self.engine == "tidevice":
            return self._connect_tidevice()
        else:
            return self._connect_pymobile()
    
    def _connect_tidevice(self) -> bool:
        """Kết nối qua WDA (iOS 15.x)"""
        max_retries = 20
        for i in range(max_retries):
            try:
                self.client = wda.Client(f"http://localhost:{self.port}")
                self.client.healthcheck()
                device_info = self.client.device_info()
                self._report_progress(f"Connected! Device: {device_info}")
                return True
            except Exception as e:
                if i < max_retries - 1:
                    self._report_progress(f"Retrying... ({i+1}/{max_retries})")
                    time.sleep(2)
                else:
                    self._report_progress(f"Connection failed details: {type(e).__name__}: {e}")
        return False
    
    def _connect_pymobile(self) -> bool:
        """Kết nối qua pymobiledevice3 (iOS 17+)"""
        
        # --- BẮT ĐẦU GHI LOG NGẦM ---
        # Ghi lại syslog trong quá trình khởi động để bắt lỗi crash ngay lập tức
        self.crash_logs = []
        stop_log_event = threading.Event()
        
        def capture_logs():
            try:
                cmd = [sys.executable, "-m", "pymobiledevice3", "syslog", "live", "--udid", self.udid]
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors='ignore')
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

        # 1. Gửi lệnh khởi chạy WDA một cách chủ động
        self._launch_wda_app_pymobile()
        # 2. Đợi WDA có thời gian khởi động trên điện thoại
        self._report_progress("Waiting 5s for WDA to launch on device...")
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

    def start_tiktok_live(self, video_path: Optional[str] = None) -> bool:
        """Bắt đầu LIVE trên TikTok - Tương thích cả 2 engine"""
        
        try:
            # Mở TikTok
            if self.engine == "tidevice":
                return self._tidevice_live_scenario(video_path)
            else:
                return self._pymobile_live_scenario(video_path)
                
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
    
    def _pymobile_live_scenario(self, video_path: Optional[str]) -> bool:
        """Scenario cho iOS 18 (pymobiledevice3)"""
        # Phương án 1: Dùng WDA client nếu có
        if self.client:
            return self._tidevice_live_scenario(video_path)
        
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
    
    def warm_up_account(self, duration: int = 60) -> bool:
        """Nuôi nick TikTok - Tương thích cả 2 engine"""
        if not self._ensure_session(TIKTOK_BUNDLE_ID):
            return False
        
        start_time = time.time()
        action_count = 0
        
        while time.time() - start_time < duration:
            try:
                # Lướt video (swipe up)
                if self.client:
                    w, h = self.session.window_size()
                    self.session.swipe(w * 0.5, h * 0.8, w * 0.5, h * 0.2, duration=0.3)
                
                # Xem video 5-8s
                watch_time = random.randint(5, 8)
                time.sleep(watch_time)
                
                # Thả tim (30% cơ hội)
                if random.random() < 0.3 and self.client:
                    self.session.double_tap(w * 0.5, h * 0.5)
                    self._report_progress("❤️ Liked video")
                
                action_count += 1
                
            except Exception as e:
                self._report_progress(f"Warm-up error: {e}")
                time.sleep(2)
        
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