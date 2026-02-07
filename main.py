import sys
import signal
import os

# Thêm thư mục hiện tại vào sys.path để Python tìm được các module
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from ui.main_window import MainWindow

# Cho phép thoát bằng Ctrl+C trong terminal mà không bị treo
signal.signal(signal.SIGINT, signal.SIG_DFL)

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()