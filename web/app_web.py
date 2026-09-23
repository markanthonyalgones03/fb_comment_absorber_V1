"""
Flask Web Application Server for Comment Absorber
High-performance REST API & Server-Sent Events (SSE) streaming server.
"""

import os
import sys
import time
import json
import queue
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from flask import Flask, render_template, request, jsonify, Response, send_file
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
CORS(app, resources={r"/*": {"origins": "*"}})

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, PUT, DELETE"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
    response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response

NETWORK_INFO: Dict[str, str] = {
    "local_url": "http://127.0.0.1:5000",
    "wifi_url": "",
    "public_url": "",
}

@app.route("/api/network/info", methods=["GET"])
def api_network_info():
    return jsonify(NETWORK_INFO)



class MetaGraphApiCollector:
    """
    Collects comments directly from official Meta Graph API v21.0.
    Communicates server-to-server with Facebook using the server's META_ACCESS_TOKEN.
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
            self.on_status("ERROR", {
                "message": "This post cannot be accessed by the Meta Graph API. Please ensure the post is public and your Meta token has permissions to read comments on this Page or post."
            })
        except PostNotFoundError:
            self.on_status("ERROR", {
                "message": "Facebook post not found. Please verify the URL and ensure the post is publicly accessible."
            })
        except AuthenticationExpiredError:
            self.on_status("ERROR", {
                "message": "The Meta Access Token has expired or is invalid. Please update META_ACCESS_TOKEN on the server."
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

        # Stream comment immediately to all connected browsers
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

    def start(self, url: str, mode: str = "api", max_comments: int = 150, speed: float = 0.25):
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
                elif mode in ("api", "browser"):
                    # Check for server-side Meta Access Token
                    from app.config import load_config
                    cfg = load_config()
                    token = os.environ.get("META_ACCESS_TOKEN") or cfg.access_token
                    if token and token.strip():
                        collector = MetaGraphApiCollector(
                            access_token=token.strip(),
                            on_comment=self.on_new_comment,
                            on_status=self.on_status_change
                        )
                        self.current_collector = collector
                        collector.run(url)
                    elif mode == "browser":
                        # Local desktop fallback using browser profile
                        collector = RealBrowserCommentCollector(
                            on_comment=self.on_new_comment,
                            on_status=self.on_status_change
                        )
                        self.current_collector = collector
                        collector.run(url)
                    else:
                        self.on_status_change("ERROR", {
                            "message": "Meta Access Token is not configured on the server. Please set the META_ACCESS_TOKEN environment variable in your cloud deployment settings."
                        })
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


session = CollectionSession()


# --- Routes ---

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/auth/status")
def api_auth_status():
    """Checks whether the persistent browser profile has active Facebook cookies."""
    try:
        collector = RealBrowserCommentCollector(lambda c: None, lambda s, d: None)
        logged = collector.is_logged_in()
        return jsonify({"logged_in": logged})
    except Exception as e:
        return jsonify({"logged_in": False, "error": str(e)})


@app.route("/api/auth/login", methods=["POST"])
def api_auth_login():
    """Opens a visible browser window allowing the user to sign in to Facebook."""
    def _login_thread():
        try:
            collector = RealBrowserCommentCollector(lambda c: None, lambda s, d: None)
            res = collector.open_login_window()
            if res or collector.is_logged_in():
                session.broadcast("auth", {"logged_in": True, "message": "Facebook login verified!"})
                session.broadcast("status", {
                    "status": "IDLE",
                    "message": "Facebook account verified! Paste your post link and click Start Collecting.",
                    "stats": session.get_stats_dict()
                })
        except Exception:
            pass

    threading.Thread(target=_login_thread, daemon=True).start()
    return jsonify({"success": True, "message": "Opening Facebook login window in browser..."})


@app.route("/api/health", methods=["GET"])
def api_health():
    """Health check endpoint for cloud platforms and frontend connectivity test."""
    return jsonify({
        "status": "ok",
        "service": "Comment Absorber API",
        "timestamp": time.time()
    })


@app.route("/api/admin/status", methods=["GET"])
def api_admin_status():
    """Reports server and Meta API connection status without exposing secrets."""
    from app.config import load_config
    cfg = load_config()
    token = os.environ.get("META_ACCESS_TOKEN") or cfg.access_token
    has_token = bool(token and token.strip())
    token_preview = f"{token[:6]}...{token[-4:]}" if has_token and len(token) > 12 else ("Configured" if has_token else "Not Configured")
    return jsonify({
        "backend_online": True,
        "meta_token_configured": has_token,
        "token_preview": token_preview,
        "api_version": "v21.0"
    })


@app.route("/api/admin/test-token", methods=["POST"])
def api_test_token():
    """Tests the server's Meta Access Token (or a provided token) against Graph API."""
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    if not token:
        from app.config import load_config
        token = os.environ.get("META_ACCESS_TOKEN") or load_config().access_token

    if not token or not token.strip():
        return jsonify({
            "success": False,
            "error": "No Meta Access Token configured on the server. Please set META_ACCESS_TOKEN in environment variables."
        }), 400

    try:
        from app.facebook_api import FacebookApiClient
        client = FacebookApiClient(access_token=token.strip())
        info = client._get("/me", params={"fields": "id,name"})
        name = info.get("name", "Authorized Account")
        acct_id = info.get("id", "N/A")
        return jsonify({
            "success": True,
            "message": f"Connected to Meta Graph API v21.0! Verified account: {name} (ID: {acct_id})."
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": f"Meta Graph API connection failed: {str(e)}"
        }), 400


@app.route("/api/collect/start", methods=["POST"])
def api_start_collect():
    data = request.get_json() or {}
    url = data.get("url", "").strip()
    mode = data.get("mode", "api") # DEFAULT TO OFFICIAL META GRAPH API
    max_comments = int(data.get("max_comments", 150))
    speed = float(data.get("speed", 0.25))

    if mode in ("api", "browser"):
        if not url:
            return jsonify({"success": False, "error": "Please paste a Facebook post URL first."}), 400
        try:
            url = clean_facebook_url(url)
        except Exception as e:
            return jsonify({"success": False, "error": f"Invalid URL: {str(e)}"}), 400
    else:
        # Simulator fallback url
        if not url:
            url = "https://www.facebook.com/demo/posts/1000"

    success, msg = session.start(url=url, mode=mode, max_comments=max_comments, speed=speed)
    if success:
        return jsonify({"success": True, "message": msg, "clean_url": url})
    return jsonify({"success": False, "error": msg}), 400


@app.route("/api/collect/stop", methods=["POST"])
def api_stop_collect():
    success, msg = session.stop()
    return jsonify({"success": success, "message": msg})


@app.route("/api/collect/clear", methods=["POST"])
def api_clear_collect():
    success, msg = session.clear()
    return jsonify({"success": success, "message": msg})


@app.route("/api/collect/state", methods=["GET"])
def api_get_state():
    with session.lock:
        return jsonify({
            "comments": [c.to_dict() for c in session.comments],
            "stats": session.get_stats_dict()
        })


@app.route("/api/collect/stream")
def api_stream():
    """Server-Sent Events endpoint for real-time push streaming to the browser."""
    def event_stream():
        q = session.add_event_queue()
        try:
            with session.lock:
                stats = session.get_stats_dict()
                comments = [c.to_dict() for c in session.comments]
            init_payload = json.dumps({
                "stats": stats,
                "comments": comments
            })
            yield f"event: init\ndata: {init_payload}\n\n"

            while True:
                try:
                    msg = q.get(timeout=4.0)
                    yield msg
                except queue.Empty:
                    yield ": ping\n\n"
        except (GeneratorExit, Exception):
            pass
        finally:
            session.remove_event_queue(q)

    resp = Response(event_stream(), mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache, no-transform, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    resp.headers["X-Accel-Buffering"] = "no"
    resp.headers["Connection"] = "keep-alive"
    return resp


@app.route("/api/export/excel", methods=["GET"])
def api_export_excel():
    with session.lock:
        comments_copy = list(session.comments)

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
    with session.lock:
        comments_copy = list(session.comments)

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
