from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from datetime import date, datetime, time as datetime_time
from typing import Any

from myQuant.news_ingestion.contracts import NewsQuery, RawNewsItem, Source, SourceCategory, Status
from myQuant.news_ingestion.sources.base import BaseNewsSource, PoliteHttpClient, SourceFetchResult

TELEGRAPH_URL = "https://www.cls.cn/nodeapi/telegraphList"
APP_NAME = "CailianpressWeb"
OS_NAME = "web"
SV_VERSION = "7.7.5"
PAGE_SIZE = 20
MAX_PAGES = 50


def compute_cls_signature(*, last_time: int, rn: int) -> str:
    param_string = (
        f"app={APP_NAME}&last_time={int(last_time)}&os={OS_NAME}&rn={int(rn)}&sv={SV_VERSION}"
    )
    sha1_digest = hashlib.sha1(param_string.encode("utf-8")).hexdigest()
    return hashlib.md5(sha1_digest.encode("utf-8")).hexdigest()


def _compute_content_hash(title: str, content: str) -> str:
    return hashlib.sha256((title + content).encode("utf-8")).hexdigest()


class ClsTelegraphSource(BaseNewsSource):
    """财联社电报 best-effort flash-news adapter."""

    source = Source.CLS_TELEGRAPH

    def __init__(
        self,
        *,
        http_client: PoliteHttpClient | None = None,
        clock: Callable[[], float] = time.time,
        page_size: int = PAGE_SIZE,
        max_pages: int = MAX_PAGES,
    ) -> None:
        self._http = http_client or PoliteHttpClient()
        self._clock = clock
        self._page_size = page_size
        self._max_pages = max_pages

    def fetch(self, query: NewsQuery) -> SourceFetchResult:
        start_dt = self._start_datetime(query.start)
        end_dt = self._end_datetime(query.end)
        last_time = int(self._clock())
        items: list[RawNewsItem] = []
        fetch_errors: list[str] = []
        pages_fetched = 0

        for _ in range(self._max_pages):
            params = self._build_params(last_time)
            response = self._http.get(
                TELEGRAPH_URL,
                params=params,
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Referer": "https://www.cls.cn/telegraph",
                    "User-Agent": "Mozilla/5.0 AgentNewsV01Research CLS Telegraph",
                },
            )
            pages_fetched += 1

            if response.status != Status.SUCCESS:
                fetch_errors.append(response.error or f"HTTP {response.http_status}")
                break

            try:
                payload = json.loads(response.text)
                rows = self._extract_rows(payload)
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                fetch_errors.append(f"Parse error: {exc}")
                break

            if not rows:
                break

            oldest_ctime = last_time
            for row in rows:
                try:
                    item = self._parse_item(row)
                except (ValueError, TypeError) as exc:
                    fetch_errors.append(f"Parse error: {exc}")
                    continue

                if item.published_at is not None:
                    oldest_ctime = min(oldest_ctime, int(item.published_at.timestamp()))
                    if start_dt <= item.published_at <= end_dt:
                        items.append(item)

            if oldest_ctime == last_time:
                break
            last_time = oldest_ctime
            if datetime.fromtimestamp(last_time) < start_dt:
                break

        error_summary = "; ".join(fetch_errors)
        status = Status.FAILED if fetch_errors and not items else Status.SUCCESS
        if fetch_errors and not items:
            coverage_status = "failed"
        elif fetch_errors:
            coverage_status = "partial"
        else:
            coverage_status = "fetched"

        return SourceFetchResult(
            source=self.source,
            status=status,
            items=tuple(items),
            error=error_summary,
            coverage_status=coverage_status,
            metadata={"pages_fetched": pages_fetched, "last_time": last_time},
        )

    def _build_params(self, last_time: int) -> dict[str, str]:
        rn = int(self._page_size)
        return {
            "app": APP_NAME,
            "os": OS_NAME,
            "sv": SV_VERSION,
            "rn": str(rn),
            "last_time": str(int(last_time)),
            "sign": compute_cls_signature(last_time=int(last_time), rn=rn),
        }

    @staticmethod
    def _extract_rows(payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            raise ValueError("top-level response is not an object")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError("missing data object")
        rows = data.get("roll_data")
        if not isinstance(rows, list):
            raise ValueError("missing data.roll_data list")
        if not all(isinstance(row, dict) for row in rows):
            raise ValueError("data.roll_data contains non-object entries")
        return rows

    def _parse_item(self, row: dict[str, Any]) -> RawNewsItem:
        title = str(row.get("title") or "").strip()
        content = str(row.get("content") or "").strip()
        source_item_id = str(row.get("id") or "").strip()
        ctime = row.get("ctime")
        if not title and not content:
            raise ValueError("telegraph item missing title/content")
        if not title:
            title = content[:80]
        if not source_item_id:
            raise ValueError("telegraph item missing id")
        if ctime is None:
            raise ValueError("telegraph item missing ctime")

        published_at = datetime.fromtimestamp(int(ctime))
        return RawNewsItem(
            source=self.source,
            source_category=SourceCategory.FLASH,
            source_item_id=source_item_id,
            url=str(row.get("shareurl") or ""),
            title=title,
            content=content,
            summary="",
            published_at=published_at,
            content_hash=_compute_content_hash(title, content),
            body_status="inline",
            raw_payload=row,
            language="zh",
        )

    @staticmethod
    def _start_datetime(value: date | datetime) -> datetime:
        if isinstance(value, datetime):
            return value
        return datetime.combine(value, datetime_time.min)

    @staticmethod
    def _end_datetime(value: date | datetime) -> datetime:
        if isinstance(value, datetime):
            return value
        return datetime.combine(value, datetime_time.max)
