import sys
import wda
from PyQt6.QtWidgets import QApplication, QMainWindow, QGridLayout, QWidget, QPushButton, QLabel, QVBoxLayout
from PyQt6.QtCore import QThread, pyqtSignal

# --- WORKER THREAD: Phần này chạy ngầm để điều khiển iPhone ---
class DeviceWorker(QThread):
    log_signal = pyqtSignal(str) # Gửi log ra giao diện

    def __init__(self, device_url, device_name):
        super().__init__()
        self.device_url = device_url # Ví dụ: http://localhost:8100
        self.device_name = device_name
        self.is_running = False

    def run(self):
        self.is_running = True
        self.log_signal.emit(f"[{self.device_name}] Đang kết nối WDA...")
        
        try:
            # Kết nối tới iPhone qua WDA
            c = wda.Client(self.device_url)
            
            # 1. Check Môi trường (IP, WebRTC...) - Giả lập
            self.log_signal.emit(f"[{self.device_name}] Checking Environment...")
            # safety_guard.check_ip() ...
            
            # 2. Mở TikTok
            self.log_signal.emit(f"[{self.device_name}] Opening TikTok...")
            s = c.session('com.zhiliaoapp.musically') # Bundle ID của TikTok US
            
            # 3. Logic Auto (Ví dụ click nút Live)
            # c(text="Live").click() ...
            
            self.log_signal.emit(f"[{self.device_name}] Đang Live... (Monitoring)")
            
            # Vòng lặp monitoring để giữ kết nối
            while self.is_running:
                # Ping WDA hoặc check xem app còn mở không
                if not s.app_state() == 4: # 4 means running in foreground
                     self.log_signal.emit(f"[{self.device_name}] App crashed! Relaunching...")
                     s = c.session('com.zhiliaoapp.musically')
                self.sleep(5) # Nghỉ 5s check 1 lần
                
        except Exception as e:
            self.log_signal.emit(f"[{self.device_name}] ERROR: {str(e)}")

    def stop(self):
        self.is_running = False
        self.terminate()

# --- GUI: Giao diện người dùng ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ZENTRA TikTok Farm Controller")
        self.resize(800, 600)
        
        # Layout chính
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.grid_layout = QGridLayout()
        central_widget.setLayout(self.grid_layout)

        # Giả lập add 6 thiết bị vào grid
        self.workers = []
        devices = [("iPhone 1", "http://localhost:8100"), ("iPhone 2", "http://localhost:8101")] 
        
        for i, (name, url) in enumerate(devices):
            # Tạo widget con cho từng máy
            frame = QWidget()
            frame.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ccc; border-radius: 5px;")
            layout = QVBoxLayout()
            
            lbl_name = QLabel(name)
            lbl_status = QLabel("Ready")
            btn_start = QPushButton("Start Live")
            
            layout.addWidget(lbl_name)
            layout.addWidget(lbl_status)
            layout.addWidget(btn_start)
            frame.setLayout(layout)
            
            # Add vào lưới (3 cột)
            self.grid_layout.addWidget(frame, i // 3, i % 3)
            
            # Gắn sự kiện
            worker = DeviceWorker(url, name)
            worker.log_signal.connect(lbl_status.setText) # Update trạng thái lên UI
            btn_start.clicked.connect(worker.start) # Bấm nút là chạy thread
            self.workers.append(worker)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())