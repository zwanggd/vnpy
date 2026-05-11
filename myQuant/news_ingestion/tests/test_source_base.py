from datetime import date

import pytest

from myQuant.news_ingestion import NewsQuery, RawNewsItem, Source, SourceCategory, Status
from myQuant.news_ingestion.sources import (
    BaseNewsSource,
    HttpResponse,
    PoliteHttpClient,
    SourceFetchResult,
    live_test_skip_marker,
    live_tests_enabled,
)


class FixtureSource(BaseNewsSource):
    source = Source.CNINFO

    def fetch(self, query: NewsQuery) -> SourceFetchResult:
        return SourceFetchResult(
            source=self.source,
            status=Status.SUCCESS,
            items=(
                RawNewsItem(
                    source=self.source,
                    source_category=SourceCategory.ANNOUNCEMENT,
                    title=f"fixture news for {query.vt_symbol}",
                    content_hash="fixture-hash",
                ),
            ),
            coverage_status="fixture",
            metadata={"query_symbol": query.symbol},
        )


def test_source_base_fetch_contract_returns_structured_result() -> None:
    query = NewsQuery(
        vt_symbol="300750.SZSE",
        start=date(2026, 5, 1),
        end=date(2026, 5, 8),
        sources=(Source.CNINFO,),
    )

    result = FixtureSource().fetch(query)

    assert result.source is Source.CNINFO
    assert result.status is Status.SUCCESS
    assert result.error == ""
    assert result.http_status is None
    assert result.coverage_status == "fixture"
    assert result.metadata == {"query_symbol": "300750"}
    assert len(result.items) == 1
    assert result.items[0].title == "fixture news for 300750.SZSE"


def test_http_429_retries_then_structured_failure() -> None:
    calls: list[dict[str, object]] = []

    def fake_transport(**kwargs: object) -> HttpResponse:
        calls.append(kwargs)
        return HttpResponse(status_code=429, text="rate limited", headers={})

    client = PoliteHttpClient(
        transport=fake_transport,
        request_interval=0.0,
        sleeper=lambda seconds: None,
    )

    result = client.get("https://example.invalid/news")

    assert result.status is Status.FAILED
    assert result.http_status == 429
    assert "429" in result.error
    assert len(calls) == 3


def test_live_marker_helper_disabled_unless_env_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_NEWS_LIVE_TEST", raising=False)

    disabled_marker = live_test_skip_marker()

    assert live_tests_enabled() is False
    assert disabled_marker.mark.name == "skipif"
    assert disabled_marker.mark.args == (True,)

    monkeypatch.setenv("AGENT_NEWS_LIVE_TEST", "1")

    enabled_marker = live_test_skip_marker()

    assert live_tests_enabled() is True
    assert enabled_marker.mark.args == (False,)


def test_http_client_applies_default_user_agent_header() -> None:
    calls: list[dict[str, object]] = []

    def fake_transport(**kwargs: object) -> HttpResponse:
        calls.append(kwargs)
        return HttpResponse(status_code=200, text="{}", headers={})

    client = PoliteHttpClient(
        transport=fake_transport,
        request_interval=0.0,
        sleeper=lambda seconds: None,
    )

    result = client.get("https://example.invalid/news")

    assert result.status is Status.SUCCESS
    assert calls
    headers = calls[0]["headers"]
    assert isinstance(headers, dict)
    assert headers["User-Agent"] == "Mozilla/5.0 AgentNewsV01Research"
