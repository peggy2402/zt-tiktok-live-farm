#!/usr/bin/env python3
import subprocess
import time
import sys
import os
import requests

UDID = "7e6dd2126490d386718e5354011076ddd620c8a4"
WDA_BUNDLE = "com.facebook.WebDriverAgentRunner.xctrunner.K5R9T76J4Z"

def run_cmd(cmd):
    """Chạy command và in output"""
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result

print("=== STEP 1: Clean up old processes ===")
os.system("pkill -f tidevice")
os.system("pkill -f iproxy")
time.sleep(2)

print("\n=== STEP 2: Check device connection ===")
result = run_cmd(["tidevice", "list"])
if result.returncode != 0:
    print("ERROR: Cannot connect to device!")
    sys.exit(1)
print(f"Device found: {result.stdout}")

print("\n=== STEP 3: Start port forwarding ===")
# Dùng RELAY đơn giản
relay_proc = subprocess.Popen(
    ["tidevice", "--udid", UDID, "relay", "8100", "8100"],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True
)
print(f"Relay started with PID: {relay_proc.pid}")
time.sleep(3)

print("\n=== STEP 4: Launch WDA on device ===")
# Launch WDA
result = run_cmd(["tidevice", "--udid", UDID, "launch", WDA_BUNDLE])
print(f"Launch output: {result.stdout.strip()}")
print(f"Launch error: {result.stderr.strip()}")

print("\n=== STEP 5: Check if WDA is installed and runnable ===")
# Kiểm tra app có tồn tại không
result = run_cmd(["tidevice", "--udid", UDID, "applist"])
if WDA_BUNDLE in result.stdout:
    print("✓ WDA app is installed")
else:
    print("✗ WDA app NOT found!")
    print("Available apps:")
    print(result.stdout)

print("\n=== STEP 6: Wait for WDA to start (45 seconds) ===")
for i in range(15):
    print(f"Waiting... {i*3+3}s", end="\r")
    try:
        response = requests.get("http://127.0.0.1:8100/status", timeout=2)
        if response.status_code == 200:
            print(f"\n✓ WDA is READY! Status: {response.json()}")
            break
    except:
        pass
    time.sleep(3)

print("\n=== STEP 7: Final check ===")
try:
    response = requests.get("http://127.0.0.1:8100/status", timeout=5)
    print(f"HTTP Status: {response.status_code}")
    if response.status_code == 200:
        print("🎉 SUCCESS! WDA is working correctly.")
        print(f"Response: {response.text[:200]}")
    else:
        print(f"WARNING: WDA returned status {response.status_code}")
except Exception as e:
    print(f"✗ WDA NOT responding: {e}")

print("\n=== STEP 8: Check if app is running on device ===")
# Kiểm tra process trên thiết bị
result = run_cmd(["tidevice", "--udid", UDID, "ps"])
if "WebDriverAgent" in result.stdout or "xctrunner" in result.stdout:
    print("✓ WDA process is running on device")
else:
    print("✗ WDA process NOT found on device")

print("\n" + "="*50)
print("If WDA is not working, try MANUALLY opening the app on your iPhone:")
print("1. Find 'WebDriverAgentRunner-Runner' app on home screen")
print("2. Tap to open it")
print("3. Wait 10 seconds")
print("4. Try checking again with: curl http://127.0.0.1:8100/status")
print("="*50)

print("\nKeep this terminal open and run 'python3 main.py' in another terminal")
input("Press Enter to stop relay and exit...")
relay_proc.terminate()