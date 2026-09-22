"""
Standalone Windows Executable Build Script for Facebook Comment Collector.
Uses PyInstaller to bundle all dependencies (Tkinter, Selenium, selenium-manager, openpyxl, etc.)
into an automated, ready-to-use desktop application for other users.
"""

import os
import sys
import shutil
import struct
import subprocess
from pathlib import Path


def generate_ico_file(ico_path: Path):
    """Generates a standard Windows 32x32 .ico icon file with Facebook Blue theme."""
    width, height = 32, 32
    # BMP format inside ICO:
    # BITMAPINFOHEADER is 40 bytes. Height in ICO BMP is 2 * height (height for image + height for AND mask)
    header_size = 40
    img_height = height * 2
    bpp = 32
    raw_pixel_size = width * height * 4
    mask_row_bytes = ((width + 31) // 32) * 4
    mask_size = mask_row_bytes * height
    image_data_size = header_size + raw_pixel_size + mask_size

    # Pixel data (BGRA): Rounded Facebook Blue rectangle with white letter/bubble
    pixels = bytearray()
    for y in range(height):
        for x in range(width):
            # Check corners for rounded rectangle
            dx = min(x, width - 1 - x)
            dy = min(y, height - 1 - y)
            is_corner = (dx < 4 and dy < 4 and ((3 - dx) ** 2 + (3 - dy) ** 2 > 9))
            
            if is_corner:
                pixels.extend([0, 0, 0, 0])  # Transparent
            else:
                # White 'C' or message shape inside
                # Draw speech bubble or 'f' accent
                in_bubble = (6 <= x <= 25 and 6 <= y <= 23)
                if in_bubble and (x in (6, 25) or y in (6, 23) or (11 <= x <= 20 and 13 <= y <= 15)):
                    # White icon elements
                    pixels.extend([255, 255, 255, 255])
                else:
                    # Facebook Blue: #1877F2 -> B=242, G=119, R=24
                    pixels.extend([242, 119, 24, 255])

    # AND mask (1 bit per pixel: 0 for opaque, 1 for transparent)
    and_mask = bytearray(mask_size)

    bmp_header = struct.pack(
        "<IiiHHIIiiII",
        header_size,
        width,
        img_height,
        1,       # color planes
        bpp,     # bits per pixel
        0,       # BI_RGB compression
        raw_pixel_size + mask_size,
        0, 0, 0, 0
    )

    ico_header = struct.pack("<HHH", 0, 1, 1)  # Reserved, Type 1 (ICO), Count 1
    ico_entry = struct.pack(
        "<BBBBHHII",
        width,
        height,
        0,       # Palette colors (0 = no palette)
        0,       # Reserved
        1,       # Color planes
        bpp,     # Bits per pixel
        image_data_size,
        6 + 16   # Offset to image data (header 6 bytes + entry 16 bytes = 22)
    )

    with open(ico_path, "wb") as f:
        f.write(ico_header)
        f.write(ico_entry)
        f.write(bmp_header)
        f.write(pixels)
        f.write(and_mask)


def build():
    project_root = Path(__file__).resolve().parent
    dist_dir = project_root / "dist"
    build_dir = project_root / "build"
    icon_path = project_root / "app_icon.ico"

    print("==========================================================")
    print("  Facebook Comment Collector • Windows Desktop Build")
    print("==========================================================")

    # 1. Generate icon if missing
    if not icon_path.exists():
        print("Generating application icon (app_icon.ico)...")
        generate_ico_file(icon_path)

    # 2. Assemble PyInstaller command
    pyinstaller_cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",                 # No black command prompt window
        "--name", "FacebookCommentCollector",
        f"--icon={str(icon_path)}",
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

    # 3. Create user distribution folder with README and helper folders
    app_dist_folder = dist_dir / "FacebookCommentCollector"
    if app_dist_folder.exists():
        (app_dist_folder / "output").mkdir(exist_ok=True)

        readme_text = """========================================================================
  FACEBOOK COMMENT COLLECTOR • COMMENT ABSORBER
========================================================================

How to Use:
1. Double-click "FacebookCommentCollector.exe" to launch.
2. If this is your first time, click "Log In to Facebook in Browser".
   Log in to your Facebook account in the browser window.
   Your session is securely saved on your computer.
3. Paste any Facebook post, reel, or video link into the URL field.
4. Click "COLLECT COMMENTS".
5. When complete, click "OPEN EXCEL" to open your spreadsheet!

Features:
- Collects real comments and replies from public posts, reels, and videos.
- Extracts exact real posting dates and times.
- Sorted Oldest -> Newest automatically.
- No Python or external setup needed!

Files and Outputs:
- Exported spreadsheets are saved in the "output" folder.
========================================================================
"""
        with open(app_dist_folder / "HOW_TO_USE.txt", "w", encoding="utf-8") as f:
            f.write(readme_text)

        # 4. Automatically compress into portable zip
        zip_output = dist_dir / "FacebookCommentCollector_Portable"
        print(f"\nCreating portable zip archive: {zip_output.with_suffix('.zip')}...")
        shutil.make_archive(str(zip_output), 'zip', str(app_dist_folder))

        print("\n==========================================================")
        print("  BUILD & PACKAGING COMPLETE!")
        print(f"  Folder:      {app_dist_folder}")
        print(f"  Executable:  {app_dist_folder / 'FacebookCommentCollector.exe'}")
        print(f"  Zip Archive: {zip_output.with_suffix('.zip')}")
        print("  You can share this zip file with ANY user!")
        print("==========================================================")


if __name__ == "__main__":
    build()
