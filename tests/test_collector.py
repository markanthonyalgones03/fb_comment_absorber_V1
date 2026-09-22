"""
Unit tests for CommentCollector orchestrator.
Verifies cursor pagination, deduplication, cancellation,
progress callbacks, and partial collections.
"""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from app.comment_collector import CommentCollector
from app.models import Comment, CollectionStatus, CollectionProgress, CollectionResult
from app.facebook_api import FacebookApiClient
from app.excel_exporter import ExcelExporter


def make_comment(cid: str, msg: str, ts_iso: str, user: str = "User") -> Comment:
    return Comment(
        comment_id=cid,
        user_name=user,
        message=msg,
        created_time=datetime.fromisoformat(ts_iso)
    )


class TestCommentCollectorPaginationAndDedup:

    def test_collects_across_pages_and_deduplicates(self, tmp_path):
        mock_api = MagicMock(spec=FacebookApiClient)
        mock_api.resolve_post_id.return_value = "123_456"

        # Page 1: comments 1 & 2, points to next page
        c1 = make_comment("1", "First", "2026-09-12T08:00:00+00:00")
        c2 = make_comment("2", "Second", "2026-09-12T08:05:00+00:00")

        # Page 2: comment 2 (duplicate overlap) & comment 3, end of pagination
        c2_dup = make_comment("2", "Second Dup", "2026-09-12T08:05:00+00:00")
        c3 = make_comment("3", "Third", "2026-09-12T08:10:00+00:00")

        mock_api.get_comments_page.side_effect = [
            ([c1, c2], "http://next_page", "cursor1", 3),
            ([c2_dup, c3], None, None, 3),
        ]

        mock_exporter = MagicMock(spec=ExcelExporter)
        mock_exporter.export.return_value = tmp_path / "test.xlsx"

        progress_events = []
        collector = CommentCollector(
            api_client=mock_api,
            exporter=mock_exporter,
            progress_callback=lambda p: progress_events.append(p),
            page_delay_seconds=0
        )

        res = collector.collect("https://www.facebook.com/page/posts/456")

        assert res.success is True
        assert res.status == CollectionStatus.COMPLETED
        # Exactly 3 unique comments (duplicate c2_dup was discarded)
        assert res.total_collected == 3
        assert len(res.comments) == 3
        assert [c.comment_id for c in res.comments] == ["1", "2", "3"]
        mock_exporter.export.assert_called_once()

    def test_cancellation_mid_stream(self, tmp_path):
        mock_api = MagicMock(spec=FacebookApiClient)
        mock_api.resolve_post_id.return_value = "123_456"

        c1 = make_comment("1", "First", "2026-09-12T08:00:00+00:00")
        c2 = make_comment("2", "Second", "2026-09-12T08:05:00+00:00")

        collector = None

        def side_effect_page(*args, **kwargs):
            # Simulate cancel button pressed during page 1
            if collector:
                collector.cancel()
            return ([c1, c2], "http://next_page", "cursor1", 100)

        mock_api.get_comments_page.side_effect = side_effect_page

        mock_exporter = MagicMock(spec=ExcelExporter)
        mock_exporter.export.return_value = tmp_path / "partial.xlsx"

        collector = CommentCollector(
            api_client=mock_api,
            exporter=mock_exporter,
            page_delay_seconds=0
        )

        res = collector.collect("https://www.facebook.com/page/posts/456")

        assert res.is_cancelled is True
        assert res.status == CollectionStatus.CANCELLED
        assert res.total_collected == 2
        assert "Collection stopped by user" in res.message
        # Partial export was triggered
        mock_exporter.export.assert_called_once()

    def test_handles_no_comments(self):
        mock_api = MagicMock(spec=FacebookApiClient)
        mock_api.resolve_post_id.return_value = "123_456"
        mock_api.get_comments_page.return_value = ([], None, None, 0)

        collector = CommentCollector(
            api_client=mock_api,
            page_delay_seconds=0
        )

        res = collector.collect("https://www.facebook.com/page/posts/456")

        assert res.success is False
        assert res.status == CollectionStatus.ERROR
        assert "no comments were available" in res.message

    def test_handles_mid_stream_error_as_partial_collection(self, tmp_path):
        mock_api = MagicMock(spec=FacebookApiClient)
        mock_api.resolve_post_id.return_value = "123_456"

        c1 = make_comment("1", "First", "2026-09-12T08:00:00+00:00")

        # Page 1 succeeds, Page 2 throws error
        mock_api.get_comments_page.side_effect = [
            ([c1], "http://next_page", "cursor1", 10),
            Exception("Rate limit reached on page 2")
        ]

        mock_exporter = MagicMock(spec=ExcelExporter)
        mock_exporter.export.return_value = tmp_path / "partial.xlsx"

        collector = CommentCollector(
            api_client=mock_api,
            exporter=mock_exporter,
            page_delay_seconds=0
        )

        res = collector.collect("https://www.facebook.com/page/posts/456")

        assert res.success is True
        assert res.is_partial is True
        assert res.total_collected == 1
        assert "Collection stopped because Facebook returned an error" in res.message
        assert "1 comments were successfully collected" in res.message

    def test_browser_collector_mode(self, tmp_path):
        mock_browser = MagicMock()
        c1 = make_comment("1", "Hello from web", "2026-09-12T08:00:00+00:00")
        mock_browser.collect.return_value = [c1]
        mock_exporter = MagicMock(spec=ExcelExporter)
        mock_exporter.export.return_value = tmp_path / "browser.xlsx"

        collector = CommentCollector(
            browser_collector=mock_browser,
            exporter=mock_exporter,
            page_delay_seconds=0
        )
        res = collector.collect("https://www.facebook.com/share/v/19VDqyKHSv/")
        assert res.success is True
        assert res.total_collected == 1
        assert res.status == CollectionStatus.COMPLETED
        mock_browser.collect.assert_called_once()
        mock_exporter.export.assert_called_once()

    def test_browser_collector_defensive_routing_when_passed_as_api_client(self, tmp_path):
        """
        Verifies that passing a BrowserCommentCollector as api_client
        is auto-detected and routed without raising 'resolve_post_id' AttributeError.
        """
        # Create a mock that has collect() but explicitly does NOT have resolve_post_id
        mock_browser = MagicMock(spec=["collect", "last_post_author"])
        c1 = make_comment("1", "Hello from web", "2026-09-12T08:00:00+00:00")
        mock_browser.collect.return_value = [c1]
        mock_browser.last_post_author = "Alisha's Gadgets Cellphone Repair"
        mock_exporter = MagicMock(spec=ExcelExporter)
        mock_exporter.export.return_value = tmp_path / "browser.xlsx"

        # Intentionally pass as api_client
        collector = CommentCollector(
            api_client=mock_browser,
            exporter=mock_exporter,
            page_delay_seconds=0
        )

        assert collector.browser_collector is mock_browser
        assert collector.api_client is None

        res = collector.collect("https://www.facebook.com/share/r/1J753i15bs/")
        assert res.success is True
        assert res.total_collected == 1
        assert res.post_author == "Alisha's Gadgets Cellphone Repair"
        mock_exporter.export.assert_called_once_with(
            [c1],
            None,
            author_name="Alisha's Gadgets Cellphone Repair"
        )

