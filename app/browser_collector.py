"""
Browser-based Comment Collector for Facebook.
Collects real comments from ANY public post, video, or reel
using automated browser extraction without requiring a Meta Developer token.
"""

import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Optional, Callable, Dict, Any

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException, InvalidSessionIdException, NoSuchWindowException

from app.config import get_project_root
from app.models import Comment, AppError
from app.utils import clean_facebook_url


class BrowserCommentCollector:
    """
    Automated browser-based scraper that extracts real Facebook comments from any public post.
    Uses a persistent browser profile so the user logs in once, and remains logged in.
    """

    def __init__(self, profile_dir: Optional[Path] = None, headless: bool = False):
        if profile_dir is None:
            profile_dir = get_project_root() / "browser_profile"
        self.profile_dir = Path(profile_dir)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.headless = headless
        self.driver: Optional[webdriver.Chrome] = None
        self.last_post_author: Optional[str] = None

    def _create_driver(self, headless: Optional[bool] = None) -> webdriver.Chrome:
        """Initializes a Chrome or Edge WebDriver with user profile persistence."""
        use_headless = self.headless if headless is None else headless

        # Try Chrome first
        try:
            options = ChromeOptions()
            if use_headless:
                options.add_argument("--headless=new")
            options.add_argument(f"--user-data-dir={str(self.profile_dir.resolve())}")
            options.add_argument("--disable-notifications")
            options.add_argument("--mute-audio")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
            
            # Suppress logging
            options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
            options.add_experimental_option("useAutomationExtension", False)

            driver = webdriver.Chrome(options=options)
            return driver
        except Exception as chrome_err:
            # Fallback to Edge
            try:
                edge_options = EdgeOptions()
                if use_headless:
                    edge_options.add_argument("--headless=new")
                edge_options.add_argument(f"--user-data-dir={str(self.profile_dir.resolve())}")
                edge_options.add_argument("--disable-notifications")
                edge_options.add_argument("--mute-audio")
                edge_options.add_argument("--disable-blink-features=AutomationControlled")
                driver = webdriver.Edge(options=edge_options)
                return driver
            except Exception as edge_err:
                raise AppError(
                    "Neither Google Chrome nor Microsoft Edge could be launched.\n\n"
                    "Please ensure Google Chrome or Microsoft Edge is installed on your computer.",
                    technical_details=f"Chrome error: {chrome_err}\nEdge error: {edge_err}"
                )

    def is_logged_in(self) -> bool:
        """Checks if Facebook login session cookies exist in the persistent profile."""
        driver = None
        try:
            driver = self._create_driver(headless=True)
            driver.get("https://www.facebook.com/")
            time.sleep(2)
            cookies = driver.get_cookies()
            cookie_names = [c["name"] for c in cookies]
            return "c_user" in cookie_names
        except Exception:
            return False
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

    def clear_login_session(self) -> None:
        """Clears Facebook cookies from the persistent browser profile to log out."""
        driver = None
        try:
            driver = self._create_driver(headless=True)
            driver.get("https://www.facebook.com/")
            time.sleep(1)
            driver.delete_all_cookies()
        except Exception:
            pass
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

    def open_login_window(self, on_close_callback: Optional[Callable[[bool], None]] = None) -> bool:
        """Opens a visible browser window allowing the user to log in to Facebook."""
        driver = None
        logged_in = False
        try:
            driver = self._create_driver(headless=False)
            driver.set_window_size(1050, 800)
            driver.get("https://www.facebook.com/login/")
            while True:
                time.sleep(1)
                try:
                    if not driver.window_handles:
                        break
                    cookies = driver.get_cookies()
                    if any(c["name"] == "c_user" for c in cookies):
                        logged_in = True
                        time.sleep(1.5)
                        break
                except Exception:
                    break
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
            if on_close_callback:
                try:
                    on_close_callback(logged_in)
                except TypeError:
                    on_close_callback()
        return logged_in

    def collect(
        self,
        post_url: str,
        progress_callback: Optional[Callable[[str, int], None]] = None,
        cancel_event: Optional[Any] = None
    ) -> List[Comment]:
        """
        Navigates to the Facebook post URL, opens comments, expands all pages,
        and extracts real comments from the live page.
        """
        driver = None
        try:
            # Check if profile is already logged in
            already_logged = self.is_logged_in()
            # If already logged in, headless mode is smooth, fast, and doesn't get interrupted
            use_headless = self.headless if self.headless is not None else already_logged

            driver = self._create_driver(headless=use_headless)
            if not use_headless:
                driver.set_window_size(1100, 850)

            if progress_callback:
                progress_callback("Opening post in browser...", 0)

            clean_url = clean_facebook_url(post_url)
            driver.get(clean_url)
            time.sleep(4)

            # Check if login is required
            cookies = driver.get_cookies()
            is_logged_in = any(c["name"] == "c_user" for c in cookies)

            if not is_logged_in:
                # If we started headless but login is required, switch to visible so user can log in
                if use_headless:
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    driver = self._create_driver(headless=False)
                    driver.set_window_size(1100, 850)
                    driver.get(clean_url)
                    time.sleep(4)

                if progress_callback:
                    progress_callback("Waiting for Facebook login in browser window (and 2FA if prompted)...", 0)

                # Wait up to 180 seconds for user to log in and approve 2FA
                login_wait = 0
                while login_wait < 180 and not (cancel_event and cancel_event.is_set()):
                    time.sleep(2)
                    login_wait += 2
                    try:
                        if not driver.window_handles:
                            raise AppError("Facebook login window was closed before completion.")
                        cookies = driver.get_cookies()
                        if any(c["name"] == "c_user" for c in cookies):
                            is_logged_in = True
                            if progress_callback:
                                progress_callback("Login detected! Proceeding to comments...", 0)
                            time.sleep(2)
                            # Reload post now that user is logged in
                            driver.get(clean_url)
                            time.sleep(4)
                            break
                    except (InvalidSessionIdException, NoSuchWindowException):
                        raise AppError("Browser window was closed before completion.")
                    except Exception:
                        break

            # Handle close button on any popups / dialogs
            self._dismiss_popups(driver)

            # Extract author of post/reel
            self.last_post_author = self._extract_post_author(driver)

            # If on Reels or Videos, click comment button to open comments drawer
            current_u = driver.current_url.lower()
            if "/reel/" in current_u or "/share/v/" in clean_url or "/share/r/" in clean_url or "/videos/" in current_u or "/watch/" in current_u:
                self._open_reel_comments(driver)

            # Expansion loop: click "View more comments" and scroll
            collected_dict: Dict[str, Comment] = {}
            last_count = 0
            no_new_cycles = 0

            if progress_callback:
                progress_callback("Expanding comments...", 0)

            while no_new_cycles < 8:
                if cancel_event and cancel_event.is_set():
                    break

                # Extract currently loaded comments
                current_comments = self._extract_comments_from_dom(driver)
                for c in current_comments:
                    # Key by author + message to avoid duplicates
                    key = f"{c.user_name}||{c.message}"
                    if key not in collected_dict:
                        collected_dict[key] = c

                count = len(collected_dict)
                if progress_callback:
                    progress_callback(f"Comments collected: {count:,}", count)

                if count > last_count:
                    last_count = count
                    no_new_cycles = 0
                else:
                    no_new_cycles += 1

                # Try clicking "View more comments" or "View previous comments"
                clicked_more = self._click_view_more_comments(driver)

                # Scroll the comments container or window
                self._scroll_comments(driver)
                time.sleep(1.2)

            if not collected_dict and not is_logged_in:
                raise AppError(
                    "No comments could be retrieved. Facebook requires you to be logged in to view comments on this content.\n\n"
                    "Please click the '🌐 Log In to Facebook in Browser' button at the top, log in to your account, and try again."
                )

            return list(collected_dict.values())

        except (InvalidSessionIdException, NoSuchWindowException):
            raise AppError("Collection stopped: the browser window was closed.")
        except WebDriverException as wde:
            err_str = str(wde).lower()
            if "invalid session id" in err_str or "no such window" in err_str:
                raise AppError("Collection stopped: the browser window was closed.")
            raise AppError(f"Browser error: {wde}")
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

    def _extract_post_author(self, driver: webdriver.Chrome) -> Optional[str]:
        """
        Extracts the name of the person or Page who published the post, video, or reel.
        Inspects page headings, post article headers, metadata, and page title.
        """
        ignore = {
            'facebook', 'notifications', 'chats', 'comments', 'reels', 'menu', 
            'log in', 'sign up', 'search', 'search results', 'create a post', 
            'posts', 'home', 'watch', 'marketplace', 'gaming'
        }

        # 1. Try h2 / h1 elements (Facebook prominently puts author name in h2)
        for tag in ['//h2', '//h1']:
            try:
                for el in driver.find_elements(By.XPATH, tag):
                    t = el.text.strip()
                    if not t:
                        continue
                    first_line = t.split('\n')[0].strip()
                    # Strip out Facebook action suffixes like " · Follow" or "Follow"
                    first_line = re.sub(r'\s*[·•]\s*Follow.*$', '', first_line, flags=re.IGNORECASE)
                    first_line = re.sub(r'\s+Follow$', '', first_line, flags=re.IGNORECASE).strip()
                    if first_line and first_line.lower() not in ignore and len(first_line) < 75:
                        return first_line
            except Exception:
                continue

        # 2. Try post article header link or author role
        try:
            author_links = driver.find_elements(
                By.XPATH,
                "//div[@role='article']//h2//a | //div[@role='article']//strong//span | //div[@role='main']//h2//a"
            )
            for al in author_links:
                t = al.text.strip()
                if t and t.lower() not in ignore and len(t) < 75:
                    return t
        except Exception:
            pass

        # 3. Try page title (e.g. "Author Name | Facebook" or "Author Name - Video Title")
        try:
            title = driver.title.strip()
            if ' | Facebook' in title:
                candidate = title.replace(' | Facebook', '').strip()
                if candidate.lower() not in ignore and 'log in' not in candidate.lower() and len(candidate) < 75:
                    return candidate
        except Exception:
            pass

        return None

    def _dismiss_popups(self, driver: webdriver.Chrome) -> None:
        """Dismisses generic cookie / login banners if present."""
        try:
            close_btns = driver.find_elements(
                By.XPATH,
                "//div[@aria-label='Close' or @aria-label='close' or @aria-label='Not Now' or @aria-label='Decline optional cookies']"
            )
            for b in close_btns:
                try:
                    driver.execute_script("arguments[0].click();", b)
                    time.sleep(0.5)
                except Exception:
                    try:
                        b.click()
                        time.sleep(0.5)
                    except Exception:
                        pass
        except Exception:
            pass

    def _open_reel_comments(self, driver: webdriver.Chrome) -> None:
        """Clicks the comments icon on Facebook Reels/videos to open the comments drawer."""
        try:
            comment_btns = driver.find_elements(
                By.XPATH,
                "//*[contains(@aria-label, 'Comment') or contains(@aria-label, 'comment') or contains(@aria-label, 'komento')]"
            )
            for btn in comment_btns:
                try:
                    driver.execute_script("arguments[0].click();", btn)
                    time.sleep(2)
                    break
                except Exception:
                    try:
                        btn.click()
                        time.sleep(2)
                        break
                    except Exception:
                        pass
        except Exception:
            pass

    def _click_view_more_comments(self, driver: webdriver.Chrome) -> bool:
        """Looks for buttons that expand earlier/more comments or replies and clicks them."""
        clicked_any = False
        keywords = [
            "View more comments", "View previous comments", "View 10 more comments",
            "View 20 more comments", "See more comments", "more comments",
            "Tingnan ang higit pang mga komento", "Tingnan ang iba pang mga komento",
            "View replies", "View 1 reply", "View reply", "replies", "mga tugon",
            "View 2 replies", "View 3 replies", "View 4 replies", "View 5 replies"
        ]
        xpath_query = (
            " | ".join([f"//span[contains(text(), '{k}')]" for k in keywords])
            + " | //div[@role='button']//span[contains(text(), 'repl') or contains(text(), 'Repl') or contains(text(), 'tugon')]"
        )
        try:
            elements = driver.find_elements(By.XPATH, xpath_query)
            for el in elements:
                try:
                    driver.execute_script("arguments[0].scrollIntoView(false);", el)
                    driver.execute_script("arguments[0].click();", el)
                    clicked_any = True
                    time.sleep(0.5)
                except Exception:
                    pass
        except Exception:
            pass
        return clicked_any

    def _scroll_comments(self, driver: webdriver.Chrome) -> None:
        """Scrolls down comments area or page."""
        try:
            # Look for scrollable comment drawer
            scrollable = driver.find_elements(By.XPATH, "//div[@role='region'] | //div[contains(@class, 'x1n2onr6')]")
            if scrollable:
                driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", scrollable[0])
            else:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        except Exception:
            pass

    def _extract_comments_from_dom(self, driver: webdriver.Chrome) -> List[Comment]:
        """Extracts comment objects from the current DOM state."""
        comments = []
        now = datetime.now()
        ignore_author_strings = {
            "like", "reply", "share", "online status indicator", "active now",
            "online", "follow", "author", "top fan", "edited", "view more",
            "send message", "react", "view replies", "write a comment...",
            "most relevant", "all comments", "top comments", "by author",
            "liked by author", "highlighted by author", "shared by author",
            "view more replies", "hide replies"
        }

        time_suffix_re = re.compile(
            r"\s+(?:"
            r"\d+\s*(?:seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?|d|weeks?|wks?|w|months?|mo|years?|yrs?|y)(?:\s+ago)?"
            r"|an?\s+(?:second|sec|minute|min|hour|hr|day|week|month|year)(?:\s+ago)?"
            r"|yesterday(?:\s+at\s+.*)?"
            r"|just now"
            r"|\d{1,2}:\d{2}.*"
            r"|\d+.*ago"
            r"|ago"
            r")$",
            re.IGNORECASE
        )

        def _clean_author_name(raw: str) -> str:
            if not raw:
                return "Facebook User"
            n = re.sub(r"\s+", " ", raw).strip()
            n = time_suffix_re.sub("", n).strip()
            n = re.sub(r"\s+an?\s+(?:second|minute|hour|day|week|month|year)$", "", n, flags=re.I).strip()
            n = re.sub(r"\s+\d+\s*(?:s|m|h|d|w|mo|y|hrs?|mins?|days?|weeks?)$", "", n, flags=re.I).strip()
            if not n or n.lower() in ignore_author_strings:
                return "Facebook User"
            return n

        # Locate all article or comment blocks
        comment_elements = driver.find_elements(
            By.XPATH,
            "//div[@role='article'] | //div[starts-with(@aria-label, 'Comment by ') or starts-with(@aria-label, 'Reply by ')]"
        )

        for el in comment_elements:
            try:
                text_content = el.text.strip()
                if not text_content:
                    continue

                # 1. Author Name
                author = "Facebook User"
                aria_lbl = el.get_attribute("aria-label") or ""

                m_reply = re.search(r"^Reply by\s+(.*?)\s+to\s+.*?'s comment", aria_lbl, re.IGNORECASE)
                if m_reply:
                    author = _clean_author_name(m_reply.group(1))
                elif "Comment by" in aria_lbl:
                    m_cb = re.search(r"Comment by\s+(.*)", aria_lbl, re.IGNORECASE)
                    if m_cb:
                        author = _clean_author_name(m_cb.group(1))

                if author == "Facebook User":
                    # Search for profile link with user name
                    profile_links = el.find_elements(
                        By.XPATH,
                        ".//a[(@role='link' or contains(@href, 'facebook.com') or contains(@href, 'profile.php')) "
                        "and not(contains(@href, 'comment')) and not(contains(@href, 'reel')) "
                        "and not(contains(@href, 'videos')) and not(contains(@href, 'watch'))]"
                    )
                    for pl in profile_links:
                        pl_txt = pl.text.strip()
                        if pl_txt and len(pl_txt) > 1 and pl_txt.lower() not in ignore_author_strings:
                            if not re.match(r"^\d+[smhdw]$", pl_txt) and not re.search(r"\b(ago|reply|like|share)\b", pl_txt, re.I):
                                cleaned_pl = _clean_author_name(pl_txt)
                                if cleaned_pl != "Facebook User":
                                    author = cleaned_pl
                                    break

                if author == "Facebook User":
                    # Fallback to span[@dir='auto'] outside the message container
                    spans = el.find_elements(By.XPATH, ".//span[@dir='auto']")
                    for sp in spans:
                        stxt = sp.text.strip()
                        if stxt and stxt.lower() not in ignore_author_strings and not re.match(r"^\d+[smhdw]$", stxt):
                            if not sp.find_elements(By.XPATH, "./ancestor::div[@dir='auto']"):
                                cleaned_sp = _clean_author_name(stxt)
                                if cleaned_sp != "Facebook User":
                                    author = cleaned_sp
                                    break

                # 2. Message Text
                # Facebook stores comment message in a div[@dir='auto']
                message = ""
                div_nodes = el.find_elements(By.XPATH, ".//div[@dir='auto']")
                for dn in div_nodes:
                    # Skip nested child divs to avoid partial fragments
                    if dn.find_elements(By.XPATH, "./ancestor::div[@dir='auto']"):
                        continue
                    d_txt = dn.text.strip()
                    if not d_txt or d_txt == author or d_txt.lower() in ignore_author_strings:
                        continue
                    if re.match(r"^\d+[smhdw]$", d_txt) or d_txt in ("Reply", "Like", "Share", "by author"):
                        continue
                    message = d_txt
                    break

                # Fallback if no div[@dir='auto'] found
                if not message:
                    span_nodes = el.find_elements(By.XPATH, ".//span[@dir='auto']")
                    for sn in span_nodes:
                        s_txt = sn.text.strip()
                        if s_txt and s_txt != author and s_txt.lower() not in ignore_author_strings:
                            if not re.match(r"^\d+[smhdw]$", s_txt) and not re.search(r"\b(ago|reply|like|share)\b", s_txt, re.I):
                                message = s_txt
                                break

                # Fallback to line split from full text
                if not message:
                    lines = [l.strip() for l in text_content.split("\n") if l.strip()]
                    for line_item in lines:
                        if line_item != author and line_item.lower() not in ignore_author_strings:
                            if not re.match(r"^\d+[smhdw]$", line_item) and not re.search(r"\b(ago|reply|like|share|indicator|active)\b", line_item, re.I):
                                message = line_item
                                break

                # Check for stickers or image comments if text is still empty
                if not message:
                    imgs = el.find_elements(By.XPATH, ".//img[@alt or @aria-label]")
                    for im in imgs:
                        alt = im.get_attribute("alt") or im.get_attribute("aria-label") or ""
                        if alt and alt.lower() not in ignore_author_strings and not any(x in alt.lower() for x in ("avatar", "profile picture", "badge")):
                            message = f"[{alt}]"
                            break

                # Skip empty messages or button noise
                if not message or message.lower() in ignore_author_strings:
                    continue

                # 3. Timestamp Extraction (Real Facebook Date & Time)
                timestamp = now
                # Strategy A: Check comment links (Facebook embeds full date/time in aria-label, or relative time in text)
                links = el.find_elements(By.XPATH, ".//a[contains(@href, 'comment') or contains(@href, 'permalink') or contains(@href, '/posts/') or contains(@href, '/reel/')]")
                for l in links:
                    aria = l.get_attribute("aria-label") or ""
                    txt = l.text.strip()
                    if aria and any(c.isdigit() for c in aria):
                        parsed_dt = self._parse_relative_time(aria, now)
                        if parsed_dt != now:
                            timestamp = parsed_dt
                            break
                    if txt and (re.match(r"^\d+[smhdw]$", txt) or re.search(r"\b(hr|hrs|hour|hours|min|mins|day|days|w|wk|wks|sec|secs|ago)\b", txt, re.I)):
                        parsed_dt = self._parse_relative_time(txt, now)
                        if parsed_dt != now:
                            timestamp = parsed_dt
                            break

                # Strategy B: Check article element's own aria-label (e.g. "Comment by Ella Romero Sadang II 15 hours ago")
                if timestamp == now:
                    if aria_lbl and ("ago" in aria_lbl.lower() or any(c.isdigit() for c in aria_lbl)):
                        parsed_dt = self._parse_relative_time(aria_lbl, now)
                        if parsed_dt != now:
                            timestamp = parsed_dt

                # Strategy C: Check all span texts inside element
                if timestamp == now:
                    spans = el.find_elements(By.XPATH, ".//span")
                    for s_node in spans:
                        stxt = s_node.text.strip()
                        if re.match(r"^\d+[smhdw]$", stxt) or re.match(r"^\d+\s*(?:min|mins|hr|hrs|hour|hours|day|days|w|wk|wks|sec|secs)(?:\s+ago)?$", stxt, re.I):
                            parsed_dt = self._parse_relative_time(stxt, now)
                            if parsed_dt != now:
                                timestamp = parsed_dt
                                break

                cid = f"web_{author}_{hash(message)}"
                comments.append(Comment(
                    comment_id=cid,
                    user_name=author,
                    message=message,
                    created_time=timestamp
                ))
            except Exception:
                continue

        return comments

    def _parse_relative_time(self, time_str: str, base_time: datetime) -> datetime:
        """
        Parses Facebook timestamp strings (both full datetimes and relative times) into UTC datetime objects.
        Handles examples such as:
          - 'Sunday, September 13, 2026 at 5:46 PM'
          - 'September 13, 2026 at 5:46 PM'
          - 'September 13 at 5:46 PM'
          - '15 hours ago', '15h', '15 hrs', '2d', '3w', '25 mins ago'
          - 'Yesterday at 3:15 PM'
          - 'Comment by [User] 15 hours ago'
        """
        if not time_str:
            return base_time

        # Normalize unicode spaces (e.g. \u202f narrow no-break space, \xa0)
        s = re.sub(r"[\s\u200b\u202f\xa0]+", " ", time_str).strip()
        s_lower = s.lower()

        # If string contains "Comment by ...", strip the prefix
        if "comment by" in s_lower:
            m_cb = re.search(r"comment by .*?(\d+.*|yesterday.*|just now.*)", s, re.IGNORECASE)
            if m_cb:
                s = m_cb.group(1).strip()
                s_lower = s.lower()

        # 1. Full dates with year
        full_date_formats = [
            "%A, %B %d, %Y at %I:%M %p",
            "%A, %d %B %Y at %I:%M %p",
            "%A, %B %d, %Y at %H:%M",
            "%B %d, %Y at %I:%M %p",
            "%d %B %Y at %I:%M %p",
            "%B %d, %Y at %H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
        ]
        for fmt in full_date_formats:
            try:
                dt = datetime.strptime(s, fmt)
                return dt
            except ValueError:
                pass

        # 2. Dates without year (assume base_time's year)
        no_year_formats = [
            "%A, %B %d at %I:%M %p",
            "%B %d at %I:%M %p",
            "%A, %d %B at %I:%M %p",
            "%d %B at %I:%M %p",
        ]
        for fmt in no_year_formats:
            try:
                dt = datetime.strptime(s, fmt)
                dt = dt.replace(year=base_time.year)
                if dt > base_time:
                    dt = dt.replace(year=base_time.year - 1)
                return dt
            except ValueError:
                pass

        # 3. Relative Hours: '15h', '15 hrs', '15 hours ago', '15hr'
        m_hours = re.search(r"(\d+)\s*(?:h|hr|hrs|hours?)(?:\s+ago)?\b", s_lower)
        if m_hours:
            return base_time - timedelta(hours=int(m_hours.group(1)))

        # 4. Relative Minutes: '3m', '3 mins', '3 minutes ago'
        m_mins = re.search(r"(\d+)\s*(?:m|min|mins|minutes?)(?:\s+ago)?\b", s_lower)
        if m_mins:
            return base_time - timedelta(minutes=int(m_mins.group(1)))

        # 5. Relative Days: '5d', '5 days', '5 days ago'
        m_days = re.search(r"(\d+)\s*(?:d|day|days)(?:\s+ago)?\b", s_lower)
        if m_days:
            return base_time - timedelta(days=int(m_days.group(1)))

        # 6. Relative Weeks: '2w', '2 wks', '2 weeks ago'
        m_weeks = re.search(r"(\d+)\s*(?:w|wk|wks|weeks?)(?:\s+ago)?\b", s_lower)
        if m_weeks:
            return base_time - timedelta(weeks=int(m_weeks.group(1)))

        # 7. Relative Seconds: '45s', '45 secs ago'
        m_secs = re.search(r"(\d+)\s*(?:s|sec|secs|seconds?)(?:\s+ago)?\b", s_lower)
        if m_secs:
            return base_time - timedelta(seconds=int(m_secs.group(1)))

        # 8. Yesterday: 'yesterday at 5:46 pm' or 'yesterday'
        if "yesterday" in s_lower or "kahapon" in s_lower:
            time_part = re.search(r"(\d{1,2}):(\d{2})\s*(am|pm)", s_lower)
            if time_part:
                hour = int(time_part.group(1))
                minute = int(time_part.group(2))
                if time_part.group(3) == "pm" and hour < 12:
                    hour += 12
                elif time_part.group(3) == "am" and hour == 12:
                    hour = 0
                y_date = (base_time - timedelta(days=1)).date()
                return datetime(y_date.year, y_date.month, y_date.day, hour, minute)
            return base_time - timedelta(days=1)

        if "just now" in s_lower:
            return base_time

        return base_time
