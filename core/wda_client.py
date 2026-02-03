# core/wda_client.py
import wda
import time
import random
from config.settings import TIKTOK_BUNDLE_ID

class WDAClient:
    """
    Client để giao tiếp với WebDriverAgent trên thiết bị iOS.
    Bao bọc thư viện facebook-wda.
    """
    def __init__(self, port):
        self.port = port
        self.client = None
        self.session = None
        self.progress_callback = None # Callback để báo cáo tiến trình về UI

    def _report_progress(self, message):
        """Gửi thông báo tiến trình về UI nếu có callback."""
        print(f"   - {message}")
        if self.progress_callback:
            self.progress_callback(message)

    def connect(self):
        self._report_progress(f"Connecting to WDA at port {self.port}...")
        
        # Retry loop: tidevice takes time to start the WDA server
        max_retries = 15
        for i in range(max_retries):
            try:
                self.client = wda.Client(f"http://localhost:{self.port}")
                self.client.healthcheck()
                self._report_progress("WDA connection successful.")
                print(f"[OK] WDA connected, device info: {self.client.device_info()}")
                return True
            except Exception as e:
                self._report_progress(f"Waiting for WDA... ({i+1}/{max_retries}) - {e}")
                time.sleep(2)

        self._report_progress("WDA connection failed!")
        print(f"[ERROR] Could not connect to WDA at port {self.port} after {max_retries} retries.")
        self.client = None
        return False

    def disconnect(self):
        if self.session:
            self.session.close()
            self.session = None
        self.client = None
        self._report_progress("WDA disconnected.")

    def _click_element(self, label=None, name=None, timeout=10):
        """Hàm tiện ích: Chờ và click vào một element bằng label của nó."""
        identifier = label if label else name
        self._report_progress(f"Finding button '{identifier}'...")
        
        # Hỗ trợ tìm theo label hoặc name (vì TikTok thay đổi liên tục)
        selector = self.session(label=label) if label else self.session(name=name)
        
        if selector.wait(timeout=timeout):
            selector.click()
            self._report_progress(f"Clicked '{identifier}'.")
            return True
            
        self._report_progress(f"Button '{identifier}' not found!")
        raise wda.WDAElementNotFoundError(f"Element '{identifier}' not found")

    def start_live_stream_scenario(self, video_path_on_device):
        if not self.client:
            self._report_progress("WDA not connected.")
            return False

        try:
            self._report_progress("Starting LIVE scenario...")

            # 1. Mở TikTok (hoặc đưa về foreground)
            self._report_progress("Launching TikTok...")
            self.session = self.client.session(TIKTOK_BUNDLE_ID)
            
            # Chờ app active thay vì sleep cứng
            # (Cần logic check app state, nhưng tạm thời sleep ít hơn và check element)
            time.sleep(3) 

            # 2. Bấm nút "Tạo" (Create/Post)
            # LƯU Ý: Label 'Tạo' là ví dụ cho Tiếng Việt.
            # Nếu App của bạn là Tiếng Anh, hãy thử 'Create' hoặc 'Post'.
            # TikTok thường dùng icon dấu cộng, đôi khi label là "Create" hoặc "Post"
            try:
                self._click_element(label="Create", timeout=15)
            except:
                # Fallback nếu không tìm thấy label tiếng Anh
                self._click_element(label="Tạo", timeout=5)

            # 3. Chuyển sang tab "LIVE"
            # LƯU Ý: Label có thể là 'LIVE' hoặc 'Live'.
            # Swipe để chuyển tab nếu click không được (TikTok UI thường là swipe ngang ở dưới)
            try:
                self._click_element(label="LIVE", timeout=10)
            except:
                self._report_progress("Click LIVE failed, trying swipe...")
                # Swipe từ phải sang trái để tìm tab LIVE
                w, h = self.session.window_size()
                self.session.swipe(w * 0.9, h * 0.9, w * 0.1, h * 0.9, duration=0.5)
                time.sleep(2)

            # --- TẠI ĐÂY: Thêm các bước cấu hình LIVE nếu cần ---
            # Ví dụ: Thêm hiệu ứng, chọn sản phẩm affiliate, đặt tiêu đề...
            # self._report_progress("Setting LIVE title...")
            # self.session(label="Add title").click()
            # self.session.send_keys("My Awesome LIVE Stream")

            # 4. Bấm nút "Phát LIVE" (Go LIVE)
            # LƯU Ý: Label có thể là 'Phát LIVE', 'Go LIVE', 'Start LIVE'...
            try:
                self._click_element(label="Go LIVE", timeout=10)
            except:
                self._click_element(label="Phát LIVE", timeout=5)
            
            # Kiểm tra xem đã thực sự LIVE chưa bằng cách tìm nút "End LIVE" hoặc icon mắt
            # time.sleep(10) # Đợi quá trình bắt đầu LIVE

            self._report_progress("LIVE session should be running!")
            return True

        except Exception as e:
            self._report_progress(f"Scenario failed: {e}")
            print(f"[ERROR] An error occurred during the LIVE scenario: {e}")
            try:
                screenshot_name = f"error_screenshot_{self.port}.png"
                self.client.screenshot(screenshot_name)
                self._report_progress(f"Saved screenshot to {screenshot_name}")
            except Exception as se:
                print(f"[ERROR] Could not take screenshot: {se}")
            return False

    def check_ip(self):
        """
        Mở Safari và truy cập whoer.net để kiểm tra IP/Proxy.
        """
        try:
            self._report_progress("Opening Safari to check IP...")
            # Bundle ID của Safari
            self.session = self.client.session("com.apple.mobilesafari")
            self.session.activate()
            time.sleep(2)
            
            # Mở trang check IP uy tín
            self.client.open_url("https://whoer.net")
            self._report_progress("Please check the device screen for IP info.")
            return True
        except Exception as e:
            self._report_progress(f"Failed to open IP check: {e}")
            return False

    def warm_up_scenario(self, duration=60):
        """
        Kịch bản nuôi nick: Lướt TikTok, xem video ngẫu nhiên, thả tim.
        """
        self._report_progress(f"Starting Warm-up for {duration}s...")
        try:
            self.session = self.client.session(TIKTOK_BUNDLE_ID)
            time.sleep(5)
            
            start_time = time.time()
            while time.time() - start_time < duration:
                # 1. Lướt video (Swipe Up)
                w, h = self.session.window_size()
                # Swipe từ 80% dưới lên 20% trên
                self.session.swipe(w * 0.5, h * 0.8, w * 0.5, h * 0.2, duration=0.2)
                
                # 2. Thời gian xem ngẫu nhiên (5-10s)
                watch_time = random.randint(5, 10)
                self._report_progress(f"Watching for {watch_time}s...")
                time.sleep(watch_time)
                
                # 3. Thả tim ngẫu nhiên (30% cơ hội)
                if random.random() < 0.3:
                    self._report_progress("❤️ Liked video")
                    self.session.double_tap(w * 0.5, h * 0.5)
                    time.sleep(1)
            
            self._report_progress("Warm-up finished.")
            return True
        except Exception as e:
            self._report_progress(f"Warm-up failed: {e}")
            return False
