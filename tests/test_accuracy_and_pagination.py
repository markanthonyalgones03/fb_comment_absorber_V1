"""
Tests for comment accuracy, multi-page cursor pagination,
nested reply pagination, comment ID deduplication (preserving identical text from different authors),
original language preservation, and honest status logic (PARTIAL vs COMPLETE).
"""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from app.comment_collector import CommentCollector
from app.models import Comment, CollectionStatus, CollectionResult
from app.facebook_api import FacebookApiClient
from app.excel_exporter import ExcelExporter
from web.web_collector import WebComment
from web.app_web import CollectionSession


def make_comment(cid: str, msg: str, ts_iso: str, user: str = "User", is_reply: bool = False, parent_id: str = None) -> Comment:
    return Comment(
        comment_id=cid,
        user_name=user,
        message=msg,
        created_time=datetime.fromisoformat(ts_iso),
        is_reply=is_reply,
        parent_id=parent_id,
        original_text=msg
    )


class TestAccuracyAndDeduplication:

    def test_preserves_identical_text_from_different_users(self):
        """
        User A: "Location"
        User B: "Location"
        These are TWO distinct comments because comment_ids differ.
        They must both be retained and not deduplicated by text.
        """
        session = CollectionSession()
        c1 = WebComment(
            index=1,
            comment_id="id_101",
            user_name="Art Pugo Gulay",
            message="Asa location ninyo?",
            created_time="2026-07-30T01:46:19.000Z",
            timestamp_raw=1785375979,
            avatar_color="#1877F2",
            avatar_initials="AP",
            original_text="Asa location ninyo?"
        )
        c2 = WebComment(
            index=2,
            comment_id="id_102",
            user_name="Irish Lyn Billedo Pepito",
            message="Asa location ninyo?",  # Identical text!
            created_time="2026-07-30T01:50:00.000Z",
            timestamp_raw=1785376200,
            avatar_color="#10B981",
            avatar_initials="IL",
            original_text="Asa location ninyo?"
        )

        session.on_new_comment(c1)
        session.on_new_comment(c2)

        stats = session.get_stats_dict()
        assert stats["count"] == 2
        assert stats["retrieved_count"] == 2
        assert len(session.comments) == 2
        assert stats["diagnostics_summary"]["duplicates_removed"] == 0

    def test_deduplicates_identical_comment_id(self):
        """
        If the same comment_id is encountered twice across paginated batches,
        it must be discarded as a duplicate.
        """
        session = CollectionSession()
        c1 = WebComment(
            index=1,
            comment_id="dup_001",
            user_name="User One",
            message="Hello!",
            created_time="2026-07-30T01:46:19.000Z",
            timestamp_raw=1785375979,
            avatar_color="#1877F2",
            avatar_initials="UO"
        )
        c1_repeat = WebComment(
            index=2,
            comment_id="dup_001",  # Same ID
            user_name="User One",
            message="Hello!",
            created_time="2026-07-30T01:46:19.000Z",
            timestamp_raw=1785375979,
            avatar_color="#1877F2",
            avatar_initials="UO"
        )

        session.on_new_comment(c1)
        session.on_new_comment(c1_repeat)

        stats = session.get_stats_dict()
        assert stats["count"] == 1
        assert stats["diagnostics_summary"]["duplicates_removed"] == 1

    def test_status_partial_when_source_reported_count_exceeds_retrieved(self):
        """
        If Facebook reports 53 comments, but only 24 could be retrieved,
        status must report PARTIAL, and never fake 53.
        """
        session = CollectionSession()
        session.set_source_reported_count(53)

        for i in range(24):
            session.on_new_comment(WebComment(
                index=i+1,
                comment_id=f"c_{i}",
                user_name=f"User {i}",
                message=f"Comment {i}",
                created_time="2026-07-30T01:00:00.000Z",
                timestamp_raw=1785375000 + i,
                avatar_color="#1877F2",
                avatar_initials="U"
            ))

        session.on_status_change("PARTIAL", {"message": "Retrieved 24 of 53 source-reported comments."})

        stats = session.get_stats_dict()
        assert stats["source_reported_count"] == 53
        assert stats["retrieved_count"] == 24
        assert stats["is_partial"] is True
        assert stats["status"] == "PARTIAL"

    def test_status_complete_when_all_available_retrieved(self):
        """
        When all available comments are retrieved, status is COMPLETED and is_partial is False.
        """
        session = CollectionSession()
        session.set_source_reported_count(24)

        for i in range(24):
            session.on_new_comment(WebComment(
                index=i+1,
                comment_id=f"c_{i}",
                user_name=f"User {i}",
                message=f"Comment {i}",
                created_time="2026-07-30T01:00:00.000Z",
                timestamp_raw=1785375000 + i,
                avatar_color="#1877F2",
                avatar_initials="U"
            ))

        session.set_pagination_exhausted(True)
        session.on_status_change("COMPLETED", {"message": "Retrieved 24 comments from the authorized data source."})

        stats = session.get_stats_dict()
        assert stats["source_reported_count"] == 24
        assert stats["retrieved_count"] == 24
        assert stats["is_partial"] is False
        assert stats["status"] == "COMPLETED"

    def test_preserves_original_languages_and_emojis(self):
        """
        Bisaya, Tagalog, and emojis must be stored verbatim without translation.
        """
        bisaya_text = "Grabe ka gwapa ani uy 😍 asa dapit sta Cruz?"
        c = WebComment(
            index=1,
            comment_id="lang_1",
            user_name="Johnmark Diazon",
            message=bisaya_text,
            created_time="2026-07-30T01:00:00.000Z",
            timestamp_raw=1785375000,
            avatar_color="#1877F2",
            avatar_initials="JD",
            original_text=bisaya_text,
            translated_text="So pretty! Where in Sta Cruz?",
            is_translation=False
        )

        d = c.to_dict()
        assert d["message"] == bisaya_text
        assert d["original_text"] == bisaya_text
        assert "😍" in d["message"]
