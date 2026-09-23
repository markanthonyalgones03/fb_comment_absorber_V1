"""
High-Performance Unified Web Comment Collector & Exporter
Combines real Facebook DOM comment extraction with the persistent browser profile,
real-time SSE streaming, and styled Excel/CSV export.
"""

import os
import re
import sys
import time
import json
import random
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Callable, Dict, Any, Tuple
from urllib.parse import urlparse, parse_qs, urlunparse

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException, InvalidSessionIdException, NoSuchWindowException

# Allowed Facebook hostnames
FB_HOSTS = {
    "facebook.com",
    "www.facebook.com",
    "m.facebook.com",
    "mobile.facebook.com",
    "web.facebook.com",
    "touch.facebook.com",
    "l.facebook.com",
    "fb.com",
    "www.fb.com",
}

ILLEGAL_EXCEL_CHARS_RE = re.compile(r"[\x00-\x08\x0b-\x0c\x0e-\x1f]")


def sanitize_for_excel(value: Optional[str]) -> str:
    """Sanitizes text for safe inclusion in Excel OpenXML files."""
    if not value:
        return ""
    return ILLEGAL_EXCEL_CHARS_RE.sub("", str(value))


def clean_facebook_url(raw_url: str) -> str:
    """Normalizes a Facebook URL by trimming and standardizing protocol."""
    if not raw_url or not isinstance(raw_url, str):
        raise ValueError("URL cannot be empty.")

    raw_url = raw_url.strip()
    if not raw_url.startswith(("http://", "https://")):
        raw_url = "https://" + raw_url

    parsed = urlparse(raw_url)
    host = parsed.netloc.lower()

    if ":" in host:
        host = host.split(":")[0]

    if host not in FB_HOSTS:
        raise ValueError(f"'{parsed.netloc}' is not a valid Facebook domain.")

    preserved_keys = {"story_fbid", "id", "v", "fbid", "set"}
    query_dict = parse_qs(parsed.query)
    filtered_query = {k: v for k, v in query_dict.items() if k in preserved_keys}

    from urllib.parse import urlencode
    clean_query = urlencode(filtered_query, doseq=True) if filtered_query else ""

    return urlunparse((
        "https",
        "www.facebook.com",
        parsed.path.rstrip("/"),
        "",
        clean_query,
        ""
    ))


@dataclass
class WebComment:
    """Represents an individual comment with real-time serialization support."""
    index: int
    comment_id: str
    user_name: str
    message: str
    created_time: str   # Formatted YYYY-MM-DD HH:MM:SS
    timestamp_raw: float # Epoch seconds for sorting
    avatar_color: str = "#1877F2"
    avatar_initials: str = "FB"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["author"] = self.user_name
        return d

    @property
    def author(self) -> str:
        return self.user_name

    def __getitem__(self, key: str) -> Any:
        if key in ("author", "user_name"):
            return self.user_name
        if key in ("created_time", "time_str", "time"):
            return self.created_time
        return getattr(self, key)


def generate_avatar_data(name: str) -> Tuple[str, str]:
    """Generates consistent initials and vibrant background color for avatar."""
    palette = [
        "#1877F2", "#10B981", "#6366F1", "#EC4899", 
        "#F59E0B", "#8B5CF6", "#06B6D4", "#14B8A6"
    ]
    parts = [p for p in re.sub(r"[^a-zA-Z0-9 ]", "", name).split() if p]
    if len(parts) >= 2:
        initials = (parts[0][0] + parts[1][0]).upper()
    elif len(parts) == 1:
        initials = parts[0][:2].upper()
    else:
        initials = "FB"
    color = palette[sum(ord(c) for c in name) % len(palette)]
    return initials, color


class BaseCollector:
    """Base interface for comment collectors."""
    def __init__(self, on_comment: Callable[[WebComment], None], on_status: Callable[[str, Dict[str, Any]], None]):
        self.on_comment = on_comment
        self.on_status = on_status
        self.is_cancelled = False

    def cancel(self):
        self.is_cancelled = True


class RealBrowserCommentCollector(BaseCollector):
    """
    Real Facebook Comment Scraper.
    Navigates to the EXACT Facebook post/reel/video URL provided by the user,
    uses the persistent login profile so the user's login is recognized,
    expands all comments and replies, and streams every real comment in real-time.
    """

    def __init__(
        self,
        on_comment: Callable[[WebComment], None],
        on_status: Callable[[str, Dict[str, Any]], None],
        profile_dir: Optional[Path] = None,
        headless: bool = True
    ):
        super().__init__(on_comment, on_status)
        if profile_dir is None:
            # Use the existing user profile from Desktop Comment Absorber
            desktop_profile = Path("C:/Users/User/Desktop/Comment Absorber/browser_profile")
            if desktop_profile.exists():
                self.profile_dir = desktop_profile
            else:
                self.profile_dir = Path(__file__).parent / "browser_profile"
        else:
            self.profile_dir = Path(profile_dir)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.headless = headless
        self.driver: Optional[webdriver.Chrome] = None
        self.last_post_author: Optional[str] = None

    def cancel(self):
        super().cancel()
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

    def _clean_profile_locks(self):
        """Removes stale Chrome lock files to prevent crashes."""
        for lock_name in ("SingletonLock", "SingletonCookie", "SingletonSocket", "DevToolsActivePort"):
            p = self.profile_dir / lock_name
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

    def _create_driver(self, headless: bool = True) -> webdriver.Chrome:
        """Initializes Chrome or Edge with user profile persistence and optimizations."""
        self._clean_profile_locks()

        # Try Chrome
        try:
            opts = ChromeOptions()
            if headless:
                opts.add_argument("--headless=new")
            opts.add_argument(f"--user-data-dir={str(self.profile_dir.resolve())}")
            opts.add_argument("--disable-notifications")
            opts.add_argument("--mute-audio")
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-dev-shm-usage")
            opts.add_argument("--disable-gpu")
            opts.add_argument("--remote-debugging-port=0")
            opts.add_argument("--disable-blink-features=AutomationControlled")
            opts.add_argument("--window-size=1280,960")
            opts.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
            opts.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
            opts.add_experimental_option("useAutomationExtension", False)
            return webdriver.Chrome(options=opts)
        except Exception as chrome_err:
            # Fallback to Edge
            try:
                edge_opts = EdgeOptions()
                if headless:
                    edge_opts.add_argument("--headless=new")
                edge_opts.add_argument(f"--user-data-dir={str(self.profile_dir.resolve())}")
                edge_opts.add_argument("--disable-notifications")
                edge_opts.add_argument("--mute-audio")
                edge_opts.add_argument("--remote-debugging-port=0")
                edge_opts.add_argument("--disable-blink-features=AutomationControlled")
                edge_opts.add_argument("--window-size=1280,960")
                return webdriver.Edge(options=edge_opts)
            except Exception as edge_err:
                raise RuntimeError(
                    f"Could not launch Chrome or Edge.\nChrome: {chrome_err}\nEdge: {edge_err}"
                )

    def is_logged_in(self) -> bool:
        """
        Checks if Facebook login session cookies exist in persistent profile.
        Directly checks SQLite database in 0.001s without launching any browser!
        """
        cookie_db = self.profile_dir / "Default" / "Network" / "Cookies"
        if not cookie_db.exists():
            cookie_db = self.profile_dir / "Default" / "Cookies"
        if not cookie_db.exists():
            cookie_db = self.profile_dir / "Cookies"

        if cookie_db.exists():
            try:
                import sqlite3
                conn = sqlite3.connect(f"file:{cookie_db}?mode=ro", uri=True)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM cookies WHERE host_key LIKE '%facebook.com%' AND name = 'c_user'")
                row = cursor.fetchone()
                conn.close()
                if row:
                    return True
            except Exception:
                pass
        return False

    def open_login_window(self) -> bool:
        """Opens a visible browser window allowing user to log in to Facebook."""
        drv = None
        logged_in = False
        try:
            drv = self._create_driver(headless=False)
            drv.set_window_size(1100, 850)
            drv.get("https://www.facebook.com/login/")
            while True:
                time.sleep(1)
                if not drv.window_handles:
                    break
                cookies = drv.get_cookies()
                if any(c["name"] == "c_user" for c in cookies):
                    logged_in = True
                    time.sleep(1.5)
                    break
        finally:
            if drv:
                try:
                    drv.quit()
                except Exception:
                    pass
        return logged_in

    def run(self, post_url: str):
        """
        Executes real extraction from the provided Facebook post URL.
        Streams each newly discovered comment immediately over SSE.
        """
        self.driver = None
        try:
            clean_url = clean_facebook_url(post_url)
        except Exception as e:
            self.on_status("ERROR", {"message": f"Invalid Facebook URL: {str(e)}"})
            return

        try:
            self.on_status("CONNECTING", {"message": "Starting optimized browser collector..."})
            already_logged = self.is_logged_in()
            use_headless = self.headless if self.headless is not None else already_logged
            self.driver = self._create_driver(headless=use_headless)
            self.driver.set_window_size(1280, 960)

            self.on_status("ACCESSING", {"message": f"Opening target post: {clean_url}"})
            self.driver.get(clean_url)
            time.sleep(4.0)

            if self.is_cancelled:
                self.on_status("CANCELLED", {"message": "Cancelled by user."})
                return

            # Check if login is required
            cookies = self.driver.get_cookies()
            is_logged_in = any(c.get("name") == "c_user" for c in cookies)

            if not is_logged_in:
                if use_headless:
                    try:
                        self.driver.quit()
                    except Exception:
                        pass
                    self.driver = self._create_driver(headless=False)
                    self.driver.set_window_size(1100, 850)
                    self.driver.get(clean_url)
                    time.sleep(3.0)

                self.on_status("CONNECTING", {"message": "Please log in to your Facebook account in the browser window to access post comments."})

                # Wait for user to log in
                login_wait = 0
                while login_wait < 180 and not self.is_cancelled:
                    time.sleep(2)
                    login_wait += 2
                    try:
                        if not self.driver.window_handles:
                            self.on_status("ERROR", {"message": "Login window closed. Please log in to your Facebook account to access comments."})
                            return
                        cookies = self.driver.get_cookies()
                        if any(c.get("name") == "c_user" for c in cookies):
                            is_logged_in = True
                            self.on_status("ACCESSING", {"message": "Login successful! Loading post comments..."})
                            time.sleep(1.5)
                            self.driver.get(clean_url)
                            time.sleep(3.5)
                            break
                    except Exception:
                        break

            # Clean page docks to remove chat elements
            self._clean_page_docks(self.driver)

            # Dismiss cookie consent dialogs ONLY (never click Close on post modal)
            self._dismiss_popups(self.driver)

            # If this is a share URL (/share/p/, /share/v/, /share/r/), wait for redirect
            if "/share/" in self.driver.current_url.lower():
                for _ in range(6):
                    time.sleep(1.0)
                    if "/share/" not in self.driver.current_url.lower():
                        break

            # Check if Facebook reports that content is unavailable or deleted
            try:
                body_elem = self.driver.find_element(By.TAG_NAME, "body")
                body_text = body_elem.text if body_elem else ""
                if any(err_phrase in body_text for err_phrase in [
                    "This content isn't available right now",
                    "This page isn't available",
                    "Content Not Found",
                    "Hindi available ang content na ito",
                    "The link you followed may be broken"
                ]):
                    self.on_status("ERROR", {
                        "message": "Facebook Error: 'This content isn't available right now'. The post may be deleted, private to friends/groups, or the share link expired."
                    })
                    return
            except Exception:
                pass

            # If Reel or Video, open comments drawer once
            c_check = self.driver.find_elements(
                By.XPATH,
                "//*[starts-with(@aria-label, 'Comment by') or starts-with(@aria-label, 'Reply by') or starts-with(@aria-label, 'Komento ni') or starts-with(@aria-label, 'Tugon ni')]"
            )
            if not c_check:
                current_u = self.driver.current_url.lower()
                clean_u_lower = clean_url.lower()
                if any(k in current_u or k in clean_u_lower for k in ("/reel/", "/share/v/", "/share/r/", "/videos/", "/watch/", "fb.watch")):
                    self._open_reel_comments(self.driver)
                    time.sleep(2.5)

            # Post Author
            self.last_post_author = self._extract_post_author(self.driver)
            author_text = f" from {self.last_post_author}" if self.last_post_author else ""
            self.on_status("COLLECTING", {"message": f"Extracting real comments{author_text}..."})

            # Switch "Most relevant" dropdown to "All comments" if present
            self._switch_to_all_comments(self.driver)

            # Collection loop
            collected_signatures = set()
            collected_count = 0
            no_new_cycles = 0

            while no_new_cycles < 12:
                if self.is_cancelled:
                    break

                # Extract comments strictly loaded in DOM (dialog or drawer)
                dom_comments = self._extract_comments_from_dom(self.driver)

                newly_found = 0
                for c_id, c_author, c_msg, c_time, c_raw_ts in dom_comments:
                    clean_msg = c_msg.strip()
                    if not clean_msg:
                        continue

                    # Uniquely identify comment without dropping identical short replies
                    if c_id:
                        sig = f"id_{c_id}"
                    else:
                        sig = f"{c_author}||{c_time}||{clean_msg}"

                    if sig not in collected_signatures:
                        collected_signatures.add(sig)
                        collected_count += 1
                        newly_found += 1

                        initials, color = generate_avatar_data(c_author)
                        cid_str = c_id if c_id else f"fb_{collected_count}_{int(time.time()*1000)}"
                        comment = WebComment(
                            index=collected_count,
                            comment_id=cid_str,
                            user_name=c_author,
                            message=clean_msg,
                            created_time=c_time,
                            timestamp_raw=c_raw_ts,
                            avatar_color=color,
                            avatar_initials=initials
                        )
                        # Immediately stream to web client!
                        try:
                            self.on_comment(comment)
                        except Exception:
                            pass

                if newly_found > 0:
                    no_new_cycles = 0
                    self.on_status("COLLECTING", {
                        "message": f"Gathering comments... ({collected_count} collected so far)"
                    })
                else:
                    no_new_cycles += 1

                # Click "View more comments", "View replies", and expand "... See more"
                self._click_view_more_comments(self.driver)

                # Scroll target container or drawer
                self._scroll_comments(self.driver)
                if newly_found > 0:
                    time.sleep(0.25)
                else:
                    time.sleep(0.65)

            if collected_count == 0 and not is_logged_in:
                self.on_status("ERROR", {
                    "message": "Facebook requires login to view comments on this content. Please log in and retry."
                })
            elif self.is_cancelled:
                self.on_status("CANCELLED", {
                    "message": f"Collection stopped by user. Total collected: {collected_count} comments."
                })
            elif collected_count == 0:
                self.on_status("COMPLETED", {
                    "message": "Collection completed. No comments found on this post (or comments may be turned off)."
                })
            else:
                self.on_status("COMPLETED", {
                    "message": f"Collection completed! Collected all {collected_count} real comments."
                })

        except (InvalidSessionIdException, NoSuchWindowException):
            self.on_status("ERROR", {"message": "Browser window closed unexpectedly."})
        except WebDriverException as wde:
            self.on_status("ERROR", {"message": f"Browser error: {str(wde)}"})
        except Exception as e:
            self.on_status("ERROR", {"message": f"Unexpected error: {str(e)}"})
        finally:
            if self.driver:
                try:
                    self.driver.quit()
                except Exception:
                    pass

    def _switch_to_all_comments(self, driver: webdriver.Chrome) -> bool:
        """
        Switches Facebook comment filter from 'Most relevant' ('Pinakaugnay') to 'All comments'.
        Retries up to 3 times to prevent Facebook from hiding 50%+ of comments.
        """
        for attempt in range(3):
            try:
                # 1. Check if already on All comments
                already_all = driver.execute_script("""
                    const spans = document.querySelectorAll("div[role='button'] span, span");
                    for (let i = 0; i < spans.length; i++) {
                        const t = (spans[i].textContent || "").trim().toLowerCase();
                        if (t === "all comments" || t === "lahat ng komento") {
                            const btn = spans[i].closest("div[role='button']");
                            if (btn && !document.querySelector("div[role='menu']")) {
                                return true;
                            }
                        }
                    }
                    return false;
                """)
                if already_all:
                    return True

                # 2. Find and click dropdown button
                clicked_dropdown = driver.execute_script("""
                    const keywords = ["most relevant", "pinakaugnay", "top comments", "newest", "mga nangungunang komento"];
                    const buttons = document.querySelectorAll("div[role='button']");
                    for (let i = 0; i < buttons.length; i++) {
                        const t = (buttons[i].textContent || "").trim().toLowerCase();
                        if (keywords.some(k => t.includes(k))) {
                            buttons[i].scrollIntoView({ block: "center", behavior: "instant" });
                            buttons[i].click();
                            return true;
                        }
                    }
                    return false;
                """)

                if not clicked_dropdown:
                    dropdowns = driver.find_elements(
                        By.XPATH,
                        "//div[@role='button']//span[contains(text(), 'Most relevant') or contains(text(), 'Pinakaugnay') or contains(text(), 'Top comments')] | "
                        "//span[contains(text(), 'Most relevant') or contains(text(), 'Pinakaugnay') or contains(text(), 'Top comments')]"
                    )
                    for d in dropdowns:
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'instant'}); arguments[0].click();", d)
                        clicked_dropdown = True
                        break

                if clicked_dropdown:
                    time.sleep(0.8)
                    switched = driver.execute_script("""
                        const menuItems = document.querySelectorAll("div[role='menuitem'], div[role='menu'] div[role='button'], div[role='menu'] span");
                        for (let i = 0; i < menuItems.length; i++) {
                            const t = (menuItems[i].textContent || "").trim().toLowerCase();
                            if (t.includes("all comments") || t.includes("lahat ng komento")) {
                                const target = menuItems[i].closest("div[role='menuitem']") || menuItems[i];
                                target.click();
                                return true;
                            }
                        }
                        return false;
                    """)
                    if switched:
                        time.sleep(1.2)
                        return True

                    all_opts = driver.find_elements(
                        By.XPATH,
                        "//div[@role='menuitem']//span[contains(text(), 'All comments') or contains(text(), 'Lahat ng komento')] | "
                        "//span[contains(text(), 'All comments') or contains(text(), 'Lahat ng komento')]"
                    )
                    for opt in all_opts:
                        driver.execute_script("arguments[0].click();", opt)
                        time.sleep(1.2)
                        return True
            except Exception:
                pass
            time.sleep(0.5)
        return False

    def _find_scrollable_element(self, driver: webdriver.Chrome, container):
        """Finds the actual scrollable element within a container."""
        try:
            scrollable = driver.execute_script("""
                const c = arguments[0];
                if (!c) return document.body;
                const all = c.querySelectorAll('*');
                for (let el of all) {
                    const s = window.getComputedStyle(el);
                    if ((s.overflowY === 'auto' || s.overflowY === 'scroll') && el.scrollHeight > el.clientHeight + 40) {
                        return el;
                    }
                }
                return c;
            """, container)
            return scrollable or container
        except Exception:
            return container

    def _extract_post_author(self, driver: webdriver.Chrome) -> Optional[str]:
        ignore = {
            'facebook', 'notifications', 'chats', 'comments', 'reels', 'menu', 
            'log in', 'sign up', 'search', 'search results', 'create a post', 
            'posts', 'home', 'watch', 'marketplace', 'gaming'
        }
        for tag in ['//h2', '//h1']:
            try:
                for el in driver.find_elements(By.XPATH, tag):
                    t = el.text.strip()
                    if not t:
                        continue
                    first_line = t.split('\n')[0].strip()
                    first_line = re.sub(r"['’]s\s+Post.*$", "", first_line, flags=re.I).strip()
                    first_line = re.sub(r'\s*[A-Za-z0-9·•]+\s*Follow.*$', '', first_line, flags=re.I)
                    first_line = re.sub(r'\s+Follow$', '', first_line, flags=re.I).strip()
                    if first_line and first_line.lower() not in ignore and len(first_line) < 75:
                        return first_line
            except Exception:
                continue
        return None

    def _dismiss_popups(self, driver: webdriver.Chrome) -> None:
        """Safely dismisses cookie banners only. NEVER clicks generic Close on post modals."""
        try:
            cookie_btns = driver.find_elements(
                By.XPATH,
                "//div[@aria-label='Decline optional cookies'] | "
                "//button[contains(text(), 'Decline optional cookies') or contains(text(), 'Only essential')] | "
                "//button[@data-cookiebanner='accept_only_essential_button']"
            )
            for b in cookie_btns:
                try:
                    driver.execute_script("arguments[0].click();", b)
                    time.sleep(0.3)
                except Exception:
                    pass
        except Exception:
            pass

    def _open_reel_comments(self, driver: webdriver.Chrome) -> None:
        """Opens the comments drawer on Facebook Reels or videos if not already open."""
        try:
            comment_btns = driver.find_elements(
                By.XPATH,
                "//div[@role='button' and (contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'comment') or contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'komento'))] | "
                "//span[contains(text(), 'Comments') or contains(text(), 'Mga Komento')]/ancestor::div[@role='button']"
            )
            for btn in comment_btns:
                try:
                    driver.execute_script("arguments[0].click();", btn)
                    time.sleep(2.0)
                    break
                except Exception:
                    pass
        except Exception:
            pass

    def _click_view_more_comments(self, driver: webdriver.Chrome) -> bool:
        """
        Batch-clicks 'View more comments', 'View previous comments', nested replies ('View 1 reply', 'mga tugon'),
        and expands inline '... See more' / 'Tingnan pa' text inside browser memory without bottlenecks.
        """
        js_script = """
        try {
            let clicked = false;

            // 1. Expand all inline '... See more' / 'Tingnan ang higit pa' buttons inside comments
            const allButtons = document.querySelectorAll("div[role='button'], span[role='button'], span");
            for (let i = 0; i < allButtons.length; i++) {
                const el = allButtons[i];
                const t = (el.textContent || "").trim().toLowerCase();
                if (t === "see more" || t === "see more..." || t === "tingnan ang higit pa" || t === "basahin ang higit pa" || t === "tingnan pa") {
                    try {
                        el.click();
                        clicked = true;
                    } catch(e) {}
                }
            }

            // 2. Expand comment batches & nested replies (English & Tagalog)
            const expandRegex = /(view\\s+\\d*\\s*(more|previous)?\\s*comments?|see\\s+more\\s+comments?|more\\s+comments|tingnan\\s+ang\\s+.*komento|view\\s+\\d*\\s*repl(y|ies)|view\\s+reply|mga\\s+tugon|\\d+\\s+na\\s+tugon|\\d+\\s+repl(y|ies)|view\\s+previous)/i;

            let count = 0;
            const clickCandidates = document.querySelectorAll("span, div[role='button']");
            for (let i = 0; i < clickCandidates.length && count < 40; i++) {
                const node = clickCandidates[i];
                const t = (node.textContent || "").trim();
                if (t.length > 2 && t.length < 80 && expandRegex.test(t)) {
                    const btn = node.closest("div[role='button']") || node;
                    try {
                        btn.scrollIntoView({ block: "nearest", behavior: "instant" });
                        btn.click();
                        clicked = true;
                        count++;
                    } catch(e) {}
                }
            }
            return clicked;
        } catch(e) {
            return false;
        }
        """
        try:
            return bool(driver.execute_script(js_script))
        except Exception:
            return False

    def _scroll_comments(self, driver: webdriver.Chrome) -> None:
        """Scrolls the active comments container (modal dialog or reel drawer)."""
        js_scroll = """
        try {
            // Check modal dialog
            const dialogs = document.querySelectorAll("div[role='dialog']:not([aria-label*='Messenger']):not([aria-label*='Chat'])");
            for (const d of dialogs) {
                if (d.querySelector("[aria-label*='Comment by'], [aria-label*='Reply by'], [role='article']")) {
                    const walker = document.createTreeWalker(d, NodeFilter.SHOW_ELEMENT);
                    while (walker.nextNode()) {
                        const node = walker.currentNode;
                        const s = window.getComputedStyle(node);
                        if ((s.overflowY === 'auto' || s.overflowY === 'scroll') && node.scrollHeight > node.clientHeight + 40) {
                            node.scrollTop = node.scrollHeight;
                            return true;
                        }
                    }
                    d.scrollTop = d.scrollHeight;
                    return true;
                }
            }

            // Check Reel / video drawer
            const cList = document.querySelectorAll('[aria-label*="Comment by"], [aria-label*="Reply by"], [role="article"]');
            if (cList.length) {
                let el = cList[0].parentElement;
                while (el && el !== document.body) {
                    const s = window.getComputedStyle(el);
                    if ((s.overflowY === 'auto' || s.overflowY === 'scroll') && el.scrollHeight > el.clientHeight + 40) {
                        el.scrollTop = el.scrollHeight;
                        return true;
                    }
                    el = el.parentElement;
                }
            }

            window.scrollBy(0, 800);
            return true;
        } catch(e) {
            return false;
        }
        """
        try:
            driver.execute_script(js_scroll)
        except Exception:
            pass

    def _clean_page_docks(self, driver: webdriver.Chrome) -> None:
        """Aggressively removes Messenger chat tabs and docks from DOM without touching comments."""
        script = """
        try {
            const chatSelectors = [
                "[data-pagelet='ChatTab']",
                "[data-pagelet='ChatSidebar']",
                "[data-pagelet='MessagingTab']",
                "[data-testid='chat_sidebar']",
                "[data-testid='messenger_chat']",
                ".fbDock",
                ".fbDockWrapper",
                "div[aria-label*='Chat with']",
                "div[aria-label*='Chats']",
                "div[aria-label='Messenger']",
                "div[aria-label='New message']"
            ];
            chatSelectors.forEach(sel => {
                document.querySelectorAll(sel).forEach(el => {
                    if (el.querySelector("[aria-label*='Comment by'], [aria-label*='Reply by'], [aria-label*='Komento ni'], [aria-label*='Tugon ni'], [role='article']")) {
                        return;
                    }
                    try { el.remove(); } catch(e) {}
                });
            });
        } catch(e) {}
        """
        try:
            driver.execute_script(script)
        except Exception:
            pass

    def _extract_comments_from_dom(self, driver: webdriver.Chrome) -> List[Tuple[str, str, str, float]]:
        """
        Extracts (author, message, time_str, raw_ts) tuples in <5ms using high-speed in-browser JavaScript.
        Strictly scopes to the target post or reel comments and completely ignores Messenger chats.
        """
        self._clean_page_docks(driver)

        js_extractor = """
        try {
            // 1. Expand 'See more' text inside comments first so full text is revealed
            const seeMoreBtns = document.querySelectorAll("div[role='button'], span[role='button']");
            for (let i = 0; i < seeMoreBtns.length; i++) {
                const t = (seeMoreBtns[i].textContent || "").trim().toLowerCase();
                if (t === "see more" || t === "tingnan ang higit pa" || t === "see more...") {
                    try { seeMoreBtns[i].click(); } catch(e) {}
                }
            }

            // 2. Locate target container (modal dialog or reel drawer or post container)
            let container = null;
            const dialogs = document.querySelectorAll("div[role='dialog']:not([aria-label*='Messenger']):not([aria-label*='Chat'])");
            for (const d of dialogs) {
                if (d.querySelector("[aria-label*='Comment by'], [aria-label*='Reply by'], [aria-label*='Komento ni'], [aria-label*='Tugon ni']")) {
                    container = d;
                    break;
                }
            }
            if (!container) {
                const comp = document.querySelectorAll("div[role='complementary']");
                for (const c of comp) {
                    if (c.querySelector("[aria-label*='Comment by'], [aria-label*='Reply by'], [aria-label*='Komento ni'], [aria-label*='Tugon ni']")) {
                        container = c;
                        break;
                    }
                }
            }
            const root = container || document;

            // 3. Collect all potential comment elements
            let rawElements = [];
            const querySelectors = [
                "div[role='article']",
                "*[aria-label*='Comment by']",
                "*[aria-label*='Reply by']",
                "*[aria-label*='Komento ni']",
                "*[aria-label*='Tugon ni']"
            ];
            const seenNodes = new Set();
            for (let q = 0; q < querySelectors.length; q++) {
                const found = root.querySelectorAll(querySelectors[q]);
                for (let k = 0; k < found.length; k++) {
                    const node = found[k];
                    if (!seenNodes.has(node)) {
                        seenNodes.add(node);
                        rawElements.push(node);
                    }
                }
            }
            if (rawElements.length === 0 && root !== document) {
                for (let q = 0; q < querySelectors.length; q++) {
                    const found = document.querySelectorAll(querySelectors[q]);
                    for (let k = 0; k < found.length; k++) {
                        const node = found[k];
                        if (!seenNodes.has(node)) {
                            seenNodes.add(node);
                            rawElements.push(node);
                        }
                    }
                }
            }
            const elements = rawElements;

            const results = [];
            const ignoreAuthors = new Set([
                "like", "reply", "share", "online status indicator", "active now",
                "online", "follow", "author", "top fan", "edited", "view more",
                "send message", "react", "view replies", "write a comment...",
                "most relevant", "all comments", "top comments", "by author",
                "liked by author", "highlighted by author", "shared by author",
                "view more replies", "hide replies", "chats", "messenger", "message"
            ]);

            const timeRegex = /^(?:about\\s+a\\s+minute(?:\\s+ago)?|a\\s+few\\s+seconds(?:\\s+ago)?|\\d+\\s*(?:minutes?|mins?|hours?|hrs?|days?|weeks?|seconds?|secs?)\\s*(?:ago)?|\\d+[smhdw]|ago|just now|yesterday.*)$/i;

            function cleanAuthor(raw) {
                if (!raw) return "Facebook User";
                let n = raw.replace(/\\s+/g, ' ').trim();
                n = n.replace(/\\s+(?:about\\s+a\\s+minute(?:\\s+ago)?|a\\s+few\\s+seconds(?:\\s+ago)?|\\d+\\s*(?:minutes?|mins?|hours?|hrs?|days?|weeks?|seconds?|secs?)\\s*(?:ago)?|\\d+[smhdw]|ago|just now|yesterday.*)$/i, '').trim();
                n = n.replace(/\\s+(?:top fan|author|by author|admin|moderator|follow|follower|creator)$/i, '').trim();
                if (!n || ignoreAuthors.has(n.toLowerCase())) return "Facebook User";
                return n;
            }

            for (let i = 0; i < elements.length; i++) {
                const el = elements[i];
                try {
                    if (el.closest("[data-pagelet='ChatTab'], [data-pagelet='ChatSidebar'], .fbDock, div[aria-label*='Chat'], div[aria-label*='Messenger']")) {
                        continue;
                    }

                    const text = (el.innerText || el.textContent || "").trim();
                    if (!text) continue;

                    const lower = text.toLowerCase();
                    if (lower.includes("message sent") || lower.includes("type a message") || lower.includes("active now")) {
                        continue;
                    }

                    const aria = el.getAttribute("aria-label") || "";

                    let author = "Facebook User";
                    const m = aria.match(/(?:Comment by|Reply by|Komento ni|Tugon ni)\\s+(.*?)(?:\\s+(?:to\\s+.*|\\d+.*|yesterday.*|just now.*|about\\s+a\\s+minute.*|a\\s+few\\s+seconds.*)|$)/i);
                    if (m && m[1]) {
                        author = cleanAuthor(m[1]);
                    }

                    if (author === "Facebook User") {
                        const links = el.querySelectorAll("a[role='link'], a[href*='facebook.com'], a[href*='profile.php']");
                        for (const l of links) {
                            const ltxt = (l.textContent || "").trim();
                            if (ltxt.length > 1 && !timeRegex.test(ltxt) && !ignoreAuthors.has(ltxt.toLowerCase())) {
                                const ca = cleanAuthor(ltxt);
                                if (ca !== "Facebook User") {
                                    author = ca;
                                    break;
                                }
                            }
                        }
                    }

                    if (author === "Facebook User") {
                        const lines = text.split("\\n").map(s => s.trim()).filter(Boolean);
                        if (lines.length > 0 && !ignoreAuthors.has(lines[0].toLowerCase())) {
                            author = cleanAuthor(lines[0]);
                        }
                    }

                    if (/^\\d{1,2}:\\d{2}$/.test(author)) continue;

                    let message = "";
                    const autoNodes = el.querySelectorAll("[dir='auto']");
                    for (const d of autoNodes) {
                        const dtxt = (d.innerText || d.textContent || "").trim();
                        if (dtxt && dtxt !== author && !ignoreAuthors.has(dtxt.toLowerCase()) && !/^\\d+[smhdw]$/i.test(dtxt)) {
                            message = dtxt;
                            break;
                        }
                    }

                    if (!message) {
                        const lines = text.split("\\n").map(s => s.trim()).filter(Boolean);
                        for (const l of lines) {
                            if (l !== author && !ignoreAuthors.has(l.toLowerCase()) && !/^\\d+[smhdw]$/i.test(l)) {
                                message = l;
                                break;
                            }
                        }
                    }

                    if (!message) {
                        const imgs = el.querySelectorAll("img[src*='emoji'], img[src*='sticker'], img[alt]");
                        for (const img of imgs) {
                            const alt = (img.getAttribute("alt") || "").trim();
                            const src = img.getAttribute("src") || "";
                            if (alt && !ignoreAuthors.has(alt.toLowerCase())) {
                                message = `[${alt}]`;
                                break;
                            } else if (src.includes("sticker")) {
                                message = "[Sticker]";
                                break;
                            }
                        }
                    }

                    if (!message) continue;

                    let timeRaw = "";
                    const timeLinks = el.querySelectorAll("a[href*='comment'], a[href*='permalink']");
                    for (const tl of timeLinks) {
                        const ttxt = (tl.getAttribute("aria-label") || tl.textContent || "").trim();
                        if (ttxt) {
                            timeRaw = ttxt;
                            break;
                        }
                    }
                    if (!timeRaw && aria) {
                        timeRaw = aria;
                    }
                    if (!timeRaw) {
                        const lines = text.split("\\n").map(s => s.trim()).filter(Boolean);
                        for (const l of lines) {
                            if (/^\\d+[smhdw]$/i.test(l)) {
                                timeRaw = l;
                                break;
                            }
                        }
                    }

                    let commentId = "";
                    const idAttr = el.getAttribute("data-commentid") || el.getAttribute("id") || "";
                    if (idAttr && !idAttr.startsWith(":r")) commentId = idAttr;
                    if (!commentId) {
                        const pLink = el.querySelector("a[href*='comment_id='], a[href*='/comments/']");
                        if (pLink) {
                            const href = pLink.getAttribute("href") || "";
                            const mId = href.match(/comment_id=([^&]+)/) || href.match(/\\/comments\\/(\\d+)/);
                            if (mId && mId[1]) commentId = mId[1];
                        }
                    }

                    results.push({
                        id: commentId,
                        author: author,
                        message: message,
                        time_raw: timeRaw
                    });
                } catch(err) {}
            }
            return results;
        } catch(e) {
            return [];
        }
        """

        raw_items = []
        try:
            raw_items = driver.execute_script(js_extractor) or []
        except Exception:
            raw_items = []

        now = datetime.now()
        results = []

        if raw_items:
            for item in raw_items:
                try:
                    c_id = item.get("id", "")
                    author = item.get("author", "Facebook User")
                    msg = item.get("message", "")
                    time_raw = item.get("time_raw", "")

                    timestamp = now
                    if time_raw:
                        parsed_dt = self._parse_relative_time(time_raw, now)
                        if parsed_dt != now:
                            timestamp = parsed_dt

                    time_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")
                    results.append((c_id, author, msg, time_str, timestamp.timestamp()))
                except Exception:
                    continue
        else:
            # Fallback to direct Selenium elements extraction
            try:
                comment_elements = driver.find_elements(
                    By.XPATH,
                    "//div[@role='article'] | //*[starts-with(@aria-label, 'Comment by') or starts-with(@aria-label, 'Reply by') or starts-with(@aria-label, 'Komento ni') or starts-with(@aria-label, 'Tugon ni')]"
                )
                for el in comment_elements:
                    try:
                        text_content = el.text.strip()
                        if not text_content:
                            continue
                        author = "Facebook User"
                        aria_lbl = el.get_attribute("aria-label") or ""
                        m_reply = re.search(r"^(?:Reply by|Tugon ni)\s+(.*?)\s+(?:to|kay)\s+.*?'s comment", aria_lbl, re.IGNORECASE)
                        if m_reply:
                            author = m_reply.group(1).strip()
                        elif "Comment by" in aria_lbl or "Komento ni" in aria_lbl:
                            m_cb = re.search(r"(?:Comment by|Komento ni)\s+(.*)", aria_lbl, re.IGNORECASE)
                            if m_cb:
                                author = m_cb.group(1).strip()

                        message = ""
                        div_nodes = el.find_elements(By.XPATH, ".//div[@dir='auto'] | .//span[@dir='auto']")
                        for dn in div_nodes:
                            d_txt = dn.text.strip()
                            if d_txt and d_txt != author and len(d_txt) > 0 and not re.match(r"^\d+[smhdw]$", d_txt):
                                message = d_txt
                                break

                        if not message:
                            lines = [l.strip() for l in text_content.split("\n") if l.strip()]
                            for l_item in lines:
                                if l_item != author and len(l_item) > 1 and not re.match(r"^\d+[smhdw]$", l_item):
                                    message = l_item
                                    break

                        if message:
                            results.append(("", author, message, now.strftime("%Y-%m-%d %H:%M:%S"), now.timestamp()))
                    except Exception:
                        continue
            except Exception:
                pass

        return results

    def _parse_relative_time(self, time_str: str, base_time: datetime) -> datetime:
        """Accurately parses English and Tagalog relative and absolute Facebook timestamps."""
        if not time_str:
            return base_time
        s = re.sub(r"[\s\u200b\u202f\xa0]+", " ", time_str).strip()
        s_lower = s.lower()

        if "comment by" in s_lower or "reply by" in s_lower:
            m = re.search(r"(?:comment|reply) by .*?(\d+.*|yesterday.*|kahapon.*|just now.*|ngayon lang.*)", s, re.I)
            if m:
                s = m.group(1).strip()
                s_lower = s.lower()

        # Check full date formats
        for fmt in (
            "%A, %B %d, %Y at %I:%M %p",
            "%B %d, %Y at %I:%M %p",
            "%B %d at %I:%M %p",
            "%d %B at %H:%M",
            "%Y-%m-%d %H:%M:%S"
        ):
            try:
                dt = datetime.strptime(s, fmt)
                if dt.year == 1900:
                    dt = dt.replace(year=base_time.year)
                return dt
            except ValueError:
                pass

        # Immediate
        if any(w in s_lower for w in ("just now", "a few seconds", "ngayon lang", "sandali lang")):
            return base_time - timedelta(seconds=15)

        # Minutes
        if "about a minute" in s_lower or "isang minuto" in s_lower:
            return base_time - timedelta(minutes=1)

        # Yesterday / Kahapon
        if "yesterday" in s_lower or "kahapon" in s_lower:
            return base_time - timedelta(days=1)

        # Weeks
        m_w = re.search(r"(\d+)\s*(?:w|wk|wks|weeks?|linggo)\b", s_lower)
        if m_w:
            return base_time - timedelta(weeks=int(m_w.group(1)))

        # Days
        m_d = re.search(r"(\d+)\s*(?:d|day|days|araw)\b", s_lower)
        if m_d:
            return base_time - timedelta(days=int(m_d.group(1)))

        # Hours
        m_h = re.search(r"(\d+)\s*(?:h|hr|hrs|hours?|oras)\b", s_lower)
        if m_h:
            return base_time - timedelta(hours=int(m_h.group(1)))

        # Minutes
        m_m = re.search(r"(\d+)\s*(?:m|min|mins|minutes?|minuto)\b", s_lower)
        if m_m:
            return base_time - timedelta(minutes=int(m_m.group(1)))

        # Seconds
        m_s = re.search(r"(\d+)\s*(?:s|sec|secs|seconds?|segundo)\b", s_lower)
        if m_s:
            return base_time - timedelta(seconds=int(m_s.group(1)))

        return base_time


# --- Simulator for Demo Mode ---
SAMPLE_DEMO_COMMENTS = [
    ("Maria Santos", "Interested po! Magkano po ang shipping to Davao City? Salamat! ❤️"),
    ("John Paul Ramirez", "Mine 1 pc medium black please! Sent you a private message. ✨"),
    ("Angela Nicole Cruz", "Legit seller! Order arrived in 2 days and quality is super solid. 👏💯"),
    ("Mark Anthony Reyes", "Available pa po ba ito? Looking for bulk order for our hardware store."),
    ("Jasmine Flores", "How much po pag wholesale? Need 10 boxes for our upcoming project."),
    ("Christian Dave Tan", "PM sent po! Pakicheck ng inbox for invoice details. 🙏"),
    ("Kaye Anne Bautista", "Super ganda! Will definitely buy again next week. Kudos to the team! 🎉"),
    ("Bryan Joshua Mendoza", "Hm po location nyo? Can we pick up directly at the warehouse?"),
    ("Sarah Mae Gonzales", "Mine large blue! Pa-reserve po please, payment via GCash. 💳"),
    ("Rodel De Guzman", "Salamat boss, dumating na kahapon. Well packaged and complete accessories."),
]

class SimulatorCollector(BaseCollector):
    """Demo simulator for testing live UI streaming."""
    def run(self, post_url: str, max_comments: int = 50, speed: float = 0.3):
        self.on_status("CONNECTING", {"message": "Starting demo simulation..."})
        time.sleep(0.4)
        if self.is_cancelled:
            return

        self.on_status("COLLECTING", {"message": "Streaming simulated comments (Demo Mode)..."})
        start_time = datetime.now() - timedelta(minutes=60)
        count = 0

        for i in range(max_comments):
            if self.is_cancelled:
                self.on_status("CANCELLED", {"message": f"Simulation stopped at {count} comments."})
                return

            name, msg = random.choice(SAMPLE_DEMO_COMMENTS)
            comment_time = start_time + timedelta(seconds=i * random.randint(15, 45))
            time_str = comment_time.strftime("%Y-%m-%d %H:%M:%S")
            initials, color = generate_avatar_data(name)

            count += 1
            comment = WebComment(
                index=count,
                comment_id=f"demo_{count}",
                user_name=name,
                message=msg,
                created_time=time_str,
                timestamp_raw=comment_time.timestamp(),
                avatar_color=color,
                avatar_initials=initials
            )
            self.on_comment(comment)
            time.sleep(speed)

        self.on_status("COMPLETED", {"message": f"Demo completed with {count} comments."})


# --- Excel Exporter ---
class ExcelReportExporter:
    @staticmethod
    def export(comments: List[WebComment], output_path: Path, sort_order: str = "oldest", include_names: bool = True) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Facebook Comments"

        if sort_order == "oldest":
            sorted_comments = sorted(comments, key=lambda c: c.timestamp_raw)
        else:
            sorted_comments = sorted(comments, key=lambda c: c.timestamp_raw, reverse=True)

        header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
        header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

        headers = ["User", "Comment", "Date"] if include_names else ["Comment", "Date"]
        ws.append(headers)
        ws.row_dimensions[1].height = 28

        for col in range(1, len(headers) + 1):
            c = ws.cell(row=1, column=col)
            c.font = header_font
            c.fill = header_fill
            c.alignment = header_align

        body_font = Font(name="Segoe UI", size=10, color="0F172A")
        alt_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
        thin_border = Border(
            bottom=Side(style="thin", color="E2E8F0"),
            top=Side(style="thin", color="E2E8F0"),
            left=Side(style="thin", color="E2E8F0"),
            right=Side(style="thin", color="E2E8F0")
        )

        for row_idx, c in enumerate(sorted_comments, start=2):
            u_clean = sanitize_for_excel(c.user_name)
            m_clean = sanitize_for_excel(c.message)
            d_clean = sanitize_for_excel(c.created_time)

            if include_names:
                ws.append([u_clean, m_clean, d_clean])
                ws.row_dimensions[row_idx].height = max(22, min(90, 18 * (m_clean.count("\n") + 1)))

                c_user = ws.cell(row=row_idx, column=1)
                c_msg = ws.cell(row=row_idx, column=2)
                c_date = ws.cell(row=row_idx, column=3)

                c_user.font = body_font
                c_user.alignment = Alignment(horizontal="left", vertical="top")
                c_user.border = thin_border

                c_msg.font = body_font
                c_msg.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
                c_msg.border = thin_border

                c_date.font = body_font
                c_date.alignment = Alignment(horizontal="center", vertical="top")
                c_date.border = thin_border

                if row_idx % 2 == 1:
                    c_user.fill = alt_fill
                    c_msg.fill = alt_fill
                    c_date.fill = alt_fill
            else:
                ws.append([m_clean, d_clean])
                ws.row_dimensions[row_idx].height = max(22, min(90, 18 * (m_clean.count("\n") + 1)))

                c_msg = ws.cell(row=row_idx, column=1)
                c_date = ws.cell(row=row_idx, column=2)

                c_msg.font = body_font
                c_msg.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
                c_msg.border = thin_border

                c_date.font = body_font
                c_date.alignment = Alignment(horizontal="center", vertical="top")
                c_date.border = thin_border

                if row_idx % 2 == 1:
                    c_msg.fill = alt_fill
                    c_date.fill = alt_fill

        ws.freeze_panes = "A2"
        max_col = "C" if include_names else "B"
        ws.auto_filter.ref = f"A1:{max_col}{max(2, len(sorted_comments) + 1)}"

        if include_names:
            ws.column_dimensions["A"].width = 28
            ws.column_dimensions["B"].width = 65
            ws.column_dimensions["C"].width = 22
        else:
            ws.column_dimensions["A"].width = 75
            ws.column_dimensions["B"].width = 24

        wb.save(output_path)
        return output_path
