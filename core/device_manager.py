# core/device_manager.py
import subprocess
import json
import os
import time
import threading
import sys
import platform
import psutil
import requests
from shutil import which

# Attempt to import WDA_BUNDLE_ID, with a fallback for standalone testing
try:
    from config.settings import WDA_BUNDLE_ID
except (ImportError, ModuleNotFoundError):
    print("[WARNING] Could not import WDA_BUNDLE_ID from config.settings. Using a default value.")
    WDA_BUNDLE_ID = "com.facebook.WebDriverAgentRunner.xctrunner"


def _is_command_available(cmd):
    """Check if a command is available in the system's PATH."""
    return which(cmd) is not None


def _log(message):
    """Global logger for this module."""
    print(f"[DeviceManager] {message}")


class PortManager:
    """
    Quản lý cấp phát port tập trung để tránh xung đột giữa các thiết bị.
    Sử dụng cơ chế 'Base + Index' deterministic.
    """
    _allocations = {} # {udid: index}
    _lock = threading.Lock()
    
    BASE_WDA_PORT = 8100
    BASE_MJPEG_PORT = 9100

    @classmethod
    def get_ports(cls, udid: str) -> dict:
        with cls._lock:
            if udid not in cls._allocations:
                # Cấp index mới tăng dần (0, 1, 2...)
                new_index = len(cls._allocations)
                cls._allocations[udid] = new_index
            
            idx = cls._allocations[udid]
            return {
                "wda_port": cls.BASE_WDA_PORT + idx,
                "mjpeg_port": cls.BASE_MJPEG_PORT + idx
            }
    
    @classmethod
    def reset(cls):
        with cls._lock:
            cls._allocations = {}
            
    @classmethod
    def release(cls, udid: str):
        with cls._lock:
            if udid in cls._allocations:
                del cls._allocations[udid]

class DeviceManager:
    @staticmethod
    def scan_devices(retry=True):
        """
        Scans for connected iOS devices using a prioritized list of backends.
        1. pymobiledevice3 (Primary - Stable & Pure Python)
        2. tidevice3 (for iOS 17+)
        3. tidevice (Legacy for iOS < 17)
        """
        devices_map = {} # Deduplicate by UDID
        
        # Environment to prevent 'blessed' library crash (setupterm failed)
        safe_env = os.environ.copy()
        safe_env["TERM"] = "dumb"

        def add_device(udid, name, version, engine, model="Unknown"):
            if udid and udid not in devices_map:
                devices_map[udid] = {
                    "udid": udid,
                    "name": name,
                    "version": version,
                    "engine": engine,
                    "model": model
                }

        # Priority 1: pymobiledevice3
        # This is preferred because it doesn't depend on binary executables and handles usbmuxd well.
        try:
            _log("Scanning via pymobiledevice3...")
            cmd = [sys.executable, "-m", "pymobiledevice3", "usbmux", "list"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=10, env=safe_env)
            if res.returncode == 0:
                pymobile_data = json.loads(res.stdout)
                for d in pymobile_data:
                    add_device(
                        udid=d.get("Identifier"),
                        name=d.get("DeviceName", "iPhone"),
                        version=d.get("ProductVersion", "15.0"), # Default if missing
                        engine="pymobile",
                        model=d.get("ProductType", "iPhone")
                    )
        except Exception as e:
            _log(f"pymobiledevice3 scan warning: {e}")
        
        # Priority 2: tidevice3 (t3)
        if _is_command_available("t3"):
            try:
                # _log("Scanning via tidevice3...")
                cmd = ["t3", "list", "--json"]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=5, env=safe_env)
                if res.returncode == 0:
                    tidevice3_data = json.loads(res.stdout)
                    for d in tidevice3_data:
                        udid = d.get("udid") or d.get("SerialNumber")
                        add_device(
                            udid=udid,
                            name=d.get("DeviceName", "iPhone (t3)"),
                            version=d.get("ProductVersion", "17.0"),
                            engine="tidevice3",
                            model=d.get("ProductType", "Unknown")
                        )
            except Exception as e:
                pass # Silent fail for secondary backends

        # Priority 3: tidevice (Legacy)
        if _is_command_available("tidevice"):
            try:
                # _log("Scanning via tidevice (Legacy)...")
                cmd = ["tidevice", "list", "--json"]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=5, env=safe_env)
                if res.returncode == 0:
                    tidevice_data = json.loads(res.stdout)
                    for d in tidevice_data:
                        add_device(
                            udid=d.get("udid"),
                            name=d.get("name", "iPhone (Legacy)"),
                            version=d.get("product_version", "15.0"),
                            engine="tidevice",
                            model=d.get("market_name", "Unknown")
                        )
            except Exception as e:
                pass
        
        devices = list(devices_map.values())

        # On Linux/WSL, we can try to restart usbmuxd if nothing is found
        if not devices and retry and platform.system() == "Linux":
            try:
                lsusb_check = subprocess.run(["lsusb"], capture_output=True, text=True)
                if "05ac:" in lsusb_check.stdout:  # Apple Vendor ID
                    _log("Found Apple device via lsusb, but no tools detected it. Restarting usbmuxd...")
                    subprocess.run(["sudo", "service", "usbmuxd", "restart"], check=False)
                    time.sleep(3)
                    return DeviceManager.scan_devices(retry=False) # Retry scan once
            except FileNotFoundError:
                pass # lsusb or sudo not available

        # [HINT] Windows specific hints for driver issues (Common after using Zadig)
        if not devices and platform.system() == "Windows":
            _log("❌ No devices detected.")
            _log("👉 TIP: Ensure iTunes is installed and you have clicked 'Trust' on the iPhone.")
            _log("👉 TIP: If you used Zadig (libusbK) for Jailbreak, check Device Manager. You might need to uninstall the libusbK driver to restore normal Apple connectivity.")

        return devices

    @staticmethod
    def clear_saved_devices(json_path="devices.json"):
        """
        Xóa file devices.json và reset trạng thái port để đảm bảo scan lại từ đầu (Clean Slate).
        """
        # 1. Xóa file JSON lưu trữ (nếu có)
        if os.path.exists(json_path):
            try:
                os.remove(json_path)
                _log(f"🗑️  Deleted old device config: {json_path}")
            except Exception as e:
                _log(f"⚠️  Error deleting {json_path}: {e}")
        
        # 2. Reset bộ nhớ cấp phát Port
        PortManager.reset()
        _log("✅ Device cache & Ports cleared. Ready for fresh scan.")

    @staticmethod
    def wsl_attach_usb_devices(logger=None):
        """
        Thực hiện chuỗi lệnh attach USB từ Windows vào WSL tự động.
        Yêu cầu: usbipd.exe phải có trong PATH (mặc định của WSL).
        """
        def _log_local(msg):
            if logger: logger(msg)
            else: print(f"[WSL-USB] {msg}")

        if platform.system() != "Linux" or "microsoft" not in platform.release().lower():
            _log_local("[ERROR] Tính năng này chỉ hoạt động trên WSL.")
            return

        if which("usbipd.exe") is None:
             _log_local("[ERROR] Không tìm thấy 'usbipd.exe'. Hãy cài đặt usbipd-win trên Windows.")
             return

        _log_local("[*] Đang quét thiết bị USB trên Windows host...")
        try:
            # 1. Lấy danh sách thiết bị từ usbipd
            res = subprocess.run(["usbipd.exe", "list"], capture_output=True, text=True)
            output = res.stdout
            
            # Tìm BUSID của thiết bị Apple (VID 05ac)
            apple_busids = []
            for line in output.splitlines():
                if "05ac:" in line or "Apple" in line:
                    # Dạng: 1-6    05ac:12a8 ...
                    parts = line.split()
                    if parts and "-" in parts[0]:
                        apple_busids.append(parts[0])
            
            if not apple_busids:
                _log_local("[-] Không tìm thấy thiết bị Apple nào đang cắm vào Windows.")
                return

            # 2. Stop Service (Yêu cầu Admin, nhưng cứ thử chạy)
            _log_local("[*] Đang dừng 'Apple Mobile Device Service' (Windows)...")
            subprocess.run(["cmd.exe", "/c", "net", "stop", "\"Apple Mobile Device Service\""], 
                           capture_output=True, text=True)

            for busid in apple_busids:
                _log_local(f"[*] Đang xử lý BUSID {busid}...")
                
                # 3. Unbind (Xóa trạng thái cũ)
                subprocess.run(["usbipd.exe", "unbind", "--busid", busid], capture_output=True)
                
                # 4. Bind (Force - Cần Admin)
                bind_res = subprocess.run(["usbipd.exe", "bind", "--busid", busid, "--force"], 
                                          capture_output=True, text=True)
                if bind_res.returncode != 0:
                    _log_local(f"[-] Bind lỗi (Cần quyền Admin?): {bind_res.stderr.strip()}")
                
                # 5. Attach vào WSL
                _log_local(f"[*] Đang Attach BUSID {busid} vào WSL...")
                attach_res = subprocess.run(["usbipd.exe", "attach", "--wsl", "--busid", busid], 
                                            capture_output=True, text=True)
                
                if attach_res.returncode == 0:
                    _log_local(f"[SUCCESS] Đã attach thành công BUSID {busid}.")
                else:
                    _log_local(f"[-] Attach lỗi: {attach_res.stderr.strip()}")

            # 6. Kiểm tra lại bằng lsusb
            time.sleep(2)
            lsusb_res = subprocess.run(["lsusb"], capture_output=True, text=True)
            if "05ac:" in lsusb_res.stdout:
                _log_local("[CHECK] ✅ Đã thấy thiết bị Apple trong lsusb (Ubuntu).")
                # Restart usbmuxd để nhận diện thiết bị mới
                subprocess.run(["sudo", "service", "usbmuxd", "restart"], check=False)
            else:
                _log_local("[CHECK] ❌ Chưa thấy thiết bị trong lsusb. Hãy kiểm tra lại.")

        except Exception as e:
            _log_local(f"[ERROR] Lỗi ngoại lệ: {e}")

    def _check_and_fix_usbmuxd(self, logger=None):
        """
        [WSL/Linux Specific] Checks if usbmuxd is running and restarts it if necessary.
        This fixes the 'Failed to connect to usbmuxd socket' error.
        """
        if platform.system() == "Linux":
            # Check if socket exists
            if not os.path.exists("/var/run/usbmuxd"):
                self._log("⚠️ usbmuxd socket missing. Restarting service...", logger)
                subprocess.run(["sudo", "service", "usbmuxd", "restart"], check=False)
                time.sleep(2)
                return

    def _get_correct_wda_bundle_id(self, logger=None):
        """
        Detects the actual WDA bundle ID installed on the device.
        Fixes 'MuxError: No app matches bundle id'.
        """
        try:
            cmd = ["tidevice", "--udid", self.udid, "applist"]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    if "WebDriverAgent" in line or "xctrunner" in line:
                        # Output format: com.facebook.WebDriverAgentRunner.xctrunner 1.0.0
                        parts = line.split()
                        if parts:
                            detected_id = parts[0]
                            if detected_id != self.wda_bundle_id:
                                self._log(f"✅ Auto-detected WDA Bundle ID: {detected_id}", logger)
                            return detected_id
        except Exception as e:
            self._log(f"Failed to detect WDA Bundle ID: {e}", logger)
        
        return self.wda_bundle_id # Fallback to config

class DeviceController:
    """
    Controls a single iOS device by starting and stopping necessary processes
    like WDA and port forwarding tunnels.
    """
    def __init__(self, udid, version="N/A", engine="tidevice3", port_offset=None):
        self.udid = udid
        self.ios_version = version
        self.engine = engine
        
        # Tự động lấy port từ PortManager nếu không chỉ định offset thủ công
        if port_offset is None:
            ports = PortManager.get_ports(udid)
            self.wda_port = ports["wda_port"]
            self.mjpeg_port = ports["mjpeg_port"]
        else:
            self.wda_port = 8100 + port_offset
            self.mjpeg_port = 9100 + port_offset
            
        self.wda_process = None
        self.relay_process = None
        self.mjpeg_relay_process = None
        self.ssh_process = None
        self.wda_bundle_id = WDA_BUNDLE_ID
        self.wda_log_file = None

    def _check_environment(self, logger=None):
        """Checks for critical environment issues (urllib3, usbmuxd)."""
        # 1. Check urllib3 compatibility for tidevice
        try:
            import urllib3
            if urllib3.__version__.startswith("2."):
                self._log("❌ CRITICAL: urllib3 v2.x detected! tidevice requires v1.26.x.", logger)
                self._log("   Attempting to auto-fix by downgrading urllib3...", logger)
                try:
                    subprocess.check_call([sys.executable, "-m", "pip", "install", "urllib3<2.0"])
                    self._log("✅ urllib3 downgraded successfully. (v1.26.x installed)", logger)
                    self._log("🛑 ACTION REQUIRED: Please RESTART the application now to apply changes!", logger)
                    return False # Stop execution here
                except Exception as e:
                    self._log(f"   Auto-fix failed: {e}. Please run 'pip install \"urllib3<2.0\"' manually.", logger)
                    return False
        except ImportError:
            pass

        # 2. Ensure usbmuxd is running (Linux/WSL)
        if platform.system() == "Linux":
            if not os.path.exists("/var/run/usbmuxd"):
                self._log("⚠️ usbmuxd socket missing. Restarting service...", logger)
                subprocess.run(["sudo", "service", "usbmuxd", "restart"], check=False)
                time.sleep(3)
        return True

    def _log(self, message, logger=None):
        """Helper to print log and emit signal if logger is provided."""
        log_message = f"[{self.udid}] {message}"
        print(log_message)
        if logger:
            logger(log_message)

    def start_processes(self, logger=None):
        """
        Starts WebDriverAgent on the device using the designated engine.
        This now acts as the main entry point for starting a device session.
        """
        self._log(f"Starting session (iOS {self.ios_version}, engine: {self.engine.upper()})", logger)

        # [FIX] Ensure environment is healthy before starting
        if not self._check_environment(logger):
            return False

        self.stop_wda(logger)  # Ensure no old processes are running for this device
        
        # Determine which method to use based on the engine found during scan
        if self.engine == "tidevice3":
            return self._start_wda_with_tidevice3(logger)
        elif self.engine == "tidevice":
            return self._start_wda_with_tidevice(logger)
        elif self.engine == "pymobile":
            return self._start_wda_with_pymobile(logger)
        else:
            self._log(f"Error: Unknown engine '{self.engine}'. Cannot start WDA.", logger)
            return False

    def _start_wda_with_tidevice3(self, logger=None):
        """Starts WDA using tidevice3. Recommended for iOS 17+."""
        self._log("Using tidevice3 to launch WDA...", logger)
        try:
            creation_flags = 0
            if platform.system() == "win32":
                creation_flags = subprocess.CREATE_NO_WINDOW

            cmd = [
                "t3", "wda",
                "--udid", self.udid,
                "--bundle-id", self.wda_bundle_id,
                "--port", str(self.wda_port),
            ]
            
            self.wda_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=creation_flags,
                text=True
            )
            
            self._log("Waiting for WDA to be ready...", logger)
            if self._wait_for_wda_status(logger):
                self._log(f"WDA is ready on port {self.wda_port}", logger)
                return True
            else:
                self._log(f"WDA failed to start or become ready.", logger)
                self.stop_wda(logger)
                return False

        except FileNotFoundError:
            self._log("Error: 't3' command not found. Is tidevice3 installed correctly (e.g., 'pipx install tidevice3')?", logger)
            return False
        except Exception as e:
            self._log(f"An error occurred while starting WDA with tidevice3: {e}", logger)
            self.stop_wda(logger)
            return False

    def _ensure_ddi_exists(self, logger=None):
        """
        Ensures Developer Disk Image for iOS 15.7 (compatible with 15.x) exists.
        Downloads it if missing.
        """
        home = os.path.expanduser("~")
        # Use 15.7 as the safe fallback for 15.8
        ddi_dir = os.path.join(home, ".cache", "tidevice", "device_support", "15.7")
        dmg_path = os.path.join(ddi_dir, "DeveloperDiskImage.dmg")
        sig_path = os.path.join(ddi_dir, "DeveloperDiskImage.dmg.signature")
        self._log(f"Path dmg: {dmg_path}, sig: {sig_path}", logger)

        if os.path.exists(dmg_path) and os.path.exists(sig_path):
            return dmg_path, sig_path

        self._log(f"DDI cache missing at {ddi_dir}. Attempting auto-download...", logger)
        
        try:
            os.makedirs(ddi_dir, exist_ok=True)
            base_url = "https://github.com/doronz88/DeveloperDiskImage/raw/main/DeveloperDiskImages/15.7"
            
            self._log("Downloading DeveloperDiskImage.dmg (This may take a while)...", logger)
            r = requests.get(f"{base_url}/DeveloperDiskImage.dmg", timeout=120)
            if r.status_code == 200:
                with open(dmg_path, "wb") as f:
                    f.write(r.content)
            
            self._log("Downloading DeveloperDiskImage.dmg.signature...", logger)
            r = requests.get(f"{base_url}/DeveloperDiskImage.dmg.signature", timeout=30)
            if r.status_code == 200:
                with open(sig_path, "wb") as f:
                    f.write(r.content)
            
            # [VALIDATION] Check file size to prevent corrupt downloads (e.g. HTML error pages)
            if os.path.exists(dmg_path) and os.path.getsize(dmg_path) < 10 * 1024 * 1024: # < 10MB
                self._log("ERROR: Downloaded DDI is too small (Corrupt). Deleting...", logger)
                os.remove(dmg_path)
                if os.path.exists(sig_path): os.remove(sig_path)
                return None, None

            self._log("DDI Download complete.", logger)
            return dmg_path, sig_path
        except Exception as e:
            self._log(f"Failed to download DDI: {e}", logger)
            return None, None

    def _start_wda_with_tidevice(self, logger=None):
        """Starts WDA using the legacy tidevice. Good for iOS < 17."""
        self._log("Using tidevice 'wdaproxy' (Stable Flow)...", logger)
        try:
            creation_flags = 0
            if platform.system() == "win32":
                creation_flags = subprocess.CREATE_NO_WINDOW
            
            # Detect correct Bundle ID before launching
            real_bundle_id = self._get_correct_wda_bundle_id(logger)
            self.wda_bundle_id = real_bundle_id

            # [ADD] Pre-mount DDI check for WSL environment
            # tidevice auto-download often fails in WSL, so we try to mount from local cache explicitly
            try:
                dmg, sig = self._ensure_ddi_exists(logger)
                
                if dmg and sig:
                    self._log(f"Pre-mounting DDI (via pymobiledevice3)...", logger)
                    # [DEBUG] Capture output to diagnose mount failures
                    # Sử dụng lệnh mount-developer của pymobiledevice3
                    mount_res = subprocess.run(
                        [sys.executable, "-m", "pymobiledevice3", "mounter", "mount-developer", dmg, sig, "--udid", self.udid],
                        capture_output=True, text=True
                    )
                    
                    # Phân tích kết quả mount
                    output = mount_res.stderr.strip() + mount_res.stdout.strip()
                    if "already mounted" in output:
                        self._log("DDI already mounted. Good.", logger)
                    elif mount_res.returncode != 0:
                        # Clean up verbose traceback in logs
                        if "Traceback" in output:
                            self._log(f"Mount Warning: {output.splitlines()[-1]}", logger)
                        else:
                            self._log(f"Mount Warning: {output}", logger)
                        # Nếu mount thất bại, thử unmount rồi mount lại (nếu cần thiết, nhưng thường là do file lỗi)
                    else:
                        self._log(f"Mount Result: {mount_res.stdout.strip()}", logger)
            except Exception as e:
                self._log(f"Pre-mount DDI warning: {e}", logger)

            # [STRATEGY] Use 'xcuitest' with ENV vars + 'relay'.
            cmd = [
                "tidevice",
                "--udid", self.udid,
                "xcuitest",
                "-B", self.wda_bundle_id,
                "-e", "USE_PORT:8100",        # Explicitly set WDA internal port
                "-e", "MJPEG_SERVER_PORT:9100", # Set MJPEG port
            ]
            
            # [IMPROVEMENT] Log WDA output to file for debugging
            log_dir = os.path.join(os.getcwd(), "logs")
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, f"wda_{self.udid}.log")
            
            # Retry loop for WDA Launch
            wda_launched = False
            for attempt in range(3):
                self._log(f"Executing WDA (xcuitest) - Attempt {attempt+1}/3...", logger)
                
                # [FIX] Pre-launch WDA app manually to warm up testmanagerd
                # This helps prevent 'xctrunner quited' errors on iOS 15
                try:
                    subprocess.run(["tidevice", "--udid", self.udid, "launch", self.wda_bundle_id], 
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
                    time.sleep(2)
                except:
                    pass

                # Re-open log file for each attempt
                if self.wda_log_file:
                    try:
                        self.wda_log_file.close()
                    except:
                        pass
                self.wda_log_file = open(log_path, "w", encoding="utf-8")

                self.wda_process = subprocess.Popen(
                    cmd,
                    stdout=self.wda_log_file,
                    stderr=subprocess.STDOUT,
                    creationflags=creation_flags,
                    text=True
                )
                
                time.sleep(4) # Wait for initialization
                
                if self.wda_process.poll() is None:
                    wda_launched = True
                    break
                
                self._log(f"⚠️ WDA process died immediately. Retrying...", logger)
                self._print_wda_log_tail(log_path, logger)
            
            if not wda_launched:
                self._log("❌ Failed to launch WDA after 3 attempts.", logger)
                self._log("👉 SUGGESTION: Re-install WDA app on your iPhone.", logger)
                self._log("❌ Failed to launch WDA with tidevice after 3 attempts.", logger)
                self._log("🔄 Switching to pymobiledevice3 fallback...", logger)
                self.stop_wda(logger)
                return self._start_wda_with_pymobile(logger)

            # [STEP 2] Start Relay separately
            self._log(f"Starting Port Relay: {self.wda_port} -> 8100", logger)
            relay_cmd = [
                "tidevice",
                "--udid", self.udid,
                "relay",
                str(self.wda_port), "8100"
            ]
            
            self.relay_process = subprocess.Popen(
                relay_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags
            )
            
            # Wait a bit for relay to bind
            time.sleep(2)

            # [STEP 3] Start MJPEG Relay (Stream màn hình)
            self._log(f"Starting MJPEG Relay: {self.mjpeg_port} -> 9100", logger)
            mjpeg_relay_cmd = [
                "tidevice",
                "--udid", self.udid,
                "relay",
                str(self.mjpeg_port), "9100"
            ]
            
            self.mjpeg_relay_process = subprocess.Popen(
                mjpeg_relay_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags
            )

            if self._wait_for_wda_status(logger, timeout=45):
                self._log(f"WDA is ready on port {self.wda_port}", logger)
                return True
            else:
                self._log(f"WDA did not become ready.", logger)
                # [DEBUG] Read log file to show why it failed
                self._print_wda_log_tail(log_path, logger)
                self.stop_wda(logger)
                return False

        except FileNotFoundError:
            self._log("Error: 'tidevice' command not found. Please install it.", logger)
            return False
        except Exception as e:
            self._log(f"An error occurred while starting WDA with tidevice: {e}", logger)
            self.stop_wda(logger)
            return False

    def _print_wda_log_tail(self, log_path, logger=None):
        """Reads the last few lines of the WDA log file and prints them."""
        try:
            if os.path.exists(log_path):
                with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    lines = content.splitlines()
                    tail = lines[-10:] if len(lines) > 10 else lines
                    if tail:
                        self._log(f"--- WDA ERROR LOG ({log_path}) ---", logger)
                        for line in tail:
                            self._log(f"   > {line.strip()}", logger)
                        self._log("-----------------------------------", logger)
                    
                    # Phân tích lỗi cụ thể để hướng dẫn người dùng
                    lower_content = content.lower()
                    if "not been explicitly trusted" in lower_content or ("security" in lower_content and "trusted" in lower_content):
                        self._log("🛑 LỖI NGHIÊM TRỌNG: App WDA chưa được TIN CẬY (TRUST) trên iPhone.", logger)
                        self._log("👉 KHẮC PHỤC: Vào Cài đặt > Cài đặt chung > Quản lý VPN & Thiết bị > Chọn Email Developer > Bấm TIN CẬY.", logger)
                    elif "cert_reqs" in lower_content:
                        self._log("⚠️ CẢNH BÁO: Lỗi phiên bản thư viện urllib3.", logger)
                        self._log("👉 KHẮC PHỤC: Chạy lại file 'scripts/setup_windows.bat' hoặc lệnh 'pip install \"urllib3<2.0\"'.", logger)
                    elif "xctrunner quited" in lower_content or "exited with status" in lower_content:
                        self._log("⚠️ WDA App crashed immediately (App tự đóng).", logger)
                        self._log("👉 NGUYÊN NHÂN: Có thể chứng chỉ 7 ngày (Free Dev) đã hết hạn.", logger)
                        self._log("👉 KHẮC PHỤC: Hãy cài lại WDA bằng Sideloadly/3uTools.", logger)
        except Exception as e:
            self._log(f"Could not read WDA log: {e}", logger)

    def _get_correct_wda_bundle_id(self, logger=None):
        """Helper to find the installed WDA Bundle ID."""
        try:
            cmd = ["tidevice", "--udid", self.udid, "applist"]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    # [IMPROVED] Tìm kiếm WDA với từ khóa mở rộng
                    line_lower = line.lower()
                    if any(k in line_lower for k in ["webdriveragent", "xctrunner", "wda", "runner"]):
                        parts = line.split()
                        if parts:
                            detected = parts[0]
                            # Kiểm tra lại xem có phải bundle id không (có dấu chấm)
                            if "." in detected:
                                if detected != self.wda_bundle_id:
                                    self._log(f"✅ Auto-detected WDA Bundle ID: {detected}", logger)
                                return detected
            
            # [FALLBACK] Try pymobiledevice3 if tidevice fails or returns nothing
            safe_env = os.environ.copy()
            safe_env["TERM"] = "dumb"
            cmd_py = [sys.executable, "-m", "pymobiledevice3", "apps", "list", "--udid", self.udid]
            res_py = subprocess.run(cmd_py, capture_output=True, text=True, env=safe_env)
            if res_py.returncode == 0:
                # Output format varies, but we look for bundle ID patterns
                for line in res_py.stdout.splitlines():
                    line_lower = line.lower()
                    # Check for keywords
                    if any(k in line_lower for k in ["webdriveragent", "xctrunner", "wda", "runner"]):
                        # Extract potential bundle ID
                        parts = line.split()
                        for part in parts:
                            # Bundle ID usually contains dots and doesn't start with (
                            if "." in part and not part.startswith("("):
                                # Verify it looks like a WDA bundle
                                if any(k in part.lower() for k in ["webdriveragent", "xctrunner", "wda", "runner"]):
                                    if part != self.wda_bundle_id:
                                        self._log(f"✅ Auto-detected WDA Bundle ID (pymobile): {part}", logger)
                                    return part

        except Exception as e:
            self._log(f"Error detecting WDA Bundle ID: {e}", logger)
        return self.wda_bundle_id

    def _start_wda_with_pymobile(self, logger=None):
        """Starts WDA using pymobiledevice3. Used as a fallback."""
        self._log("Using pymobiledevice3 to launch WDA...", logger)
        
        # [FIX] Set TERM=dumb to prevent 'blessed' library from crashing in subprocess
        safe_env = os.environ.copy()
        safe_env["TERM"] = "dumb"

        # [FIX] Detect correct Bundle ID first!
        self.wda_bundle_id = self._get_correct_wda_bundle_id(logger)

        try:
            self._log(f"Forwarding local port {self.wda_port} to device port 8100.", logger)
            creation_flags = 0
            if platform.system() == "win32":
                creation_flags = subprocess.CREATE_NO_WINDOW

            # [UPDATE] Auto-mount DDI cho mọi phiên bản (iOS 15-17+) khi dùng engine pymobile
            # Lệnh này sẽ tự động tải và mount DDI phù hợp.
            self._log("Checking/Mounting Developer Disk Image...", logger)
            mount_cmd = [sys.executable, "-m", "pymobiledevice3", "mounter", "auto-mount", "--udid", self.udid]
            mount_res = subprocess.run(mount_cmd, capture_output=True, text=True, timeout=60, env=safe_env)
            
            if mount_res.returncode != 0:
                err_out = mount_res.stderr + mount_res.stdout
                if "183" in err_out or "PasswordProtected" in err_out or "PairingDialogResponsePending" in err_out:
                    self._log("🛑 ERROR: Device is LOCKED or NOT TRUSTED. Please Unlock & Trust.", logger)
                    return False
                self._log(f"Mount info: {err_out.strip()[:200]}...", logger)

            self._log("Attempting to launch WDA app...", logger)
            launch_cmd = [
                sys.executable, "-m", "pymobiledevice3",
                "developer", "dvt", "launch",
                "--udid", self.udid,
                "--env", "USE_PORT", "8100",
                "--env", "MJPEG_SERVER_PORT", "9100",
                self.wda_bundle_id
            ]
            res = subprocess.run(launch_cmd, capture_output=True, text=True, timeout=15, env=safe_env)
            if res.returncode != 0:
                self._log(f"Launch failed: {res.stderr.strip()}", logger)
                err_out = res.stderr + res.stdout
                if "183" in err_out or "PairingDialogResponsePending" in err_out or "PasswordProtected" in err_out:
                    self._log("🛑 ERROR: Device locked or not trusted. Please UNLOCK and TRUST THIS COMPUTER.", logger)
                    return False
            else:
                self._log(f"Launch output: {res.stdout.strip()}", logger)
            
            forward_cmd = [
                sys.executable, "-m", "pymobiledevice3",
                "usbmux", "forward", "--serial", self.udid, str(self.wda_port), "8100"
            ]
            self.wda_process = subprocess.Popen(
                forward_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, # Capture stderr để debug lỗi Exit Code 2
                creationflags=creation_flags,
                text=True
            )
            
            # [ADD] Forward MJPEG Port (9100)
            self._log(f"Forwarding local MJPEG port {self.mjpeg_port} to device port 9100.", logger)
            mjpeg_forward_cmd = [
                sys.executable, "-m", "pymobiledevice3",
                "usbmux", "forward", "--serial", self.udid, str(self.mjpeg_port), "9100"
            ]
            self.mjpeg_relay_process = subprocess.Popen(
                mjpeg_forward_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags
            )

            if self._wait_for_wda_status(logger):
                self._log(f"WDA is ready on port {self.wda_port}", logger)
                return True
            else:
                self._log(f"WDA did not become ready.", logger)
                self.stop_wda(logger)
                return False

        except FileNotFoundError:
            self._log("Error: 'pymobiledevice3' is not installed or Python env is not correct.", logger)
            return False
        except Exception as e:
            self._log(f"An error occurred while starting WDA with pymobiledevice3: {e}", logger)
            self.stop_wda(logger)
            return False

    def _wait_for_wda_status(self, logger=None, timeout=30):
        """Polls the WDA /status endpoint until it's ready or times out."""
        self._log("Waiting for WDA status...", logger)
        start_time = time.time()
        while time.time() - start_time < timeout:
            # [CHECK] If process died prematurely
            if self.wda_process and self.wda_process.poll() is not None:
                err_msg = ""
                if self.wda_process.stderr:
                    err_msg = self.wda_process.stderr.read()
                self._log(f"❌ WDA process died unexpectedly (Exit Code: {self.wda_process.returncode}). Error: {err_msg.strip()}", logger)
                return False

            try:
                response = requests.get(f"http://127.0.0.1:{self.wda_port}/status", timeout=2)
                if response.status_code == 200 and "state" in response.json().get("value", {}):
                    return True
            except requests.RequestException:
                pass
            time.sleep(1)
        self._log("Timed out waiting for WDA status.", logger)
        return False

    def stop_wda(self, logger=None):
        """Stops the WDA process and any related tunnels."""
        if self.wda_process:
            self._log(f"Stopping WDA process (PID: {self.wda_process.pid}).", logger)
            try:
                self.wda_process.terminate()
                self.wda_process.wait(timeout=5)
            except (psutil.NoSuchProcess, subprocess.TimeoutExpired):
                try:
                    self.wda_process.kill()
                except psutil.NoSuchProcess:
                    pass
            except Exception as e:
                self._log(f"Error while stopping WDA process: {e}", logger)
            self.wda_process = None
        
        if self.relay_process:
            self._log(f"Stopping Relay process.", logger)
            try:
                self.relay_process.terminate()
                self.relay_process.wait(timeout=2)
            except:
                try: self.relay_process.kill()
                except: pass
            self.relay_process = None

        if self.mjpeg_relay_process:
            self._log(f"Stopping MJPEG Relay process.", logger)
            try:
                self.mjpeg_relay_process.terminate()
                self.mjpeg_relay_process.wait(timeout=2)
            except: pass
            self.mjpeg_relay_process = None

        # Close log file handle
        if self.wda_log_file:
            try:
                self.wda_log_file.close()
            except:
                pass
            self.wda_log_file = None

        self._kill_process_on_port(self.wda_port, logger)
        self._kill_process_on_port(self.mjpeg_port, logger)
        PortManager.release(self.udid)

    def _kill_process_on_port(self, port, logger=None):
        """Finds and kills any process listening on a specific port."""
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                for conn in proc.connections(kind='inet'):
                    if conn.status == psutil.CONN_LISTEN and conn.laddr.port == port:
                        self._log(f"Found zombie process '{proc.name()}' (PID: {proc.pid}) on port {port}. Terminating.", logger)
                        proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                # These exceptions are expected if the process disappears during iteration
                pass
            except Exception as e:
                # Other errors are unexpected, log for debugging
                self._log(f"[DEBUG] Error checking process {proc.pid}: {e}", logger)