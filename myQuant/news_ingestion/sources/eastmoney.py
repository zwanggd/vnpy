from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any

from myQuant.news_ingestion.contracts import NewsQuery, RawNewsItem, Source, SourceCategory, Status
from myQuant.news_ingestion.sources.base import BaseNewsSource, PoliteHttpClient, SourceFetchResult

ANNOUNCEMENT_URL = "https://np-anotice-stock.eastmoney.com/api/security/ann"
ANNOUNCEMENT_PAGE_SIZE = 50
ANNOUNCEMENT_MAX_PAGES = 50
KEYWORD_SEARCH_URL = "https://so.eastmoney.com/news/s"


def _compute_content_hash(title: str, content: str) -> str:
    return hashlib.sha256((title + (content or "")).encode("utf-8")).hexdigest()


class EastmoneyNewsSource(BaseNewsSource):
    """Best-effort Eastmoney stock/news recall source.

    Eastmoney public news/search pages do not expose reliable historical date-range
    pagination for this adapter, so fetch results are always marked partial.
    """

    source = Source.EASTMONEY

    def __init__(self, *, http_client: PoliteHttpClient | None = None) -> None:
        self._http = http_client or PoliteHttpClient()

    def fetch(self, query: NewsQuery) -> SourceFetchResult:
        items: list[RawNewsItem] = []
        errors: list[str] = []

        if query.symbol:
            # Primary: announcement endpoint (stock-targeted, paginated JSON)
            for page_index in range(1, ANNOUNCEMENT_MAX_PAGES + 1):
                response = self._http.get(
                    ANNOUNCEMENT_URL,
                    params={
                        "sr": "-1",
                        "page_size": str(ANNOUNCEMENT_PAGE_SIZE),
                        "page_index": str(page_index),
                        "ann_type": "A",
                        "client_source": "web",
                        "stock_list": query.symbol,
                    },
                )
                if response.status != Status.SUCCESS:
                    errors.append(response.error)
                    break

                page_items = _parse_announcement_items(response.text, SourceCategory.ANNOUNCEMENT)
                if not page_items:
                    break
                items.extend(page_items)

                if len(page_items) < ANNOUNCEMENT_PAGE_SIZE:
                    break

        # Fallback 1: keyword search with stock symbol
        if not items and query.symbol:
            response = self._http.get(
                KEYWORD_SEARCH_URL,
                params={"keyword": query.symbol},
            )
            if response.status is Status.SUCCESS:
                items.extend(self._parse_response(response.text, SourceCategory.FINANCIAL_NEWS))
            else:
                errors.append(response.error)

        # Fallback 2: keyword search with provided keywords
        if not items and query.keywords:
            response = self._http.get(
                KEYWORD_SEARCH_URL,
                params={"keyword": query.keywords[0]},
            )
            if response.status is Status.SUCCESS:
                items.extend(self._parse_response(response.text, SourceCategory.UNKNOWN))
            else:
                errors.append(response.error)

        warnings = _warnings_for_items(items)
        status = Status.FAILED if errors and not items else Status.SUCCESS
        return SourceFetchResult(
            source=Source.EASTMONEY,
            status=status,
            items=tuple(items),
            error="; ".join(error for error in errors if error),
            coverage_status="partial",
            metadata={
                "coverage_status": "partial",
                "date_range_coverage": "partial",
                "warnings": warnings,
            },
        )

    def _parse_response(self, text: str, category: SourceCategory) -> list[RawNewsItem]:
        if not text.strip():
            return []

        json_payload = _loads_json_or_jsonp(text)
        if json_payload is not None:
            return [_raw_item(record, category) for record in _json_records(json_payload)]

        parser = _EastmoneyHtmlParser()
        try:
            parser.feed(text)
            parser.close()
        except Exception:
            return []
        return [_raw_item(record, category) for record in parser.records]


class _EastmoneyHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.records: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._capture: str = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key.lower(): value or "" for key, value in attrs}
        if tag == "a" and attrs_dict.get("href"):
            self._flush_current()
            self._current = {
                "title": attrs_dict.get("title", ""),
                "url": attrs_dict["href"],
            }
            self._capture = "title"
            return

        if self._current is None:
            return

        class_name = attrs_dict.get("class", "").lower()
        if tag in {"p", "div"} and any(token in class_name for token in ("summary", "desc", "abstract")):
            self._capture = "content"
        elif tag in {"p"}:
            self._capture = "content"
        elif tag in {"span", "em", "cite", "time"} and any(
            token in class_name for token in ("time", "date", "source")
        ):
            self._capture = "published_at"

    def handle_endtag(self, tag: str) -> None:
        if tag in {"a", "p", "div", "span", "em", "cite", "time"}:
            self._capture = ""

    def handle_data(self, data: str) -> None:
        if self._current is None or not self._capture:
            return
        value = _clean_text(data)
        if not value:
            return
        existing = self._current.get(self._capture, "")
        if self._capture == "title" and _clean_text(existing) == value:
            return
        self._current[self._capture] = _clean_text(f"{existing} {value}")

    def close(self) -> None:
        self._flush_current()
        super().close()

    def _flush_current(self) -> None:
        if self._current is None:
            return
        title = _clean_text(self._current.get("title", ""))
        url = _normalize_url(self._current.get("url", ""))
        if title and url:
            record = dict(self._current)
            record["title"] = title
            record["url"] = url
            self.records.append(record)
        self._current = None
        self._capture = ""


def _raw_item(record: dict[str, Any], category: SourceCategory) -> RawNewsItem:
    title = _clean_text(_first(record, ("title", "Title", "newsTitle", "art_title", "Art_Title", "Ntitle")))
    content = _clean_text(
        _first(
            record,
            ("content", "summary", "digest", "description", "abstract", "simtitle", "NewsContent"),
        )
    )
    published_at = _parse_datetime(
        _first(
            record,
            ("published_at", "publish_time", "showtime", "date", "time", "NewsTime", "Art_ShowTime", "ctime"),
        )
    )
    url = _normalize_url(_first(record, ("url", "Url", "URL", "art_url", "Art_UniqueUrl", "uniqueUrl")))
    body_status = "inline" if published_at is not None else "missing_published_at"

    return RawNewsItem(
        source=Source.EASTMONEY,
        source_category=category,
        title=title,
        content=content,
        summary=content,
        content_hash=_compute_content_hash(title, content),
        source_item_id=url or title,
        url=url,
        published_at=published_at,
        body_status=body_status,
        raw_payload=record,
        language="zh",
    )


def _loads_json_or_jsonp(text: str) -> Any | None:
    stripped = text.strip()
    candidates = [stripped]
    match = re.search(r"^[\w$.]+\((.*)\)\s*;?$", stripped, flags=re.S)
    if match:
        candidates.append(match.group(1))

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _json_records(payload: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                walk(item)
            return
        if not isinstance(value, dict):
            return

        if _first(value, ("title", "Title", "newsTitle", "art_title", "Art_Title", "Ntitle")) and _first(
            value,
            ("url", "Url", "URL", "art_url", "Art_UniqueUrl", "uniqueUrl"),
        ):
            records.append(value)
            return

        for child in value.values():
            walk(child)

    walk(payload)
    return records


def _first(record: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = record.get(key)
        if value is not None and value != "":
            return str(value)
    return ""


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value)).strip()


def _normalize_url(url: str) -> str:
    value = _clean_text(url)
    if value.startswith("//"):
        return f"https:{value}"
    if value.startswith("/"):
        return f"https://finance.eastmoney.com{value}"
    return value


def _parse_datetime(value: str) -> datetime | None:
    text = _clean_text(value)
    if not text:
        return None
    if text.isdigit():
        timestamp = int(text)
        if timestamp > 10_000_000_000:
            timestamp //= 1000
        return datetime.fromtimestamp(timestamp)
    match = re.search(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:\s+\d{1,2}:\d{1,2}(?::\d{1,2})?)?", text)
    if match:
        text = match.group(0).replace("/", "-")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _parse_announcement_items(text: str, category: SourceCategory) -> list[RawNewsItem]:
    if not text.strip():
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return []
    items_list = data.get("list")
    if not isinstance(items_list, list):
        return []

    result: list[RawNewsItem] = []
    for record in items_list:
        if not isinstance(record, dict):
            continue
        item = _raw_item_from_announcement(record, category)
        if item is not None:
            result.append(item)
    return result


def _raw_item_from_announcement(record: dict[str, Any], category: SourceCategory) -> RawNewsItem | None:
    title = _clean_text(str(record.get("title", "")))
    if not title:
        return None

    content = _clean_text(str(record.get("content", "")))
    source_item_id = str(record.get("art_code", ""))

    notice_date = record.get("notice_date")
    published_at = None
    if notice_date is not None:
        try:
            ts = int(notice_date)
            if ts > 10_000_000_000:
                ts //= 1000
            published_at = datetime.fromtimestamp(ts)
        except (ValueError, OSError):
            published_at = _parse_datetime(str(notice_date))

    url = _normalize_url(str(record.get("pdf_url", "")))
    body_status = "inline" if published_at is not None else "missing_published_at"

    return RawNewsItem(
        source=Source.EASTMONEY,
        source_category=category,
        title=title,
        content=content,
        summary=content,
        content_hash=_compute_content_hash(title, content),
        source_item_id=source_item_id or title,
        url=url,
        published_at=published_at,
        body_status=body_status,
        raw_payload=record,
        language="zh",
    )


def _warnings_for_items(items: list[RawNewsItem]) -> list[str]:
    warnings: list[str] = []
    if any(item.published_at is None for item in items):
        warnings.append("missing_published_at")
    return warnings
