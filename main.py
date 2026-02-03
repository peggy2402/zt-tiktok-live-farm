# main.py
import sys
import os
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPalette, QColor
from PyQt6.QtCore import Qt
from ui.main_window import MainWindow

def ensure_directories():
    """Đảm bảo các thư mục cần thiết tồn tại"""
    dirs = ["logs", "config", "scripts"]
    for d in dirs:
        if not os.path.exists(d):
            os.makedirs(d)
            print(f"[INIT] Created directory: {d}")

def main():
    ensure_directories()
    
    # 1. Khởi tạo App
    app = QApplication(sys.argv)
    
    # 2. Apply theme (Auto dark mode)
    # Fix lỗi pyqtdarktheme không hỗ trợ Python 3.12 trên Ubuntu 24.04
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.Base, QColor(25, 25, 25))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ToolTipBase, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
    palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)
    app.setPalette(palette)

    # 3. Load thêm CSS tùy chỉnh của mình
    with open("ui/styles.qss", "r") as f:
        app.setStyleSheet(app.styleSheet() + f.read())

    # 4. Show cửa sổ
    window = MainWindow()
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()