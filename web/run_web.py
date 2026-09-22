#!/usr/bin/env python
"""
Launcher for Comment Absorber Web Application
Starts the Flask server and opens the web application in your default browser.
"""

import os
import sys
import time
import webbrowser
import threading

def open_browser(url: str):
    time.sleep(1.2)
    try:
        webbrowser.open(url)
    except Exception as e:
        print(f"Note: Could not automatically open browser ({e}). Please open {url} manually.")

def main():
    port = int(os.environ.get("PORT", 5000))
    url = f"http://127.0.0.1:{port}"
    
    print("=" * 65)
    print("   COMMENT ABSORBER STUDIO - WEB APPLICATION")
    print("   Fast & Lightweight Real-Time Comment Streaming")
    print("=" * 65)
    print(f"\n[+] Server launching on: {url}")
    print("[+] Opening web browser automatically...\n")
    print("[!] Press Ctrl+C in this console anytime to stop the server.\n")

    # Open browser in a detached thread
    threading.Thread(target=open_browser, args=(url,), daemon=True).start()

    from app_web import app
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False)

if __name__ == "__main__":
    main()
