"""Polite shared HTTP client used by all adapters.

Rules enforced here (never bypassed):
- configurable delay between requests to the same source
- request timeout and bounded retries with exponential backoff
- 403 / 401 / 429 / CAPTCHA challenges are NOT retried - they raise
  :class:`ManualReviewError` so the run marks the source MANUAL_REVIEW
- optional memory + disk cache so the same page is not re-downloaded
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable, Optional

import requests

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; PersonalJobSearchBot/0.1; personal use; "
    "+local research project)"
)

_CAPTCHA_MARKERS = (
    "captcha", "are you a robot", "unusual traffic", "verify you are human",
    "cloudflare ray id", "attention required",
)


class ManualReviewError(Exception):
    """Access denied / rate limited / CAPTCHA - do not retry, do not bypass."""

    def __init__(self, reason: str, url: Optional[str] = None,
                 http_status: Optional[int] = None,
                 recommended_action: Optional[str] = None):
        super().__init__(reason)
        self.reason = reason
        self.url = url
        self.http_status = http_status
        self.recommended_action = recommended_action or (
            "Review the page manually in a normal browser; respect the "
            "site's terms and robots policy. Do not attempt to bypass it.")


class FetchError(Exception):
    """Ordinary fetch failure (timeout, 404, exhausted 5xx retries)."""

    def __init__(self, message: str, url: Optional[str] = None,
                 http_status: Optional[int] = None):
        super().__init__(message)
        self.url = url
        self.http_status = http_status


class HttpClient:
    """Rate-limited, retrying, caching GET client."""

    def __init__(
        self,
        request_delay: float = 1.5,
        timeout: float = 20.0,
        max_retries: int = 2,
        backoff_factor: float = 2.0,
        cache_ttl: int = 0,
        cache_dir: Optional[Path] = None,
        user_agent: str = DEFAULT_USER_AGENT,
        session: Optional[Any] = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.request_delay = max(0.0, float(request_delay))
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))
        self.backoff_factor = float(backoff_factor)
        self.cache_ttl = int(cache_ttl)
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.sleep_fn = sleep_fn
        self.clock = clock
        self._session = session or requests.Session()
        if hasattr(self._session, "headers"):
            self._session.headers.setdefault("User-Agent", user_agent)
        self._memory_cache: dict[str, str] = {}
        self._last_request_at: Optional[float] = None

    # -- public ------------------------------------------------------------
    def get(self, url: str, params: Optional[dict] = None,
            use_cache: bool = True) -> str:
        """Return the response body text for ``url``."""
        cache_key = self._cache_key(url, params)
        if use_cache:
            cached = self._read_cache(cache_key)
            if cached is not None:
                return cached

        self._respect_rate_limit()
        attempt = 0
        while True:
            try:
                response = self._session.get(url, params=params,
                                             timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise FetchError(f"Request failed after "
                                     f"{attempt + 1} attempts: {exc}",
                                     url=url) from exc
                self._backoff(attempt)
                attempt += 1
                continue

            status = int(response.status_code)
            if status == 200:
                body = response.text
                self._mark_request()
                if use_cache:
                    self._write_cache(cache_key, body)
                return body

            body = getattr(response, "text", "") or ""
            if status in (401, 403, 429, 503) or self._looks_blocked(status, body):
                self._mark_request()
                raise ManualReviewError(
                    f"HTTP {status} - access blocked or rate limited; "
                    "not retrying and not bypassing.",
                    url=url, http_status=status)
            if status == 404:
                self._mark_request()
                raise FetchError("HTTP 404 - page not found", url=url,
                                 http_status=404)
            if 500 <= status < 600:
                if attempt >= self.max_retries:
                    self._mark_request()
                    raise FetchError(f"HTTP {status} - server error after "
                                     f"{attempt + 1} attempts", url=url,
                                     http_status=status)
                self._backoff(attempt)
                attempt += 1
                continue

            self._mark_request()
            raise FetchError(f"HTTP {status} - unexpected response", url=url,
                             http_status=status)

    # -- internals ---------------------------------------------------------
    @staticmethod
    def _cache_key(url: str, params: Optional[dict]) -> str:
        raw = url + "|" + json.dumps(params or {}, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _looks_blocked(status: int, body: str) -> bool:
        if status >= 400 and body:
            low = body[:4000].casefold()
            return any(marker in low for marker in _CAPTCHA_MARKERS)
        return False

    def _respect_rate_limit(self) -> None:
        if self._last_request_at is None or self.request_delay <= 0:
            return
        elapsed = self.clock() - self._last_request_at
        remaining = self.request_delay - elapsed
        if remaining > 0:
            self.sleep_fn(remaining)

    def _mark_request(self) -> None:
        self._last_request_at = self.clock()

    def _backoff(self, attempt: int) -> None:
        self.sleep_fn(self.backoff_factor * (2 ** attempt))

    def _read_cache(self, key: str) -> Optional[str]:
        if key in self._memory_cache:
            return self._memory_cache[key]
        if not self.cache_ttl or not self.cache_dir:
            return None
        path = self.cache_dir / f"{key}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if time.time() - float(data.get("fetched_at", 0)) > self.cache_ttl:
            return None
        return data.get("body")

    def _write_cache(self, key: str, body: str) -> None:
        self._memory_cache[key] = body
        if not self.cache_ttl or not self.cache_dir:
            return
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            (self.cache_dir / f"{key}.json").write_text(
                json.dumps({"fetched_at": time.time(), "body": body}),
                encoding="utf-8")
        except OSError:
            pass

