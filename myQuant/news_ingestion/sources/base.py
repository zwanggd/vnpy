from __future__ import annotations

import json
import os
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from myQuant.news_ingestion.contracts import NewsQuery, RawNewsItem, Source, Status


DEFAULT_USER_AGENT = "Mozilla/5.0 AgentNewsV01Research"
DEFAULT_TIMEOUT = 15.0
DEFAULT_RETRY_COUNT = 2
DEFAULT_REQUEST_INTERVAL = 1.0
RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}


@dataclass
class SourceFetchResult:
    source: Source
    status: Status
    items: tuple[RawNewsItem, ...] = ()
    error: str = ""
    http_status: int | None = None
    coverage_status: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.source = Source(self.source)
        self.status = Status(self.status)
        self.items = tuple(self.items)


class BaseNewsSource(ABC):
    source: Source

    @abstractmethod
    def fetch(self, query: NewsQuery) -> SourceFetchResult:
        raise NotImplementedError


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    text: str = ""
    headers: Mapping[str, str] = field(default_factory=dict)
    content: bytes = b""
    url: str = ""


@dataclass
class HttpRequestResult:
    status: Status
    text: str = ""
    error: str = ""
    http_status: int | None = None
    headers: dict[str, str] = field(default_factory=dict)
    content: bytes = b""
    attempts: int = 0
    url: str = ""

    def __post_init__(self) -> None:
        self.status = Status(self.status)


class HttpTransport(Protocol):
    def __call__(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        params: Mapping[str, str] | None,
        data: bytes | str | None,
        json: Mapping[str, Any] | None,
        timeout: float,
    ) -> HttpResponse:
        ...


def _default_transport(
    *,
    method: str,
    url: str,
    headers: Mapping[str, str],
    params: Mapping[str, str] | None,
    data: bytes | str | None,
    json: Mapping[str, Any] | None,
    timeout: float,
) -> HttpResponse:
    request_url = url
    if params:
        separator = "&" if "?" in request_url else "?"
        request_url = f"{request_url}{separator}{urlencode(params)}"

    body: bytes | None
    request_headers = dict(headers)
    if json is not None:
        body = json_dumps_bytes(json)
        request_headers.setdefault("Content-Type", "application/json")
    elif isinstance(data, str):
        body = data.encode("utf-8")
    else:
        body = data

    request = Request(
        request_url,
        data=body,
        headers=request_headers,
        method=method.upper(),
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            content = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            return HttpResponse(
                status_code=response.status,
                text=content.decode(charset, errors="replace"),
                headers=dict(response.headers.items()),
                content=content,
                url=response.url,
            )
    except HTTPError as exc:
        content = exc.read()
        return HttpResponse(
            status_code=exc.code,
            text=content.decode("utf-8", errors="replace"),
            headers=dict(exc.headers.items()) if exc.headers else {},
            content=content,
            url=request_url,
        )


def json_dumps_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class PoliteHttpClient:
    def __init__(
        self,
        *,
        transport: HttpTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        retry_count: int = DEFAULT_RETRY_COUNT,
        request_interval: float = DEFAULT_REQUEST_INTERVAL,
        user_agent: str = DEFAULT_USER_AGENT,
        backoff_base: float = 1.0,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.transport = transport or _default_transport
        self.timeout = timeout
        self.retry_count = retry_count
        self.request_interval = request_interval
        self.user_agent = user_agent
        self.backoff_base = backoff_base
        self.sleeper = sleeper
        self.clock = clock
        self._last_request_at: float | None = None

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> HttpRequestResult:
        return self.request(
            "GET",
            url,
            params=params,
            headers=headers,
            timeout=timeout,
        )

    def post(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        data: bytes | str | None = None,
        json_body: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> HttpRequestResult:
        return self.request(
            "POST",
            url,
            params=params,
            data=data,
            json_body=json_body,
            headers=headers,
            timeout=timeout,
        )

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        data: bytes | str | None = None,
        json_body: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> HttpRequestResult:
        request_headers = {"User-Agent": self.user_agent}
        if headers:
            request_headers.update(headers)

        attempts = self.retry_count + 1
        last_http_status: int | None = None
        last_error = ""

        for attempt_no in range(1, attempts + 1):
            self._wait_for_request_interval()
            try:
                response = self.transport(
                    method=method.upper(),
                    url=url,
                    headers=request_headers,
                    params=params,
                    data=data,
                    json=json_body,
                    timeout=timeout or self.timeout,
                )
            except (TimeoutError, URLError, OSError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                self._last_request_at = self.clock()
                if attempt_no < attempts:
                    self._sleep_backoff(attempt_no)
                    continue
                return HttpRequestResult(
                    status=Status.FAILED,
                    error=last_error,
                    attempts=attempt_no,
                    url=url,
                )

            self._last_request_at = self.clock()
            last_http_status = response.status_code
            if 200 <= response.status_code < 300:
                return HttpRequestResult(
                    status=Status.SUCCESS,
                    text=response.text,
                    http_status=response.status_code,
                    headers=dict(response.headers),
                    content=response.content,
                    attempts=attempt_no,
                    url=response.url or url,
                )

            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
            if response.status_code in RETRYABLE_HTTP_STATUSES and attempt_no < attempts:
                self._sleep_backoff(attempt_no)
                continue

            return HttpRequestResult(
                status=Status.FAILED,
                text=response.text,
                error=last_error,
                http_status=response.status_code,
                headers=dict(response.headers),
                content=response.content,
                attempts=attempt_no,
                url=response.url or url,
            )

        return HttpRequestResult(
            status=Status.FAILED,
            error=last_error or "HTTP request failed",
            http_status=last_http_status,
            attempts=attempts,
            url=url,
        )

    def _wait_for_request_interval(self) -> None:
        if self._last_request_at is None or self.request_interval <= 0:
            return
        elapsed = self.clock() - self._last_request_at
        remaining = self.request_interval - elapsed
        if remaining > 0:
            self.sleeper(remaining)

    def _sleep_backoff(self, attempt_no: int) -> None:
        if self.backoff_base <= 0:
            return
        self.sleeper(self.backoff_base * (2 ** (attempt_no - 1)))


def live_tests_enabled() -> bool:
    return os.environ.get("AGENT_NEWS_LIVE_TEST") == "1"


def live_test_skip_marker(reason: str = "set AGENT_NEWS_LIVE_TEST=1 to run live source tests"):
    import pytest

    return pytest.mark.skipif(not live_tests_enabled(), reason=reason)
