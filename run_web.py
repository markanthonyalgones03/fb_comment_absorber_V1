#!/usr/bin/env python
"""
Root launcher for Comment Absorber Web Studio.
Launches the Web Studio Flask server from root repository.
"""
import sys
from pathlib import Path

# Add project root and web directories to sys.path
root_dir = Path(__file__).resolve().parent
web_dir = root_dir / "web"
if str(web_dir) not in sys.path:
    sys.path.insert(0, str(web_dir))
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import run_web

if __name__ == "__main__":
    run_web.main()
