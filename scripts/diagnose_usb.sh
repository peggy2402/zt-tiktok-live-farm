#!/bin/bash
echo "=== CHẨN ĐOÁN KẾT NỐI USB (WSL) ==="

echo "[1] Kiểm tra thiết bị USB ở cấp độ Kernel (lsusb)..."
# Tìm thiết bị Apple (Vendor ID 05ac)
if lsusb | grep -q "05ac"; then
    echo "✅ Đã thấy thiết bị Apple trong lsusb."
    lsusb | grep "05ac"
else
    echo "❌ KHÔNG TÌM THẤY IPHONE TRONG LSUSB!"
    echo "👉 Nguyên nhân: Bạn chưa attach thành công từ Windows hoặc cáp lỏng."
    echo "👉 Giải pháp: Mở PowerShell Admin và chạy: usbipd attach --wsl --busid <BUSID>"
    exit 1
fi

echo ""
echo "[2] Kiểm tra dịch vụ usbmuxd..."
if pgrep -x "usbmuxd" > /dev/null; then
    PID=$(pgrep -x usbmuxd)
    echo "✅ usbmuxd đang chạy (PID: $PID)."
else
    echo "❌ usbmuxd KHÔNG chạy."
    echo "👉 Đang thử khởi động lại..."
    sudo service usbmuxd restart
    sleep 2
fi

echo ""
echo "[3] Kiểm tra kết nối thiết bị (idevice_id)..."
# Cần cài libimobiledevice-utils nếu chưa có
if ! command -v idevice_id &> /dev/null; then
    echo "⚠️ Chưa cài idevice_id. Đang cài đặt..."
    sudo apt update && sudo apt install -y libimobiledevice-utils
fi

IDS=$(idevice_id -l)
if [ -z "$IDS" ]; then
    echo "❌ usbmuxd đang chạy nhưng KHÔNG nhìn thấy thiết bị nào!"
    echo "👉 Đây là lỗi phổ biến do usbmuxd khởi động trước khi có thiết bị."
    echo "👉 GIẢI PHÁP KHẮC PHỤC NGAY:"
    echo "   1. Chạy lệnh: sudo service usbmuxd restart"
    echo "   2. Chạy lại tool này để kiểm tra."
else
    echo "✅ KẾT NỐI THÀNH CÔNG! Đã phát hiện UDID:"
    echo "$IDS"
    echo ""
    echo "🎉 Bây giờ bạn có thể chạy 'python3 main.py' và bấm Scan."
fi