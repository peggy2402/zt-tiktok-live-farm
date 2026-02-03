#!/bin/bash
echo "=== Hướng dẫn cài đặt cho iOS 17+ (pymobiledevice3) ==="
echo "1. Cài đặt python 3.10+"
echo "2. Cài đặt thư viện:"
echo "   pip install pymobiledevice3"
echo "3. Cần bật Developer Mode trên iPhone (Settings -> Privacy & Security -> Developer Mode)."
echo "4. Mount Developer Disk Image (Tự động trong code, nhưng lần đầu cần mạng)."
echo "==================================================="

# Lệnh mẫu mount thủ công
# python -m pymobiledevice3 mounter auto-mount

read -p "Press Enter to exit..."