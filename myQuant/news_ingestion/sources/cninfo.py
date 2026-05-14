from __future__ import annotations

import hashlib
import json
import urllib.parse
from collections.abc import Callable
from datetime import date, datetime
from io import BytesIO
from typing import Any

from myQuant.news_ingestion.contracts import NewsQuery, RawNewsItem, Source, SourceCategory, Status
from myQuant.news_ingestion.sources.base import BaseNewsSource, PoliteHttpClient, SourceFetchResult

SEARCH_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
ORG_LOOKUP_URL = "http://www.cninfo.com.cn/new/information/topSearch/query"
SZSE_STOCK_URL = "http://www.cninfo.com.cn/new/data/szse_stock.json"
SSE_STOCK_URL = "http://www.cninfo.com.cn/new/data/sse_stock.json"
PDF_BASE_URL = "http://static.cninfo.com.cn"
MAX_PAGES = 100
PAGE_SIZE = 30
# Safety cap: stop even if hasMore is true; with orgId filtering, 20 pages suffices
HARD_PAGE_LIMIT = 200

_PDF_EXTRACTOR_AVAILABLE = True
_PDF_IMPORT_ERROR = ""

_ORG_ID_CACHE: dict[str, str] = {}
_ORG_ID_CACHE_LOADED = False


def _load_org_id_cache(http_client: PoliteHttpClient) -> None:
    global _ORG_ID_CACHE, _ORG_ID_CACHE_LOADED
    if _ORG_ID_CACHE_LOADED:
        return

    for url in (SZSE_STOCK_URL, SSE_STOCK_URL):
        try:
            response = http_client.get(url)
            if response.status == Status.SUCCESS:
                data = json.loads(response.text)
                items = data.get("stockList") if isinstance(data, dict) else data
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, dict):
                            code = str(item.get("code", "")).strip()
                            org_id = str(item.get("orgId", "")).strip()
                            if code and org_id:
                                _ORG_ID_CACHE[code] = org_id
        except Exception:
            pass

    _ORG_ID_CACHE_LOADED = True


def _get_org_id(symbol: str) -> str:
    return _ORG_ID_CACHE.get(symbol, "")


def _default_pdf_extractor(pdf_bytes: bytes) -> dict[str, Any]:
    """Try pdfplumber first, then PyPDF2.  Return ``{"text": ... , "status": ...}``."""
    global _PDF_EXTRACTOR_AVAILABLE, _PDF_IMPORT_ERROR
    try:
        import pdfplumber  # noqa: F811

        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            pages_text: list[str] = []
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages_text.append(text)
            if pages_text:
                return {"text": "\n".join(pages_text), "status": "extracted"}
    except ImportError as exc:
        _PDF_IMPORT_ERROR = str(exc)
    except Exception:
        return {"text": "", "status": "failed"}

    try:
        import PyPDF2  # noqa: F811

        reader = PyPDF2.PdfReader(BytesIO(pdf_bytes))
        pages_text = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages_text.append(text)
        if pages_text:
            return {"text": "\n".join(pages_text), "status": "extracted"}
    except ImportError as exc:
        _PDF_IMPORT_ERROR = str(exc)
    except Exception:
        return {"text": "", "status": "failed"}

    _PDF_EXTRACTOR_AVAILABLE = False
    return {"text": "", "status": "skipped_no_pdf_extractor"}


def _compute_content_hash(*parts: str) -> str:
    joined = "|".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


class CninfoAnnouncementSource(BaseNewsSource):
    """CNInfo 巨潮资讯网 announcement adapter.

    Sources announcements via the public ``hisAnnouncement/query`` endpoint and
    best-effort PDF body extraction from ``static.cninfo.com.cn``.
    """

    source = Source.CNINFO

    def __init__(
        self,
        *,
        http_client: PoliteHttpClient | None = None,
        pdf_extractor: Callable[[bytes], dict[str, Any]] | None = None,
    ) -> None:
        self._http = http_client or PoliteHttpClient()
        self._pdf_extractor = pdf_extractor or _default_pdf_extractor

    # ------------------------------------------------------------------
    def fetch(self, query: NewsQuery) -> SourceFetchResult:
        # -- date window ------------------------------------------------
        start_str = self._format_date(query.start)
        end_str = self._format_date(query.end)

        # -- org ID cache (best-effort) ---------------------------------
        _load_org_id_cache(self._http)
        org_id = _get_org_id(query.symbol)
        if not org_id:
            org_id = self._lookup_org(query.symbol)

        # -- exchange → column ------------------------------------------
        exchange_lower = query.exchange.lower()
        column = exchange_lower if exchange_lower in ("szse", "sse") else "szse"

        # -- paginated search -------------------------------------------
        all_items: list[RawNewsItem] = []
        fetch_errors: list[str] = []

        for page_num in range(1, MAX_PAGES + 1):
            form_pairs: list[tuple[str, str]] = [
                ("pageNum", str(page_num)),
                ("pageSize", str(PAGE_SIZE)),
                ("tabName", "fulltext"),
                ("column", column),
                ("seDate", f"{start_str}~{end_str}"),
                ("sortName", "announcementTime"),
                ("sortType", "-1"),
            ]
            if org_id:
                form_pairs.append(("stock", f"{query.symbol},{org_id}"))
            else:
                form_pairs.append(("stock", query.symbol))

            data = urllib.parse.urlencode(form_pairs)

            response = self._http.post(
                SEARCH_URL,
                data=data,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "X-Requested-With": "XMLHttpRequest",
                },
            )

            if response.status != Status.SUCCESS:
                fetch_errors.append(response.error)
                break

            try:
                data = json.loads(response.text)
            except json.JSONDecodeError as exc:
                fetch_errors.append(f"JSON decode error: {exc}")
                break

            announcements = data.get("announcements", [])
            if not isinstance(announcements, list):
                announcements = []

            for ann in announcements:
                item = self._parse_announcement(ann)
                if item is not None:
                    all_items.append(item)
                    if item.body_status == "failed":
                        fetch_errors.append(
                            f"PDF extraction failed for {item.title or item.source_item_id}"
                        )

            # -- pagination guard ---------------------------------------
            has_more = data.get("hasMore", False)
            if not has_more or page_num >= HARD_PAGE_LIMIT:
                break

            # CNInfo may ignore seDate and return all-time results;
            # stop when all parsed items on this page are before start
            page_before_start = all(
                item.published_at is not None and item.published_at.date() < query.start
                for item in all_items[-len(announcements):] if item.published_at is not None
            )
            if page_before_start and announcements:
                break

        if not _PDF_EXTRACTOR_AVAILABLE and _PDF_IMPORT_ERROR:
            fetch_errors.append(f"PDF extractor unavailable: {_PDF_IMPORT_ERROR}")
        error_summary = "; ".join(fetch_errors) if fetch_errors else ""
        return SourceFetchResult(
            source=Source.CNINFO,
            status=Status.FAILED if fetch_errors and not all_items else Status.SUCCESS,
            items=tuple(all_items),
            error=error_summary,
            coverage_status="partial" if fetch_errors else "fetched",
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _lookup_org(self, symbol: str) -> str:
        response = self._http.get(ORG_LOOKUP_URL, params={"keyWord": symbol})
        if response.status != Status.SUCCESS:
            return ""
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            return ""
        if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
            return str(data[0].get("orgId", ""))
        return ""

    def _parse_announcement(self, ann: dict[str, Any]) -> RawNewsItem | None:
        title = ann.get("announcementTitle", "")
        if not title:
            return None

        adjunct_url: str = ann.get("adjunctUrl", "")
        ann_date_str: str = ann.get("annDate", "")

        # -- published_at -----------------------------------------------
        published_at: datetime | None = None
        if ann_date_str:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    published_at = datetime.strptime(ann_date_str, fmt)
                    break
                except ValueError:
                    continue
        if published_at is None:
            ann_time = ann.get("announcementTime")
            if isinstance(ann_time, (int, float)) and ann_time > 0:
                published_at = datetime.fromtimestamp(ann_time / 1000)

        # -- source_item_id / url ---------------------------------------
        source_item_id = adjunct_url if adjunct_url else title
        pdf_url = f"{PDF_BASE_URL}/{adjunct_url.lstrip('/')}" if adjunct_url else ""

        # -- PDF body (best-effort) -------------------------------------
        content = ""
        body_status = ""
        if adjunct_url:
            content, body_status = self._fetch_and_extract_pdf(adjunct_url)
        else:
            body_status = "no_adjunct_url"

        content_hash = _compute_content_hash(title, content)

        return RawNewsItem(
            source=Source.CNINFO,
            source_category=SourceCategory.ANNOUNCEMENT,
            title=title,
            content=content,
            summary="",
            content_hash=content_hash,
            source_item_id=source_item_id,
            url=pdf_url or "",
            published_at=published_at,
            body_status=body_status,
            raw_payload=ann,
            language="zh",
        )

    def _fetch_and_extract_pdf(self, adjunct_url: str) -> tuple[str, str]:
        """Download PDF bytes and run the injectable extractor.

        Returns ``(content, body_status)``.
        """
        pdf_url = f"{PDF_BASE_URL}/{adjunct_url.lstrip('/')}"
        response = self._http.get(pdf_url)

        if response.status != Status.SUCCESS:
            return "", "failed"

        result = self._pdf_extractor(response.content)
        return result.get("text", ""), result.get("status", "failed")

    @staticmethod
    def _format_date(d: date | datetime) -> str:
        if isinstance(d, datetime):
            return d.strftime("%Y-%m-%d")
        if isinstance(d, date):
            return d.isoformat()
        return str(d)
