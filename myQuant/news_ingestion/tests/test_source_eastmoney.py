from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import date, datetime

from myQuant.news_ingestion.contracts import NewsQuery, Source, SourceCategory, Status
from myQuant.news_ingestion.sources.base import HttpResponse, PoliteHttpClient
from myQuant.news_ingestion.sources.eastmoney import EastmoneyNewsSource


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
        assert item.source_category is SourceCategory.FINANCIAL_NEWS
        assert item.title == "宁德时代储能业务获新订单"
        assert item.url == "https://finance.eastmoney.com/a/202601153000001.html"
        assert item.summary == "公司储能产品需求持续改善。"
        assert item.content == "公司储能产品需求持续改善。"
        assert item.published_at == datetime(2026, 1, 15, 9, 30, 0)
        assert item.body_status == "inline"
        assert item.content_hash == hashlib.sha256((item.title + item.content).encode("utf-8")).hexdigest()
        assert len(item.content_hash) == 64

        first_params = calls[0]["params"]
        assert isinstance(first_params, Mapping)
        assert first_params["keyword"] == "300750"

    def test_eastmoney_missing_date_records_warning(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_transport(**kwargs: object) -> HttpResponse:
            calls.append(kwargs)  # type: ignore[arg-type]
            url = str(kwargs.get("url", ""))
            if "so.eastmoney.com" in url:
                return _response_html(_MISSING_DATE_SEARCH_HTML)
            return _response_html(_EMPTY_STOCK_HTML)

        client = PoliteHttpClient(
            transport=fake_transport,
            request_interval=0.0,
            sleeper=lambda s: None,
        )
        source = EastmoneyNewsSource(http_client=client)

        result = source.fetch(_query(keywords=("锂电",)))

        assert result.status is Status.SUCCESS
        assert result.coverage_status == "partial"
        assert result.metadata["coverage_status"] == "partial"
        assert result.metadata["warnings"] == ["missing_published_at"]
        assert len(result.items) == 1

        item = result.items[0]
        assert item.source is Source.EASTMONEY
        assert item.source_category is SourceCategory.UNKNOWN
        assert item.title == "锂电产业链景气度跟踪"
        assert item.url == "https://finance.eastmoney.com/a/202601153000002.html"
        assert item.content == "行业需求有恢复迹象。"
        assert item.published_at is None
        assert item.body_status == "missing_published_at"
        assert len(item.content_hash) == 64

        search_call = calls[-1]
        assert "so.eastmoney.com/news/s" in str(search_call["url"])
        params = search_call["params"]
        assert isinstance(params, Mapping)
        assert params["keyword"] == "锂电"
