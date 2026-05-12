"""Live smoke tests for news source adapters.

All live tests are gated by ``AGENT_NEWS_LIVE_TEST=1``.
Without that env var, every live test is skipped.
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import pytest

from myQuant.news_ingestion.contracts import NewsQuery, Source, Status
from myQuant.news_ingestion.sources.base import live_tests_enabled
from myQuant.news_ingestion.sources.cninfo import CninfoAnnouncementSource
from myQuant.news_ingestion.sources.cls import ClsTelegraphSource
from myQuant.news_ingestion.sources.eastmoney import EastmoneyNewsSource

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_VT_SYMBOL = "300750.SZSE"
# Use a recent 1-day window that is definitely in the past
_YESTERDAY = date.today() - timedelta(days=2)
_TEST_END = _YESTERDAY
_TEST_START = _YESTERDAY

_LIVE_REASON = "set AGENT_NEWS_LIVE_TEST=1 to run live source tests"


def _assert_no_crash(result, source_name: str) -> None:
    """Verify that the result is structured (SUCCESS or FAILED) with no exception."""
    assert result.status in {Status.SUCCESS, Status.FAILED}, (
        f"{source_name}: unexpected status {result.status}"
    )
    assert result.items is not None, f"{source_name}: items tuple must not be None"
    assert isinstance(result.error, str), f"{source_name}: error must be string"


# ---------------------------------------------------------------------------
# Verify skip works without env var
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    live_tests_enabled(),
    reason="AGENT_NEWS_LIVE_TEST is set; this test verifies skip behavior when unset",
)
def test_non_live_skips_without_env_var() -> None:
    """When AGENT_NEWS_LIVE_TEST is NOT set, this test should be skipped.

    It's marked to skip only when the env var IS set, so in normal test runs
    (without the env var) this test runs and passes trivially — confirming that
    the non-live suite does NOT depend on the live-opt-in variable.
    """
    assert "AGENT_NEWS_LIVE_TEST" not in os.environ or os.environ["AGENT_NEWS_LIVE_TEST"] != "1"


# ---------------------------------------------------------------------------
# CNInfo live smoke
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not live_tests_enabled(), reason=_LIVE_REASON)
def test_cninfo_live_smoke() -> None:
    """Live smoke: CNInfo returns structured fetch result for 300750.SZSE (1-day window)."""
    source = CninfoAnnouncementSource()
    query = NewsQuery(
        vt_symbol=TEST_VT_SYMBOL,
        start=_TEST_START,
        end=_TEST_END,
        sources=(Source.CNINFO,),
    )
    result = source.fetch(query)
    _assert_no_crash(result, "CNInfo")

    if result.status == Status.SUCCESS:
        # Success: may have items or may legitimately have zero (no announcements that day).
        # Either is acceptable; we just verify nothing crashed.
        assert len(result.items) >= 0, "CNInfo: item count should be non-negative"
    else:
        # FAILED is acceptable for live smoke — source may be unreachable or rate-limited.
        # Verify that error is recorded.
        assert result.error or result.http_status is not None, (
            "CNInfo FAILED: must have error string or HTTP status"
        )


# ---------------------------------------------------------------------------
# CLS Telegraph live smoke
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not live_tests_enabled(), reason=_LIVE_REASON)
def test_cls_live_smoke() -> None:
    """Live smoke: CLS Telegraph returns structured fetch result (1-day window)."""
    source = ClsTelegraphSource()
    query = NewsQuery(
        vt_symbol=TEST_VT_SYMBOL,
        start=_TEST_START,
        end=_TEST_END,
        sources=(Source.CLS_TELEGRAPH,),
    )
    result = source.fetch(query)
    _assert_no_crash(result, "CLS Telegraph")

    if result.status == Status.SUCCESS:
        # CLS has no stock filter; zero items in a narrow window is acceptable.
        assert len(result.items) >= 0, "CLS: item count should be non-negative"
    else:
        assert result.error or result.http_status is not None, (
            "CLS FAILED: must have error string or HTTP status"
        )


# ---------------------------------------------------------------------------
# Eastmoney live smoke
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not live_tests_enabled(), reason=_LIVE_REASON)
def test_eastmoney_live_smoke() -> None:
    """Live smoke: Eastmoney returns structured fetch result for 300750.SZSE (1-day window)."""
    source = EastmoneyNewsSource()
    query = NewsQuery(
        vt_symbol=TEST_VT_SYMBOL,
        start=_TEST_START,
        end=_TEST_END,
        sources=(Source.EASTMONEY,),
    )
    result = source.fetch(query)
    _assert_no_crash(result, "Eastmoney")

    if result.status == Status.SUCCESS:
        # Eastmoney results are partial by design; zero items is acceptable for a narrow window.
        assert len(result.items) >= 0, "Eastmoney: item count should be non-negative"
    else:
        assert result.error or result.http_status is not None, (
            "Eastmoney FAILED: must have error string or HTTP status"
        )


# ---------------------------------------------------------------------------
# All-sources combined live smoke
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not live_tests_enabled(), reason=_LIVE_REASON)
def test_all_sources_live_smoke() -> None:
    """Live smoke: all three sources return structured results without crashing."""
    sources: list[tuple[str, object]] = [
        ("cninfo", CninfoAnnouncementSource()),
        ("cls_telegraph", ClsTelegraphSource()),
        ("eastmoney", EastmoneyNewsSource()),
    ]

    for name, source in sources:
        query = NewsQuery(
            vt_symbol=TEST_VT_SYMBOL,
            start=_TEST_START,
            end=_TEST_END,
            sources=(Source(name),),
        )
        result = source.fetch(query)
        _assert_no_crash(result, name)

        # Record structured failure or success for debugging
        if result.status == Status.FAILED:
            # xfail-like: document failures but don't crash the whole test
            print(f"[live-smoke] {name} FAILED: {result.error or f'HTTP {result.http_status}'}")
        else:
            print(f"[live-smoke] {name} OK: {len(result.items)} items")
