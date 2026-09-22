"""
Comment collection orchestrator.
Manages post resolution, cursor pagination, duplicate tracking,
live progress reporting, thread cancellation, and partial collection handling.
"""

import time
import threading
from typing import Callable, Optional, Set, List, Any
from pathlib import Path

from app.models import (
    Comment,
    CollectionStatus,
    CollectionProgress,
    CollectionResult,
    AppError,
    NoCommentsError,
)
from app.facebook_api import FacebookApiClient
from app.excel_exporter import ExcelExporter
from app.utils import sort_comments_oldest_first


class CommentCollector:
    """
    Coordinates the comment collection workflow for a single Facebook post.
    Designed to run inside a worker thread.
    """

    def __init__(
        self,
        api_client: Optional[Any] = None,
        browser_collector: Optional[Any] = None,
        exporter: Optional[ExcelExporter] = None,
        progress_callback: Optional[Callable[[CollectionProgress], None]] = None,
        page_delay_seconds: float = 0.25,
        fetch_nested_replies: bool = True
    ):
        # Defensive routing: auto-detect if BrowserCommentCollector was passed as api_client
        if api_client is not None and browser_collector is None:
            if hasattr(api_client, "collect") and not hasattr(api_client, "resolve_post_id"):
                browser_collector = api_client
                api_client = None

        self.api_client = api_client
        self.browser_collector = browser_collector
        self.exporter = exporter or ExcelExporter()
        self.progress_callback = progress_callback
        self.page_delay_seconds = page_delay_seconds
        self.fetch_nested_replies = fetch_nested_replies

        self._cancel_flag = threading.Event()
        self.collected_comments: List[Comment] = []
        self.seen_comment_ids: Set[str] = set()

    def cancel(self) -> None:
        """Signals the collector to safely halt pagination."""
        self._cancel_flag.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_flag.is_set()

    def _notify(self, status: CollectionStatus, count: int = 0, message: str = "", error: Optional[str] = None) -> None:
        if self.progress_callback:
            self.progress_callback(CollectionProgress(
                status=status,
                count=count,
                message=message,
                error_detail=error
            ))

    def collect(self, post_url: str, custom_export_path: Optional[Path] = None) -> CollectionResult:
        """
        Executes the full collection process for the provided Facebook post URL.
        Supports both official Meta API and direct browser extraction.
        """
        self._cancel_flag.clear()
        self.collected_comments = []
        self.seen_comment_ids = set()
        exhausted_pagination = True

        try:
            # 1. Direct Browser Extraction Mode
            if self.browser_collector is not None:
                self._notify(CollectionStatus.CONNECTING, message="Connecting to browser...")

                def browser_progress(msg: str, count: int):
                    self._notify(CollectionStatus.COLLECTING, count=count, message=msg)

                self.collected_comments = self.browser_collector.collect(
                    post_url=post_url,
                    progress_callback=browser_progress,
                    cancel_event=self._cancel_flag
                )

            # 2. Graph API / Demo API Mode
            elif self.api_client is not None:
                self._notify(CollectionStatus.CONNECTING, message="Connecting to Facebook...")
                self._notify(CollectionStatus.ACCESSING, message="Accessing post...")
                post_id = self.api_client.resolve_post_id(post_url)
                self._notify(CollectionStatus.COLLECTING, count=0, message="Collecting comments...")

                next_url = None
                after_cursor = None
                page_index = 0
                exhausted_pagination = False

                while not self._cancel_flag.is_set():
                    page_index += 1
                    try:
                        comments, next_url, after_cursor, reported_total = self.api_client.get_comments_page(
                            post_id=post_id,
                            after_cursor=after_cursor,
                            next_page_url=next_url,
                            limit=100
                        )
                    except Exception as api_err:
                        if self.collected_comments:
                            return self._handle_partial_collection(
                                error_msg=f"Collection stopped because Facebook returned an error: {api_err}. {len(self.collected_comments)} comments were successfully collected.",
                                custom_export_path=custom_export_path
                            )
                        raise

                    for c in comments:
                        if c.comment_id not in self.seen_comment_ids:
                            self.seen_comment_ids.add(c.comment_id)
                            self.collected_comments.append(c)

                    current_count = len(self.collected_comments)
                    self._notify(
                        CollectionStatus.COLLECTING,
                        count=current_count,
                        message=f"Comments collected: {current_count:,}"
                    )

                    if not next_url and not after_cursor:
                        exhausted_pagination = True
                        break

                    if not comments:
                        exhausted_pagination = True
                        break

                    if self.page_delay_seconds > 0:
                        time.sleep(self.page_delay_seconds)
            else:
                raise AppError("No API client or browser collector configured.")

            # Retrieve post author if available
            post_author = None
            if self.browser_collector is not None:
                post_author = getattr(self.browser_collector, "last_post_author", None)

            # Handle Cancellation
            if self._cancel_flag.is_set():
                current_count = len(self.collected_comments)
                excel_file = None
                if current_count > 0:
                    # Allow exporting partial collected comments
                    sorted_comments = sort_comments_oldest_first(self.collected_comments)
                    excel_file = self.exporter.export(sorted_comments, custom_export_path, author_name=post_author)

                msg = f"Collection stopped by user. {current_count:,} comments were collected before cancellation."
                self._notify(CollectionStatus.CANCELLED, count=current_count, message=msg)
                return CollectionResult(
                    success=True,
                    status=CollectionStatus.CANCELLED,
                    comments=self.collected_comments,
                    total_collected=current_count,
                    file_path=str(excel_file) if excel_file else None,
                    message=msg,
                    is_cancelled=True,
                    is_partial=True,
                    post_author=post_author
                )

            # 4. Check for 0 comments
            if not self.collected_comments:
                raise NoCommentsError()

            # 5. Sorting Oldest -> Newest
            self._notify(
                CollectionStatus.SORTING,
                count=len(self.collected_comments),
                message="Sorting comments (Oldest → Newest)..."
            )
            sorted_comments = sort_comments_oldest_first(self.collected_comments)

            # 6. Excel Generation
            self._notify(
                CollectionStatus.CREATING_EXCEL,
                count=len(sorted_comments),
                message="Creating Excel file..."
            )
            excel_path = self.exporter.export(sorted_comments, custom_export_path, author_name=post_author)

            total_collected = len(sorted_comments)
            final_msg = f"Completed — {total_collected:,} comments collected."
            self._notify(
                CollectionStatus.COMPLETED,
                count=total_collected,
                message=final_msg
            )

            return CollectionResult(
                success=True,
                status=CollectionStatus.COMPLETED,
                comments=sorted_comments,
                total_collected=total_collected,
                file_path=str(excel_path),
                message=final_msg,
                is_cancelled=False,
                is_partial=not exhausted_pagination,
                post_author=post_author
            )

        except AppError as err:
            self._notify(CollectionStatus.ERROR, count=len(self.collected_comments), message=err.user_message, error=err.technical_details)
            return CollectionResult(
                success=False,
                status=CollectionStatus.ERROR,
                comments=self.collected_comments,
                total_collected=len(self.collected_comments),
                message=err.user_message
            )
        except Exception as err:
            generic_msg = f"An unexpected error occurred: {str(err)}"
            self._notify(CollectionStatus.ERROR, count=len(self.collected_comments), message=generic_msg, error=str(err))
            return CollectionResult(
                success=False,
                status=CollectionStatus.ERROR,
                comments=self.collected_comments,
                total_collected=len(self.collected_comments),
                message=generic_msg
            )

    def _handle_partial_collection(self, error_msg: str, custom_export_path: Optional[Path] = None) -> CollectionResult:
        """Saves partially collected comments when an error occurs mid-stream."""
        excel_path = None
        if self.collected_comments:
            sorted_comments = sort_comments_oldest_first(self.collected_comments)
            excel_path = self.exporter.export(sorted_comments, custom_export_path)

        self._notify(
            CollectionStatus.COMPLETED,
            count=len(self.collected_comments),
            message=error_msg
        )
        return CollectionResult(
            success=True,
            status=CollectionStatus.COMPLETED,
            comments=self.collected_comments,
            total_collected=len(self.collected_comments),
            file_path=str(excel_path) if excel_path else None,
            message=error_msg,
            is_partial=True
        )
