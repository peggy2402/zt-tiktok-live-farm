#!/usr/bin/env python3
import subprocess
import time
import signal
import sys
import wdapy

UDID = "7e6dd2126490d386718e5354011076ddd620c8a4"
WDA_BUNDLE = "com.facebook.WebDriverAgentRunner.xctrunner.K5R9T76J4Z"

def start_wda_via_xcuitest():
    """Khởi động WDA ổn định nhất thông qua tidevice xcuitest"""
    print("1. Starting WDA via 'tidevice xcuitest' (most stable)...")
    # Lệnh này sẽ build (nếu cần) và khởi chạy WDA server trực tiếp, không qua app UI
    cmd = ["tidevice", "--udid", UDID, "xcuitest", "-B", WDA_BUNDLE]
    # Chạy trong background, ghi log ra file để debug
    with open("wda_xcuitest.log", "w") as log_file:
        proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)
        print(f"   xcuitest process started (PID: {proc.pid}, log: wda_xcuitest.log)")
        return proc

def start_port_relay():
    print("2. Starting port relay...")
    relay_proc = subprocess.Popen(
        ["tidevice", "--udid", UDID, "relay", "8100", "8100"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    print(f"   Relay started (PID: {relay_proc.pid})")
    return relay_proc

def cleanup(procs):
    print("\n🧹 Cleaning up...")
    for p in procs:
        if p:
            p.terminate()
            p.wait(timeout=5)

# Xử lý Ctrl+C
procs_to_cleanup = []
def signal_handler(sig, frame):
    cleanup(procs_to_cleanup)
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

# Main execution
try:
    wda_proc = start_wda_via_xcuitest()
    procs_to_cleanup.append(wda_proc)
    
    time.sleep(10)  # Chờ WDA khởi động lâu hơn
    
    relay_proc = start_port_relay()
    procs_to_cleanup.append(relay_proc)
    
    time.sleep(3)
    
    print("3. Testing connection with wdapy...")
    client = wdapy.AppiumClient("http://localhost:8100")
    client.request_timeout = 60
    
    # Retry logic
    for i in range(5):
        try:
            print(f"   Attempt {i+1}/5 to get status...")
            info = client.device_info()
            print(f"   ✅ SUCCESS! Device Info: {info}")
            print(f"\n🌟 WDA is ready! You can now run your main app ('python3 main.py').")
            print(f"   Keep this terminal open, or run these commands in background:")
            print(f"   - tidevice --udid {UDID} xcuitest -B {WDA_BUNDLE} &")
            print(f"   - tidevice --udid {UDID} relay 8100 8100 &")
            
            # Keep scripts running
            input("\nPress Enter to stop WDA and exit...")
            break
        except Exception as e:
            print(f"   Attempt failed: {e}")
            if i < 4:
                time.sleep(5)
            else:
                print("   All attempts failed. Check 'wda_xcuitest.log' for details.")
                
except Exception as e:
    print(f"❌ Setup failed: {e}")
finally:
    cleanup(procs_to_cleanup)