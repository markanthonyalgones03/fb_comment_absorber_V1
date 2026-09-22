"""
Unit tests for URL parsing, post identifier extraction,
date parsing, sorting, and text sanitization.
"""

import pytest
from datetime import datetime, timezone
from app.models import InvalidUrlError, Comment
from app.utils import (
    clean_facebook_url,
    extract_post_identifiers,
    parse_fb_timestamp,
    format_excel_date,
    sort_comments_oldest_first,
    sanitize_for_excel,
)


class TestUrlCleaningAndValidation:

    def test_valid_desktop_url(self):
        url = "https://www.facebook.com/NASA/posts/1015948291029384"
        clean = clean_facebook_url(url)
        assert clean == "https://www.facebook.com/NASA/posts/1015948291029384"

    def test_valid_mobile_url(self):
        url = "https://m.facebook.com/NASA/posts/1015948291029384"
        clean = clean_facebook_url(url)
        assert clean == "https://www.facebook.com/NASA/posts/1015948291029384"

    def test_url_with_tracking_parameters_stripped(self):
        url = "https://www.facebook.com/BBCNews/posts/1015928374?mibextid=ZbWKwL&__tn__=%2CO%2CP-R"
        clean = clean_facebook_url(url)
        assert clean == "https://www.facebook.com/BBCNews/posts/1015928374"
        assert "mibextid" not in clean
        assert "__tn__" not in clean

    def test_permalink_preserves_story_fbid_and_id(self):
        url = "https://www.facebook.com/permalink.php?story_fbid=1015928374&id=228735667216&substory_index=0"
        clean = clean_facebook_url(url)
        assert "story_fbid=1015928374" in clean
        assert "id=228735667216" in clean
        assert "substory_index" not in clean

    def test_invalid_domain_raises_error(self):
        with pytest.raises(InvalidUrlError):
            clean_facebook_url("https://www.google.com/search?q=facebook")

    def test_non_url_string_raises_error(self):
        with pytest.raises(InvalidUrlError):
            clean_facebook_url("not a url at all")

    def test_empty_string_raises_error(self):
        with pytest.raises(InvalidUrlError):
            clean_facebook_url("")


class TestPostIdentifierExtraction:

    def test_standard_page_post(self):
        url = clean_facebook_url("https://www.facebook.com/NASA/posts/1015948291029384")
        page, post_id = extract_post_identifiers(url)
        assert page == "NASA"
        assert post_id == "1015948291029384"

    def test_pfbid_permalink(self):
        url = clean_facebook_url("https://www.facebook.com/Meta/posts/pfbid02AbC99xyz88771122")
        page, post_id = extract_post_identifiers(url)
        assert page == "Meta"
        assert post_id == "pfbid02AbC99xyz88771122"

    def test_permalink_php(self):
        url = clean_facebook_url("https://www.facebook.com/permalink.php?story_fbid=987654321&id=123456789")
        page, post_id = extract_post_identifiers(url)
        assert page == "123456789"
        assert post_id == "987654321"

    def test_story_php(self):
        url = clean_facebook_url("https://www.facebook.com/story.php?story_fbid=987654321&id=123456789")
        page, post_id = extract_post_identifiers(url)
        assert page == "123456789"
        assert post_id == "987654321"

    def test_watch_video(self):
        url = clean_facebook_url("https://www.facebook.com/watch/?v=1122334455")
        page, post_id = extract_post_identifiers(url)
        assert post_id == "1122334455"

    def test_page_video(self):
        url = clean_facebook_url("https://www.facebook.com/NASA/videos/1122334455")
        page, post_id = extract_post_identifiers(url)
        assert page == "NASA"
        assert post_id == "1122334455"

    def test_photo_php(self):
        url = clean_facebook_url("https://www.facebook.com/photo.php?fbid=9988776655&id=123456")
        page, post_id = extract_post_identifiers(url)
        assert page == "123456"
        assert post_id == "9988776655"

    def test_group_post(self):
        url = clean_facebook_url("https://www.facebook.com/groups/techcommunity/posts/4433221100")
        group, post_id = extract_post_identifiers(url)
        assert group == "techcommunity"
        assert post_id == "4433221100"

    def test_share_video_url(self):
        url = clean_facebook_url("https://www.facebook.com/share/v/1HGqJTFGsb/")
        page, post_id = extract_post_identifiers(url)
        assert post_id is not None
        assert len(post_id) > 0


class TestDateParsingAndSorting:

    def test_parse_iso_with_positive_offset(self):
        dt = parse_fb_timestamp("2026-09-12T08:01:15+0000")
        assert dt.year == 2026
        assert dt.month == 9
        assert dt.day == 12
        assert dt.hour == 8
        assert dt.minute == 1
        assert dt.second == 15
        assert dt.tzinfo is not None

    def test_parse_iso_with_zulu(self):
        dt = parse_fb_timestamp("2026-09-12T14:30:00Z")
        assert dt.year == 2026
        assert dt.hour == 14
        assert dt.minute == 30

    def test_format_excel_date(self):
        dt = datetime(2026, 9, 12, 19, 55, 0, tzinfo=timezone.utc)
        formatted = format_excel_date(dt)
        assert formatted == "2026-09-12 19:55:00"

    def test_sort_oldest_first(self):
        c1 = Comment(
            comment_id="1",
            user_name="User C",
            message="Third comment",
            created_time=datetime(2026, 9, 12, 8, 7, 45, tzinfo=timezone.utc)
        )
        c2 = Comment(
            comment_id="2",
            user_name="User A",
            message="First comment",
            created_time=datetime(2026, 9, 12, 8, 1, 15, tzinfo=timezone.utc)
        )
        c3 = Comment(
            comment_id="3",
            user_name="User B",
            message="Second comment",
            created_time=datetime(2026, 9, 12, 8, 3, 22, tzinfo=timezone.utc)
        )

        # Given in arbitrary order [c1, c2, c3]
        sorted_list = sort_comments_oldest_first([c1, c2, c3])

        assert sorted_list[0].comment_id == "2"  # 08:01:15
        assert sorted_list[1].comment_id == "3"  # 08:03:22
        assert sorted_list[2].comment_id == "1"  # 08:07:45


class TestTextSanitization:

    def test_sanitizes_illegal_xml_chars(self):
        raw_text = "Good job!\x00\x08\x0b\x0c\x1fAwesome"
        cleaned = sanitize_for_excel(raw_text)
        assert cleaned == "Good job!Awesome"
        assert "\x00" not in cleaned

    def test_preserves_valid_whitespaces(self):
        raw_text = "Line 1\nLine 2\tTabbed\r\nLine 3"
        cleaned = sanitize_for_excel(raw_text)
        assert cleaned == raw_text

    def test_preserves_emojis_and_multilingual_text(self):
        filipino_and_emojis = "Maraming salamat po! Magandang gabi sa inyo ❤️ 🚀 🇵🇭 🎉"
        cleaned = sanitize_for_excel(filipino_and_emojis)
        assert cleaned == filipino_and_emojis
