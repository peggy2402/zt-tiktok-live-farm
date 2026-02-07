import json
import time
import platform
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QScrollArea, QPushButton, QLabel, QPlainTextEdit, QSplitter,
                             QStackedWidget, QListWidget, QListWidgetItem, QFrame, QSizePolicy)
from PyQt6.QtCore import QTimer, Qt, QThread, pyqtSignal, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QFont, QColor, QTextCharFormat

from core.device_manager import DeviceManager, DeviceController
from core.unified_client import UnifiedClient
from ui.device_widget import DeviceWidget
from ui.resources import get_icon # Import the new icon loader

class ScanThread(QThread):
    """Runs the device scan in a background thread to keep the UI responsive."""
    devices_found = pyqtSignal(list)

    def run(self):
        devices = DeviceManager.scan_devices()
        self.devices_found.emit(devices)

class AttachUsbThread(QThread):
    """Runs the USB attach process in background."""
    log_message = pyqtSignal(str)
    finished = pyqtSignal()

    def run(self):
        DeviceManager.wsl_attach_usb_devices(logger=self.log_message.emit)
        self.finished.emit()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ZT TikTok Live Farm")
        self.setWindowIcon(get_icon("logo.svg")) # App icon
        self.resize(1280, 850)
        self.devices = {}

        # --- Dark Theme Style Constants ---
        self.SIDEBAR_BG = "#121212"
        self.SIDEBAR_TEXT = "#B0BEC5"
        self.SIDEBAR_HOVER = "#263238"
        self.CONTENT_BG = "#181818" # Deep Dark content background
        self.PRIMARY_COLOR = "#2196F3"
        self.TEXT_COLOR = "#E0E0E0" # General light text color

        self.init_ui()
        QTimer.singleShot(500, self.load_devices_from_json)

    def init_ui(self):
        """Initializes the main UI with a sidebar and content area."""
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- Right Content Area (must be created before sidebar which connects to it) ---
        content_container = QWidget()
        content_container.setStyleSheet(f"background-color: {self.CONTENT_BG}; color: {self.TEXT_COLOR};")
        content_layout = QVBoxLayout(content_container)
        self.pages = QStackedWidget()
        content_layout.addWidget(self.pages)

        # --- Left Sidebar ---
        sidebar_container = self.setup_sidebar()
        main_layout.addWidget(sidebar_container)
        main_layout.addWidget(content_container)

        # --- Populate Pages ---
        self.page_dashboard = QWidget()
        self.setup_dashboard_ui(self.page_dashboard)
        self.pages.addWidget(self.page_dashboard)

        self.page_config = QLabel("Configuration Page (Coming Soon)")
        self.page_config.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_config.setFont(QFont("Segoe UI", 12))
        self.pages.addWidget(self.page_config)

        self.menu_list.setCurrentRow(0)

    def setup_sidebar(self):
        """Creates the left sidebar widget and returns it."""
        self.sidebar_container = QWidget()
        self.sidebar_container.setFixedWidth(220)
        self.sidebar_container.setStyleSheet(f"background-color: {self.SIDEBAR_BG}; border-right: 1px solid #333;")
        sidebar_layout = QVBoxLayout(self.sidebar_container)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        # Toggle Button (Hamburger)
        self.btn_toggle_menu = QPushButton("☰")
        self.btn_toggle_menu.setFixedSize(40, 40)
        self.btn_toggle_menu.setStyleSheet("border: none; color: white; font-size: 20px; background: transparent;")
        self.btn_toggle_menu.clicked.connect(self.toggle_sidebar)
        
        header_layout = QHBoxLayout()
        header_layout.addWidget(self.btn_toggle_menu)
        
        lbl_title = QLabel("ZT TIKTOK FARM")
        self.lbl_title = lbl_title # Save ref to hide when collapsed
        lbl_title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        lbl_title.setStyleSheet(f"""
            padding: 15px 0; 
            color: {self.PRIMARY_COLOR}; 
        """)
        header_layout.addWidget(lbl_title)
        header_layout.addStretch()
        
        sidebar_layout.addLayout(header_layout)

        self.menu_list = QListWidget()
        self.menu_list.setFrameShape(QFrame.Shape.NoFrame)
        self.menu_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.menu_list.setStyleSheet(f"""
            QListWidget {{ background-color: {self.SIDEBAR_BG}; border: none; }}
            QListWidget::item {{ padding: 12px; color: {self.SIDEBAR_TEXT}; border-left: 3px solid transparent; }}
            QListWidget::item:selected, QListWidget::item:hover {{ 
                background-color: {self.SIDEBAR_HOVER};
                border-left-color: {self.PRIMARY_COLOR};
                color: white;
            }}
        """)
        self.add_menu_item("Dashboard", "dashboard.svg")
        self.add_menu_item("Configuration", "settings.svg")
        self.menu_list.currentRowChanged.connect(self.pages.setCurrentIndex)
        sidebar_layout.addWidget(self.menu_list)

        sidebar_layout.addStretch()

        lbl_version = QLabel("v2.2.0-dark")
        self.lbl_version = lbl_version
        lbl_version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_version.setStyleSheet("color: #7f8c8d; padding: 10px;")
        sidebar_layout.addWidget(lbl_version)
        
        return self.sidebar_container

    def toggle_sidebar(self):
        """Animates the sidebar width."""
        width = self.sidebar_container.width()
        new_width = 60 if width == 220 else 220
        
        # --- Text Visibility Logic (Clean Look) ---
        # Khi đóng: Text màu trong suốt (ẩn). Khi mở: Text màu bình thường.
        text_color = "transparent" if new_width == 60 else self.SIDEBAR_TEXT
        self.menu_list.setStyleSheet(f"""
            QListWidget {{ background-color: {self.SIDEBAR_BG}; border: none; }}
            QListWidget::item {{ padding: 12px; color: {text_color}; border-left: 3px solid transparent; }}
            QListWidget::item:selected, QListWidget::item:hover {{ 
                background-color: {self.SIDEBAR_HOVER}; border-left-color: {self.PRIMARY_COLOR}; color: {text_color if new_width == 60 else 'white'};
            }}
        """)

        self.anim = QPropertyAnimation(self.sidebar_container, b"minimumWidth")
        self.anim.setDuration(250)
        self.anim.setStartValue(width)
        self.anim.setEndValue(new_width)
        self.anim.setEasingCurve(QEasingCurve.Type.InOutQuart)
        self.anim.start()
        
        # Hacky way to animate max width too
        self.sidebar_container.setFixedWidth(new_width) # This snaps, animation needs layout handling
        # Better approach for fixed layout:
        self.anim_max = QPropertyAnimation(self.sidebar_container, b"maximumWidth")
        self.anim_max.setDuration(250)
        self.anim_max.setStartValue(width)
        self.anim_max.setEndValue(new_width)
        self.anim_max.start()

        # Hide/Show text elements
        is_collapsed = new_width == 60
        self.lbl_title.setVisible(not is_collapsed)
        self.lbl_version.setVisible(not is_collapsed)

    def add_menu_item(self, text, icon_name):
        item = QListWidgetItem(get_icon(icon_name), text)
        item.setFont(QFont("Segoe UI", 11))
        self.menu_list.addItem(item)

    def setup_dashboard_ui(self, parent_widget):
        """Creates the main dashboard UI with controls, grid, and log."""
        layout = QVBoxLayout(parent_widget)
        
        # --- Top Control Bar ---
        control_bar = QHBoxLayout()
        self.btn_scan = QPushButton(" Scan Devices")
        self.btn_scan.setIcon(get_icon("scan.svg"))
        self.btn_scan.clicked.connect(self.scan_and_add_devices)
        control_bar.addWidget(self.btn_scan)

        self.btn_attach = QPushButton(" Attach USB (WSL)")
        self.btn_attach.setIcon(get_icon("usb.svg")) # Icon USB nếu có, hoặc mặc định
        self.btn_attach.clicked.connect(self.attach_usb_wsl)
        
        # Chỉ hiện nút Attach USB nếu đang chạy trên Linux/WSL
        if platform.system() == "Linux":
            control_bar.addWidget(self.btn_attach)

        btn_start_all = QPushButton(" Start All")
        btn_start_all.setIcon(get_icon("start_all.svg"))
        btn_start_all.clicked.connect(self.start_all_devices)
        control_bar.addWidget(btn_start_all)

        btn_stop_all = QPushButton(" Stop All")
        btn_stop_all.setIcon(get_icon("stop_all.svg"))
        btn_stop_all.clicked.connect(self.stop_all_devices)
        control_bar.addWidget(btn_stop_all)

        control_bar.addStretch()
        layout.addLayout(control_bar)

        # --- Devices Grid and Log Splitter ---
        splitter = QSplitter(Qt.Orientation.Vertical)
        
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("background-color: transparent; border: none;")
        
        self.devices_container = QWidget()
        self.devices_container.setStyleSheet("background-color: transparent;")
        self.devices_grid = QGridLayout(self.devices_container)
        self.devices_grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.devices_container)
        splitter.addWidget(self.scroll)
        
        self.log_console = QPlainTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setStyleSheet(f"""
            background-color: #111;
            color: {self.TEXT_COLOR};
            font-family: Consolas, monospace;
            border-top: 1px solid #333;
            border-radius: 5px;
        """)
        splitter.addWidget(self.log_console)
        
        splitter.setSizes([500, 200])
        layout.addWidget(splitter)
        
        # Apply stylesheet to buttons
        for btn in [self.btn_scan, self.btn_attach, btn_start_all, btn_stop_all]:
            btn.setFixedHeight(40)
            btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.btn_scan.setStyleSheet("background-color: #1976D2; color: white; border-radius: 4px;")
        self.btn_attach.setStyleSheet("background-color: #7B1FA2; color: white; border-radius: 4px;") 
        btn_start_all.setStyleSheet("background-color: #388E3C; color: white; border-radius: 4px;")
        btn_stop_all.setStyleSheet("background-color: #D32F2F; color: white; border-radius: 4px;")

    def append_log(self, message: str):
        """Adds a message to the system log console with appropriate color."""
        color = "#ecf0f1"  # Default
        if "[ERROR]" in message or "fail" in message.lower(): color = "#e74c3c"
        elif "[OK]" in message or "success" in message.lower() or "ready" in message.lower(): color = "#2ecc71"
        elif "[*]" in message or "wait" in message.lower() or "scan" in message.lower(): color = "#f1c40f"
        
        self.log_console.appendHtml(f"<font color='{color}'><b>{time.strftime('%H:%M:%S')} |</b> {message}</font>")
        self.log_console.ensureCursorVisible()

    # --- Device Management Logic ---

    def scan_and_add_devices(self):
        self.btn_scan.setEnabled(False)
        self.btn_scan.setText(" Scanning...")
        self.append_log("[*] Scanning for connected devices...")
        
        self.scan_thread = ScanThread()
        self.scan_thread.devices_found.connect(self.on_scan_finished)
        self.scan_thread.start()

    def attach_usb_wsl(self):
        self.btn_attach.setEnabled(False)
        self.btn_attach.setText(" Attaching...")
        self.append_log("[*] Bắt đầu quy trình Attach USB từ Windows...")
        
        self.attach_thread = AttachUsbThread()
        self.attach_thread.log_message.connect(self.append_log)
        self.attach_thread.finished.connect(lambda: self.btn_attach.setEnabled(True))
        self.attach_thread.finished.connect(lambda: self.btn_attach.setText(" Attach USB (WSL)"))
        self.attach_thread.start()

    def on_scan_finished(self, found_devices):
        self.btn_scan.setEnabled(True)
        self.btn_scan.setText(" Scan Devices")
        if not found_devices:
            self.append_log("[ERROR] No devices found. Check connection and drivers.")
            return
            
        self.append_log(f"[*] Found {len(found_devices)} device(s).")
        for device in found_devices:
            self._process_add_device(device)
        self.save_devices_to_json()

    def _process_add_device(self, device_info):
        udid = device_info["udid"]
        
        # [FILTER] Tạm thời bỏ qua iOS 17+ (iPhone SE) vì chưa có Mac
        # Giúp hệ thống tập trung vào 5 máy iPhone 7 đang ổn định
        version = device_info.get("version", "Unknown")
        try:
            if version and version[0].isdigit() and int(version.split('.')[0]) >= 17:
                self.append_log(f"[-] Skipped {udid} (iOS {version}) - High OS version (No Mac).")
                return
        except Exception:
            pass

        if udid in self.devices:
            self.append_log(f"[*] Device {udid[:8]}... already in view.")
            return

        controller = DeviceController(
            udid=udid,
            # Fallback version logic if tidevice returns Unknown
            version=device_info.get("version", "15.0"), 
            engine=device_info.get("engine", "tidevice3"),
            port_offset=len(self.devices)
        )
        
        # Special handling for known iOS 18 device (Manual override if needed)
        # You can add a check here if you know the specific UDID of your iPhone SE
        # if udid == "YOUR_IPHONE_SE_UDID":
        #     controller.major_version = 18

        client = UnifiedClient(port=controller.wda_port, udid=udid)
        
        widget = DeviceWidget(controller=controller, client=client)
        widget.log_message.connect(self.append_log)
        # Kết nối signal xóa từ widget
        widget.remove_clicked.connect(self.remove_device)
        
        # Lưu trực tiếp widget, không cần container wrapper nữa
        self.devices[udid] = {"controller": controller, "client": client, "widget": widget, "info": device_info}
        
        self.refresh_grid()

    def get_grid_columns(self, item_width=230):
        return max(1, self.scroll.width() // (item_width + 10)) 

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Re-organize the grid on window resize
        # This is complex, so we will do a simple version
        # A better implementation would move widgets without recreating them
        self.refresh_grid()

    def start_all_devices(self):
        for udid in self.devices:
            self.devices[udid]["widget"].on_start_click()
            time.sleep(0.5) # Stagger starts
            
    def stop_all_devices(self):
        for udid in self.devices:
            self.devices[udid]["widget"].on_stop_click()

    def remove_device(self, udid):
        """Xóa thiết bị khỏi danh sách, dừng process và cập nhật UI."""
        if udid not in self.devices:
            return

        self.append_log(f"[*] Removing device {udid}...")
        device = self.devices[udid]
        
        # 1. Dừng WDA và giải phóng port
        try:
            device["controller"].stop_wda()
        except Exception as e:
            self.append_log(f"[WARN] Error stopping WDA: {e}")

        # 2. Xóa khỏi UI
        widget = device.get("widget")
        self.devices_grid.removeWidget(widget)
        widget.deleteLater()
        
        # 3. Xóa khỏi bộ nhớ
        del self.devices[udid]
        
        # 4. Lưu lại config và sắp xếp lại lưới
        self.save_devices_to_json()
        self.refresh_grid()
        self.append_log(f"[OK] Device {udid} removed.")

    def refresh_grid(self):
        """Sắp xếp lại grid layout để lấp đầy khoảng trống."""
        # Tạm thời gỡ tất cả widget khỏi layout (nhưng không xóa object)
        for i in reversed(range(self.devices_grid.count())):
            item = self.devices_grid.itemAt(i)
            if item.widget():
                item.widget().setParent(None)
        
        # Thêm lại theo thứ tự
        cols = self.get_grid_columns()
        for i, udid in enumerate(self.devices):
            widget = self.devices[udid]["widget"]
            row, col = divmod(i, cols)
            self.devices_grid.addWidget(widget, row, col)

    def save_devices_to_json(self):
        data = [d["info"] for d in self.devices.values()]
        try:
            with open("config/devices.json", "w") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            self.append_log(f"[ERROR] Could not save devices.json: {e}")

    def load_devices_from_json(self):
        try:
            with open("config/devices.json", "r") as f:
                devices_from_file = json.load(f)
            if devices_from_file:
                self.append_log(f"[*] Loading {len(devices_from_file)} device(s) from config.")
                for device in devices_from_file:
                    self._process_add_device(device)
        except FileNotFoundError:
            self.append_log("[*] No saved devices found. Please scan.")
        except Exception as e:
            self.append_log(f"[ERROR] Could not load devices.json: {e}")

    def closeEvent(self, event):
        self.append_log("[*] Application closing, stopping all devices...")
        self.stop_all_devices()
        # Add a small delay to allow processes to terminate
        start_time = time.time()
        while any(d["controller"].wda_process for d in self.devices.values()):
            if time.time() - start_time > 3:
                self.append_log("[ERROR] Timed out waiting for devices to stop.")
                break
            time.sleep(0.1)
        event.accept()
