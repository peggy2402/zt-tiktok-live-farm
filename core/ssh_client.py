import paramiko
from scp import SCPClient
import os

class SSHClient:
    """
    Client để giao tiếp SSH và SCP (truyền file) với iPhone.
    Mặc định iPhone Jailbreak có user='root', pass='alpine'.
    """
    def __init__(self, host='127.0.0.1', port=2222, user='root', password='alpine'):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.client = None

    def connect(self):
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            # Timeout 5s để tránh treo nếu sai IP/Port
            self.client.connect(self.host, port=self.port, username=self.user, password=self.password, timeout=5)
            print(f"[SSH] Connected to {self.host}:{self.port}")
            return True
        except Exception as e:
            print(f"[SSH] Connection failed: {e}")
            return False

    def execute_command(self, command):
        """Thực thi lệnh shell trên iPhone."""
        if not self.client:
            return None, "Not connected"
        stdin, stdout, stderr = self.client.exec_command(command)
        return stdout.read().decode(), stderr.read().decode()

    def upload_file(self, local_path, remote_path, progress_callback=None):
        """Upload file video lên iPhone."""
        if not self.client:
            return False
        
        try:
            # Hàm callback cho SCP để báo % tiến trình
            def scp_progress(filename, size, sent):
                if progress_callback and size > 0:
                    percent = (sent / size) * 100
                    progress_callback(f"Uploading: {percent:.1f}%")

            with SCPClient(self.client.get_transport(), progress=scp_progress) as scp:
                scp.put(local_path, remote_path)
            
            print(f"[SSH] Uploaded {local_path} to {remote_path}")
            return True
        except Exception as e:
            print(f"[SSH] Upload failed: {e}")
            return False
            
    def close(self):
        if self.client:
            self.client.close()
            self.client = None