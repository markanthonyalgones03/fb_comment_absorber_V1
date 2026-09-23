"""
Tunnel and Network Manager for Comment Absorber Web Studio.
Manages local Wi-Fi detection and Cloudflare HTTP/2 Tunnel for rock-solid
worldwide access from any device (mobile data 4G/5G, foreign networks, or Wi-Fi).
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
        self.log_path = self.web_dir / "tunnel.log"
        self._stop_event = threading.Event()

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
            # Open tunnel log file to avoid pipe buffer deadlocks
            log_file = open(self.log_path, "w", encoding="utf-8")

            # Launch cloudflared quick tunnel using HTTP/2 protocol (stable on all mobile cellular networks)
            cmd = [
                str(exe), "tunnel",
                "--protocol", "http2",
                "--url", f"http://127.0.0.1:{self.port}"
            ]
            self.process = subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )

            # Monitor log file for the generated trycloudflare.com URL
            start_time = time.time()
            while time.time() - start_time < 20:
                time.sleep(0.8)
                if not self.log_path.exists():
                    continue
                try:
                    content = self.log_path.read_text(encoding="utf-8", errors="ignore")
                    match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", content)
                    if match:
                        self.public_url = match.group(0)
                        self._save_backend_url(self.public_url)
                        self._auto_push_github_async()
                        return self.public_url
                except Exception:
                    pass

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

    def _auto_push_github_async(self):
        """Asynchronously syncs backend_url.json to GitHub repository so GitHub Pages connects automatically."""
        def push_worker():
            try:
                time.sleep(2)
                git_cmd = r"C:\Program Files\Git\cmd\git.exe"
                if not os.path.exists(git_cmd):
                    git_cmd = "git"
                subprocess.run(
                    [git_cmd, "add", "backend_url.json", "web/backend_url.json"],
                    cwd=str(self.root_dir),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                subprocess.run(
                    [git_cmd, "commit", "-m", "update: sync active live mobile tunnel url"],
                    cwd=str(self.root_dir),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                subprocess.run(
                    [git_cmd, "push", "origin", "main"],
                    cwd=str(self.root_dir),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            except Exception:
                pass

        threading.Thread(target=push_worker, daemon=True).start()

    def stop(self):
        self._stop_event.set()
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
