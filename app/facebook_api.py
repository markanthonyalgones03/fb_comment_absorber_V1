"""
Official Meta Graph API client for Facebook Comment Collector.
Implements compliant authentication, cursor-based pagination, rate-limit awareness,
and user-friendly error mappings.
"""

import time
import requests
from typing import Optional, Dict, Any, Tuple, List
from urllib.parse import urlparse, parse_qs

from app.models import (
    Comment,
    AppError,
    InvalidUrlError,
    PostNotFoundError,
    PermissionDeniedError,
    AuthenticationExpiredError,
    RateLimitError,
    NetworkError,
)
from app.utils import (
    clean_facebook_url,
    extract_post_identifiers,
    parse_fb_timestamp,
)


class FacebookApiClient:
    """
    Communicates with Meta's official Graph API.
    """

    def __init__(self, access_token: str, api_version: str = "v21.0", timeout: int = 25):
        if not access_token or not access_token.strip():
            raise AuthenticationExpiredError("Facebook access token is missing or empty.")

        self.access_token = access_token.strip()
        self.api_version = api_version
        self.base_url = f"https://graph.facebook.com/{self.api_version}"
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "FacebookCommentCollector/1.0",
            "Accept": "application/json",
        })

    def _get(self, endpoint_or_url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Executes a GET request against the Meta Graph API with comprehensive error handling.
        """
        if params is None:
            params = {}

        # If a full URL is supplied (e.g. from paging.next), use it directly
        if endpoint_or_url.startswith("http://") or endpoint_or_url.startswith("https://"):
            url = endpoint_or_url
            # Make sure access token is present
            if "access_token" not in url and "access_token" not in params:
                params["access_token"] = self.access_token
        else:
            path = endpoint_or_url.lstrip("/")
            url = f"{self.base_url}/{path}"
            params["access_token"] = self.access_token

        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
        except (requests.ConnectionError, requests.ConnectTimeout) as exc:
            raise NetworkError(technical_details=str(exc))
        except requests.RequestException as exc:
            raise NetworkError(technical_details=str(exc))

        try:
            data = resp.json()
        except Exception:
            if resp.status_code >= 400:
                raise AppError(
                    f"Facebook returned an unexpected HTTP {resp.status_code} response.",
                    technical_details=resp.text
                )
            return {}

        if "error" in data:
            self._handle_api_error(data["error"], resp.status_code)

        if resp.status_code >= 400:
            raise AppError(
                f"Facebook API request failed with HTTP {resp.status_code}.",
                technical_details=str(data)
            )

        return data

    def _handle_api_error(self, error_obj: Dict[str, Any], status_code: int) -> None:
        """
        Translates Meta Graph API error codes and messages into clear, actionable exceptions.
        """
        code = error_obj.get("code")
        subcode = error_obj.get("error_subcode")
        message = error_obj.get("message", "")
        error_type = error_obj.get("type", "")

        tech_info = f"Code: {code}, Subcode: {subcode}, Type: {error_type}, Message: {message}"

        # 1. Authentication errors (Token invalid, expired, revoked, session expired)
        # Codes: 190, 102, 104
        if code in (190, 102, 104) or "OAuthException" in error_type and code == 190:
            raise AuthenticationExpiredError(technical_details=tech_info)

        # 2. Permission / Access Denied errors
        # Codes: 200, 10, 210, 220, 230
        if code in (10, 200, 210, 220, 230):
            raise PermissionDeniedError(technical_details=tech_info)

        # 3. Object does not exist or cannot be loaded due to missing permissions
        # Meta returns code 100 or 803 for non-existent objects or objects without permissions
        if code in (100, 803):
            # Check if it's permission-related disguised as code 100/803
            msg_lower = message.lower()
            if any(term in msg_lower for term in ["permission", "unsupported get request", "cannot be loaded due to"]):
                raise PermissionDeniedError(technical_details=tech_info)
            raise PostNotFoundError(technical_details=tech_info)

        # 4. Rate limiting
        # Codes: 4, 17, 32, 613, 80001
        if code in (4, 17, 32, 613, 80001) or "rate limit" in message.lower():
            raise RateLimitError(technical_details=tech_info)

        # Generic App Error fallback
        raise AppError(
            f"Facebook returned an error: {message}",
            technical_details=tech_info
        )

    def resolve_post_id(self, raw_url: str) -> str:
        """
        Resolves the usable Meta Graph API post identifier from a Facebook URL.
        Uses official Graph API endpoints where possible.
        """
        clean_url = clean_facebook_url(raw_url)
        page_id_or_slug, post_id = extract_post_identifiers(clean_url)

        # 1. Check if we have both numeric page ID and post ID
        if page_id_or_slug and post_id:
            if page_id_or_slug.isdigit() and post_id.isdigit():
                composite_id = f"{page_id_or_slug}_{post_id}"
                # Verify accessibility
                if self._verify_node_accessible(composite_id):
                    return composite_id
                if self._verify_node_accessible(post_id):
                    return post_id

        # 2. If post_id is known (numeric or pfbid), test directly
        if post_id:
            if self._verify_node_accessible(post_id):
                return post_id

        # 3. Query Meta Graph API URL Node lookup: /?id={url}
        try:
            url_lookup = self._get("/", params={"id": clean_url, "fields": "id,og_object{id}"})
            if "og_object" in url_lookup and "id" in url_lookup["og_object"]:
                candidate_id = url_lookup["og_object"]["id"]
                if self._verify_node_accessible(candidate_id):
                    return candidate_id
            if "id" in url_lookup and self._verify_node_accessible(url_lookup["id"]):
                return url_lookup["id"]
        except (PostNotFoundError, PermissionDeniedError):
            raise
        except Exception:
            pass

        # 4. If we have a page slug and a numeric post id, try resolving page ID first
        if page_id_or_slug and post_id and post_id.isdigit():
            try:
                page_node = self._get(f"/{page_id_or_slug}", params={"fields": "id"})
                if "id" in page_node:
                    numeric_page_id = page_node["id"]
                    composite_id = f"{numeric_page_id}_{post_id}"
                    if self._verify_node_accessible(composite_id):
                        return composite_id
            except Exception:
                pass

        # If post_id was identified, return it as final candidate (will be validated on comments call)
        if post_id:
            return post_id

        raise PostNotFoundError(technical_details=f"Could not resolve post ID from URL: {clean_url}")

    def _verify_node_accessible(self, node_id: str) -> bool:
        """
        Quick check if the object node exists and can be queried.
        """
        try:
            self._get(f"/{node_id}", params={"fields": "id"})
            return True
        except (PermissionDeniedError, AuthenticationExpiredError):
            raise
        except PostNotFoundError:
            return False
        except Exception:
            return False

    def get_comments_page(
        self,
        post_id: str,
        after_cursor: Optional[str] = None,
        next_page_url: Optional[str] = None,
        limit: int = 100
    ) -> Tuple[List[Comment], Optional[str], Optional[str], int]:
        """
        Retrieves one page of comments from Meta Graph API.
        
        Returns:
          (comments_list, next_page_url, next_after_cursor, total_count_if_reported)
        """
        if next_page_url:
            data = self._get(next_page_url)
        else:
            params = {
                "fields": "id,from{id,name},message,created_time,comment_count,parent{id}",
                "limit": min(limit, 100),
                "filter": "stream",  # Retrieves stream of comments including replies where permitted
                "order": "chronological",
                "summary": "total_count",
            }
            if after_cursor:
                params["after"] = after_cursor

            data = self._get(f"/{post_id}/comments", params=params)

        raw_comments = data.get("data", [])
        paging = data.get("paging", {})
        summary = data.get("summary", {})
        total_count = summary.get("total_count", 0)

        comments: List[Comment] = []
        for item in raw_comments:
            c_id = item.get("id")
            if not c_id:
                continue

            from_obj = item.get("from") or {}
            # Comply with requirement 8: Use officially provided name, or fallback to permitted ID / "Facebook User"
            user_name = from_obj.get("name") or from_obj.get("id") or "Facebook User"
            user_id = from_obj.get("id")
            message = item.get("message", "") or ""
            created_time = parse_fb_timestamp(item.get("created_time", ""))
            parent_id = (item.get("parent") or {}).get("id")

            comments.append(Comment(
                comment_id=str(c_id),
                user_name=str(user_name),
                user_id=str(user_id) if user_id else None,
                message=str(message),
                created_time=created_time,
                parent_id=str(parent_id) if parent_id else None
            ))

        next_url = paging.get("next")
        cursors = paging.get("cursors", {})
        next_after = cursors.get("after")

        return comments, next_url, next_after, total_count

    def get_comment_replies(self, comment_id: str, limit: int = 50) -> List[Comment]:
        """
        Fetches nested replies for a specific top-level comment if not included in main stream.
        """
        try:
            data = self._get(f"/{comment_id}/comments", params={
                "fields": "id,from{id,name},message,created_time,parent{id}",
                "limit": limit,
                "order": "chronological"
            })
            raw_replies = data.get("data", [])
            replies = []
            for item in raw_replies:
                r_id = item.get("id")
                if not r_id:
                    continue
                from_obj = item.get("from") or {}
                user_name = from_obj.get("name") or from_obj.get("id") or "Facebook User"
                user_id = from_obj.get("id")
                message = item.get("message", "") or ""
                created_time = parse_fb_timestamp(item.get("created_time", ""))
                replies.append(Comment(
                    comment_id=str(r_id),
                    user_name=str(user_name),
                    user_id=str(user_id) if user_id else None,
                    message=str(message),
                    created_time=created_time,
                    parent_id=comment_id
                ))
            return replies
        except Exception:
            return []


class DemoFacebookApiClient:
    """
    Simulation client for offline testing, evaluation, and demonstrations
    without requiring a live Meta Developer Access Token.
    Generates realistic multilingual Facebook comments, pagination batches,
    and timestamps for testing all features seamlessly.
    """

    def __init__(self, access_token: str = "demo_token", api_version: str = "v21.0"):
        self.access_token = "demo_mode_token"
        self.api_version = api_version

    def resolve_post_id(self, raw_url: str) -> str:
        clean_url = clean_facebook_url(raw_url)
        page, post_id = extract_post_identifiers(clean_url)
        return f"demo_{page or 'page'}_{post_id or '1015948291029384'}"

    def get_comments_page(
        self,
        post_id: str,
        after_cursor: Optional[str] = None,
        next_page_url: Optional[str] = None,
        limit: int = 50
    ) -> Tuple[List[Comment], Optional[str], Optional[str], int]:
        from datetime import datetime, timezone, timedelta

        # Parse current page number from cursor
        page_num = 1
        if after_cursor and after_cursor.startswith("cursor_page_"):
            try:
                page_num = int(after_cursor.split("_")[-1])
            except Exception:
                page_num = 1

        total_pages = 5
        items_per_page = 30
        total_comments = total_pages * items_per_page

        # Seed comments templates
        sample_users = [
            "Maria Santos", "Juan Dela Cruz", "Sarah Jenkins", "Angelo Reyes",
            "Bea Alonzo", "David Kim", "Carlos Yulo", "Patricia Tan",
            "Michael Johnson", "Katarina Rodriguez", "Mark Anthony Cruz", "Anna Lee"
        ]

        sample_messages = [
            "Maraming salamat po sa napakagandang balita na ito! Mabuhay! 🇵🇭 ❤️",
            "Very informative post. Thanks for sharing this useful update! 👍",
            "Sobrang ganda nito! Congrats to everyone involved! 🎉🙌",
            "Does this apply to all branches nationwide? Looking forward to your reply.",
            "First time seeing this feature, very impressed! 🚀",
            "Sana all! Always supporting this page and community! ❤️",
            "Great initiative! Hope more organizations follow this standard. 👏",
            "Following this thread for future announcements! 🔔",
            "Well deserved! More blessings and success to your entire team! ✨",
            "Thank you admin for addressing our questions promptly."
        ]

        base_time = datetime(2026, 9, 10, 8, 0, 0, tzinfo=timezone.utc)
        comments: List[Comment] = []

        start_index = (page_num - 1) * items_per_page
        for i in range(items_per_page):
            global_idx = start_index + i
            # Increment timestamp by minutes/hours
            c_time = base_time + timedelta(minutes=global_idx * 14 + (i % 5))
            u_name = sample_users[global_idx % len(sample_users)]
            msg = sample_messages[global_idx % len(sample_messages)]
            c_id = f"demo_comment_{global_idx + 1}"

            comments.append(Comment(
                comment_id=c_id,
                user_name=u_name,
                message=f"#{global_idx + 1} - {msg}",
                created_time=c_time,
                parent_id=None
            ))

        if page_num < total_pages:
            next_after = f"cursor_page_{page_num + 1}"
            next_url = f"https://graph.facebook.com/v21.0/{post_id}/comments?after={next_after}"
        else:
            next_after = None
            next_url = None

        return comments, next_url, next_after, total_comments

