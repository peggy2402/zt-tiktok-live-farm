# ui/main_window.py (phần quan trọng)
import threading
import time
import json
import sys
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QScrollArea, QPushButton, QLabel, QMessageBox, QPlainTextEdit, QSplitter)
from PyQt6.QtCore import QTimer, Qt, QThread, pyqtSignal
from core.device_manager import DeviceManager, DeviceController
from PyQt6.QtGui import QFont, QColor, QTextCharFormat
from core.unified_client import UnifiedClient
from ui.device_widget import DeviceWidget
from config.settings import REMOTE_VIDEO_PATH

class ScanThread(QThread):
    """Luồng quét thiết bị chạy ngầm để không làm đơ UI"""
    devices_found = pyqtSignal(list)

    def run(self):
        # Gọi hàm scan (có thể mất nhiều thời gian)
        devices = DeviceManager.scan_devices()
        self.devices_found.emit(devices)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TikTok Live Farm Control")
        self.resize(1100, 800)
        self.devices = {}  # {udid: {"controller": DeviceController, "client": UnifiedClient}}
        self.init_ui()
        
        # Tự động load thiết bị đã lưu
        QTimer.singleShot(1000, self.load_devices_from_json)
    
    def init_ui(self):
        """Khởi tạo giao diện chính"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main Layout
        main_layout = QVBoxLayout(central_widget)
        
        # Toolbar / Header Buttons
        header_layout = QHBoxLayout()
        
        self.btn_scan = QPushButton("🔄 Scan Devices")
        self.btn_scan.clicked.connect(self.scan_and_add_devices)
        header_layout.addWidget(self.btn_scan)
        
        btn_start_all = QPushButton("▶ Start All")
        btn_start_all.clicked.connect(self.start_all_devices)
        header_layout.addWidget(btn_start_all)
        
        btn_live_all = QPushButton("🎥 Live All")
        btn_live_all.clicked.connect(self.start_live_streams)
        header_layout.addWidget(btn_live_all)
        
        header_layout.addStretch()
        main_layout.addLayout(header_layout)
        
        # Tạo một splitter để có thể thay đổi kích thước vùng log
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Scroll Area chứa danh sách thiết bị (phần trên)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.devices_container = QWidget()
        self.devices_layout = QHBoxLayout(self.devices_container)
        self.devices_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.devices_container)
        splitter.addWidget(self.scroll)

        # Bảng Log (phần dưới)
        self.log_console = QPlainTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setObjectName("LogConsole")
        self.log_console.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFont("Consolas", 10) # Dùng font monospaced cho đẹp
        self.log_console.setFont(font)
        splitter.addWidget(self.log_console)

        # Đặt kích thước ban đầu cho 2 phần
        splitter.setSizes([600, 200])

        main_layout.addWidget(splitter)

    def add_device(self, udid, name, version):
        """Hàm thêm thiết bị thủ công (được gọi từ main.py)"""
        # Tự động đoán engine dựa trên version nếu không có info
        engine = "tidevice"
        try:
            if float(version.split('.')[0]) >= 17:
                engine = "pymobile"
        except:
            pass
            
        # Giả lập cấu trúc dữ liệu giống như scan được
        device_info = {
            "udid": udid,
            "name": name,
            "version": version,
            "engine": engine
        }
        
        # Tận dụng logic thêm thiết bị
        self._process_add_device(device_info)

    def scan_and_add_devices(self):
        """Quét và thêm thiết bị tự động (Chạy ngầm)"""
        self.btn_scan.setEnabled(False)
        self.btn_scan.setText("Scanning...")
        self.append_log("[*] Scanning for devices...")
        
        self.scan_thread = ScanThread()
        self.scan_thread.devices_found.connect(self.on_scan_finished)
        self.scan_thread.start()

    def on_scan_finished(self, devices):
        """Xử lý kết quả sau khi quét xong"""
        self.btn_scan.setEnabled(True)
        self.btn_scan.setText("🔄 Scan Devices")
        
        if not devices:
            self.append_log("[SCAN ERROR] No devices found via tidevice.")
            self.append_log("[HINT] Quick Fix: Run 'sudo service usbmuxd restart' in terminal.")
            self.append_log("[HINT] Permanent Fix: Run './scripts/setup_udev.sh' then restart WSL.")

        for device in devices:
            self._process_add_device(device)
        self.save_devices_to_json()

    def _process_add_device(self, device):
        """Xử lý logic thêm thiết bị vào danh sách quản lý"""
        udid = device["udid"]
        if udid not in self.devices:
            # Tạo controller với engine phù hợp
            controller = DeviceController(
                udid=udid,
                version=device["version"],
                engine=device["engine"],
                port_offset=len(self.devices)  # Mỗi device 1 port riêng
            )
            
            # Tạo client thống nhất
            client = UnifiedClient(
                port=controller.wda_port,
                engine=device["engine"],
                udid=udid
            )
            
            self.devices[udid] = {
                "info": device,
                "controller": controller,
                "client": client,
                "status": "disconnected"
            }
            
            self.add_device_to_ui(device)
    
    def add_device_to_ui(self, device):
        """Tạo Widget hiển thị cho thiết bị"""
        udid = device["udid"]
        if udid in self.devices:
            # Lấy port offset đã tính toán
            controller = self.devices[udid]["controller"]
            client = self.devices[udid]["client"]
            port_offset = controller.wda_port - 8100
            
            # Tạo Widget từ ui/device_widget.py
            widget = DeviceWidget(
                udid=udid,
                name=device.get("name", "iPhone"),
                version=device["version"],
                index=port_offset,
                controller=controller,
                client=client
            )
            
            # Lưu tham chiếu widget vào dict devices để update sau này
            self.devices[udid]["widget"] = widget
            
            # Kết nối tín hiệu log từ widget con lên bảng log chính
            widget.log_message.connect(self.append_log)
            
            self.devices_layout.addWidget(widget)

    def append_log(self, message: str):
        """Thêm message vào bảng log với màu sắc tương ứng."""
        # Phân loại màu sắc dựa trên nội dung log
        color = QColor("#dcdcdc") # Mặc định (trắng xám)
        if "[ERROR]" in message or "failed" in message.lower() or "Fail" in message or "[SCAN ERROR]" in message:
            color = QColor("#e74c3c") # Đỏ
        elif "[OK]" in message or "success" in message.lower() or "Connected" in message:
            color = QColor("#2ecc71") # Xanh lá
        elif "[*]" in message or "Starting" in message or "Waiting" in message or "[HINT]" in message:
            color = QColor("#f1c40f") # Vàng
        elif "[PYMOBILE]" in message or "[TIDEVICE]" in message:
            color = QColor("#3498db") # Xanh dương
        
        char_format = QTextCharFormat()
        char_format.setForeground(color)
        
        cursor = self.log_console.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(f"{time.strftime('%H:%M:%S')} | ", char_format)
        cursor.insertText(message + "\n", char_format)
        self.log_console.ensureCursorVisible() # Tự động cuộn xuống

    def save_devices_to_json(self):
        """Lưu danh sách thiết bị ra file JSON"""
        data = []
        for udid, info in self.devices.items():
            data.append(info["info"])
        
        try:
            with open("config/devices.json", "w") as f:
                json.dump(data, f, indent=4)
            print("[INFO] Devices saved to config/devices.json")
        except Exception as e:
            print(f"[ERROR] Could not save devices: {e}")

    def load_devices_from_json(self):
        """Load thiết bị từ file JSON"""
        try:
            with open("config/devices.json", "r") as f:
                devices = json.load(f)
                if not devices:
                    return
                
                print(f"[INFO] Loading {len(devices)} devices from config...")
                for device in devices:
                    self._process_add_device(device)
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"[ERROR] Could not load devices: {e}")

    def update_device_status(self, udid, status_text):
        """Cập nhật trạng thái lên UI"""
        if udid in self.devices and "widget" in self.devices[udid]:
            self.devices[udid]["widget"].lbl_status.setText(status_text)

    def start_device(self, udid):
        """Khởi động thiết bị với engine phù hợp"""
        device_data = self.devices.get(udid)
        if not device_data:
            return
        
        controller = device_data["controller"]
        client = device_data["client"]
        
        try:
            # Khởi động engine phù hợp
            if controller.start_processes():
                # Kết nối client
                if client.connect():
                    device_data["status"] = "connected"
                    self.update_device_status(udid, "✅ Connected")
                    
                    # Tự động bắt đầu warm-up
                    QTimer.singleShot(3000, lambda: self.start_warm_up(udid))
                else:
                    self.update_device_status(udid, "❌ Connection failed")
            else:
                self.update_device_status(udid, "❌ Engine start failed")
                
        except Exception as e:
            print(f"[ERROR] Failed to start device {udid}: {e}")
            self.update_device_status(udid, "❌ Error")
    
    def start_warm_up(self, udid):
        """Bắt đầu nuôi nick"""
        if udid in self.devices:
            client = self.devices[udid]["client"]
            threading.Thread(target=client.warm_up_account, daemon=True).start()

    def start_all_devices(self):
        """Khởi động tất cả thiết bị - Mỗi máy dùng engine riêng"""
        for udid in self.devices:
            self.start_device(udid)
            time.sleep(2)  # Tránh xung đột port
    
    def start_live_streams(self):
        """Bắt đầu LIVE trên tất cả thiết bị đã kết nối"""
        for udid, device_data in self.devices.items():
            if device_data["status"] == "connected":
                client = device_data["client"]
                # Mỗi device chạy trong thread riêng
                thread = threading.Thread(
                    target=client.start_tiktok_live,
                    args=(None,)  # Hoặc đường dẫn video
                )
                thread.daemon = True
                thread.start()

    def closeEvent(self, event):
        """Xử lý khi đóng cửa sổ: Dừng toàn bộ thiết bị để giải phóng port"""
        print("[EXIT] Cleaning up processes...")
        for udid, device in self.devices.items():
            if "controller" in device:
                device["controller"].stop_processes()
        event.accept()