from __future__ import annotations

import hashlib
import re
import time
from datetime import date, datetime, time as datetime_time
from typing import Any

from scrapling import Fetcher, Selector

from myQuant.news_ingestion.contracts import NewsQuery, RawNewsItem, Source, SourceCategory, Status
from myQuant.news_ingestion.sources.base import BaseNewsSource, SourceFetchResult

BASE_URL = "http://vip.stock.finance.sina.com.cn/corp/view/vCB_AllNewsStock.php"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
DEFAULT_REFERER = "http://finance.sina.com.cn"
DEFAULT_HEADERS = {
    "Referer": DEFAULT_REFERER,
    "User-Agent": DEFAULT_USER_AGENT,
}
REQUEST_INTERVAL = 1.5
MAX_PAGES = 200
CONTENT_SELECTORS = ("#artibody", ".article-content", ".article", "#article")

_DATE_TIME_PATTERN = re.compile(
    r"&#160;+(\d{4}-\d{2}-\d{2})&#160;(\d{2}:\d{2})&#160;&#160;"
    r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>'
)
_DATE_ONLY_PATTERN = re.compile(
    r"&#160;+(\d{4}-\d{2}-\d{2})&#160;&#160;"
    r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>'
)
_ENTITY_RE = re.compile(r"&#\d+;")

_SINA_SYMBOL_RE = re.compile(r"[a-z]{2}\d{6}")


def _compute_content_hash(title: str, content: str) -> str:
    return hashlib.sha256((title + (content or "")).encode("utf-8")).hexdigest()


def _clean_text(value: str) -> str:
    from html import unescape
    return re.sub(r"\s+", " ", unescape(value)).strip()


def _normalize_url(url: str) -> str:
    value = _clean_text(url)
    if value.startswith("//"):
        return f"https:{value}"
    return value


def _build_sina_symbol(symbol: str, exchange: str) -> str:
    prefix = "sh" if "SSE" in exchange.upper() else "sz"
    return f"{prefix}{symbol}"


def _symbol_from_code(code: str) -> str:
    if code.startswith("6"):
        return f"sh{code}"
    return f"sz{code}"


def _parse_datetime(date_str: str, time_str: str | None = None) -> datetime | None:
    text = _clean_text(date_str)
    if not text:
        return None
    if time_str:
        time_text = _clean_text(time_str)
        combined = f"{text} {time_text}"
        for fmt_candidate in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(combined, fmt_candidate)
            except ValueError:
                continue
    for fmt_candidate in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt_candidate)
        except ValueError:
            continue
    return None


def _start_datetime(value: date | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.combine(value, datetime_time.min)


def _end_datetime(value: date | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.combine(value, datetime_time.max)


def _fetch_article_content(url: str, fetch_url_func: Any) -> str:
    if not url:
        return ""
    status, html = fetch_url_func(url)
    if not _is_http_ok(status) or not html:
        return ""
    try:
        sel = Selector(html)
        for sel_str in CONTENT_SELECTORS:
            elements = sel.css(sel_str)
            if elements:
                text = elements[0].get_all_text()
                if text and len(text) > 50:
                    return _clean_text(text)
    except Exception:
        pass
    return ""


def _is_http_ok(status_code: int) -> bool:
    return 200 <= status_code < 300


class SinaFinanceSource(BaseNewsSource):
    """Sina Finance historical stock news source.

    Fetches paginated news from Sina Finance's vCB_AllNewsStock.php endpoint,
    extracts article detail for each item, and filters by date range.
    Uses Scrapling's Fetcher for HTTP (handles GBK encoding automatically).
    """

    source = Source.SINA_FINANCE

    def __init__(
        self,
        *,
        fetcher: Any = None,
        request_interval: float = REQUEST_INTERVAL,
        max_pages: int = MAX_PAGES,
    ) -> None:
        self._fetcher = fetcher
        self._request_interval = request_interval
        self._max_pages = max_pages
        self._last_request_at: float = 0.0

    @property
    def fetcher(self) -> Any:
        if self._fetcher is None:
            self._fetcher = Fetcher(auto_match=False)
        return self._fetcher

    def _rate_limit(self) -> None:
        if self._request_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        remaining = self._request_interval - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def _fetch_url(self, url: str) -> tuple[int, str]:
        self._rate_limit()
        try:
            resp = self.fetcher.get(url, headers=DEFAULT_HEADERS)
            self._last_request_at = time.monotonic()
            return resp.status, resp.html_content or ""
        except Exception as exc:
            self._last_request_at = time.monotonic()
            return -1, str(exc)

    def fetch(self, query: NewsQuery) -> SourceFetchResult:
        start_dt = _start_datetime(query.start)
        end_dt = _end_datetime(query.end)
        symbol = query.symbol
        exchange = query.exchange

        if _SINA_SYMBOL_RE.match(symbol):
            sina_symbol = symbol
        elif exchange:
            sina_symbol = _build_sina_symbol(symbol, exchange)
        else:
            sina_symbol = _symbol_from_code(symbol)

        items: list[RawNewsItem] = []
        errors: list[str] = []
        seen_hashes: set[str] = set()
        pages_fetched = 0

        for page in range(1, self._max_pages + 1):
            list_url = f"{BASE_URL}?symbol={sina_symbol}&Page={page}"
            status, html = self._fetch_url(list_url)
            pages_fetched += 1

            if not _is_http_ok(status):
                errors.append(f"List page {page}: HTTP {status}")
                break

            page_items, stop_flag = _parse_list_page(html, start_dt, end_dt)
            if not page_items and stop_flag:
                break

            for item in page_items:
                content = ""
                if item.get("url"):
                    content = _fetch_article_content(
                        item["url"], self._fetch_url
                    )

                title = _clean_text(item.get("title", ""))
                if not title:
                    continue

                content = _clean_text(content)
                content_hash = _compute_content_hash(title, content)
                if content_hash in seen_hashes:
                    continue
                seen_hashes.add(content_hash)

                published_at = item.get("published_at") or _parse_datetime(
                    item.get("date_str", ""), item.get("time_str")
                )

                url = _normalize_url(item.get("url", ""))

                raw_item = RawNewsItem(
                    source=Source.SINA_FINANCE,
                    source_category=SourceCategory.FINANCIAL_NEWS,
                    title=title,
                    content=content,
                    summary=content[:200] if content else "",
                    content_hash=content_hash,
                    source_item_id=content_hash[:16],
                    url=url,
                    published_at=published_at,
                    body_status="fetched" if content else "no_content",
                    raw_payload=item,
                    language="zh",
                )
                items.append(raw_item)

            if stop_flag:
                break

        error_summary = "; ".join(errors)
        status_out = Status.FAILED if errors and not items else Status.SUCCESS
        if errors and not items:
            coverage_status = "failed"
        elif errors:
            coverage_status = "partial"
        else:
            coverage_status = "fetched"

        return SourceFetchResult(
            source=Source.SINA_FINANCE,
            status=status_out,
            items=tuple(items),
            error=error_summary,
            coverage_status=coverage_status,
            metadata={
                "pages_fetched": pages_fetched,
                "sina_symbol": sina_symbol,
            },
        )


def _parse_list_page(
    html: str,
    start_dt: datetime,
    end_dt: datetime,
) -> tuple[list[dict[str, Any]], bool]:
    if not html:
        return [], True

    datelist_match = re.search(
        r'<div[^>]*class="datelist"[^>]*>(.*?)</div>', html, re.DOTALL
    )
    if not datelist_match:
        return [], True

    datelist_html = datelist_match.group(1)

    all_items: list[dict[str, Any]] = []
    earliest_date: datetime | None = None

    for match in _DATE_TIME_PATTERN.finditer(datelist_html):
        date_str = match.group(1)
        time_str = match.group(2)
        url = _normalize_url(match.group(3))
        title = _ENTITY_RE.sub(" ", match.group(4))

        pub_dt = _parse_datetime(date_str, time_str)
        if pub_dt is None:
            pub_dt = _parse_datetime(date_str)

        if pub_dt is not None:
            if earliest_date is None or pub_dt < earliest_date:
                earliest_date = pub_dt

        all_items.append({
            "date_str": date_str,
            "time_str": time_str,
            "url": url,
            "title": title,
            "published_at": pub_dt,
        })

    for match in _DATE_ONLY_PATTERN.finditer(datelist_html):
        date_str = match.group(1)
        url = _normalize_url(match.group(2))
        title = _ENTITY_RE.sub(" ", match.group(3))

        pub_dt = _parse_datetime(date_str)
        if pub_dt is not None:
            if earliest_date is None or pub_dt < earliest_date:
                earliest_date = pub_dt

        all_items.append({
            "date_str": date_str,
            "time_str": "",
            "url": url,
            "title": title,
            "published_at": pub_dt,
        })

    stop = False
    if earliest_date is not None and earliest_date < start_dt:
        stop = True
    elif not all_items:
        stop = True

    filtered: list[dict[str, Any]] = []
    for item in all_items:
        pub_dt = item.get("published_at")
        if pub_dt is None:
            filtered.append(item)
        elif start_dt <= pub_dt <= end_dt:
            filtered.append(item)

    return filtered, stop



