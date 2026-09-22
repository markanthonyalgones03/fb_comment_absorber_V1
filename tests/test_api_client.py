"""
Unit tests for FacebookApiClient with mocked Meta Graph API responses.
Verifies error code mappings, token expiration, permission denials,
rate-limits, pagination decoding, and post ID resolution.
"""

from unittest.mock import patch, MagicMock
import pytest
import requests

from app.facebook_api import FacebookApiClient
from app.models import (
    AuthenticationExpiredError,
    PermissionDeniedError,
    PostNotFoundError,
    RateLimitError,
    NetworkError,
)


class TestFacebookApiClientErrors:

    def test_missing_token_raises_error(self):
        with pytest.raises(AuthenticationExpiredError):
            FacebookApiClient(access_token="")

        with pytest.raises(AuthenticationExpiredError):
            FacebookApiClient(access_token="   ")

    @patch("requests.Session.get")
    def test_token_expired_error_190(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {
            "error": {
                "message": "Error validating access token: Session has expired.",
                "type": "OAuthException",
                "code": 190,
                "error_subcode": 463
            }
        }
        mock_get.return_value = mock_resp

        client = FacebookApiClient(access_token="test_token")
        with pytest.raises(AuthenticationExpiredError) as exc_info:
            client.get_comments_page("12345_67890")
        assert "Facebook authentication is required or has expired." in str(exc_info.value)

    @patch("requests.Session.get")
    def test_permission_denied_error_200(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.json.return_value = {
            "error": {
                "message": "(#200) Requires pages_read_user_content permission to manage the object",
                "type": "OAuthException",
                "code": 200
            }
        }
        mock_get.return_value = mock_resp

        client = FacebookApiClient(access_token="test_token")
        with pytest.raises(PermissionDeniedError) as exc_info:
            client.get_comments_page("12345_67890")
        assert "Facebook/Meta does not allow this application to access comments" in str(exc_info.value)

    @patch("requests.Session.get")
    def test_unmanaged_page_disguised_as_code_100(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {
            "error": {
                "message": "Unsupported get request. Object with ID '12345' does not exist, cannot be loaded due to missing permissions, or does not support this operation.",
                "type": "GraphMethodException",
                "code": 100
            }
        }
        mock_get.return_value = mock_resp

        client = FacebookApiClient(access_token="test_token")
        with pytest.raises(PermissionDeniedError) as exc_info:
            client.get_comments_page("12345")
        assert "Facebook/Meta does not allow this application to access comments" in str(exc_info.value)

    @patch("requests.Session.get")
    def test_nonexistent_post_code_100(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.json.return_value = {
            "error": {
                "message": "Object does not exist.",
                "type": "GraphMethodException",
                "code": 100
            }
        }
        mock_get.return_value = mock_resp

        client = FacebookApiClient(access_token="test_token")
        with pytest.raises(PostNotFoundError) as exc_info:
            client.get_comments_page("12345_99999")
        assert "The Facebook post could not be found or the URL is invalid." in str(exc_info.value)

    @patch("requests.Session.get")
    def test_rate_limit_error_613(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {
            "error": {
                "message": "(#613) Calls to this api have exceeded the rate limit.",
                "type": "OAuthException",
                "code": 613
            }
        }
        mock_get.return_value = mock_resp

        client = FacebookApiClient(access_token="test_token")
        with pytest.raises(RateLimitError) as exc_info:
            client.get_comments_page("12345_67890")
        assert "Facebook temporarily limited requests." in str(exc_info.value)

    @patch("requests.Session.get")
    def test_network_connection_error(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("Failed to establish a new connection")

        client = FacebookApiClient(access_token="test_token")
        with pytest.raises(NetworkError) as exc_info:
            client.get_comments_page("12345_67890")
        assert "Unable to connect to Facebook. Check your internet connection" in str(exc_info.value)


class TestFacebookApiClientDataParsing:

    @patch("requests.Session.get")
    def test_get_comments_page_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {
                    "id": "comment_1",
                    "from": {"id": "user_1", "name": "Maria Santos"},
                    "message": "Gandang gabi! Very informative post 👍",
                    "created_time": "2026-09-12T10:15:30+0000"
                },
                {
                    "id": "comment_2",
                    # Privacy restricted: No 'from' name
                    "message": "Nice one!",
                    "created_time": "2026-09-12T10:20:00+0000"
                }
            ],
            "paging": {
                "cursors": {
                    "before": "QVFIUk...",
                    "after": "QVFIUl..."
                },
                "next": "https://graph.facebook.com/v21.0/123_456/comments?after=QVFIUl..."
            },
            "summary": {
                "total_count": 2
            }
        }
        mock_get.return_value = mock_resp

        client = FacebookApiClient(access_token="test_token")
        comments, next_url, after_cursor, total = client.get_comments_page("123_456")

        assert len(comments) == 2
        assert comments[0].comment_id == "comment_1"
        assert comments[0].user_name == "Maria Santos"
        assert comments[0].message == "Gandang gabi! Very informative post 👍"
        assert comments[1].comment_id == "comment_2"
        # User name should fallback to "Facebook User"
        assert comments[1].user_name == "Facebook User"

        assert next_url == "https://graph.facebook.com/v21.0/123_456/comments?after=QVFIUl..."
        assert after_cursor == "QVFIUl..."
        assert total == 2


class TestPostIdResolution:

    @patch("requests.Session.get")
    def test_resolve_permalink_post_id(self, mock_get):
        # When checking node accessibility, return 200 OK
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "228735667216_1015928374"}
        mock_get.return_value = mock_resp

        client = FacebookApiClient(access_token="test_token")
        url = "https://www.facebook.com/permalink.php?story_fbid=1015928374&id=228735667216"
        post_id = client.resolve_post_id(url)
        assert post_id == "228735667216_1015928374"


class TestDemoFacebookApiClient:

    def test_demo_client_workflow(self):
        from app.facebook_api import DemoFacebookApiClient
        demo_client = DemoFacebookApiClient()
        post_id = demo_client.resolve_post_id("https://www.facebook.com/NASA/posts/1015948291029384")
        assert "demo" in post_id

        # Page 1
        comments, next_url, next_after, total = demo_client.get_comments_page(post_id)
        assert len(comments) == 30
        assert next_url is not None
        assert next_after == "cursor_page_2"
        assert total == 150
        assert "Maria Santos" in [c.user_name for c in comments]

        # Final page
        comments_5, next_url_5, next_after_5, _ = demo_client.get_comments_page(post_id, after_cursor="cursor_page_5")
        assert len(comments_5) == 30
        assert next_url_5 is None
        assert next_after_5 is None

