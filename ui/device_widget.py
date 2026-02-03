# ui/device_widget.py
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QFrame, QMessageBox, QFileDialog)
from PyQt6.QtCore import Qt, pyqtSignal, QThread

# Import logic
from core.device_manager import DeviceController
from core.unified_client import UnifiedClient
from core.ssh_client import SSHClient
from config.settings import REMOTE_VIDEO_PATH, LOCAL_VIDEO_EXTENSIONS

# Tạo luồng chạy ngầm để không đơ giao diện
class WorkerThread(QThread):
    finished = pyqtSignal(bool)
    progress = pyqtSignal(str) # Thêm signal để báo cáo tiến trình

    def __init__(self, controller, client, action, extra_data=None):
        super().__init__()
        self.controller = controller
        self.client = client
        self.action = action # "start", "stop", "run_live", "warm_up", "check_ip", "upload"
        self.extra_data = extra_data # Dữ liệu phụ (ví dụ đường dẫn file)

    def run(self):
        try:
            if self.action == "start":
                # Truyền callback logger để nhận log từ DeviceController
                process_success = self.controller.start_processes(logger=self.progress.emit)
                if not process_success:
                    self.finished.emit(False)
                    return
                # Khởi động luôn SSH Tunnel khi start
                ssh_tunnel_ok = self.controller.start_ssh_tunnel()
                if not ssh_tunnel_ok:
                    print(f"[{self.controller.udid}] SSH Tunnel failed. Upload feature will be disabled.")
                
                # Gắn callback cho client để nhận log kết nối WDA
                self.client.progress_callback = self.progress.emit
                wda_success = self.client.connect()
                self.client.progress_callback = None # Dọn dẹp callback
                self.finished.emit(wda_success)

            elif self.action == "stop":
                self.client.disconnect()
                self.controller.stop_processes()
                self.finished.emit(True)
                
            elif self.action == "run_live":
                # Gắn signal vào client để nó có thể báo cáo lại
                self.client.progress_callback = self.progress.emit
                # Tạm thời chưa truyền video path
                success = self.client.start_tiktok_live(video_path="")
                self.client.progress_callback = None # Xóa callback sau khi xong
                self.finished.emit(success)
                
            elif self.action == "warm_up":
                self.client.progress_callback = self.progress.emit
                success = self.client.warm_up_account(duration=60) # Chạy 60s demo
                self.client.progress_callback = None
                self.finished.emit(success)
                
            elif self.action == "check_ip":
                self.client.progress_callback = self.progress.emit
                success = self.client.check_region_health() # Đổi sang hàm check region mới
                self.client.progress_callback = None
                self.finished.emit(success)
                
            elif self.action == "upload":
                video_path = self.extra_data
                self.progress.emit("Connecting SSH...")
                
                # Kết nối SSH qua tunnel localhost
                ssh = SSHClient(port=self.controller.ssh_port)
                if ssh.connect():
                    self.progress.emit("Uploading video...")
                    # Đường dẫn đích trên iPhone (Tùy chỉnh theo tweak bạn dùng)
                    # Ví dụ: /var/mobile/Media/DCIM/100APPLE/IMG_9999.MOV
                    remote_path = REMOTE_VIDEO_PATH
                    
                    success = ssh.upload_file(video_path, remote_path, self.progress.emit)
                    ssh.close()
                    self.finished.emit(success)
                else:
                    self.progress.emit("SSH Connect Failed!")
                    self.finished.emit(False)
        except Exception as e:
            import traceback
            error_msg = f"CRITICAL WORKER ERROR: {str(e)}\n{traceback.format_exc()}"
            print(error_msg)
            self.progress.emit(f"System Error: {str(e)}")
            self.finished.emit(False)


class DeviceWidget(QFrame):
    # Tín hiệu để gửi log lên cửa sổ chính
    log_message = pyqtSignal(str)

    def __init__(self, udid, name="iPhone", version="N/A", index=0, parent=None, controller=None, client=None):
        super().__init__(parent)
        self.udid = udid
        self.setObjectName("DeviceCard")
        self.setFixedSize(220, 350) # Tăng chiều cao để chứa nút mới
        
        self.controller = controller if controller else DeviceController(udid, version=version, port_offset=index)
        self.client = client if client else UnifiedClient(self.controller.wda_port, udid=udid)
        self.worker = None

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)

        header_layout = QHBoxLayout()
        self.lbl_name = QLabel(f"📱 {name} (iOS {version})")
        self.lbl_name.setStyleSheet("font-weight: bold; font-size: 14px; color: #ecf0f1;")
        self.lbl_status = QLabel("● Offline")
        self.lbl_status.setStyleSheet("color: #7f8c8d; font-weight: bold;")
        header_layout.addWidget(self.lbl_name)
        header_layout.addStretch()
        header_layout.addWidget(self.lbl_status)
        layout.addLayout(header_layout)

        self.screen_placeholder = QLabel(f"Port: {self.controller.wda_port}")
        self.screen_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.screen_placeholder.setStyleSheet("background-color: #000; border-radius: 5px; color: #555;")
        self.screen_placeholder.setFixedHeight(180)
        layout.addWidget(self.screen_placeholder)

        lbl_udid = QLabel(f"ID: {udid[:8]}...")
        lbl_udid.setStyleSheet("color: #666; font-size: 10px;")
        lbl_udid.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_udid)

        # --- Buttons ---
        # Tách layout nút ra để dễ quản lý
        btn_container = QWidget()
        btn_layout = QVBoxLayout(btn_container)
        btn_layout.setContentsMargins(0,0,0,0)
        btn_layout.setSpacing(5)

        # Hàng nút Start/Stop
        start_stop_layout = QHBoxLayout()
        self.btn_start = QPushButton("Start")
        self.btn_start.clicked.connect(self.on_start_click)
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setObjectName("StopButton")
        self.btn_stop.clicked.connect(self.on_stop_click)
        self.btn_stop.setEnabled(False)
        start_stop_layout.addWidget(self.btn_start)
        start_stop_layout.addWidget(self.btn_stop)
        btn_layout.addLayout(start_stop_layout)

        # Hàng nút chức năng (Warm Up / Check IP)
        func_layout = QHBoxLayout()
        self.btn_warmup = QPushButton("🔥 Warm Up")
        self.btn_warmup.clicked.connect(self.on_warmup_click)
        self.btn_warmup.setEnabled(False)
        
        self.btn_check_ip = QPushButton("🇺🇸 Check Region")
        self.btn_check_ip.clicked.connect(self.on_check_ip_click)
        self.btn_check_ip.setEnabled(False)
        
        func_layout.addWidget(self.btn_warmup)
        func_layout.addWidget(self.btn_check_ip)
        btn_layout.addLayout(func_layout)

        # Nút Upload Video
        self.btn_upload = QPushButton("📤 Upload Video")
        self.btn_upload.clicked.connect(self.on_upload_click)
        self.btn_upload.setEnabled(False)
        btn_layout.addWidget(self.btn_upload)

        # Nút Run LIVE (To nhất)
        self.btn_run_live = QPushButton("🚀 Run LIVE")
        self.btn_run_live.clicked.connect(self.on_run_live_click)
        self.btn_run_live.setEnabled(False) # Chỉ bật khi online
        btn_layout.addWidget(self.btn_run_live)
        
        layout.addWidget(btn_container)

    def handle_worker_progress(self, message: str):
        """Nhận tín hiệu từ luồng worker và đẩy lên UI chính."""
        # Gửi log lên MainWindow
        self.log_message.emit(f"[{self.udid[:8]}] {message}")
        # Cập nhật nhanh trạng thái trên widget
        self.screen_placeholder.setText(message[:100] + "..." if len(message) > 100 else message)

    def on_worker_finished(self, success):
        """Xử lý khi luồng worker hoàn thành công việc."""
        # Mở lại các nút sau khi tác vụ xong
        if self.lbl_status.text() == "● Online":
            self.btn_run_live.setEnabled(True)
            self.btn_warmup.setEnabled(True)
            self.btn_check_ip.setEnabled(True)
            
            # Chỉ bật nút Upload nếu SSH Tunnel còn sống
            if self.controller.ssh_process:
                self.btn_upload.setEnabled(True)

        if self.worker.action == "start":
            if success:
                self.lbl_status.setText("● Online")
                self.lbl_status.setStyleSheet("color: #2ecc71; font-weight: bold;")
                self.btn_stop.setEnabled(True)
                self.btn_run_live.setEnabled(True)
                self.btn_warmup.setEnabled(True)
                self.btn_check_ip.setEnabled(True)
                
                # Chỉ bật nút Upload nếu SSH Tunnel còn sống
                if self.controller.ssh_process:
                    self.btn_upload.setEnabled(True)
            else:
                self.lbl_status.setText("● Error")
                self.lbl_status.setStyleSheet("color: #e74c3c; font-weight: bold;")
                self.btn_start.setEnabled(True)
        
        elif self.worker.action == "stop":
            self.lbl_status.setText("● Offline")
            self.lbl_status.setStyleSheet("color: #7f8c8d; font-weight: bold;")
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.btn_run_live.setEnabled(False)
            self.btn_warmup.setEnabled(False)
            self.btn_check_ip.setEnabled(False)
            self.btn_upload.setEnabled(False)
            
        elif self.worker.action == "run_live":
            if success:
                QMessageBox.information(self, "Success", f"LIVE started on {self.udid}!")
            else:
                QMessageBox.warning(self, "Failed", f"Could not start LIVE on {self.udid}.")
        
        elif self.worker.action == "warm_up":
            print(f"[{self.udid}] Warm up finished.")
            
        elif self.worker.action == "upload":
            if success:
                QMessageBox.information(self, "Done", "Video uploaded successfully!")
            else:
                QMessageBox.warning(self, "Error", "Upload failed. Check SSH connection.")

        self.worker = None

    def on_start_click(self):
        self.lbl_status.setText("Starting...")
        self.lbl_status.setStyleSheet("color: #f1c40f;")
        self.btn_start.setEnabled(False)
        self.btn_run_live.setEnabled(False)
        self.btn_warmup.setEnabled(False)
        self.btn_check_ip.setEnabled(False)
        self.btn_upload.setEnabled(False)
        
        self.worker = WorkerThread(self.controller, self.client, "start")
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.progress.connect(self.handle_worker_progress)
        self.worker.start()

    def on_stop_click(self):
        self.lbl_status.setText("Stopping...")
        self.btn_stop.setEnabled(False)
        self.btn_run_live.setEnabled(False)
        self.btn_warmup.setEnabled(False)
        self.btn_check_ip.setEnabled(False)
        self.btn_upload.setEnabled(False)
        
        self.worker = WorkerThread(self.controller, self.client, "stop")
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.start()

    def on_run_live_click(self):
        self.btn_run_live.setEnabled(False)
        self.btn_warmup.setEnabled(False)
        self.btn_check_ip.setEnabled(False)
        self.btn_upload.setEnabled(False)
        
        self.worker = WorkerThread(self.controller, self.client, "run_live")
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.progress.connect(self.handle_worker_progress)
        self.worker.start()

    def on_warmup_click(self):
        self.btn_run_live.setEnabled(False)
        self.btn_warmup.setEnabled(False)
        self.btn_check_ip.setEnabled(False)
        self.btn_upload.setEnabled(False)

        self.worker = WorkerThread(self.controller, self.client, "warm_up")
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.progress.connect(self.handle_worker_progress)
        self.worker.start()

    def on_check_ip_click(self):
        # Check IP nhanh nên không cần disable nút lâu
        self.worker = WorkerThread(self.controller, self.client, "check_ip")
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.progress.connect(self.handle_worker_progress)
        self.worker.start()

    def on_upload_click(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Video", "", LOCAL_VIDEO_EXTENSIONS)
        if not file_path:
            return

        self.btn_upload.setEnabled(False)
        
        self.worker = WorkerThread(self.controller, self.client, "upload", extra_data=file_path)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.progress.connect(self.handle_worker_progress)
        self.worker.start()