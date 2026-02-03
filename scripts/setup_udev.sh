#!/bin/bash
# Dừng script ngay nếu có lệnh bị lỗi
set -e

echo "=== CÀI ĐẶT UDEV RULE CHO IPHONE ==="
echo "Thao tác này cấp quyền cho user của bạn truy cập thiết bị Apple mà không cần sudo."

# 1. Tạo file rule
RULE_CONTENT='SUBSYSTEM=="usb", ATTR{idVendor}=="05ac", MODE="0666", GROUP="plugdev"'
echo "$RULE_CONTENT" | sudo tee /etc/udev/rules.d/51-imobiledevice.rules > /dev/null

# 2. Thêm user hiện tại vào group 'plugdev'
sudo usermod -aG plugdev $USER

# 3. Tải lại các rule
sudo udevadm control --reload-rules && sudo udevadm trigger

echo "=== HOÀN TẤT! ==="
echo "Để thay đổi có hiệu lực, hãy khởi động lại WSL bằng cách chạy 'wsl --shutdown' trong PowerShell, sau đó mở lại Ubuntu."