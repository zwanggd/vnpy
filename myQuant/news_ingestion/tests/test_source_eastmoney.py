from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from myQuant.news_ingestion.contracts import NewsQuery, Source, SourceCategory, Status
from myQuant.news_ingestion.sources.base import HttpResponse, PoliteHttpClient
from myQuant.news_ingestion.sources.eastmoney import EastmoneyNewsSource


_ANNOUNCEMENT_FIXTURE = {
    "data": {
        "list": [
            {
                "art_code": "AN202601153000001",
                "title": "\u5b81\u5fb7\u65f6\u4ee3\u50a8\u80fd\u4e1a\u52a1\u83b7\u65b0\u8ba2\u5355",
                "notice_date": 1768433400000,
                "codes": [{"short_name": "\u5b81\u5fb7\u65f6\u4ee3"}],
                "content": "\u516c\u53f8\u50a8\u80fd\u4ea7\u54c1\u9700\u6c42\u6301\u7eed\u6539\u5584\u3002",
                "pdf_url": "//np-anotice-stock.eastmoney.com/a/202601153000001.html",
            }
        ]
    }
}


_STOCK_NEWS_HTML = """
<html>
  <body>
    <div class="news-list">
      <div class="news-item">
        <a href="//finance.eastmoney.com/a/202601153000001.html" title="宁德时代储能业务获新订单">宁德时代储能业务获新订单</a>
        <p class="summary">公司储能产品需求持续改善。</p>
        <span class="time">2026-01-15 09:30:00</span>
      </div>
    </div>
  </body>
</html>
"""


_EMPTY_STOCK_HTML = """
<html><body><div class="news-list"></div></body></html>
"""


_MISSING_DATE_SEARCH_HTML = """
<html>
  <body>
    <div class="result">
      <a href="https://finance.eastmoney.com/a/202601153000002.html">锂电产业链景气度跟踪</a>
      <p>行业需求有恢复迹象。</p>
    </div>
  </body>
</html>
"""


def _response_html(text: str, status_code: int = 200) -> HttpResponse:
    return HttpResponse(
        status_code=status_code,
        text=text,
        headers={"Content-Type": "text/html; charset=utf-8"},
    )


def _response_json(data: Any, status_code: int = 200) -> HttpResponse:
    return HttpResponse(
        status_code=status_code,
        text=json.dumps(data, ensure_ascii=False),
        headers={"Content-Type": "application/json"},
    )


def _query(*, keywords: tuple[str, ...] = ()) -> NewsQuery:
    return NewsQuery(
        vt_symbol="300750.SZSE",
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        keywords=keywords,
    )


class TestEastmoneyNewsSource:
    def test_eastmoney_parses_stock_news_fixture(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_transport(**kwargs: object) -> HttpResponse:
            calls.append(kwargs)  # type: ignore[arg-type]
            url = str(kwargs.get("url", ""))
            if "np-anotice-stock" in url:
                return _response_json(_ANNOUNCEMENT_FIXTURE)
            return _response_html(_STOCK_NEWS_HTML)

        client = PoliteHttpClient(
            transport=fake_transport,
            request_interval=0.0,
            sleeper=lambda s: None,
        )
        source = EastmoneyNewsSource(http_client=client)

        result = source.fetch(_query())

        assert result.status is Status.SUCCESS
        assert result.coverage_status == "partial"
        assert result.metadata["coverage_status"] == "partial"
        assert len(result.items) == 1

        item = result.items[0]
        assert item.source is Source.EASTMONEY
        assert item.source_category is SourceCategory.ANNOUNCEMENT
        assert item.title == "\u5b81\u5fb7\u65f6\u4ee3\u50a8\u80fd\u4e1a\u52a1\u83b7\u65b0\u8ba2\u5355"
        assert item.url == "https://np-anotice-stock.eastmoney.com/a/202601153000001.html"
        assert item.summary == "\u516c\u53f8\u50a8\u80fd\u4ea7\u54c1\u9700\u6c42\u6301\u7eed\u6539\u5584\u3002"
        assert item.content == "\u516c\u53f8\u50a8\u80fd\u4ea7\u54c1\u9700\u6c42\u6301\u7eed\u6539\u5584\u3002"
        assert item.published_at == datetime.fromtimestamp(1768433400)
        assert item.body_status == "inline"
        assert item.content_hash == hashlib.sha256((item.title + item.content).encode("utf-8")).hexdigest()
        assert len(item.content_hash) == 64

        first_params = calls[0]["params"]
        assert isinstance(first_params, Mapping)
        assert first_params["stock_list"] == "300750"
        assert first_params["page_size"] == "50"
        assert first_params["ann_type"] == "A"

    def test_eastmoney_missing_date_records_warning(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_transport(**kwargs: object) -> HttpResponse:
            calls.append(kwargs)  # type: ignore[arg-type]
            url = str(kwargs.get("url", ""))
            params = kwargs.get("params", {}) or {}
            if "so.eastmoney.com" in url:
                keyword = str(params.get("keyword", "") or "")
                if keyword == "\u9502\u7535":
                    return _response_html(_MISSING_DATE_SEARCH_HTML)
                return _response_html(_EMPTY_STOCK_HTML)
            return _response_html(_EMPTY_STOCK_HTML)

        client = PoliteHttpClient(
            transport=fake_transport,
            request_interval=0.0,
            sleeper=lambda s: None,
        )
        source = EastmoneyNewsSource(http_client=client)

        result = source.fetch(_query(keywords=("\u9502\u7535",)))

        assert result.status is Status.SUCCESS
        assert result.coverage_status == "partial"
        assert result.metadata["coverage_status"] == "partial"
        assert result.metadata["warnings"] == ["missing_published_at"]
        assert len(result.items) == 1

        item = result.items[0]
        assert item.source is Source.EASTMONEY
        assert item.source_category is SourceCategory.UNKNOWN
        assert item.title == "\u9502\u7535\u4ea7\u4e1a\u94fe\u666f\u6c14\u5ea6\u8ddf\u8e2a"
        assert item.url == "https://finance.eastmoney.com/a/202601153000002.html"
        assert item.content == "\u884c\u4e1a\u9700\u6c42\u6709\u6062\u590d\u8ff9\u8c61\u3002"
        assert item.published_at is None
        assert item.body_status == "missing_published_at"
        assert len(item.content_hash) == 64

        # Third call is the keyword search with "锂电"
        search_call = calls[-1]
        assert "so.eastmoney.com/news/s" in str(search_call["url"])
        params = search_call["params"]
        assert isinstance(params, Mapping)
        assert params["keyword"] == "\u9502\u7535"
