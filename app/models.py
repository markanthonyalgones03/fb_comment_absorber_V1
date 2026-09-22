"""
Data models and custom exceptions for Facebook Comment Collector.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List


class CollectionStatus(str, Enum):
    READY = "Ready"
    CONNECTING = "Connecting to Facebook..."
    ACCESSING = "Accessing post..."
    COLLECTING = "Collecting comments..."
    SORTING = "Sorting comments..."
    CREATING_EXCEL = "Creating Excel file..."
    COMPLETED = "Completed"
    CANCELLED = "Cancelled"
    ERROR = "Error"


@dataclass
class Comment:
    """
    Represents an individual comment or reply collected from Meta Graph API.
    
    Fields:
      comment_id: Used strictly internally for duplicate protection.
      user_name: Permitted user display name.
      user_id: Optional Meta user identifier.
      message: Raw text of the comment (handles emojis, linebreaks, unicode).
      created_time: Datetime object used for chronological sorting (oldest to newest).
      parent_id: Optional parent comment ID if this is a reply.
    """
    comment_id: str
    user_name: str
    message: str
    created_time: datetime
    user_id: Optional[str] = None
    parent_id: Optional[str] = None


@dataclass
class CollectionProgress:
    """Progress update emitted during comment collection."""
    status: CollectionStatus
    count: int = 0
    message: str = ""
    error_detail: Optional[str] = None


@dataclass
class CollectionResult:
    """Final result of a comment collection run."""
    success: bool
    status: CollectionStatus
    comments: List[Comment] = field(default_factory=list)
    total_collected: int = 0
    file_path: Optional[str] = None
    message: str = ""
    is_cancelled: bool = False
    is_partial: bool = False
    post_author: Optional[str] = None


# Custom Application Exceptions for precise and user-friendly error handling

class AppError(Exception):
    """Base exception for application errors."""
    def __init__(self, message: str, technical_details: Optional[str] = None):
        super().__init__(message)
        self.user_message = message
        self.technical_details = technical_details


class InvalidUrlError(AppError):
    """Raised when the URL is invalid or not a recognizable Facebook post URL."""
    def __init__(self, technical_details: Optional[str] = None):
        super().__init__("Please enter a valid Facebook post URL.", technical_details)


class PostNotFoundError(AppError):
    """Raised when post cannot be located on Facebook."""
    def __init__(self, technical_details: Optional[str] = None):
        super().__init__("The Facebook post could not be found or the URL is invalid.", technical_details)


class PermissionDeniedError(AppError):
    """Raised when Meta API rejects access due to lack of permissions / unmanaged page."""
    def __init__(self, technical_details: Optional[str] = None):
        super().__init__(
            "Facebook/Meta does not allow this application to access comments from this post with the current permissions.",
            technical_details
        )


class AuthenticationExpiredError(AppError):
    """Raised when access token is invalid or expired."""
    def __init__(self, technical_details: Optional[str] = None):
        super().__init__(
            "Facebook authentication is required or has expired. Please authenticate again.",
            technical_details
        )


class RateLimitError(AppError):
    """Raised when Meta API rate limits are hit."""
    def __init__(self, technical_details: Optional[str] = None):
        super().__init__(
            "Facebook temporarily limited requests. Please wait and try again.",
            technical_details
        )


class NetworkError(AppError):
    """Raised when connection to Meta fails."""
    def __init__(self, technical_details: Optional[str] = None):
        super().__init__(
            "Unable to connect to Facebook. Check your internet connection and try again.",
            technical_details
        )


class NoCommentsError(AppError):
    """Raised when post exists and is accessed, but has 0 comments."""
    def __init__(self):
        super().__init__("The post was accessed successfully, but no comments were available through the API.")
