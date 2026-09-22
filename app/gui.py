"""
Modern Tkinter Desktop GUI for Facebook Comment Collector.
Features mandatory Facebook login gating, asynchronous background collection,
thread-safe queue updates, responsive cancellation, and seamless Excel exporting.
"""

import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from app.config import load_config, save_config, AppConfig, get_project_root
from app.models import CollectionStatus, CollectionProgress, CollectionResult
from app.facebook_api import FacebookApiClient
from app.comment_collector import CommentCollector
from app.browser_collector import BrowserCommentCollector
from app.excel_exporter import ExcelExporter
from app.utils import clean_facebook_url


class FacebookCommentCollectorApp:
    """
    Main Tkinter Desktop Application with mandatory Facebook Login gate
    and modern clean dashboard interface.
    """

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Facebook Comment Collector • Comment Absorber")
        self.root.geometry("720x820")
        self.root.minsize(660, 740)

        # Modern palette
        self.bg_color = "#F8FAFC"          # Slate 50
        self.card_bg = "#FFFFFF"           # Pure White
        self.border_color = "#E2E8F0"      # Slate 200
        self.primary_color = "#1877F2"     # Facebook Blue
        self.primary_hover = "#166FE5"
        self.cancel_color = "#EF4444"      # Red 500
        self.cancel_hover = "#DC2626"
        self.excel_color = "#107C41"       # Excel Forest Green
        self.excel_hover = "#0C5E31"
        self.neutral_color = "#334155"     # Slate 700
        self.neutral_hover = "#1E293B"

        self.root.configure(bg=self.bg_color)

        # Configuration and state
        self.config: AppConfig = load_config()
        self.collector: Optional[CommentCollector] = None
        self.browser_collector = BrowserCommentCollector()
        self.worker_thread: Optional[threading.Thread] = None
        self.update_queue: queue.Queue = queue.Queue()

        self.last_result: Optional[CollectionResult] = None
        self.last_excel_path: Optional[str] = None
        self.is_logged_in: bool = False
        self.is_running: bool = True

        # Build UI containers
        self._setup_styles()
        self._create_main_layout()

        self.root.protocol("WM_DELETE_WINDOW", self._on_window_close)
        self.root.after(100, self._process_queue)

        # Check initial login state in background
        self._check_initial_login_state()

    def _on_window_close(self):
        """Safely terminates background threads when window is closed."""
        self.is_running = False
        if self.collector and not self.collector.is_cancelled:
            self.collector.cancel()
        try:
            self.root.destroy()
        except Exception:
            pass

    def _setup_styles(self):
        """Initializes modern ttk styles."""
        self.style = ttk.Style()
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        self.style.configure("TFrame", background=self.bg_color)

        # Modern Button Styles
        self.style.configure(
            "Primary.TButton",
            font=("Segoe UI", 11, "bold"),
            background=self.primary_color,
            foreground="#FFFFFF",
            borderwidth=0,
            focuscolor="none",
            padding=(20, 12)
        )
        self.style.map("Primary.TButton",
            background=[("active", self.primary_hover), ("disabled", "#94A3B8")],
            foreground=[("disabled", "#E2E8F0")]
        )

        self.style.configure(
            "Cancel.TButton",
            font=("Segoe UI", 10, "bold"),
            background=self.cancel_color,
            foreground="#FFFFFF",
            borderwidth=0,
            focuscolor="none",
            padding=(14, 10)
        )
        self.style.map("Cancel.TButton",
            background=[("active", self.cancel_hover), ("disabled", "#FCA5A5")],
            foreground=[("disabled", "#FFFFFF")]
        )

        self.style.configure(
            "Excel.TButton",
            font=("Segoe UI", 10, "bold"),
            background=self.excel_color,
            foreground="#FFFFFF",
            borderwidth=0,
            focuscolor="none",
            padding=(14, 10)
        )
        self.style.map("Excel.TButton",
            background=[("active", self.excel_hover), ("disabled", "#86EFAC")],
            foreground=[("disabled", "#FFFFFF")]
        )

        self.style.configure(
            "Secondary.TButton",
            font=("Segoe UI", 10),
            background="#F1F5F9",
            foreground="#1E293B",
            borderwidth=1,
            focuscolor="none",
            padding=(12, 9)
        )
        self.style.map("Secondary.TButton",
            background=[("active", "#E2E8F0"), ("disabled", "#F8FAFC")],
            foreground=[("disabled", "#94A3B8")]
        )

        self.style.configure(
            "TProgressbar",
            thickness=10,
            troughcolor="#E2E8F0",
            background=self.primary_color
        )

    def _create_main_layout(self):
        """Creates the root layout holding the Login View and Dashboard View."""
        # Main container that fills the window
        self.main_container = tk.Frame(self.root, bg=self.bg_color)
        self.main_container.pack(fill="both", expand=True)

        # 1. Loading Screen (Initial verification)
        self.loading_view = tk.Frame(self.main_container, bg=self.bg_color)
        self.loading_label = tk.Label(
            self.loading_view,
            text="Checking Facebook connection...",
            font=("Segoe UI", 11),
            bg=self.bg_color,
            fg="#64748B"
        )
        self.loading_label.pack(expand=True)

        # 2. Login View (Shown when not authenticated)
        self.login_view = tk.Frame(self.main_container, bg=self.bg_color)
        self._build_login_view()

        # 3. Dashboard View (Shown when authenticated)
        self.dashboard_view = tk.Frame(self.main_container, bg=self.bg_color)
        self._build_dashboard_view()

        # Show loading initially
        self.loading_view.pack(fill="both", expand=True)

    def _build_login_view(self):
        """Constructs the modern, welcoming Facebook Login gate."""
        container = tk.Frame(self.login_view, bg=self.bg_color)
        container.pack(expand=True, fill="both", padx=40, pady=30)

        # Hero Card
        card = tk.Frame(
            container,
            bg=self.card_bg,
            bd=1,
            relief="solid",
            highlightbackground=self.border_color,
            highlightthickness=1
        )
        card.pack(expand=True, fill="both", padx=20, pady=20)

        # Top Accent Strip
        accent = tk.Frame(card, bg=self.primary_color, height=5)
        accent.pack(fill="x", side="top")

        content_frame = tk.Frame(card, bg=self.card_bg)
        content_frame.pack(expand=True, fill="both", padx=36, pady=30)

        # Logo / Icon Badge
        badge_circle = tk.Label(
            content_frame,
            text="🌐",
            font=("Segoe UI", 36),
            bg=self.card_bg
        )
        badge_circle.pack(pady=(10, 8))

        # Title & Subtitle
        title = tk.Label(
            content_frame,
            text="Facebook Comment Collector",
            font=("Segoe UI", 18, "bold"),
            bg=self.card_bg,
            fg="#0F172A"
        )
        title.pack(pady=(0, 4))

        subtitle = tk.Label(
            content_frame,
            text="Sign in to your Facebook account to unlock comment extraction.",
            font=("Segoe UI", 10),
            bg=self.card_bg,
            fg="#64748B"
        )
        subtitle.pack(pady=(0, 24))

        # Highlights Box
        hl_box = tk.Frame(content_frame, bg="#F8FAFC", bd=1, relief="solid", highlightbackground="#E2E8F0", highlightthickness=1)
        hl_box.pack(fill="x", padx=10, pady=(0, 24), ipady=12)

        items = [
            ("🔒", "100% Private & Secure", "Your login session is saved locally on your PC. Passwords are never seen or stored."),
            ("⚡", "Log In Once, Stay Logged In", "Automatic session persistence saves your session across app restarts."),
            ("📊", "Exact Real Dates & Times", "Pulls real timestamps and full comments sorted chronologically into Excel.")
        ]
        for icon, h, desc in items:
            row = tk.Frame(hl_box, bg="#F8FAFC")
            row.pack(fill="x", padx=16, pady=6)
            tk.Label(row, text=icon, font=("Segoe UI", 13), bg="#F8FAFC").pack(side="left", padx=(0, 10))
            text_col = tk.Frame(row, bg="#F8FAFC")
            text_col.pack(side="left", fill="x", expand=True)
            tk.Label(text_col, text=h, font=("Segoe UI", 9, "bold"), bg="#F8FAFC", fg="#1E293B").pack(anchor="w")
            tk.Label(text_col, text=desc, font=("Segoe UI", 8), bg="#F8FAFC", fg="#64748B", wraplength=420, justify="left").pack(anchor="w")

        # Action Button
        self.login_cta_btn = tk.Button(
            content_frame,
            text="🌐  Log In to Facebook in Browser",
            font=("Segoe UI", 11, "bold"),
            bg=self.primary_color,
            fg="#FFFFFF",
            activebackground=self.primary_hover,
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            padx=28,
            pady=12,
            cursor="hand2",
            command=self._start_browser_login
        )
        self.login_cta_btn.pack(pady=(4, 12))

        # Status indicator on Login screen
        self.login_status_lbl = tk.Label(
            content_frame,
            text="Ready. Click the button above to log in.",
            font=("Segoe UI", 9),
            bg=self.card_bg,
            fg="#64748B"
        )
        self.login_status_lbl.pack(pady=(0, 8))

    def _build_dashboard_view(self):
        """Constructs the clean, modern Comment Collector Dashboard."""
        # 1. Header Bar
        header = tk.Frame(self.dashboard_view, bg="#0F172A", height=64)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        header_content = tk.Frame(header, bg="#0F172A")
        header_content.pack(fill="both", expand=True, padx=20, pady=10)

        # Title & Subtitle Left
        title_box = tk.Frame(header_content, bg="#0F172A")
        title_box.pack(side="left")

        app_title = tk.Label(
            title_box,
            text="Facebook Comment Collector",
            font=("Segoe UI", 13, "bold"),
            bg="#0F172A",
            fg="#FFFFFF"
        )
        app_title.pack(anchor="w")

        app_sub = tk.Label(
            title_box,
            text="Comment Absorber • Single Post & Reel Downloader",
            font=("Segoe UI", 8),
            bg="#0F172A",
            fg="#94A3B8"
        )
        app_sub.pack(anchor="w")

        # Top Right Controls: Status Pill & Logout Button
        right_box = tk.Frame(header_content, bg="#0F172A")
        right_box.pack(side="right")

        # Green Logged In Chip
        self.auth_badge = tk.Label(
            right_box,
            text="● Logged In to Facebook",
            font=("Segoe UI", 8, "bold"),
            bg="#14532D",
            fg="#86EFAC",
            padx=10,
            pady=3
        )
        self.auth_badge.pack(side="left", padx=(0, 10))

        # Switch Account / Logout Button
        self.logout_btn = tk.Button(
            right_box,
            text="Log Out",
            font=("Segoe UI", 8),
            bg="#1E293B",
            fg="#E2E8F0",
            activebackground="#334155",
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            padx=10,
            pady=3,
            cursor="hand2",
            command=self._handle_logout
        )
        self.logout_btn.pack(side="left", padx=(0, 6))

        # Settings gear button
        settings_btn = tk.Button(
            right_box,
            text="⚙ Settings",
            font=("Segoe UI", 8),
            bg="#1E293B",
            fg="#94A3B8",
            activebackground="#334155",
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            padx=8,
            pady=3,
            cursor="hand2",
            command=self._open_settings_dialog
        )
        settings_btn.pack(side="left")

        # Dashboard Scrollable Body
        body = tk.Frame(self.dashboard_view, bg=self.bg_color)
        body.pack(fill="both", expand=True, padx=24, pady=16)

        # ---------------- Card 1: URL Input ----------------
        input_card = tk.Frame(body, bg=self.card_bg, bd=1, relief="solid", highlightbackground=self.border_color, highlightthickness=1)
        input_card.pack(fill="x", pady=(0, 14), ipady=6)

        url_title = tk.Label(
            input_card,
            text="Facebook Post or Reel URL",
            font=("Segoe UI", 10, "bold"),
            bg=self.card_bg,
            fg="#1E293B"
        )
        url_title.pack(anchor="w", padx=16, pady=(10, 4))

        # URL Entry + Paste Row
        entry_row = tk.Frame(input_card, bg=self.card_bg)
        entry_row.pack(fill="x", padx=16, pady=(0, 6))

        self.url_var = tk.StringVar()
        self.url_entry = tk.Entry(
            entry_row,
            textvariable=self.url_var,
            font=("Segoe UI", 10),
            bg="#F8FAFC",
            fg="#0F172A",
            relief="solid",
            bd=1,
            highlightthickness=1,
            highlightbackground="#CBD5E1",
            highlightcolor="#1877F2"
        )
        self.url_entry.pack(side="left", fill="x", expand=True, ipady=7, padx=(0, 8))
        self.url_entry.bind("<Return>", lambda event: self._on_collect_clicked())

        paste_btn = tk.Button(
            entry_row,
            text="Paste",
            font=("Segoe UI", 9, "bold"),
            bg="#E2E8F0",
            fg="#1E293B",
            activebackground="#CBD5E1",
            relief="flat",
            bd=0,
            padx=14,
            pady=6,
            cursor="hand2",
            command=self._paste_from_clipboard
        )
        paste_btn.pack(side="right")

        url_hint = tk.Label(
            input_card,
            text="Supports public posts, reels, videos, and photos (e.g. facebook.com/share/r/..., /posts/..., /reel/...)",
            font=("Segoe UI", 8),
            bg=self.card_bg,
            fg="#64748B"
        )
        url_hint.pack(anchor="w", padx=16, pady=(0, 12))

        # Action Buttons Area: COLLECT & CANCEL
        action_row = tk.Frame(input_card, bg=self.card_bg)
        action_row.pack(fill="x", padx=16, pady=(0, 12))

        self.collect_btn = ttk.Button(
            action_row,
            text="COLLECT COMMENTS",
            style="Primary.TButton",
            cursor="hand2",
            command=self._on_collect_clicked
        )
        self.collect_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.cancel_btn = ttk.Button(
            action_row,
            text="CANCEL",
            style="Cancel.TButton",
            cursor="hand2",
            state="disabled",
            command=self._on_cancel_clicked
        )
        self.cancel_btn.pack(side="right")

        # ---------------- Card 2: Live Progress & Status ----------------
        status_card = tk.Frame(body, bg=self.card_bg, bd=1, relief="solid", highlightbackground=self.border_color, highlightthickness=1)
        status_card.pack(fill="x", pady=(0, 14), ipady=10)

        # Status & Counter Row
        stats_row = tk.Frame(status_card, bg=self.card_bg)
        stats_row.pack(fill="x", padx=20, pady=(10, 6))

        # Left: Status indicator
        status_left = tk.Frame(stats_row, bg=self.card_bg)
        status_left.pack(side="left")

        tk.Label(status_left, text="Status", font=("Segoe UI", 8, "bold"), bg=self.card_bg, fg="#94A3B8").pack(anchor="w")
        self.status_val_label = tk.Label(
            status_left,
            text="Ready",
            font=("Segoe UI", 12, "bold"),
            bg=self.card_bg,
            fg="#1877F2"
        )
        self.status_val_label.pack(anchor="w")

        # Right: Big Live Counter
        counter_right = tk.Frame(stats_row, bg=self.card_bg)
        counter_right.pack(side="right")

        tk.Label(counter_right, text="Comments Collected", font=("Segoe UI", 8, "bold"), bg=self.card_bg, fg="#94A3B8").pack(anchor="e")
        self.counter_val_label = tk.Label(
            counter_right,
            text="0",
            font=("Segoe UI", 16, "bold"),
            bg=self.card_bg,
            fg="#0F172A"
        )
        self.counter_val_label.pack(anchor="e")

        # Progress Bar
        self.progressbar = ttk.Progressbar(status_card, mode="indeterminate", style="TProgressbar")
        self.progressbar.pack(fill="x", padx=20, pady=(6, 8))

        # Detail Message Label
        self.message_label = tk.Label(
            status_card,
            text="",
            font=("Segoe UI", 9),
            bg=self.card_bg,
            fg="#475569",
            wraplength=600,
            justify="left"
        )
        self.message_label.pack(anchor="w", padx=20, pady=(0, 4))

        # Sorting Chip
        self.sorting_val_label = tk.Label(
            status_card,
            text="",
            font=("Segoe UI", 8, "italic"),
            bg=self.card_bg,
            fg="#059669"
        )
        self.sorting_val_label.pack(anchor="w", padx=20, pady=(0, 4))

        # ---------------- Card 3: Excel Export Actions ----------------
        self.export_card = tk.Frame(body, bg=self.card_bg, bd=1, relief="solid", highlightbackground=self.border_color, highlightthickness=1)
        self.export_card.pack(fill="x", pady=(0, 10), ipady=10)

        export_header = tk.Frame(self.export_card, bg=self.card_bg)
        export_header.pack(fill="x", padx=20, pady=(10, 4))

        tk.Label(
            export_header,
            text="Excel Spreadsheet",
            font=("Segoe UI", 10, "bold"),
            bg=self.card_bg,
            fg="#1E293B"
        ).pack(side="left")

        self.file_path_label = tk.Label(
            self.export_card,
            text="No comments exported yet.",
            font=("Segoe UI", 9),
            bg=self.card_bg,
            fg="#64748B",
            anchor="w"
        )
        self.file_path_label.pack(anchor="w", padx=20, pady=(0, 10))

        # 4 Action Buttons Row
        action_btn_row = tk.Frame(self.export_card, bg=self.card_bg)
        action_btn_row.pack(fill="x", padx=20, pady=(0, 8))

        self.open_excel_btn = ttk.Button(
            action_btn_row,
            text="OPEN EXCEL",
            style="Excel.TButton",
            cursor="hand2",
            state="disabled",
            command=self._open_excel_file
        )
        self.open_excel_btn.pack(side="left", padx=(0, 6))

        self.save_as_btn = ttk.Button(
            action_btn_row,
            text="SAVE AS...",
            style="Secondary.TButton",
            cursor="hand2",
            state="disabled",
            command=self._save_excel_as
        )
        self.save_as_btn.pack(side="left", padx=(0, 6))

        self.open_folder_btn = ttk.Button(
            action_btn_row,
            text="OPEN FOLDER",
            style="Secondary.TButton",
            cursor="hand2",
            command=self._open_output_folder
        )
        self.open_folder_btn.pack(side="left", padx=(0, 6))

        self.reset_btn = ttk.Button(
            action_btn_row,
            text="COLLECT ANOTHER POST",
            style="Secondary.TButton",
            cursor="hand2",
            command=self._reset_for_another_post
        )
        self.reset_btn.pack(side="right")

    # ---------------- View Switching Logic ----------------

    def _check_initial_login_state(self):
        """Checks if the user has an existing login session on launch."""
        def task():
            logged = self.browser_collector.is_logged_in()
            self.is_logged_in = logged
            def update():
                self.loading_view.pack_forget()
                if logged:
                    self._show_dashboard()
                else:
                    self._show_login()
            self.root.after(0, update)

        threading.Thread(target=task, daemon=True).start()

    def _show_login(self):
        """Transitions UI to Login View."""
        self.dashboard_view.pack_forget()
        self.login_view.pack(fill="both", expand=True)
        self.login_cta_btn.config(state="normal")
        self.login_status_lbl.config(text="Ready. Click the button above to log in.", fg="#64748B")

    def _show_dashboard(self):
        """Transitions UI to Dashboard View."""
        self.login_view.pack_forget()
        self.dashboard_view.pack(fill="both", expand=True)
        self.url_entry.focus_set()

    def _start_browser_login(self):
        """Launches the visible Chrome window to log in to Facebook."""
        self.login_cta_btn.config(state="disabled")
        self.login_status_lbl.config(
            text="Browser window opened. Please log in to Facebook in that window...",
            fg="#1877F2"
        )

        def worker():
            success = self.browser_collector.open_login_window()
            def on_done():
                self.login_cta_btn.config(state="normal")
                if success:
                    self.is_logged_in = True
                    self.login_status_lbl.config(text="Login successful! Unlocking collector...", fg="#107C41")
                    self.root.after(800, self._show_dashboard)
                else:
                    self.login_status_lbl.config(
                        text="Login was not completed. Click the button to try again.",
                        fg="#EF4444"
                    )
            self.root.after(0, on_done)

        threading.Thread(target=worker, daemon=True).start()

    def _handle_logout(self):
        """Logs out from Facebook session and returns to login gate."""
        if not messagebox.askyesno(
            "Log Out of Facebook",
            "Are you sure you want to log out of your Facebook session in this app?\n\n"
            "You will need to log in again to collect comments."
        ):
            return

        def worker():
            self.browser_collector.clear_login_session()
            self.is_logged_in = False
            self.root.after(0, self._show_login)

        threading.Thread(target=worker, daemon=True).start()

    # ---------------- Comment Collection Logic ----------------

    def _paste_from_clipboard(self):
        """Pastes clipboard text into the URL entry field."""
        try:
            clipboard_text = self.root.clipboard_get().strip()
            self.url_var.set(clipboard_text)
            self.url_entry.icursor(tk.END)
        except Exception:
            pass

    def _on_collect_clicked(self):
        """Triggered when user clicks COLLECT COMMENTS."""
        raw_url = self.url_var.get().strip()
        if not raw_url:
            messagebox.showwarning("URL Required", "Please enter or paste a Facebook post URL.")
            self.url_entry.focus_set()
            return

        # Double check login before starting collection
        if not self.is_logged_in:
            messagebox.showinfo("Login Required", "Please log in to Facebook before collecting comments.")
            self._show_login()
            return

        try:
            self.collector = CommentCollector(
                browser_collector=self.browser_collector,
                exporter=ExcelExporter(output_dir=self.config.output_dir),
                progress_callback=self._queue_progress_update
            )

            # Reset state & UI
            self.last_result = None
            self.last_excel_path = None
            self.file_path_label.config(text="Collecting comments...", fg="#64748B")
            self.open_excel_btn.config(state="disabled")
            self.save_as_btn.config(state="disabled")
            self.sorting_val_label.config(text="")
            self.message_label.config(text="", fg="#334155")
            self.status_val_label.config(text="Starting...", fg="#1877F2")
            self.counter_val_label.config(text="0")
            self.progressbar.start(10)

            # Disable Collect button, Enable Cancel button
            self.collect_btn.config(state="disabled")
            self.cancel_btn.config(state="normal")

            self.worker_thread = threading.Thread(
                target=self._run_collection_worker,
                args=(raw_url,),
                daemon=True
            )
            self.worker_thread.start()
        except Exception as exc:
            self.progressbar.stop()
            self.status_val_label.config(text="Error", fg="#DC2626")
            self.message_label.config(text=str(exc), fg="#DC2626")
            self.collect_btn.config(state="normal")
            self.cancel_btn.config(state="disabled")
            messagebox.showerror("Error", str(exc))

    def _run_collection_worker(self, post_url: str):
        """Worker thread entrypoint for asynchronous comment collection."""
        try:
            result = self.collector.collect(post_url=post_url)
            self.update_queue.put(("RESULT", result))
        except Exception as exc:
            self.update_queue.put(("UNCAUGHT_ERROR", str(exc)))

    def _queue_progress_update(self, progress: CollectionProgress):
        """Thread-safe callback to enqueue progress reports."""
        self.update_queue.put(("PROGRESS", progress))

    def _on_cancel_clicked(self):
        """Triggered when user clicks CANCEL."""
        if self.collector and not self.collector.is_cancelled:
            self.cancel_btn.config(state="disabled")
            self.status_val_label.config(text="Cancelling...", fg="#DC2626")
            self.message_label.config(text="Stopping scraper. Exporting already collected comments...", fg="#DC2626")
            self.collector.cancel()

    def _process_queue(self):
        """Processes enqueued GUI updates on the main Tkinter thread."""
        try:
            while not self.update_queue.empty():
                msg_type, payload = self.update_queue.get_nowait()
                if msg_type == "PROGRESS":
                    self._handle_progress_update(payload)
                elif msg_type == "RESULT":
                    self.progressbar.stop()
                    self._handle_collection_result(payload)
                elif msg_type == "UNCAUGHT_ERROR":
                    self.progressbar.stop()
                    self._handle_collection_result(
                        CollectionResult(
                            success=False,
                            status=CollectionStatus.ERROR,
                            message=f"An unexpected error occurred: {payload}"
                        )
                    )
        except Exception:
            pass
        finally:
            if self.is_running:
                self.root.after(100, self._process_queue)

    def _handle_progress_update(self, p: CollectionProgress):
        """Updates GUI widgets based on progress events."""
        self.counter_val_label.config(text=f"{p.count:,}")

        if p.status == CollectionStatus.CONNECTING:
            self.status_val_label.config(text="Connecting...", fg="#1877F2")
        elif p.status == CollectionStatus.ACCESSING:
            self.status_val_label.config(text="Accessing Post...", fg="#1877F2")
        elif p.status == CollectionStatus.COLLECTING:
            self.status_val_label.config(text="Collecting...", fg="#1877F2")
        elif p.status == CollectionStatus.SORTING:
            self.status_val_label.config(text="Sorting...", fg="#059669")
            self.sorting_val_label.config(text="Sorting comments: Oldest → Newest...")
        elif p.status == CollectionStatus.CREATING_EXCEL:
            self.status_val_label.config(text="Writing Excel...", fg="#107C41")
        elif p.status == CollectionStatus.CANCELLED:
            self.status_val_label.config(text="Cancelled", fg="#DC2626")
            self.message_label.config(text=p.message, fg="#DC2626")
        elif p.status == CollectionStatus.ERROR:
            self.status_val_label.config(text="Error", fg="#DC2626")
            self.status_val_label.config(fg="#DC2626")
            self.message_label.config(text=p.message, fg="#DC2626")

        if p.message and p.status not in (CollectionStatus.ERROR, CollectionStatus.CANCELLED):
            self.message_label.config(text=p.message, fg="#334155")

    def _handle_collection_result(self, res: CollectionResult):
        """Finalizes UI state after collection completes, is cancelled, or errors."""
        self.last_result = res
        self.collect_btn.config(state="normal")
        self.cancel_btn.config(state="disabled")

        if res.file_path:
            self.last_excel_path = res.file_path
            filename = Path(res.file_path).name
            self.file_path_label.config(text=f"📁 File: {filename}", fg="#0F172A")
            self.open_excel_btn.config(state="normal")
            self.save_as_btn.config(state="normal")

        if res.success:
            if res.is_cancelled:
                self.status_val_label.config(text="Cancelled", fg="#DC2626")
                self.counter_val_label.config(text=f"{res.total_collected:,}")
                self.message_label.config(text=res.message, fg="#DC2626")
            else:
                self.status_val_label.config(text="Completed", fg="#107C41")
                self.counter_val_label.config(text=f"{res.total_collected:,}")
                if res.post_author:
                    self.sorting_val_label.config(text=f"Author: {res.post_author} • Sorted: Oldest → Newest")
                else:
                    self.sorting_val_label.config(text="Sorted: Oldest → Newest")
                self.message_label.config(text=res.message, fg="#107C41")
        else:
            self.status_val_label.config(text="Error", fg="#DC2626")
            self.message_label.config(text=res.message, fg="#DC2626")
            messagebox.showerror("Comment Collection Error", res.message)

    def _open_excel_file(self):
        """Opens the exported Excel file with Windows default application."""
        if not self.last_excel_path or not os.path.exists(self.last_excel_path):
            messagebox.showwarning("File Not Found", "No Excel file exists to open.")
            return

        try:
            if sys.platform == "win32":
                os.startfile(self.last_excel_path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", self.last_excel_path])
            else:
                subprocess.Popen(["xdg-open", self.last_excel_path])
        except Exception as exc:
            messagebox.showerror("Error Opening File", f"Could not open file: {exc}")

    def _save_excel_as(self):
        """Allows user to copy/save the generated Excel file to a custom destination."""
        if not self.last_excel_path or not os.path.exists(self.last_excel_path):
            messagebox.showwarning("File Not Found", "No Excel file exists to save.")
            return

        source = Path(self.last_excel_path)
        dest_str = filedialog.asksaveasfilename(
            title="Save Comments Excel File",
            initialdir=str(source.parent),
            initialfile=source.name,
            defaultextension=".xlsx",
            filetypes=[("Excel Workbook (*.xlsx)", "*.xlsx")]
        )
        if dest_str:
            try:
                dest = Path(dest_str)
                if dest.resolve() == source.resolve():
                    messagebox.showinfo(
                        "File Already Saved",
                        f"The Excel file is already saved at this location:\n{dest_str}"
                    )
                    return
                import shutil
                shutil.copy2(source, dest_str)
                messagebox.showinfo("File Saved", f"Excel file successfully saved to:\n{dest_str}")
            except PermissionError:
                messagebox.showerror(
                    "File Locked by Excel",
                    f"Could not save to:\n{dest_str}\n\n"
                    "The destination file is currently open in Microsoft Excel or another program.\n\n"
                    "Please close Excel and try again, or choose a different file name."
                )
            except Exception as exc:
                messagebox.showerror("Error Saving File", f"Could not save file: {exc}")

    def _open_output_folder(self):
        """Opens the output directory in Windows File Explorer."""
        folder = str(self.config.output_dir)
        if not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as exc:
            messagebox.showerror("Error Opening Folder", f"Could not open folder: {exc}")

    def _reset_for_another_post(self):
        """Clears the current state to allow collecting from another post."""
        self.url_var.set("")
        self.status_val_label.config(text="Ready", fg="#1877F2")
        self.counter_val_label.config(text="0")
        self.sorting_val_label.config(text="")
        self.message_label.config(text="")
        self.file_path_label.config(text="No comments exported yet.", fg="#64748B")
        self.open_excel_btn.config(state="disabled")
        self.save_as_btn.config(state="disabled")
        self.url_entry.focus_set()

    def _open_settings_dialog(self):
        """Opens modal dialog for advanced Meta Graph API settings."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Settings • Meta Graph API")
        dialog.geometry("520x440")
        dialog.minsize(480, 400)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=self.bg_color)

        container = tk.Frame(dialog, bg=self.bg_color)
        container.pack(fill="both", expand=True, padx=24, pady=20)

        title = tk.Label(
            container,
            text="Meta Graph API Configuration (Optional)",
            font=("Segoe UI", 12, "bold"),
            bg=self.bg_color,
            fg="#1E293B"
        )
        title.pack(anchor="w", pady=(0, 4))

        desc = tk.Label(
            container,
            text="By default, the app uses the built-in Real Comments Extractor (no token needed).\n"
                 "If you manage an official Facebook Page, you can optionally configure your Meta Access Token here.",
            font=("Segoe UI", 8),
            bg=self.bg_color,
            fg="#64748B",
            justify="left",
            wraplength=460
        )
        desc.pack(anchor="w", pady=(0, 16))

        tk.Label(container, text="Meta Page Access Token:", font=("Segoe UI", 9, "bold"), bg=self.bg_color, fg="#1E293B").pack(anchor="w")
        token_var = tk.StringVar(value=self.config.access_token or "")
        token_entry = tk.Entry(container, textvariable=token_var, font=("Segoe UI", 9), show="•", relief="solid", bd=1)
        token_entry.pack(fill="x", ipady=4, pady=(2, 10))

        tk.Label(container, text="Meta App ID:", font=("Segoe UI", 9, "bold"), bg=self.bg_color, fg="#1E293B").pack(anchor="w")
        app_id_var = tk.StringVar(value=self.config.app_id or "")
        app_id_entry = tk.Entry(container, textvariable=app_id_var, font=("Segoe UI", 9), relief="solid", bd=1)
        app_id_entry.pack(fill="x", ipady=4, pady=(2, 10))

        tk.Label(container, text="Meta App Secret:", font=("Segoe UI", 9, "bold"), bg=self.bg_color, fg="#1E293B").pack(anchor="w")
        secret_var = tk.StringVar(value=self.config.app_secret or "")
        secret_entry = tk.Entry(container, textvariable=secret_var, font=("Segoe UI", 9), show="•", relief="solid", bd=1)
        secret_entry.pack(fill="x", ipady=4, pady=(2, 16))

        def save_and_close():
            tok = token_var.get().strip() or None
            aid = app_id_var.get().strip() or None
            sec = secret_var.get().strip() or None
            self.config = save_config(access_token=tok, app_id=aid, app_secret=sec)
            messagebox.showinfo("Settings Saved", "Configuration updated successfully!")
            dialog.destroy()

        btn_box = tk.Frame(container, bg=self.bg_color)
        btn_box.pack(fill="x", side="bottom", pady=(10, 0))

        save_btn = tk.Button(
            btn_box,
            text="Save Settings",
            font=("Segoe UI", 10, "bold"),
            bg=self.primary_color,
            fg="#FFFFFF",
            relief="flat",
            padx=16,
            pady=6,
            cursor="hand2",
            command=save_and_close
        )
        save_btn.pack(side="right", padx=(8, 0))

        cancel_d_btn = tk.Button(
            btn_box,
            text="Cancel",
            font=("Segoe UI", 10),
            bg="#E2E8F0",
            fg="#1E293B",
            relief="flat",
            padx=14,
            pady=6,
            cursor="hand2",
            command=dialog.destroy
        )
        cancel_d_btn.pack(side="right")
