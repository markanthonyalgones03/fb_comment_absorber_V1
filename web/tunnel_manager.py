"""
Tunnel and Network Manager for Comment Absorber Web Studio.
Manages local Wi-Fi detection and Cloudflare Tunnel for seamless mobile access.
"""

import os
import re
import sys
import time
import json
import socket
import threading
import subprocess
from pathlib import Path
from typing import Optional, Dict

class TunnelManager:
    def __init__(self, port: int = 5000):
        self.port = port
        self.process: Optional[subprocess.Popen] = None
        self.public_url: Optional[str] = None
        self.wifi_ip: str = self.detect_wifi_ip()
        self.root_dir = Path(__file__).resolve().parent.parent
        self.web_dir = Path(__file__).resolve().parent

    def detect_wifi_ip(self) -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def find_cloudflared(self) -> Optional[Path]:
        candidates = [
            self.root_dir / "cloudflared.exe",
            self.web_dir / "cloudflared.exe",
            Path.cwd() / "cloudflared.exe",
        ]
        for c in candidates:
            if c.is_file():
                return c

        if sys.platform == "win32":
            dest = self.root_dir / "cloudflared.exe"
            try:
                import urllib.request
                url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
                urllib.request.urlretrieve(url, dest)
                if dest.is_file():
                    return dest
            except Exception:
                pass

        return None

    def start_tunnel(self) -> Optional[str]:
        exe = self.find_cloudflared()
        if not exe:
            return None

        try:
            # Launch cloudflared quick tunnel
            cmd = [str(exe), "tunnel", "--url", f"http://127.0.0.1:{self.port}"]
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )

            # Monitor stderr for the generated trycloudflare.com URL
            start_time = time.time()
            while time.time() - start_time < 18:
                line = self.process.stderr.readline()
                if not line:
                    time.sleep(0.1)
                    continue
                match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
                if match:
                    self.public_url = match.group(0)
                    self._save_backend_url(self.public_url)
                    return self.public_url

            return None
        except Exception as e:
            print(f"[!] Tunnel startup notice: {e}")
            return None

    def _save_backend_url(self, url: str):
        payload = {
            "url": url,
            "wifi_url": f"http://{self.wifi_ip}:{self.port}",
            "updated_at": time.time()
        }
        for target_dir in (self.root_dir, self.web_dir):
            try:
                target_file = target_dir / "backend_url.json"
                target_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            except Exception:
                pass

    def stop(self):
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None

    def get_info(self) -> Dict[str, str]:
        return {
            "local_url": f"http://127.0.0.1:{self.port}",
            "wifi_url": f"http://{self.wifi_ip}:{self.port}",
            "public_url": self.public_url or "",
        }
