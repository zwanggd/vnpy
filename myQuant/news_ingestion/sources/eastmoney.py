"""Eastmoney stock news source via cmsArticleWeb search API.

Replaces the legacy announcement+PDF pipeline with direct text search
over the search-api-web.eastmoney.com endpoint.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

import requests

from myQuant.news_ingestion.contracts import NewsQuery, RawNewsItem, Source, SourceCategory, Status
from myQuant.news_ingestion.sources.base import BaseNewsSource, PoliteHttpClient, SourceFetchResult

SEARCH_URL = "https://search-api-web.eastmoney.com/search/jsonp"
SEARCH_COOKIE = (
    "qgqp_b_id=652bf4c98a74e210088f372a17d4e27b; "
    "st_si=55269775884615; st_pvi=66803244437563; st_sn=2"
)
PAGE_SIZE = 100
MAX_PAGES = 40  # safety cap


def _content_hash(title: str, content: str) -> str:
    return hashlib.sha256((title + (content or "")).encode()).hexdigest()


def _strip_tags(text: str) -> str:
    return re.sub(r"</?em>", "", text).replace("\u3000", " ").replace("\r\n", " ").strip()


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


class EastmoneyNewsSource(BaseNewsSource):
    """Search-based Eastmoney stock news source (cmsArticleWeb)."""

    source = Source.EASTMONEY

    def __init__(self, *, http_client: PoliteHttpClient | None = None) -> None:
        self._http = http_client or PoliteHttpClient()

    def fetch(self, query: NewsQuery) -> SourceFetchResult:
        items: list[RawNewsItem] = []
        errors: list[str] = []
        seen: set[str] = set()

        for page in range(1, MAX_PAGES + 1):
            raw_items, page_error = _fetch_page(query.symbol, page=page, size=PAGE_SIZE)
            if page_error:
                errors.append(page_error)
            if not raw_items:
                break

            for article in raw_items:
                title = _strip_tags(article.get("title", ""))
                content = _strip_tags(article.get("content", ""))
                if not title or not content or len(content) < 10:
                    continue

                published_at = _parse_date(article.get("date"))
                if published_at is None:
                    continue

                # date filter
                pub_date = published_at.date()
                if pub_date < query.start or pub_date > query.end:
                    continue  # after end — still might be earlier pages

                ch = _content_hash(title, content)
                if ch in seen:
                    continue
                seen.add(ch)

                url = article.get("url", "")
                items.append(
                    RawNewsItem(
                        source=Source.EASTMONEY,
                        source_category=SourceCategory.FINANCIAL_NEWS,
                        title=title,
                        content=content,
                        content_hash=ch,
                        source_item_id=article.get("code", ""),
                        url=url,
                        published_at=published_at,
                        language="zh",
                        body_status="text",
                    )
                )

        error_summary = "; ".join(errors) if errors else ""
        return SourceFetchResult(
            source=Source.EASTMONEY,
            status=Status.FAILED if errors and not items else Status.SUCCESS,
            items=tuple(items),
            error=error_summary,
            coverage_status="partial" if errors else "fetched",
        )


def _fetch_page(keyword: str, page: int, size: int) -> tuple[list[dict], str]:
    inner = {
        "uid": "",
        "keyword": keyword,
        "type": ["cmsArticleWeb"],
        "client": "web",
        "clientType": "web",
        "clientVersion": "curr",
        "param": {
            "cmsArticleWeb": {
                "searchScope": "default",
                "sort": "default",
                "pageIndex": page,
                "pageSize": size,
                "preTag": "<em>",
                "postTag": "</em>",
            }
        },
    }
    params = {
        "cb": "jQuery",
        "param": json.dumps(inner, ensure_ascii=False),
        "_": "",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": f"https://so.eastmoney.com/news/s?keyword={keyword}",
        "Cookie": SEARCH_COOKIE,
    }
    try:
        r = requests.get(SEARCH_URL, params=params, headers=headers, timeout=30)
        r.raise_for_status()
        text = r.text
        idx = text.index("(")
        jdx = text.rindex(")")
        data = json.loads(text[idx + 1 : jdx])
        result = data.get("result", data)
        articles = result.get("cmsArticleWeb", [])
        return articles, ""
    except Exception as exc:
        return [], str(exc)
