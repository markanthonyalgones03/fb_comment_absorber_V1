"""
Flask Web Application Server for Comment Absorber
High-performance REST API & Server-Sent Events (SSE) streaming server.
Supports multi-user sessions, official Meta OAuth 2.0 (Facebook Login),
and isolated per-user comment collection.
"""

import os
import sys
import time
import json
import queue
import secrets
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
from urllib.parse import urlencode

from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    Response,
    send_file,
    redirect,
    g,
    has_request_context,
)
from flask_cors import CORS

# Ensure root directory is on sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from web_collector import (
    WebComment,
    clean_facebook_url,
    RealBrowserCommentCollector,
    SimulatorCollector,
    ExcelReportExporter,
    sanitize_for_excel,
)

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = os.environ.get("SESSION_SECRET") or secrets.token_hex(32)
CORS(app, resources={r"/*": {"origins": "*"}})

SESSION_COOKIE_NAME = "ca_session_id"

NETWORK_INFO: Dict[str, str] = {
    "local_url": "http://127.0.0.1:5000",
    "wifi_url": "",
    "public_url": "",
}


# ============================================================================
# Meta Graph API Collector (Uses Authenticated User's Access Token)
# ============================================================================

class MetaGraphApiCollector:
    """
    Collects comments directly from official Meta Graph API v21.0.
    Communicates server-to-server with Facebook using the authenticated user's access token.
    """
    def __init__(self, access_token: str, on_comment: Any, on_status: Any):
        self.access_token = access_token
        self.on_comment = on_comment
        self.on_status = on_status
        self.is_cancelled = False

    def cancel(self):
        self.is_cancelled = True

    def run(self, raw_url: str):
        self.on_status("CONNECTING", {"message": "Connecting to Meta Graph API..."})
        try:
            from app.facebook_api import FacebookApiClient
            from app.utils import clean_facebook_url
            from app.models import (
                AppError,
                InvalidUrlError,
                PostNotFoundError,
                PermissionDeniedError,
                AuthenticationExpiredError,
                RateLimitError,
                NetworkError,
            )

            client = FacebookApiClient(access_token=self.access_token)
            clean_url = clean_facebook_url(raw_url)
            self.on_status("ACCESSING", {"message": "Resolving Facebook post identifier..."})
            post_id = client.resolve_post_id(clean_url)

            self.on_status("COLLECTING", {"message": f"Fetching comments for post {post_id}..."})

            next_url = None
            after_cursor = None
            count = 0

            palette = [
                "#1877F2", "#10B981", "#6366F1", "#EC4899", 
                "#F59E0B", "#8B5CF6", "#06B6D4", "#14B8A6"
            ]

            while not self.is_cancelled:
                comments, next_url, after_cursor, total_reported = client.get_comments_page(
                    post_id=post_id,
                    after_cursor=after_cursor,
                    next_page_url=next_url,
                    limit=100
                )

                if not comments and count == 0:
                    self.on_status("COMPLETED", {"message": "No comments found on this post (or comments are restricted)."})
                    return

                for c in comments:
                    if self.is_cancelled:
                        break
                    count += 1
                    parts = [p for p in (c.user_name or "").split() if p]
                    if len(parts) >= 2:
                        initials = (parts[0][0] + parts[1][0]).upper()
                    elif len(parts) == 1:
                        initials = parts[0][:2].upper()
                    else:
                        initials = "FB"
                    color = palette[sum(ord(ch) for ch in (c.user_name or "FB")) % len(palette)]

                    created_str = c.created_time.strftime("%Y-%m-%d %H:%M:%S") if hasattr(c.created_time, "strftime") else str(c.created_time or "")
                    timestamp_raw = c.created_time.timestamp() if hasattr(c.created_time, "timestamp") else time.time()

                    web_comment = WebComment(
                        index=count,
                        comment_id=str(c.comment_id),
                        user_name=c.user_name or "Facebook User",
                        message=c.message or "",
                        created_time=created_str,
                        timestamp_raw=timestamp_raw,
                        avatar_color=color,
                        avatar_initials=initials
                    )
                    self.on_comment(web_comment)

                if not next_url and not after_cursor:
                    break
                if not comments:
                    break

                time.sleep(0.1)

            if self.is_cancelled:
                self.on_status("CANCELLED", {"message": f"Collection stopped by user. {count} comments absorbed."})
            else:
                self.on_status("COMPLETED", {"message": f"Successfully absorbed {count} comments via Meta Graph API."})

        except PermissionDeniedError:
            if "/share/" in raw_url:
                msg = (
                    "This mobile share link (/share/p/) cannot be resolved through the Meta API. "
                    "Please open the post in your browser and copy the direct post URL (e.g. facebook.com/PageName/posts/...)."
                )
            else:
                msg = "Meta does not allow this post to be accessed with your current Facebook permissions."
            self.on_status("ERROR", {"message": msg})
        except PostNotFoundError:
            if "/share/" in raw_url:
                msg = (
                    "This mobile share link (/share/p/) cannot be resolved through the Meta API. "
                    "Please open the post in your browser and copy the direct post URL (e.g. facebook.com/PageName/posts/...)."
                )
            else:
                msg = "Facebook post not found. Please verify the URL and ensure the post is publicly accessible."
            self.on_status("ERROR", {"message": msg})
        except AuthenticationExpiredError:
            self.on_status("ERROR", {
                "message": "Your Facebook login session has expired. Please log in again with Facebook."
            })
        except RateLimitError:
            self.on_status("ERROR", {
                "message": "Facebook API rate limit reached. Please wait a few minutes before trying again."
            })
        except InvalidUrlError:
            self.on_status("ERROR", {
                "message": "Invalid Facebook URL format. Please provide a standard Facebook post, video, or reel link."
            })
        except NetworkError as e:
            self.on_status("ERROR", {
                "message": f"Network error communicating with Meta Graph API: {str(e)}"
            })
        except Exception as e:
            self.on_status("ERROR", {
                "message": f"Meta Graph API error: {str(e)}"
            })


# ============================================================================
# Collection Session (Per-User Comment State & Streaming Queues)
# ============================================================================

class CollectionSession:
    def __init__(self):
        self.lock = threading.RLock()
        self.status = "IDLE"
        self.message = "System ready. Paste your Facebook post URL to collect comments."
        self.comments: List[WebComment] = []
        self.seen_ids = set()
        self.unique_authors = set()
        self.current_collector = None
        self.worker_thread: Optional[threading.Thread] = None
        self.start_time: Optional[float] = None
        self.last_comment: Optional[WebComment] = None
        self.event_queues: List[queue.Queue] = []
        self.mode = "api"
        self.post_url = ""

    def add_event_queue(self) -> queue.Queue:
        q = queue.Queue(maxsize=500)
        with self.lock:
            self.event_queues.append(q)
        return q

    def remove_event_queue(self, q: queue.Queue):
        with self.lock:
            if q in self.event_queues:
                self.event_queues.remove(q)

    def broadcast(self, event_type: str, data: Any):
        payload = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
        with self.lock:
            for q in list(self.event_queues):
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    pass

    def on_new_comment(self, comment: WebComment):
        with self.lock:
            self.comments.append(comment)
            self.seen_ids.add(comment.comment_id)
            self.unique_authors.add(comment.user_name)
            self.last_comment = comment

        # Stream comment immediately to connected browser queues for this session
        self.broadcast("comment", {
            "comment": comment.to_dict(),
            "stats": self.get_stats_dict()
        })

    def on_status_change(self, status: str, details: Dict[str, Any]):
        with self.lock:
            self.status = status
            self.message = details.get("message", "")
        self.broadcast("status", {
            "status": self.status,
            "message": self.message,
            "stats": self.get_stats_dict()
        })

    def get_stats_dict(self) -> Dict[str, Any]:
        with self.lock:
            count = len(self.comments)
            unique = len(self.unique_authors)
            elapsed = 0.0
            cps = 0.0
            if self.start_time:
                elapsed = max(0.1, time.time() - self.start_time)
                cps = round(count / elapsed, 1)

            return {
                "count": count,
                "unique_authors": unique,
                "elapsed_seconds": round(elapsed, 1),
                "comments_per_sec": cps,
                "status": self.status,
                "message": self.message,
                "latest_comment": self.last_comment.to_dict() if self.last_comment else None
            }

    def start(self, url: str, mode: str = "api", user_token: Optional[str] = None, max_comments: int = 150, speed: float = 0.25):
        with self.lock:
            if self.status in ("CONNECTING", "ACCESSING", "COLLECTING"):
                return False, "Collection is already running."

            self.status = "CONNECTING"
            self.message = "Initializing comment extraction..."
            self.comments.clear()
            self.seen_ids.clear()
            self.unique_authors.clear()
            self.last_comment = None
            self.start_time = time.time()
            self.mode = mode
            self.post_url = url

        self.broadcast("status", {
            "status": self.status,
            "message": self.message,
            "stats": self.get_stats_dict()
        })

        def _worker():
            try:
                if mode == "simulator":
                    collector = SimulatorCollector(
                        on_comment=self.on_new_comment,
                        on_status=self.on_status_change
                    )
                    self.current_collector = collector
                    collector.run(url, max_comments=max_comments, speed=speed)
                elif mode == "api":
                    if not user_token:
                        self.on_status_change("ERROR", {
                            "message": "Please log in with Facebook first to collect comments."
                        })
                        return
                    collector = MetaGraphApiCollector(
                        access_token=user_token,
                        on_comment=self.on_new_comment,
                        on_status=self.on_status_change
                    )
                    self.current_collector = collector
                    collector.run(url)
                else:
                    self.on_status_change("ERROR", {"message": f"Unknown mode: {mode}"})
            except Exception as e:
                self.on_status_change("ERROR", {"message": f"Collection error: {str(e)}"})
            finally:
                self.current_collector = None

        self.worker_thread = threading.Thread(target=_worker, daemon=True)
        self.worker_thread.start()
        return True, "Collection started."

    def stop(self):
        with self.lock:
            if self.current_collector:
                self.current_collector.cancel()
                self.status = "CANCELLED"
                self.message = "Collection stopped by user."
            else:
                self.status = "IDLE"
                self.message = "System ready."

        self.broadcast("status", {
            "status": self.status,
            "message": self.message,
            "stats": self.get_stats_dict()
        })
        return True, "Stopped."

    def clear(self):
        with self.lock:
            if self.status in ("CONNECTING", "ACCESSING", "COLLECTING"):
                if self.current_collector:
                    self.current_collector.cancel()
            self.comments.clear()
            self.seen_ids.clear()
            self.unique_authors.clear()
            self.last_comment = None
            self.start_time = None
            self.status = "IDLE"
            self.message = "Feed cleared. Paste your Facebook post URL to begin."

        self.broadcast("clear", {
            "status": self.status,
            "stats": self.get_stats_dict()
        })
        return True, "Cleared."


# ============================================================================
# Multi-User Session Registry (Zero Global Credential Sharing)
# ============================================================================

class UserSessionData:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.is_authenticated = False
        self.user_id: Optional[str] = None
        self.user_name: Optional[str] = None
        self.user_picture: Optional[str] = None
        self.access_token: Optional[str] = None
        self.token_expires_at: Optional[float] = None
        self.oauth_state: Optional[str] = None
        self.collection_session = CollectionSession()
        self.created_at = time.time()
        self.last_active = time.time()

    def touch(self):
        self.last_active = time.time()

    def logout(self):
        self.is_authenticated = False
        self.user_id = None
        self.user_name = None
        self.user_picture = None
        self.access_token = None
        self.token_expires_at = None
        self.oauth_state = None
        self.collection_session.clear()

    def to_user_dict(self) -> Dict[str, Any]:
        """Safe dict returned to frontend — NEVER exposes access_token."""
        return {
            "authenticated": self.is_authenticated,
            "user": {
                "id": self.user_id,
                "name": self.user_name,
                "picture": self.user_picture,
            } if self.is_authenticated else None,
        }


class UserSessionManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._sessions: Dict[str, UserSessionData] = {}

    def get_or_create(self, session_id: Optional[str]) -> UserSessionData:
        with self._lock:
            self._cleanup_stale()
            if session_id and session_id in self._sessions:
                sess = self._sessions[session_id]
                sess.touch()
                return sess
            new_id = session_id.strip() if (session_id and session_id.strip()) else secrets.token_urlsafe(32)
            sess = UserSessionData(session_id=new_id)
            self._sessions[new_id] = sess
            return sess

    def get(self, session_id: Optional[str]) -> Optional[UserSessionData]:
        if not session_id:
            return None
        with self._lock:
            return self._sessions.get(session_id)

    def delete(self, session_id: Optional[str]):
        if not session_id:
            return
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].logout()
                del self._sessions[session_id]

    def _cleanup_stale(self):
        now = time.time()
        stale_keys = [k for k, v in self._sessions.items() if (now - v.last_active) > 172800]
        for k in stale_keys:
            try:
                self._sessions[k].logout()
                del self._sessions[k]
            except Exception:
                pass


user_manager = UserSessionManager()
default_test_session = CollectionSession()


def get_current_user_session() -> UserSessionData:
    if hasattr(g, "user_session") and g.user_session is not None:
        return g.user_session

    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    auth_header = request.headers.get("X-Session-ID") or request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        session_id = auth_header.replace("Bearer ", "").strip()
    elif auth_header:
        session_id = auth_header.strip()

    sess = user_manager.get_or_create(session_id)
    g.user_session = sess
    return sess


@app.after_request
def add_session_and_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, PUT, DELETE"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With, X-Session-ID"
    response.headers["Access-Control-Allow-Private-Network"] = "true"

    if hasattr(g, "user_session") and g.user_session:
        current_cookie = request.cookies.get(SESSION_COOKIE_NAME)
        if current_cookie != g.user_session.session_id:
            is_secure = request.is_secure or request.headers.get("X-Forwarded-Proto") == "https"
            response.set_cookie(
                SESSION_COOKIE_NAME,
                g.user_session.session_id,
                max_age=86400 * 30,
                httponly=True,
                samesite="Lax",
                secure=is_secure
            )
    return response


class SessionProxy:
    """
    Backwards-compatible proxy delegating to the current user's CollectionSession
    within HTTP request contexts, or to a default session for unit tests.
    """
    def clear(self):
        default_test_session.clear()
        if has_request_context():
            return get_current_user_session().collection_session.clear()
        return True, "Cleared."

    def on_new_comment(self, comment):
        default_test_session.on_new_comment(comment)
        if has_request_context():
            get_current_user_session().collection_session.on_new_comment(comment)

    def __getattr__(self, name):
        if has_request_context():
            sess = get_current_user_session().collection_session
            if app.config.get("TESTING") and not sess.comments and default_test_session.comments:
                return getattr(default_test_session, name)
            return getattr(sess, name)
        return getattr(default_test_session, name)


session = SessionProxy()


# ============================================================================
# Routes & API Endpoints
# ============================================================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/network/info", methods=["GET"])
def api_network_info():
    return jsonify(NETWORK_INFO)


@app.route("/api/health", methods=["GET"])
def api_health():
    """Health check endpoint for cloud platforms and frontend connectivity test."""
    return jsonify({
        "status": "ok",
        "service": "Comment Absorber API",
        "timestamp": time.time()
    })


# ============================================================================
# Meta OAuth 2.0 (Facebook Login) Endpoints
# ============================================================================

@app.route("/auth/facebook/login", methods=["GET"])
def auth_facebook_login():
    """Initiates official Meta OAuth 2.0 dialog for the requesting user."""
    app_id = os.environ.get("META_APP_ID", "").strip()
    if not app_id:
        return (
            "<h3>Facebook Login Not Configured</h3>"
            "<p>The administrator has not configured <code>META_APP_ID</code> and <code>META_APP_SECRET</code> in the cloud environment.</p>"
            "<p><a href='/'>Return to Comment Absorber</a></p>",
            503
        )

    user_session = get_current_user_session()
    oauth_state = secrets.token_urlsafe(24)
    user_session.oauth_state = oauth_state

    redirect_uri = os.environ.get("META_REDIRECT_URI", "").strip()
    if not redirect_uri:
        scheme = "https" if (request.is_secure or request.headers.get("X-Forwarded-Proto") == "https") else request.scheme
        redirect_uri = f"{scheme}://{request.host}/auth/facebook/callback"

    scope = "public_profile,user_posts"

    params = {
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "state": oauth_state,
        "scope": scope,
        "response_type": "code"
    }
    fb_auth_url = f"https://www.facebook.com/v21.0/dialog/oauth?{urlencode(params)}"
    return redirect(fb_auth_url)


@app.route("/auth/facebook/callback", methods=["GET"])
def auth_facebook_callback():
    """Handles OAuth 2.0 redirect callback, exchanges code for user access token."""
    error = request.args.get("error")
    error_desc = request.args.get("error_description", "Authentication was cancelled or failed.")
    if error:
        return redirect(f"/?auth_error={error_desc}")

    code = request.args.get("code")
    state = request.args.get("state")
    user_session = get_current_user_session()

    if not code:
        return redirect("/?auth_error=No authorization code received from Facebook.")

    if not user_session.oauth_state or state != user_session.oauth_state:
        return redirect("/?auth_error=Invalid security state. Please try logging in again.")

    app_id = os.environ.get("META_APP_ID", "").strip()
    app_secret = os.environ.get("META_APP_SECRET", "").strip()
    redirect_uri = os.environ.get("META_REDIRECT_URI", "").strip()
    if not redirect_uri:
        scheme = "https" if (request.is_secure or request.headers.get("X-Forwarded-Proto") == "https") else request.scheme
        redirect_uri = f"{scheme}://{request.host}/auth/facebook/callback"

    try:
        import requests
        token_url = "https://graph.facebook.com/v21.0/oauth/access_token"
        token_resp = requests.get(token_url, params={
            "client_id": app_id,
            "client_secret": app_secret,
            "redirect_uri": redirect_uri,
            "code": code
        }, timeout=10)

        token_data = token_resp.json()
        if "error" in token_data:
            err_msg = token_data["error"].get("message", "Failed to retrieve access token.")
            return redirect(f"/?auth_error={err_msg}")

        user_token = token_data.get("access_token")
        expires_in = token_data.get("expires_in", 3600)

        # Retrieve user identity to personalize their session
        me_resp = requests.get("https://graph.facebook.com/v21.0/me", params={
            "fields": "id,name,picture.type(large)",
            "access_token": user_token
        }, timeout=8)
        me_data = me_resp.json()

        user_id = me_data.get("id")
        user_name = me_data.get("name", "Facebook User")
        user_pic = me_data.get("picture", {}).get("data", {}).get("url", "")

        # Store ONLY on the secure server-side session
        user_session.is_authenticated = True
        user_session.user_id = user_id
        user_session.user_name = user_name
        user_session.user_picture = user_pic
        user_session.access_token = user_token
        user_session.token_expires_at = time.time() + expires_in

        return redirect("/?auth_success=1")

    except Exception as e:
        return redirect(f"/?auth_error=Failed to complete Facebook login: {str(e)}")


@app.route("/api/auth/me", methods=["GET"])
def api_auth_me():
    """Returns current user's authentication state without exposing secret tokens."""
    user_session = get_current_user_session()
    app_id = os.environ.get("META_APP_ID", "").strip()
    return jsonify({
        "authenticated": user_session.is_authenticated,
        "app_configured": bool(app_id),
        "user": {
            "id": user_session.user_id,
            "name": user_session.user_name,
            "picture": user_session.user_picture
        } if user_session.is_authenticated else None
    })


@app.route("/api/auth/logout", methods=["POST"])
def api_auth_logout():
    """Logs out the current user and invalidates their session and credentials."""
    user_session = get_current_user_session()
    user_session.logout()
    return jsonify({"success": True, "message": "Logged out successfully."})


@app.route("/api/auth/set-token", methods=["POST"])
def api_auth_set_token():
    """Developer / testing utility: sets an authorized token for the current isolated session."""
    data = request.get_json(silent=True) or {}
    token = data.get("access_token", "").strip()
    user_session = get_current_user_session()
    if not token:
        return jsonify({"status": "error", "message": "No access token provided."}), 400

    try:
        import requests
        resp = requests.get(
            "https://graph.facebook.com/v21.0/me",
            params={"fields": "id,name,picture", "access_token": token},
            timeout=5
        )
        user_data = resp.json()
        if "error" in user_data:
            return jsonify({
                "status": "error",
                "message": user_data["error"].get("message", "Invalid token")
            }), 400

        user_session.is_authenticated = True
        user_session.user_id = user_data.get("id")
        user_session.user_name = user_data.get("name")
        user_session.user_picture = user_data.get("picture", {}).get("data", {}).get("url", "")
        user_session.access_token = token
        return jsonify({
            "status": "ok",
            "user": {
                "id": user_session.user_id,
                "name": user_session.user_name
            }
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@app.route("/api/admin/status", methods=["GET"])
def api_admin_status():
    """Reports server status and whether Meta OAuth app credentials are configured."""
    app_id = os.environ.get("META_APP_ID", "").strip()
    user_session = get_current_user_session()
    has_app_id = bool(app_id)
    app_preview = f"{app_id[:4]}...{app_id[-4:]}" if has_app_id and len(app_id) > 8 else ("Configured" if has_app_id else "Not Configured")
    return jsonify({
        "backend_online": True,
        "api_version": "v21.0",
        "app_id_configured": has_app_id,
        "app_preview": app_preview,
        "meta_token_configured": user_session.is_authenticated or has_app_id,
        "user_authenticated": user_session.is_authenticated,
        "user_name": user_session.user_name if user_session.is_authenticated else None
    })


# ============================================================================
# Collection API Endpoints (Operates on the Current User's Session)
# ============================================================================

@app.route("/api/collect/start", methods=["POST"])
def api_start_collect():
    user_session = get_current_user_session()
    data = request.get_json(silent=True) or {}
    url = data.get("url", "").strip()
    mode = data.get("mode", "api")
    max_comments = int(data.get("max_comments", 150))
    speed = float(data.get("speed", 0.25))

    if mode == "simulator":
        if not url:
            url = "https://www.facebook.com/demo/posts/1000"
        ok, msg = user_session.collection_session.start(
            url=url,
            mode="simulator",
            max_comments=max_comments,
            speed=speed
        )
        return jsonify({"success": ok, "status": "ok" if ok else "error", "message": msg, "clean_url": url})

    # For real API collection, user MUST be authenticated with their own Facebook account
    if not url:
        return jsonify({"status": "error", "error": "Please paste a Facebook post URL first."}), 400

    try:
        url = clean_facebook_url(url)
    except Exception as e:
        return jsonify({"status": "error", "error": f"Invalid URL: {str(e)}"}), 400

    if not user_session.is_authenticated or not user_session.access_token:
        return jsonify({
            "status": "error",
            "error": "Please log in with Facebook first to collect comments with your account.",
            "message": "Please log in with Facebook first to collect comments with your account."
        }), 401

    ok, msg = user_session.collection_session.start(
        url=url,
        mode="api",
        user_token=user_session.access_token,
        max_comments=max_comments,
        speed=speed
    )
    if ok:
        return jsonify({"success": True, "status": "ok", "message": msg, "clean_url": url})
    return jsonify({"success": False, "status": "error", "error": msg}), 400


@app.route("/api/collect/stop", methods=["POST"])
def api_stop_collect():
    user_session = get_current_user_session()
    success, msg = user_session.collection_session.stop()
    return jsonify({"success": success, "message": msg})


@app.route("/api/collect/clear", methods=["POST"])
def api_clear_collect():
    user_session = get_current_user_session()
    success, msg = user_session.collection_session.clear()
    return jsonify({"success": success, "message": msg})


@app.route("/api/collect/state", methods=["GET"])
def api_get_state():
    user_session = get_current_user_session()
    with user_session.collection_session.lock:
        return jsonify({
            "comments": [c.to_dict() for c in user_session.collection_session.comments],
            "stats": user_session.collection_session.get_stats_dict()
        })


@app.route("/api/collect/stream")
def api_stream():
    """Server-Sent Events endpoint for real-time push streaming to the current user."""
    user_session = get_current_user_session()
    sess = user_session.collection_session
    q = sess.add_event_queue()

    def event_stream():
        try:
            with sess.lock:
                stats = sess.get_stats_dict()
                comments = [c.to_dict() for c in sess.comments]
            init_payload = json.dumps({
                "stats": stats,
                "comments": comments
            })
            yield f"event: init\ndata: {init_payload}\n\n"

            while True:
                try:
                    msg = q.get(timeout=25.0)
                    yield msg
                except queue.Empty:
                    yield ": ping\n\n"
        except (GeneratorExit, Exception):
            pass
        finally:
            sess.remove_event_queue(q)

    resp = Response(event_stream(), mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache, no-transform, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    resp.headers["X-Accel-Buffering"] = "no"
    resp.headers["Connection"] = "keep-alive"
    return resp


@app.route("/api/export/excel", methods=["GET"])
def api_export_excel():
    user_session = get_current_user_session()
    sess = user_session.collection_session
    with sess.lock:
        comments_copy = list(sess.comments)

    if not comments_copy and app.config.get("TESTING"):
        with default_test_session.lock:
            comments_copy = list(default_test_session.comments)

    if not comments_copy:
        return jsonify({"error": "No comments available to export."}), 400

    sort_order = request.args.get("sort", "oldest")
    include_names = request.args.get("include_names", "true").lower() not in ("false", "0", "no")
    exports_dir = Path(__file__).parent / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = "Facebook_Comments" if include_names else "Facebook_Comments_No_Names"
    filename = f"{prefix}_{timestamp_str}.xlsx"
    file_path = exports_dir / filename

    ExcelReportExporter.export(comments_copy, file_path, sort_order=sort_order, include_names=include_names)

    return send_file(
        str(file_path.resolve()),
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@app.route("/api/export/csv", methods=["GET"])
def api_export_csv():
    user_session = get_current_user_session()
    sess = user_session.collection_session
    with sess.lock:
        comments_copy = list(sess.comments)

    if not comments_copy and app.config.get("TESTING"):
        with default_test_session.lock:
            comments_copy = list(default_test_session.comments)

    if not comments_copy:
        return jsonify({"error": "No comments available to export."}), 400

    sort_order = request.args.get("sort", "oldest")
    if sort_order == "oldest":
        sorted_comments = sorted(comments_copy, key=lambda c: c.timestamp_raw)
    else:
        sorted_comments = sorted(comments_copy, key=lambda c: c.timestamp_raw, reverse=True)

    lines = ['"User","Comment","Date"']
    for c in sorted_comments:
        u = sanitize_for_excel(c.user_name).replace('"', '""')
        m = sanitize_for_excel(c.message).replace('"', '""')
        d = sanitize_for_excel(c.created_time)
        lines.append(f'"{u}","{m}","{d}"')

    csv_data = "\r\n".join(lines).encode("utf-8-sig")
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"Facebook_Comments_{timestamp_str}.csv"

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting Comment Absorber Web on http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False)
