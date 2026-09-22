"""
Main application launcher for Facebook Comment Collector.
"""

import sys
import tkinter as tk
from app.gui import FacebookCommentCollectorApp


def main():
    root = tk.Tk()
    # High DPI awareness on Windows if available
    if sys.platform == "win32":
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    def report_callback_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            sys.exit(0)
        import traceback
        traceback.print_exception(exc_type, exc_value, exc_traceback)

    root.report_callback_exception = report_callback_exception

    app = FacebookCommentCollectorApp(root)
    try:
        root.mainloop()
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
