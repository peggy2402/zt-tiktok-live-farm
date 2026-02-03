#!/bin/bash
# Dừng script ngay nếu có lệnh bị lỗi
set -e

echo "=== CÀI ĐẶT MÔI TRƯỜNG CHO WSL (UBUNTU) ==="

# 1. Cập nhật hệ thống
echo "[*] Updating apt..."
sudo apt update

# 2. Cài đặt các gói hệ thống cần thiết
# - usbmuxd & libimobiledevice: Để giao tiếp với iPhone
# - python3-pip & venv: Môi trường Python
# - ffmpeg: Xử lý video (nếu cần)
# - Các thư viện libxcb*: Cần thiết để PyQt6 hiển thị được cửa sổ trên WSLg
# - libgl1: Thay thế cho libgl1-mesa-glx trên Ubuntu 24.04
echo "[*] Installing system dependencies..."
sudo apt install -y \
    python3-pip python3-venv \
    usbmuxd libimobiledevice-utils libimobiledevice6 usbutils \
    ffmpeg \
    libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
    libxcb-randr0 libxcb-render-util0 libxcb-xinerama0 libxcb-xfixes0 \
    libgl1 libxcb-cursor0

# 3. Cài đặt thư viện Python
echo "[*] Installing Python libraries..."
# Ubuntu 24.04 yêu cầu --break-system-packages nếu cài trực tiếp vào hệ thống
if [ -f "requirements.txt" ]; then
    pip3 install -r requirements.txt --break-system-packages
else
    # Hoặc cài trực tiếp nếu chưa có file requirements
    pip3 install PyQt6 wda tidevice pymobiledevice3 psutil requests --break-system-packages
fi

# 4. Khởi động dịch vụ usbmuxd (Quan trọng)
echo "[*] Starting usbmuxd service..."
# Restart để đảm bảo service chạy
sudo service usbmuxd restart

echo "=== CÀI ĐẶT HOÀN TẤT ==="
echo "Hãy đọc file scripts/wsl_usb_guide.txt để biết cách kết nối USB!"