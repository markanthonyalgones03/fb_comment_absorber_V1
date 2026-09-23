#!/usr/bin/env python
"""
Launcher for Comment Absorber Web Application
Starts the Flask server, enables local Wi-Fi & public mobile tunnels,
and provides instant access links for phones, tablets, and remote PCs.
"""

import os
import sys
import time
import atexit
import webbrowser
import threading
from pathlib import Path

# Configure utf-8 encoding safely for Windows console
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Add web directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tunnel_manager import TunnelManager

def open_browser(url: str):
    time.sleep(1.2)
    try:
        webbrowser.open(url)
    except Exception as e:
        pass

def main():
    port = int(os.environ.get("PORT", 5000))
    tm = TunnelManager(port=port)
    atexit.register(tm.stop)

    local_url = f"http://127.0.0.1:{port}"
    wifi_url = f"http://{tm.wifi_ip}:{port}"

    print("\n" + "=" * 70)
    print("   COMMENT ABSORBER STUDIO -- LIVE WEB & MOBILE ENGINE")
    print("   Real-Time Comment Streaming | Excel Exporter | Mobile Ready")
    print("=" * 70)
    print(f"  [+] Local PC Browser:      {local_url}")
    print(f"  [+] Mobile (Same Wi-Fi):   {wifi_url}")
    print("  [+] Public Web Link:       Generating secure HTTPS tunnel...")
    print("=" * 70)
    print("  [i] Access on Mobile Phone / Another Device:")
    print(f"      1. Connect your phone to Wi-Fi and open: {wifi_url}")
    print("      2. Or use the Worldwide Public Web link below once generated.")
    print("=" * 70 + "\n")

    # Start tunnel in background
    def run_tunnel():
        pub = tm.start_tunnel()
        if pub:
            print("\n" + "*" * 70)
            print("  WORLDWIDE PUBLIC LINK (Use on ANY phone, tablet, or PC):")
            print(f"  --> {pub}")
            print("*" * 70 + "\n")
            # Update app_web NETWORK_INFO
            try:
                import app_web
                app_web.NETWORK_INFO["public_url"] = pub
                app_web.NETWORK_INFO["wifi_url"] = wifi_url
            except Exception:
                pass
        else:
            print("  [i] Note: Using local network mode (Mobile link: " + wifi_url + ")")

    threading.Thread(target=run_tunnel, daemon=True).start()

    # Open local browser
    threading.Thread(target=open_browser, args=(local_url,), daemon=True).start()

    # Start Flask server
    from app_web import app, NETWORK_INFO
    NETWORK_INFO["local_url"] = local_url
    NETWORK_INFO["wifi_url"] = wifi_url

    app.run(host="0.0.0.0", port=port, threaded=True, debug=False)

if __name__ == "__main__":
    main()
