"""Shared HTTP client: pooling, timeouts, and selective retries.

Retries are reserved for transient conditions only — network errors,
timeouts, and statuses 408/429/5xx. Client errors such as 400/401/403/404
are returned as-is without retrying.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

import requests
from requests.adapters import HTTPAdapter

logger = logging.getLogger("f2m.http")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Statuses worth another attempt; everything else fails fast.
_RETRYABLE_STATUSES = frozenset({408, 429, 500, 502, 503, 504})

_RETRYABLE_EXCEPTIONS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


class HttpError(Exception):
    """Raised when a request ultimately fails after retries."""

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        url: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.url = url


@dataclass
class HttpClientConfig:
    """Knobs for :class:`HttpClient`. All timeouts are in seconds."""

    user_agent: str = DEFAULT_USER_AGENT
    accept_language: str = "fa-IR,fa;q=0.9,en-US;q=0.8,en;q=0.7"
    timeout: float = 15.0
    connect_timeout: float = 8.0
    max_retries: int = 3
    backoff_factor: float = 1.5
    verify_ssl: bool = True
    extra_headers: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "HttpClientConfig":
        """Build a config from ``F2MEDIA_*`` environment variables."""
        def _flag(name: str, default: bool) -> bool:
            raw = os.environ.get(name)
            if raw is None:
                return default
            return raw.strip().lower() not in {"0", "false", "no", "off"}

        def _float(name: str, default: float) -> float:
            try:
                return float(os.environ[name])
            except (KeyError, ValueError):
                return default

        return cls(
            user_agent=os.environ.get("F2MEDIA_USER_AGENT", DEFAULT_USER_AGENT),
            timeout=_float("F2MEDIA_TIMEOUT", cls.timeout),
            max_retries=int(_float("F2MEDIA_MAX_RETRIES", cls.max_retries)),
            verify_ssl=_flag("F2MEDIA_VERIFY_SSL", True),
        )


class HttpClient:
    """Session-backed GET client with exponential-backoff retries."""

    def __init__(self, config: Optional[HttpClientConfig] = None) -> None:
        self.config = config or HttpClientConfig()
        self.session = requests.Session()
        if not self.config.verify_ssl:
            # Targeted suppression only when the operator opted out;
            # urllib3 must not be silenced globally from library code.
            import urllib3  # local import: only needed on this path

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        adapter = HTTPAdapter(
            pool_connections=4,
            pool_maxsize=8,
            max_retries=0,
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.session.headers.update(self._default_headers())

    def _default_headers(self) -> dict[str, str]:
        headers = {
            "User-Agent": self.config.user_agent,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": self.config.accept_language,
            "Connection": "keep-alive",
        }
        headers.update(self.config.extra_headers)
        return headers

    def get(
        self,
        url: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> requests.Response:
        """GET ``url``, retrying only transient failures.

        Returns the final (possibly non-2xx) response for HTTP-level
        outcomes so callers can branch on status codes themselves.
        Raises :class:`HttpError` only when retries are exhausted on a
        transient failure.
        """
        merged_headers = dict(self.session.headers)
        if headers:
            merged_headers.update(headers)

        effective_timeout = (
            timeout if timeout is not None else self.config.timeout
        )
        tuple_timeout = (self.config.connect_timeout, effective_timeout)

        last_error: Optional[str] = None

        for attempt in range(1, self.config.max_retries + 1):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    headers=merged_headers,
                    timeout=tuple_timeout,
                    allow_redirects=True,
                    verify=self.config.verify_ssl,
                )
            except _RETRYABLE_EXCEPTIONS as exc:
                last_error = type(exc).__name__
                logger.warning(
                    "[HTTP] %s on %s (attempt %d/%d)",
                    last_error,
                    url,
                    attempt,
                    self.config.max_retries,
                )
                if attempt < self.config.max_retries:
                    time.sleep(self._sleep_seconds(attempt))
                continue

            if response.status_code in _RETRYABLE_STATUSES:
                logger.warning(
                    "[HTTP] status=%d on %s (attempt %d/%d)",
                    response.status_code,
                    url,
                    attempt,
                    self.config.max_retries,
                )
                if attempt < self.config.max_retries:
                    time.sleep(
                        self._retry_after_or_backoff(response, attempt)
                    )
                continue

            # Non-retryable outcome (success or client error): hand it back.
            logger.debug(
                "[HTTP] GET %s -> %d (%d bytes)",
                url,
                response.status_code,
                len(response.content),
            )
            return response

        raise HttpError(
            f"request failed after {self.config.max_retries} attempts "
            f"(last error: {last_error or 'retryable status'})",
            url=url,
        )

    def _sleep_seconds(self, attempt: int) -> float:
        return min(self.config.backoff_factor * (2 ** (attempt - 1)), 30.0)

    def _retry_after_or_backoff(
        self, response: requests.Response, attempt: int
    ) -> float:
        raw = response.headers.get("Retry-After")
        if raw:
            try:
                return min(float(raw), 60.0)
            except ValueError:
                pass
        return self._sleep_seconds(attempt)

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "HttpClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
