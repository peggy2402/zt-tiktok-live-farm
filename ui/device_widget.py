import os
import requests
import time
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QFrame, QMessageBox, QFileDialog, QMenu, QInputDialog, QGridLayout)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QSize
from PyQt6.QtGui import QFont, QImage, QPixmap

from core.device_manager import DeviceController
from core.unified_client import UnifiedClient
from core.ssh_client import SSHClient
from config.settings import REMOTE_VIDEO_PATH, LOCAL_VIDEO_EXTENSIONS
from ui.resources import get_icon

class WorkerThread(QThread):
    """
    Handles long-running tasks (start, stop, etc.) to prevent UI freezing.
    Emits signals to report progress and completion status.
    """
    finished = pyqtSignal(bool)
    progress = pyqtSignal(str)

    def __init__(self, controller: DeviceController, client: UnifiedClient, action: str, extra_data=None):
        super().__init__()
        self.controller = controller
        self.client = client
        self.action = action
        self.extra_data = extra_data

    def run(self):
        try:
            success = False
            if self.action == "start":
                self.progress.emit("Starting engine...")
                
                # 1. Start WDA & Relay (Standard)
                if self.controller.start_processes(logger=self.progress.emit):
                    self.progress.emit("Connecting to WDA...")
                    wda_success = self.client.connect()
                else:
                    wda_success = False
                # Success if EITHER WDA 
                success = wda_success
                
                if not success:
                    self.progress.emit("[ERROR] WDA failed to connect.")
            
            elif self.action == "stop":
                self.progress.emit("Stopping...")
                self.client.disconnect()
                self.controller.stop_wda(logger=self.progress.emit)
                success = True

            elif self.action == "farm":
                self.progress.emit("Starting farm task...")
                success = self.client.warm_up_account()

            elif self.action == "live":
                self.progress.emit("Starting LIVE stream...")
                success = self.client.start_tiktok_live(video_path="")
            
            elif self.action == "upload":
                success = self.upload_video()

            elif self.action == "install_deb":
                success = self.install_deb_package()
            
            elif self.action == "set_location":
                success = self.client.set_virtual_location(34.0522, -118.2437) # Los Angeles
            
            elif self.action == "check_ip":
                ip = self.client.get_public_ip()
                if ip and ip != "Error" and ip != "Not Found":
                    self.progress.emit(f"IP: {ip}") # Gửi signal đặc biệt để UI bắt
                    success = True
                else:
                    success = False
            
            elif self.action == "install_proxy":
                # extra_data = {"ssid": "...", "host": "...", "port": ...}
                data = self.extra_data
                success = self.client.install_proxy_profile(data["ssid"], data["host"], data["port"])

            self.finished.emit(success)
        except Exception as e:
            self.progress.emit(f"[ERROR] Worker thread crashed: {e}")
            self.finished.emit(False)

    def install_deb_package(self):
        deb_path = self.extra_data
        deb_filename = os.path.basename(deb_path)
        remote_path = f"/var/mobile/{deb_filename}"
        
        self.progress.emit("Starting SSH tunnel...")
        if not self.controller.start_ssh_tunnel(logger=self.progress.emit):
            self.progress.emit("[ERROR] Failed to start SSH tunnel.")
            return False
            
        self.progress.emit("Connecting SSH (root/alpine)...")
        ssh = SSHClient(port=self.controller.ssh_port)
        if ssh.connect():
            # 1. Upload file
            self.progress.emit(f"Uploading {deb_filename}...")
            if not ssh.upload_file(deb_path, remote_path, progress_callback=self.progress.emit):
                self.progress.emit("[ERROR] Upload failed.")
                ssh.close()
                return False
            
            # 2. Cài đặt bằng lệnh dpkg
            self.progress.emit("Installing package (dpkg -i)...")
            stdout, stderr = ssh.execute_command(f"dpkg -i {remote_path}")
            self.progress.emit(f"DPKG Output: {stdout}")
            if stderr: self.progress.emit(f"DPKG Error: {stderr}")
            
            # 3. Respring để áp dụng
            self.progress.emit("Respringing device...")
            ssh.execute_command("killall -9 SpringBoard")
            
            ssh.close()
            self.progress.emit("[SUCCESS] Installation complete.")
            return True
        else:
            self.progress.emit("[ERROR] SSH connection failed. Did you install OpenSSH via Sileo?")
            return False

    def upload_video(self):
        video_path = self.extra_data
        self.progress.emit("Starting SSH tunnel...")
        if not self.controller.start_ssh_tunnel(logger=self.progress.emit):
            self.progress.emit("[ERROR] Failed to start SSH tunnel.")
            return False
        
        self.progress.emit("Connecting SSH...")
        ssh = SSHClient(port=self.controller.ssh_port)
        if ssh.connect():
            self.progress.emit(f"Uploading {os.path.basename(video_path)}...")
            success = ssh.upload_file(video_path, REMOTE_VIDEO_PATH, progress_callback=self.progress.emit)
            ssh.close()
            return success
        else:
            self.progress.emit("[ERROR] SSH connection failed.")
            return False

class ScreenStreamThread(QThread):
    """
    Luồng riêng để đọc MJPEG stream từ WDA và gửi hình ảnh về UI.
    """
    change_pixmap_signal = pyqtSignal(QImage)

    def __init__(self, mjpeg_port, fps_limit=10):
        super().__init__()
        self.mjpeg_port = mjpeg_port
        self.running = True
        self.fps_limit = fps_limit
        self.last_emit_time = 0

    def run(self):
        url = f"http://localhost:{self.mjpeg_port}"
        try:
            # Kết nối stream với timeout để tránh treo thread
            stream = requests.get(url, stream=True, timeout=5)
            if stream.status_code == 200:
                bytes_data = b''
                for chunk in stream.iter_content(chunk_size=1024):
                    if not self.running: break
                    bytes_data += chunk
                    a = bytes_data.find(b'\xff\xd8') # JPEG Start
                    b = bytes_data.find(b'\xff\xd9') # JPEG End
                    if a != -1 and b != -1:
                        jpg = bytes_data[a:b+2]
                        bytes_data = bytes_data[b+2:]
                        
                        # [PERFORMANCE] Frame Throttling
                        # Chỉ emit signal nếu đủ thời gian (ví dụ 10fps = 0.1s)
                        current_time = time.time()
                        if current_time - self.last_emit_time < (1.0 / self.fps_limit):
                            continue
                        self.last_emit_time = current_time

                        # Tạo QImage từ dữ liệu binary
                        image = QImage.fromData(jpg)
                        if not image.isNull():
                            self.change_pixmap_signal.emit(image)
        except Exception:
            pass

    def stop(self):
        self.running = False
        self.wait()

class DeviceWidget(QFrame):
    log_message = pyqtSignal(str)
    remove_clicked = pyqtSignal(str)

    def __init__(self, controller: DeviceController, client: UnifiedClient):
        super().__init__()
        self.controller = controller
        self.client = client
        self.worker = None
        self.screen_thread = None
        self.is_connected = False

        # [UI UPDATE] Scale nhỏ lại theo yêu cầu (vẫn giữ tỷ lệ 9:16)
        # Screen: 210x374 (Scale ~0.78 so với trước)
        # Widget: 240x580
        self.setFixedSize(240, 500)
        self.setObjectName("DeviceCard")
        
        # Styling mô phỏng khung máy điện thoại
        self.setStyleSheet("""
            #DeviceCard { 
                background-color: #1e1e1e; 
                border-radius: 10px; 
                border: 1px solid #333;
            }
            /* Top Info Overlay */
            #TopInfo {
                background-color: rgba(0, 0, 0, 0.7);
                border-top-left-radius: 11px;
                border-top-right-radius: 11px;
            }
            QLabel { font-family: 'Segoe UI', sans-serif; }
            
            /* Bottom Control Bar */
            #ControlBar {
                background-color: #252525;
                border-bottom-left-radius: 12px;
                border-bottom-right-radius: 12px;
                border-top: 1px solid #333;
            }
            
            /* Modern Icon Buttons */
            QPushButton { 
                background-color: transparent; 
                border: none; 
                border-radius: 6px; 
                padding: 4px;
            }
            QPushButton:hover { background-color: #424242; }
            QPushButton:pressed { background-color: #616161; }
            
            /* Fix menu button alignment (remove arrow space) */
            QPushButton::menu-indicator { 
                width: 0px; 
                image: none; 
            }
            
            /* Special Buttons */
            #BtnLive {
                background-color: #E91E63; 
                color: white; 
                font-weight: bold;
                border-radius: 15px;
                padding-left: 15px;
                padding-right: 15px;
            }
            #BtnLive:hover { background-color: #FF4081; }
            #BtnLive:disabled { background-color: #555; color: #888; }
        """)

        # --- UI Elements ---
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # --- Video Area Container (Relative) ---
        self.video_container = QFrame()
        self.video_container.setStyleSheet("background-color: black; border-top-left-radius: 12px; border-top-right-radius: 12px;")
        video_layout = QGridLayout(self.video_container)
        video_layout.setContentsMargins(0, 0, 0, 0)
        video_layout.setSpacing(0)
        
        # 1. Screen Placeholder (Background)
        self.screen_placeholder = QLabel(f"Waiting...\nPort: {self.controller.wda_port}")
        self.screen_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.screen_placeholder.setStyleSheet("color: #555;")
        self.screen_placeholder.setScaledContents(True)
        video_layout.addWidget(self.screen_placeholder, 0, 0)
        
        # 2. Top Info Overlay (Foreground)
        self.top_info = QWidget()
        self.top_info.setObjectName("TopInfo")
        self.top_info.setFixedHeight(45)
        
        top_layout = QHBoxLayout(self.top_info)
        top_layout.setContentsMargins(10, 0, 10, 0)
        
        # Name & IP
        info_vbox = QVBoxLayout()
        info_vbox.setSpacing(0)
        self.lbl_name = QLabel(f"{self.client.udid[:8]}")
        self.lbl_name.setStyleSheet("color: white; font-weight: bold; font-size: 12px;")
        self.lbl_ip = QLabel("IP: ...")
        self.lbl_ip.setStyleSheet("color: #ccc; font-size: 10px;")
        info_vbox.addWidget(self.lbl_name)
        info_vbox.addWidget(self.lbl_ip)
        info_vbox.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        
        # Status Dot
        self.lbl_status = QLabel("● Offline")
        self.lbl_status.setStyleSheet("color: #757575; font-weight: bold; font-size: 10px;")
        
        top_layout.addLayout(info_vbox)
        top_layout.addStretch()
        top_layout.addWidget(self.lbl_status)
        
        # --- Compact Remove Button (Integrated in Header) ---
        self.btn_remove = QPushButton("×")
        self.btn_remove.setFixedSize(24, 24)
        self.btn_remove.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_remove.setToolTip(f"Remove {self.controller.udid[:8]}")
        self.btn_remove.setStyleSheet("""
            QPushButton {
                background-color: transparent; color: #7f8c8d; border: none; 
                font-weight: bold; font-size: 18px; margin-left: 5px; padding-bottom: 3px;
            }
            QPushButton:hover { 
                color: #ff5252; background-color: rgba(255, 82, 82, 0.15); border-radius: 12px; 
            }
        """)
        self.btn_remove.clicked.connect(lambda: self.remove_clicked.emit(self.controller.udid))
        top_layout.addWidget(self.btn_remove)
        
        # Add Top Info to Grid (Row 0, Col 0, Align Top)
        video_layout.addWidget(self.top_info, 0, 0, Qt.AlignmentFlag.AlignTop)
        
        layout.addWidget(self.video_container, 1) # Stretch factor 1

        # --- Bottom Control Bar ---
        self.control_bar = QFrame()
        self.control_bar.setObjectName("ControlBar")
        self.control_bar.setFixedHeight(50)
        
        bar_layout = QHBoxLayout(self.control_bar)
        bar_layout.setContentsMargins(10, 5, 10, 5)
        bar_layout.setSpacing(10)
        
        # Power Button (Start/Stop Toggle)
        self.btn_power = QPushButton()
        self.btn_power.setIcon(get_icon("start.svg"))
        self.btn_power.setToolTip("Start/Stop Connection")
        self.btn_power.setFixedSize(32, 32)
        self.btn_power.clicked.connect(self.toggle_connection)
        
        # Farm Button
        self.btn_farm = QPushButton(" Farm")
        self.btn_farm.setIcon(get_icon("farm.svg"))
        self.btn_farm.setToolTip("Start Farming")
        self.btn_farm.setFixedSize(32, 32)
        self.btn_farm.setText("") # Icon only
        self.btn_farm.clicked.connect(lambda: self.run_task("farm"))
        
        # Live Button (Prominent)
        self.btn_live = QPushButton(" LIVE")
        self.btn_live.setObjectName("BtnLive")
        self.btn_live.setIcon(get_icon("live.svg"))
        self.btn_live.setFixedHeight(30)
        self.btn_live.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_live.clicked.connect(lambda: self.run_task("live"))
        
        # Menu Button
        self.btn_menu = QPushButton()
        self.btn_menu.setIcon(get_icon("settings.svg"))
        self.btn_menu.setFixedSize(32, 32)
        self.btn_menu.setMenu(self.create_tools_menu())
        
        bar_layout.addWidget(self.btn_power)
        bar_layout.addWidget(self.btn_farm)
        bar_layout.addStretch()
        bar_layout.addWidget(self.btn_live)
        bar_layout.addStretch()
        bar_layout.addWidget(self.btn_menu)
        
        layout.addWidget(self.control_bar)
        
        # Initial state
        self.set_online_status(False)

    def toggle_connection(self):
        if self.is_connected:
            self.on_stop_click()
        else:
            self.on_start_click()

    def create_tools_menu(self):
        menu = QMenu(self)
        
        action_upload = menu.addAction("Upload Video")
        action_upload.triggered.connect(self.on_upload_click)
        
        action_check_ip = menu.addAction("Check Public IP")
        action_check_ip.triggered.connect(self.on_check_ip_click)
        
        action_proxy = menu.addAction("Install Proxy Profile")
        action_proxy.triggered.connect(self.on_install_proxy_click)
        
        action_set_loc = menu.addAction("Set US Location (GPS)")
        action_set_loc.triggered.connect(self.on_set_location_click)

        action_install_deb = menu.addAction("Install Zxtouch (.deb)")
        action_install_deb.triggered.connect(self.on_install_deb_click)
        
        return menu

    def on_set_location_click(self):
        self.log_message.emit("Setting GPS to US...")
        self.run_task("set_location")

    def on_check_ip_click(self):
        self.run_task("check_ip")

    def on_install_proxy_click(self):
        # 1. Hỏi Proxy Host:Port
        host_ip = self.client._get_host_ip() # Gợi ý IP LAN hiện tại
        proxy_str, ok1 = QInputDialog.getText(self, "Proxy Config", "Enter Proxy (Host:Port):", text=f"{host_ip}:7890")
        if ok1 and proxy_str and ":" in proxy_str:
            # 2. Hỏi SSID Wifi
            ssid, ok2 = QInputDialog.getText(self, "Wi-Fi SSID", "Enter Wi-Fi Name (Case Sensitive):", text="MyWiFi")
            if ok2 and ssid:
                host, port = proxy_str.split(":")
                self.run_task("install_proxy", extra_data={"ssid": ssid, "host": host, "port": int(port)})

    def set_online_status(self, is_online):
        """Enables or disables buttons based on connection status."""
        self.is_connected = is_online
        
        # Update Power Button
        if is_online:
            self.btn_power.setIcon(get_icon("stop.svg"))
            # Brighter Red for Stop (Neon Red) with Border
            self.btn_power.setStyleSheet("""
                QPushButton { 
                    background-color: rgba(255, 23, 68, 0.25); 
                    border: 1px solid rgba(255, 23, 68, 0.6);
                    border-radius: 6px; 
                }
                QPushButton:hover { background-color: rgba(255, 23, 68, 0.4); }
            """)
            self.lbl_status.setText("● Online")
            self.lbl_status.setStyleSheet("color: #00E676; font-weight: bold; font-size: 10px;")
            
            # Update Menu Button (Settings) - Bright Cyan/Blue
            self.btn_menu.setStyleSheet("""
                QPushButton { 
                    background-color: rgba(0, 229, 255, 0.2); 
                    border: 1px solid rgba(0, 229, 255, 0.5);
                    border-radius: 6px;
                }
                QPushButton:hover { background-color: rgba(0, 229, 255, 0.4); }
                QPushButton::menu-indicator { width: 0px; image: none; }
            """)
        else:
            self.btn_power.setIcon(get_icon("start.svg"))
            # Brighter Green for Start (Neon Green) with Border
            self.btn_power.setStyleSheet("""
                QPushButton { 
                    background-color: rgba(0, 230, 118, 0.25); 
                    border: 1px solid rgba(0, 230, 118, 0.6);
                    border-radius: 6px; 
                }
                QPushButton:hover { background-color: rgba(0, 230, 118, 0.4); }
            """)
            self.lbl_status.setText("● Offline")
            self.lbl_status.setStyleSheet("color: #757575; font-weight: bold; font-size: 10px;")
            
            # Reset Menu Button
            self.btn_menu.setStyleSheet("""
                QPushButton { background-color: transparent; border: none; border-radius: 6px; } 
                QPushButton:hover { background-color: #424242; }
                QPushButton::menu-indicator { width: 0px; image: none; }
            """)

        self.btn_farm.setEnabled(is_online)
        self.btn_live.setEnabled(is_online)
        self.btn_menu.setEnabled(is_online)

        if not is_online:
            # Dừng stream nếu offline
            if self.screen_thread:
                self.screen_thread.stop()
                self.screen_thread = None

    def on_start_click(self):
        self.set_online_status(False) # Disable all buttons
        self.btn_power.setEnabled(False)
        self.lbl_status.setText("● Starting...")
        self.lbl_status.setStyleSheet("color: #FFC107; font-weight: bold; font-size: 10px;")
        self.run_task("start")

    def on_stop_click(self):
        self.set_online_status(False) # Disable all buttons
        self.lbl_status.setText("● Stopping...")
        self.lbl_status.setStyleSheet("color: #FF9800; font-weight: bold; font-size: 10px;")
        self.run_task("stop")
        
    def on_upload_click(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Video File", "", f"Videos ({LOCAL_VIDEO_EXTENSIONS})")
        if file_path:
            self.run_task("upload", extra_data=file_path)

    def on_install_deb_click(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select .deb file", "", "Debian Package (*.deb)")
        if file_path:
            self.run_task("install_deb", extra_data=file_path)

    def run_task(self, action, extra_data=None):
        if self.worker and self.worker.isRunning():
            self.log_message.emit(f"A task is already running for {self.controller.udid[:8]}.")
            return
            
        self.worker = WorkerThread(self.controller, self.client, action, extra_data)
        self.worker.progress.connect(self.handle_progress)
        self.worker.finished.connect(self.handle_finished)
        self.worker.start()

    def handle_progress(self, message: str):
        self.log_message.emit(message)
        self.screen_placeholder.setText(message)
        
        # [NEW] Cập nhật Label IP nếu nhận được thông tin từ Worker
        if message.startswith("IP: ") or "Detected IP:" in message:
            ip_text = message.replace("✅ Detected IP: ", "").replace("IP: ", "")
            self.lbl_ip.setText(f"IP: {ip_text}")

    def handle_finished(self, success: bool):
        if not self.worker:
            return # Safety check in case of rapid signals

        action = self.worker.action
        self.worker = None # It's safe to clear the worker now

        if action == "start":
            self.set_online_status(success)
            self.btn_power.setEnabled(True)
            if not success:
                self.lbl_status.setText("● Error")
                self.lbl_status.setStyleSheet("color: #FF5252; font-weight: bold; font-size: 10px;")
            else:
                # Bắt đầu hiển thị màn hình khi start thành công
                if not self.screen_thread:
                    # [PERFORMANCE] Limit FPS to 10 for grid view
                    self.screen_thread = ScreenStreamThread(self.controller.mjpeg_port, fps_limit=10)
                    self.screen_thread.change_pixmap_signal.connect(self.update_screen_image)
                    self.screen_thread.start()

        elif action == "stop":
            self.set_online_status(False)
            self.btn_power.setEnabled(True)
            self.screen_placeholder.setText(f"WDA Port: {self.controller.wda_port}")
        
        # For other tasks, re-enable controls if the device is still online
        elif self.lbl_status.text() == "● Online":
            self.set_online_status(True)
        else: # Task finished but device is not online (e.g. start failed)
            self.set_online_status(False)

    def update_screen_image(self, image):
        """Nhận QImage từ thread và hiển thị lên QLabel"""
        # [PERFORMANCE] Visibility Check
        # Nếu widget bị ẩn (ví dụ tab khác đè lên hoặc scroll ra ngoài), không vẽ
        if not self.isVisible():
            return

        # Scale hình ảnh cho vừa khít khung màn hình mà vẫn giữ tỷ lệ (nếu cần)
        # Tuy nhiên vì setScaledContents(True) đã bật và khung đã chuẩn tỷ lệ 9:16
        # nên ta chỉ cần setPixmap.
        # Nếu muốn đẹp hơn (tránh méo nếu nguồn không chuẩn):
        pixmap = QPixmap.fromImage(image)
        # pixmap = pixmap.scaled(self.screen_placeholder.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.screen_placeholder.setPixmap(pixmap)
