# core/device_manager.py
import subprocess
import json
import os
import locale
import time
import sys
import platform
from config.settings import WDA_BUNDLE_ID
import psutil
import threading

class DeviceManager:
    @staticmethod
    def scan_devices():
        """Quét và phát hiện iOS version của từng thiết bị"""
        try:
            print("[DEBUG] Executing tidevice list...")
            cmd = [sys.executable, "-m", "tidevice", "list", "--json"]
            # Thêm timeout 10s để tránh treo vĩnh viễn
            result = subprocess.run(cmd, capture_output=True, check=False, timeout=10)

            if result.returncode != 0:
                err_msg = result.stderr.decode(locale.getpreferredencoding(False), errors='ignore')
                if "socket unix" in err_msg or "unable to connect" in err_msg:
                    print("[SCAN ERROR] Cannot connect to usbmuxd service.")
                    print("[FIX] Please run this command in terminal: sudo service usbmuxd restart")
                else:
                    print(f"[SCAN ERROR] tidevice command failed: {err_msg}")
                return []
            
            try:
                decoded_stdout = result.stdout.decode('utf-8')
            except UnicodeDecodeError:
                system_encoding = locale.getpreferredencoding(False)
                decoded_stdout = result.stdout.decode(system_encoding, errors='ignore')

            print(f"[DEBUG] Raw tidevice output: {decoded_stdout.strip()}")

            devices = []
            if decoded_stdout.strip():
                raw_data = json.loads(decoded_stdout)
                for d in raw_data:
                    # Log thiết bị tìm thấy để debug
                    print(f"[DEBUG] Found device entry: {d}")
                    
                    # Chấp nhận nếu là USB hoặc có UDID (nới lỏng điều kiện)
                    if d.get("conn_type") == "usb" or d.get("udid"):
                        version = d.get("product_version", d.get("ProductVersion", "N/A"))
                        
                        # UPDATE: Force pymobile engine to avoid tidevice/Python 3.12 compatibility issues
                        # (tidevice crashes with 'chunked' argument error on Py3.12)
                        engine = "pymobile"
                        
                        devices.append({
                            "udid": d.get("udid"),
                            "name": d.get("name", "Unknown Device"),
                            "version": version,
                            "engine": engine,
                            "model": d.get("market_name", d.get("model", "Unknown Model"))
                        })
            return devices
        except subprocess.TimeoutExpired:
            print("[SCAN ERROR] tidevice timed out (10s). Check usbmuxd service.")
            return []
        except Exception as e:
            print(f"[SCAN ERROR] {e}")
            return []

class DeviceController:
    """
    Điều khiển thiết bị - Tự động chọn engine phù hợp
    """
    def __init__(self, udid, version="N/A", engine="tidevice", port_offset=0):
        self.udid = udid
        self.ios_version = version
        self.engine = engine  # "tidevice" hoặc "pymobile"
        self.wda_port = 8100 + port_offset
        self.ssh_port = 2200 + port_offset
        self.process = None
        self.ssh_process = None
        self.tunneld_process = None
        self.wda_process = None
        
    def _log(self, message, logger=None):
        """Helper để in log ra console và gửi callback nếu có"""
        print(message)
        if logger:
            logger(message)

    def start_processes(self, logger=None):
        # Dọn dẹp các process cũ trước khi chạy mới để tránh xung đột port
        self.stop_processes(logger)
        
        try:
            self._kill_zombie_processes(logger)
        except Exception as e:
            self._log(f"[WARNING] Failed to kill zombie processes: {e}", logger)
            # Không return False ở đây, cứ thử chạy tiếp

        """Khởi động thiết bị với engine phù hợp"""
        self._log(f"[*] Starting {self.engine.upper()} engine for {self.udid} (iOS {self.ios_version})...", logger)
        
        if self.engine == "pymobile":
            return self._start_pymobile(logger)
        else:
            return self._start_tidevice(logger)
    
    def _start_tidevice(self, logger=None):
        """Dùng cho iPhone 7 iOS 15.x"""
        self._log(f"[TIDEVICE] Starting WDA for iOS {self.ios_version}...", logger)
        try:
            cmd = [
                sys.executable, "-m", "tidevice",
                "-u", self.udid,
                "wdaproxy",
                "-B", WDA_BUNDLE_ID,
                "--port", str(self.wda_port)
            ]

            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding=locale.getpreferredencoding(False),
                errors='ignore',
                creationflags=creation_flags,
                bufsize=1 # Line buffered
            )

            # Start logging immediately to see what's happening
            self._start_log_forwarder(logger)

            # Wait for WDA to become ready, with a timeout
            max_wait_time = 20  # seconds
            start_time = time.time()
            wda_is_ready = False

            self._log(f"[*] Waiting for WDA to be ready (up to {max_wait_time}s)...", logger)

            while time.time() - start_time < max_wait_time:
                # Check if process died unexpectedly
                if self.process.poll() is not None:
                    self._log("[FATAL] Tidevice process crashed unexpectedly.", logger)
                    break  # Exit the wait loop

                # Check if WDA is listening on the port
                if self._check_wda_ready():
                    wda_is_ready = True
                    break

                time.sleep(1)  # Check every second

            if wda_is_ready:
                self._log(f"[OK] Tidevice WDA ready at port {self.wda_port}", logger)
                return True
            else:
                # WDA failed to start in time. Kill the process and get logs.
                self._log(f"[ERROR] Tidevice WDA failed to become ready on port {self.wda_port} after {max_wait_time}s.", logger)
                
                try:
                    self.process.terminate()
                    self.process.wait(timeout=2)
                except:
                    if self.process.poll() is None:
                        self.process.kill()
                
                self._log("[HINT] Check logs above (WDA/WDA ERR). Common issues:", logger)
                self._log("  1. On iPhone: Go to Settings > General > VPN & Device Management and 'Trust' the developer app.", logger)
                self._log(f"  2. In config/settings.py: Verify WDA_BUNDLE_ID is correct ('{WDA_BUNDLE_ID}').", logger)
                self._log("  3. If WDA crashes immediately, it might be a signing issue (0xe8008018). Re-install WDA with a NEW Apple ID.", logger)
                return False
        except Exception as e:
            self._log(f"[ERROR] Tidevice start failed: {e}", logger)
            return False
    
    def _start_pymobile(self, logger=None):
        """Dùng cho iPhone SE iOS 18.6"""
        self._log(f"[PYMOBILE] Starting pymobiledevice3 for iOS {self.ios_version}...", logger)
        
        try:
            # 1. Start Tunneld (Chỉ cần cho iOS 17+)
            # iOS 15/16 dùng usbmuxd truyền thống, không cần tunneld (yêu cầu sudo)
            is_ios_17_plus = False
            try:
                if self.ios_version and self.ios_version != "N/A":
                    if float(self.ios_version.split('.')[0]) >= 17:
                        is_ios_17_plus = True
            except:
                pass

            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

            if is_ios_17_plus and not self._is_process_running('tunneld'):
                self._log("[*] Starting tunneld (iOS 17+)...", logger)
                tunnel_cmd = [sys.executable, "-m", "pymobiledevice3", "remote", "tunneld"]
                
                self.tunneld_process = subprocess.Popen(
                    tunnel_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    creationflags=creation_flags
                )
                time.sleep(3)
                if self.tunneld_process.poll() is not None:
                     _, err = self.tunneld_process.communicate()
                     self._log(f"[WARNING] Tunneld exited early: {err}", logger)
            
            # 2. Mount Developer Image
            # Bước này rất quan trọng cho iOS 17
            try:
                self._log("[*] Mounting developer image...", logger)
                mount_cmd = [sys.executable, "-m", "pymobiledevice3", "mounter", 
                            "auto-mount", "--udid", self.udid]
                res = subprocess.run(mount_cmd, capture_output=True, text=True, timeout=15)
                if res.returncode != 0:
                     # Chỉ log nếu có lỗi hoặc output lạ
                     self._log(f"[MOUNT INFO] {res.stderr.strip()} {res.stdout.strip()}", logger)
                else:
                     self._log("[OK] Developer Image mounted successfully.", logger)
            except Exception as e:
                self._log(f"[WARNING] Mount failed (might be already mounted): {e}", logger)
            
            # 3. Forward port
            self._log(f"[*] Forwarding port {self.wda_port} -> 8100...", logger)
            # Với pymobiledevice3, lệnh forward nằm trong nhóm 'usbmux', không phải 'remote'
            relay_cmd = [
                sys.executable, "-m", "pymobiledevice3", 
                "usbmux", "forward", str(self.wda_port), "8100",
                "--udid", self.udid
            ]
            
            self.process = subprocess.Popen(
                relay_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=creation_flags
            )
            
            # Đợi một chút để port forward thiết lập
            time.sleep(2)
            
            if self.process.poll() is not None:
                # Process đã chết
                out, err = self.process.communicate()
                self._log(f"[FATAL] Pymobile forward process died unexpectedly.\nSTDOUT: {out}\nSTDERR: {err}", logger)
                return False

            self._log(f"[OK] Pymobile forwarding ready at port {self.wda_port}", logger)
            # Start log forwarder
            self._start_log_forwarder(logger)
            
            self._log(f"[INFO] Port forwarding active. Attempting to launch WDA...", logger)
            return True
            
        except Exception as e:
            self._log(f"[ERROR] Pymobile start failed: {e}", logger)
            return False
    
    def _check_wda_ready(self):
        """Kiểm tra WDA đã sẵn sàng chưa"""
        import requests
        try:
            response = requests.get(f"http://127.0.0.1:{self.wda_port}/status", timeout=5)
            if response.status_code == 200:
                return True
            print(f"[DEBUG] WDA Status Code: {response.status_code}")
            return False
        except Exception as e:
            # print(f"[DEBUG] WDA Check Error: {e}") # Uncomment nếu muốn debug sâu
            return False
    
    def _is_process_running(self, process_name_part):
        """Kiểm tra process có đang chạy không dựa trên tên"""
        for proc in psutil.process_iter(['name', 'cmdline']):
            try:
                if proc.info['cmdline'] and process_name_part in str(proc.info['cmdline']):
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return False

    def _start_log_forwarder(self, logger):
        """Starts daemon threads to forward logs from the child process."""
        def read_stream(stream, prefix):
            if not stream: return
            try:
                for line in iter(stream.readline, ''):
                    if line:
                        self._log(f"[{prefix}] {line.strip()}", logger)
                    else:
                        break
            except (ValueError, OSError):
                pass

        if self.process.stdout:
            threading.Thread(target=read_stream, args=(self.process.stdout, "WDA"), daemon=True).start()
        if self.process.stderr:
            threading.Thread(target=read_stream, args=(self.process.stderr, "WDA ERR"), daemon=True).start()
    
    def start_ssh_tunnel(self):
        """Khởi động SSH tunnel (chỉ hỗ trợ với tidevice cho iOS 15)"""
        print(f"[*] Starting SSH tunnel on port {self.ssh_port}...")
        
        if self.engine == "pymobile":
            try:
                # pymobiledevice3 usbmux forward <local> 22
                cmd = [sys.executable, "-m", "pymobiledevice3", "usbmux", "forward", 
                       str(self.ssh_port), "22", "--udid", self.udid]
                
                creation_flags = 0
                if sys.platform == "win32":
                    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

                self.ssh_process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creation_flags
                )
                time.sleep(1)
                return True
            except Exception as e:
                print(f"[ERROR] SSH tunnel (pymobile) failed: {e}")
                return False

        try:
            cmd = [sys.executable, "-m", "tidevice", "-u", self.udid, "relay", 
                  str(self.ssh_port), "22"]
            
            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

            self.ssh_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags
            )
            time.sleep(1)
            return True
        except Exception as e:
            print(f"[ERROR] SSH tunnel failed: {e}")
            return False
    
    def stop_processes(self, logger=None):
        """Dừng tất cả tiến trình"""
        processes = [
            ("WDA/Forward", self.process),
            ("SSH", self.ssh_process),
            ("Tunneld", self.tunneld_process)
        ]
        
        for name, proc in processes:
            if proc:
                self._log(f"[*] Stopping {name}...", logger)
                try:
                    proc.terminate()
                    proc.wait(timeout=3)
                except:
                    try:
                        proc.kill()
                    except:
                        pass
                
        # Reset tất cả
        self.process = None
        self.ssh_process = None
        self.tunneld_process = None
        self._log(f"[OK] Device {self.udid} stopped completely", logger)

    def _kill_zombie_processes(self, logger=None):
        """Diệt các process cũ đang chiếm port (do lần chạy trước để lại)"""
        ports_to_check = [self.wda_port]
        if self.ssh_port:
            ports_to_check.append(self.ssh_port)
            
        # FIX: Không dùng 'connections' trong process_iter vì psutil mới không hỗ trợ
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                # Lấy connections thủ công cho từng process
                for conn in proc.net_connections():
                    if conn.laddr.port in ports_to_check:
                        self._log(f"[*] Killing zombie {proc.info['name']} (PID {proc.info['pid']}) on port {conn.laddr.port}", logger)
                        proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, ValueError):
                pass
