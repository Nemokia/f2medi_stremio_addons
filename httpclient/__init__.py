"""Shared HTTP client for the F2Media resolver stack.

Provides a configured ``requests.Session`` with connection pooling,
timeouts, and retry logic that only retries transient failures.
"""

from httpclient.client import (
    HttpClient,
    HttpClientConfig,
    HttpError,
)

__all__ = [
    "HttpClient",
    "HttpClientConfig",
    "HttpError",
]
