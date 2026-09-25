"""
Utility functions for URL parsing, post ID extraction, date parsing,
and Excel text sanitization.
"""

import re
from datetime import datetime, timezone
from typing import Optional, Tuple
from urllib.parse import urlparse, parse_qs, urlunparse

from app.models import InvalidUrlError, Comment


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

# Illegal XML characters that Excel disallows:
# ASCII 0-8, 11-12, 14-31 (except \t (0x09), \n (0x0A), \r (0x0D))
ILLEGAL_EXCEL_CHARS_RE = re.compile(r"[\x00-\x08\x0b-\x0c\x0e-\x1f]")


def sanitize_for_excel(value: Optional[str]) -> str:
    """
    Sanitizes text for safe inclusion in Excel OpenXML files.
    Preserves all standard Unicode characters, emojis, Filipino/multilingual scripts,
    newlines, tabs, and carriage returns, while removing illegal XML control characters.
    """
    if not value:
        return ""
    return ILLEGAL_EXCEL_CHARS_RE.sub("", str(value))


def clean_facebook_url(raw_url: str) -> str:
    """
    Normalizes a Facebook URL by trimming whitespace, standardizing protocol,
    and stripping tracking query parameters.
    """
    if not raw_url or not isinstance(raw_url, str):
        raise InvalidUrlError("URL cannot be empty.")

    raw_url = raw_url.strip()
    if not raw_url.startswith(("http://", "https://")):
        raw_url = "https://" + raw_url

    parsed = urlparse(raw_url)
    host = parsed.netloc.lower()

    # Remove port if present
    if ":" in host:
        host = host.split(":")[0]

    if host not in FB_HOSTS:
        raise InvalidUrlError(f"'{parsed.netloc}' is not a valid Facebook domain.")

    # Remove tracking query parameters, but preserve essential ones
    preserved_keys = {"story_fbid", "id", "v", "fbid", "set"}
    query_dict = parse_qs(parsed.query)
    filtered_query = {k: v for k, v in query_dict.items() if k in preserved_keys}

    # Rebuild query string
    from urllib.parse import urlencode
    clean_query = urlencode(filtered_query, doseq=True) if filtered_query else ""

    clean_url = urlunparse((
        "https",
        "www.facebook.com",
        parsed.path.rstrip("/"),
        "",
        clean_query,
        ""
    ))
    return clean_url


def extract_post_identifiers(clean_url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extracts potential page identifier and post identifier from a normalized Facebook URL.
    Returns (page_id_or_slug, post_id_or_fbid).
    
    Supported formats:
    1. /permalink.php?story_fbid={post_id}&id={page_id}
    2. /{page_slug}/posts/{post_id} (numeric or pfbid)
    3. /{page_slug}/videos/{video_id}
    4. /watch/?v={video_id}
    5. /photo.php?fbid={photo_id}
    6. /{page_slug}/photos/.../{photo_id}
    7. /groups/{group_id}/posts/{post_id}
    """
    parsed = urlparse(clean_url)
    path = parsed.path
    query = parse_qs(parsed.query)

    # Format 1: permalink.php or story.php
    if "permalink.php" in path or "story.php" in path:
        story_fbid = query.get("story_fbid", [None])[0]
        page_id = query.get("id", [None])[0]
        if story_fbid:
            return page_id, story_fbid

    # Format 2: watch/?v={video_id}
    if "watch" in path and "v" in query:
        return None, query["v"][0]

    # Format 3: photo.php?fbid={photo_id}
    if "photo.php" in path and "fbid" in query:
        return query.get("id", [None])[0], query["fbid"][0]

    # Format 4: /{page}/posts/{post_id} (including pfbid)
    # Examples: /BBCNews/posts/10159238472 or /PageName/posts/pfbid02AbC...
    posts_match = re.search(r"/([^/]+)/posts/(pfbid[a-zA-Z0-9]+|[0-9]+)", path)
    if posts_match:
        page_slug = posts_match.group(1)
        post_id = posts_match.group(2)
        return page_slug, post_id

    # Format 5: /{page}/videos/{video_id}
    videos_match = re.search(r"/([^/]+)/videos/([0-9]+)", path)
    if videos_match:
        return videos_match.group(1), videos_match.group(2)

    # Format 5b: /reel/{reel_id}
    reel_match = re.search(r"/reel/([0-9]+)", path)
    if reel_match:
        return None, reel_match.group(1)

    # Format 5c: /share/v/{id}, /share/p/{id}, /share/r/{id} (Mobile share links)
    share_match = re.search(r"/share/(?:v|p|r)/([a-zA-Z0-9_\-]+)", path)
    if share_match:
        share_token = share_match.group(1)
        try:
            import requests
            session = requests.Session()
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            })
            # 1. Quick check without redirect to read Location header directly
            r = session.head(clean_url, allow_redirects=False, timeout=5)
            loc = r.headers.get("Location")
            if not loc:
                r = session.get(clean_url, allow_redirects=False, timeout=5)
                loc = r.headers.get("Location")
            if loc:
                if loc.startswith("/"):
                    loc = f"https://www.facebook.com{loc}"
                if "facebook.com" in loc and "/share/" not in loc and "login.php" not in loc:
                    c_page, c_post = extract_post_identifiers(loc)
                    if c_post:
                        return c_page, c_post

            # 2. Check full redirect history
            resp = session.head(clean_url, allow_redirects=True, timeout=5)
            candidates = [resp.url] + [h.headers.get("Location") for h in resp.history if h.headers.get("Location")]
            for cand in candidates:
                if cand:
                    if cand.startswith("/"):
                        cand = f"https://www.facebook.com{cand}"
                    if "facebook.com" in cand and "/share/" not in cand and "login.php" not in cand:
                        c_page, c_post = extract_post_identifiers(cand)
                        if c_post:
                            return c_page, c_post
        except Exception:
            pass
        return None, share_token

    # Format 6: /photos/.../{photo_id}
    photos_match = re.search(r"/photos/(?:[a-zA-Z0-9\._\-]+/)?([0-9]+)", path)
    if photos_match:
        return None, photos_match.group(1)

    # Format 7: /groups/{group_id}/posts/{post_id} or /groups/{group_id}/permalink/{post_id}
    groups_match = re.search(r"/groups/([^/]+)/(?:posts|permalink)/([0-9]+)", path)
    if groups_match:
        return groups_match.group(1), groups_match.group(2)

    # Fallback: check if the last path component is numeric (e.g. /{page}/posts/{id})
    parts = [p for p in path.split("/") if p]
    if parts:
        last = parts[-1]
        if last.isdigit() or last.startswith("pfbid"):
            parent = parts[-2] if len(parts) > 1 else None
            return parent, last

    return None, None


def parse_fb_timestamp(ts_str: str) -> datetime:
    """
    Parses Facebook Graph API ISO timestamp strings into UTC datetime objects.
    Example formats:
      '2026-09-12T08:01:15+0000'
      '2026-09-12T08:01:15Z'
      '2026-09-12T08:01:15+00:00'
    """
    if not ts_str:
        return datetime.fromtimestamp(0, tz=timezone.utc)

    # Clean standard ISO variations
    s = ts_str.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    elif len(s) >= 5 and (s[-5] in ("+", "-")) and (":" not in s[-5:]):
        # Format '+0000' -> '+00:00'
        s = s[:-2] + ":" + s[-2:]

    try:
        dt = datetime.fromisoformat(s)
        # Ensure UTC timezone
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        # Fallback to current time if unparseable
        return datetime.now(timezone.utc)


def format_excel_date(dt: datetime) -> str:
    """
    Formats a datetime object as 'YYYY-MM-DD HH:MM:SS'.
    """
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def sort_comments_oldest_first(comments: list[Comment]) -> list[Comment]:
    """
    Sorts a list of Comment objects ascending by created_time (oldest -> newest).
    Safely handles both naive and timezone-aware datetimes.
    """
    def _sort_key(c: Comment):
        dt = c.created_time
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    return sorted(comments, key=_sort_key)
