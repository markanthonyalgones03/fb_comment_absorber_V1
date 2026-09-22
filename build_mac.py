"""
Standalone macOS Application Build Script for Facebook Comment Collector.
Uses PyInstaller to bundle all dependencies (Tkinter, Selenium, openpyxl, etc.)
into a native macOS .app application bundle.

Run on a Mac:
    python3 build_mac.py
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path


def build():
    if sys.platform != "darwin":
        print("Note: This script is intended to be run on macOS to create a native macOS .app bundle.")
        print(f"Current platform: {sys.platform}")

    project_root = Path(__file__).resolve().parent
    dist_dir = project_root / "dist"
    build_dir = project_root / "build"

    print("==========================================================")
    print("  Facebook Comment Collector • macOS App Build")
    print("==========================================================")

    pyinstaller_cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",                 # macOS .app bundle without terminal
        "--name", "FacebookCommentCollector",
        "--collect-all", "selenium",
        "--collect-all", "openpyxl",
        "--collect-all", "requests",
        "--collect-all", "dotenv",
        "--hidden-import", "app",
        "--hidden-import", "app.config",
        "--hidden-import", "app.gui",
        "--hidden-import", "app.models",
        "--hidden-import", "app.browser_collector",
        "--hidden-import", "app.comment_collector",
        "--hidden-import", "app.excel_exporter",
        "--hidden-import", "app.facebook_api",
        "--hidden-import", "app.utils",
        str(project_root / "run.py")
    ]

    print("\nRunning PyInstaller...")
    print("Command:", " ".join(pyinstaller_cmd))

    res = subprocess.run(pyinstaller_cmd, cwd=str(project_root))
    if res.returncode != 0:
        print("\n[ERROR] PyInstaller build failed with exit code:", res.returncode)
        sys.exit(res.returncode)

    print("\n==========================================================")
    print("  macOS BUILD COMPLETE!")
    print(f"  App Bundle: {dist_dir / 'FacebookCommentCollector.app'}")
    print("==========================================================")


if __name__ == "__main__":
    build()
