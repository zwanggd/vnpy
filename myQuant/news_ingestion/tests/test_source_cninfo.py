from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from myQuant.news_ingestion.contracts import NewsQuery, Source, SourceCategory, Status
from myQuant.news_ingestion.sources.base import HttpResponse, PoliteHttpClient
from myQuant.news_ingestion.sources.cninfo import CninfoAnnouncementSource

_SECNAME = "\u6d4b\u8bd5\u80a1\u4efd"  # 测试股份

_ORG_FIXTURE = [
    {"orgId": "org_9900025208", "category": "A\u80a1", "code": "300750", "zwjc": "\u5b81\u5fb7\u65f6\u4ee3"}
]

_ANNOUNCEMENT_FIXTURE = {
    "announcements": [
        {
            "announcementTitle": "\u5173\u4e8e2024\u5e74\u5ea6\u4e1a\u7ee9\u9884\u544a",
            "adjunctUrl": "final/2026/01/15/xxxxx.pdf",
            "annDate": "2026-01-15 16:30:00",
            "secName": _SECNAME,
        }
    ],
    "hasMore": False,
    "totalRecordNum": 1,
}

_PAGE_1_FIXTURE = {
    "announcements": [
        {
            "announcementTitle": "\u9875\u9762\u4e00\u516c\u544a",
            "adjunctUrl": "final/2026/01/10/p1.pdf",
            "annDate": "2026-01-10 10:00:00",
            "secName": _SECNAME,
        }
    ],
    "hasMore": True,
    "totalRecordNum": 2,
}

_PAGE_2_FIXTURE = {
    "announcements": [
        {
            "announcementTitle": "\u9875\u9762\u4e8c\u516c\u544a",
            "adjunctUrl": "final/2026/01/11/p2.pdf",
            "annDate": "2026-01-11 10:00:00",
            "secName": _SECNAME,
        }
    ],
    "hasMore": False,
    "totalRecordNum": 2,
}

_MOCK_PDF_BYTES = b"%PDF-1.4 mock pdf content"


def _fake_pdf_extractor_ok(pdf_bytes: bytes) -> dict[str, Any]:
    return {"text": "mock extracted text content", "status": "extracted"}


def _response_json(data: Any, status_code: int = 200) -> HttpResponse:
    return HttpResponse(
        status_code=status_code,
        text=json.dumps(data, ensure_ascii=False),
        headers={"Content-Type": "application/json"},
    )


def _response_pdf(status_code: int = 200) -> HttpResponse:
    return HttpResponse(
        status_code=status_code,
        content=_MOCK_PDF_BYTES,
        headers={"Content-Type": "application/pdf"},
    )


def _is_org_lookup(kwargs: Mapping[str, Any]) -> bool:
    return "topSearch" in str(kwargs.get("url", ""))


def _is_search(kwargs: Mapping[str, Any]) -> bool:
    return "hisAnnouncement" in str(kwargs.get("url", ""))


def _is_pdf(kwargs: Mapping[str, Any]) -> bool:
    return "static.cninfo.com.cn" in str(kwargs.get("url", ""))


def _page_num_from_search(kwargs: Mapping[str, Any]) -> int:
    json_body = kwargs.get("json")
    if isinstance(json_body, Mapping):
        return int(json_body.get("pageNum", 1))
    return 1


class TestCninfoAnnouncementSource:
    def test_parses_announcement_fixture(self) -> None:
        """Fixture metadata parses title, source_item_id/url, published_at, source cninfo, category announcement, content_hash."""
        calls: list[dict[str, object]] = []

        def fake_transport(**kwargs: object) -> HttpResponse:
            calls.append(kwargs)  # type: ignore[arg-type]
            url = str(kwargs.get("url", ""))
            if "topSearch" in url:
                return _response_json(_ORG_FIXTURE)
            if "hisAnnouncement" in url:
                return _response_json(_ANNOUNCEMENT_FIXTURE)
            return _response_pdf()

        client = PoliteHttpClient(
            transport=fake_transport,
            request_interval=0.0,
            sleeper=lambda s: None,
        )
        source = CninfoAnnouncementSource(
            http_client=client,
            pdf_extractor=_fake_pdf_extractor_ok,
        )

        query = NewsQuery(
            vt_symbol="300750.SZSE",
            start=date(2026, 1, 1),
            end=date(2026, 1, 31),
        )

        result = source.fetch(query)

        assert result.status is Status.SUCCESS
        assert len(result.items) == 1

        item = result.items[0]
        assert item.source is Source.CNINFO
        assert item.source_category is SourceCategory.ANNOUNCEMENT
        assert item.title == "\u5173\u4e8e2024\u5e74\u5ea6\u4e1a\u7ee9\u9884\u544a"
        assert item.source_item_id == "final/2026/01/15/xxxxx.pdf"
        assert "static.cninfo.com.cn/final/2026/01/15/xxxxx.pdf" in item.url
        assert item.published_at == datetime(2026, 1, 15, 16, 30, 0)
        assert len(item.content_hash) == 64
        assert item.content_hash != ""
        assert item.body_status == "extracted"
        assert item.content == "mock extracted text content"

    def test_pdf_failure_keeps_metadata(self) -> None:
        """RawNewsItem is still returned with body_status='failed' when PDF download fails."""
        calls: list[dict[str, object]] = []

        def fake_transport(**kwargs: object) -> HttpResponse:
            calls.append(kwargs)  # type: ignore[arg-type]
            url = str(kwargs.get("url", ""))
            if "topSearch" in url:
                return _response_json(_ORG_FIXTURE)
            if "hisAnnouncement" in url:
                return _response_json(_ANNOUNCEMENT_FIXTURE)
            return HttpResponse(
                status_code=500,
                text="Internal Server Error",
                headers={},
            )

        client = PoliteHttpClient(
            transport=fake_transport,
            request_interval=0.0,
            sleeper=lambda s: None,
        )
        source = CninfoAnnouncementSource(http_client=client)

        query = NewsQuery(
            vt_symbol="300750.SZSE",
            start=date(2026, 1, 1),
            end=date(2026, 1, 31),
        )

        result = source.fetch(query)

        assert result.status is Status.SUCCESS
        assert len(result.items) == 1

        item = result.items[0]
        assert item.body_status == "failed"
        assert item.title == "\u5173\u4e8e2024\u5e74\u5ea6\u4e1a\u7ee9\u9884\u544a"
        assert item.source_item_id == "final/2026/01/15/xxxxx.pdf"
        assert item.published_at == datetime(2026, 1, 15, 16, 30, 0)
        assert item.content == ""
        assert item.source is Source.CNINFO
        assert item.source_category is SourceCategory.ANNOUNCEMENT
        assert len(item.content_hash) == 64

    def test_pagination_loops_until_hasmore_false(self) -> None:
        """Fixture with hasMore=True on page 1, hasMore=False on page 2. Collects all items from both pages."""

        def fake_transport(**kwargs: object) -> HttpResponse:
            url = str(kwargs.get("url", ""))
            if "topSearch" in url:
                return _response_json(_ORG_FIXTURE)
            if "hisAnnouncement" in url:
                pg = _page_num_from_search(kwargs)
                if pg == 1:
                    return _response_json(_PAGE_1_FIXTURE)
                return _response_json(_PAGE_2_FIXTURE)
            return _response_pdf()

        client = PoliteHttpClient(
            transport=fake_transport,
            request_interval=0.0,
            sleeper=lambda s: None,
        )
        source = CninfoAnnouncementSource(
            http_client=client,
            pdf_extractor=_fake_pdf_extractor_ok,
        )

        query = NewsQuery(
            vt_symbol="300750.SZSE",
            start=date(2026, 1, 1),
            end=date(2026, 1, 31),
        )

        result = source.fetch(query)

        assert result.status is Status.SUCCESS
        assert len(result.items) == 2

        titles = {item.title for item in result.items}
        assert "\u9875\u9762\u4e00\u516c\u544a" in titles
        assert "\u9875\u9762\u4e8c\u516c\u544a" in titles

        for item in result.items:
            assert item.source is Source.CNINFO
            assert item.source_category is SourceCategory.ANNOUNCEMENT
            assert item.published_at is not None
            assert len(item.content_hash) == 64

    def test_no_adjunct_url_sets_skipped_status(self) -> None:
        """Announcement without adjunctUrl gets body_status='no_adjunct_url'."""
        no_adjunct_fixture = {
            "announcements": [
                {
                    "announcementTitle": "\u65e0\u9644\u4ef6\u516c\u544a",
                    "adjunctUrl": "",
                    "annDate": "2026-01-15",
                    "secName": _SECNAME,
                }
            ],
            "hasMore": False,
            "totalRecordNum": 1,
        }

        def fake_transport(**kwargs: object) -> HttpResponse:
            url = str(kwargs.get("url", ""))
            if "topSearch" in url:
                return _response_json(_ORG_FIXTURE)
            if "hisAnnouncement" in url:
                return _response_json(no_adjunct_fixture)
            return _response_pdf()

        client = PoliteHttpClient(
            transport=fake_transport,
            request_interval=0.0,
            sleeper=lambda s: None,
        )
        source = CninfoAnnouncementSource(http_client=client)

        query = NewsQuery(
            vt_symbol="300750.SZSE",
            start=date(2026, 1, 1),
            end=date(2026, 1, 31),
        )

        result = source.fetch(query)

        assert result.status is Status.SUCCESS
        assert len(result.items) == 1

        item = result.items[0]
        assert item.body_status == "no_adjunct_url"
        assert item.url == ""
        assert item.content == ""
        assert len(item.content_hash) == 64

    def test_org_lookup_failure_continues_without_orgid(self) -> None:
        """When org lookup fails, search proceeds with just stock code."""
        calls: list[dict[str, object]] = []

        def fake_transport(**kwargs: object) -> HttpResponse:
            calls.append(kwargs)  # type: ignore[arg-type]
            url = str(kwargs.get("url", ""))
            if "topSearch" in url:
                return HttpResponse(status_code=500, text="error", headers={})
            if "hisAnnouncement" in url:
                return _response_json(_ANNOUNCEMENT_FIXTURE)
            return _response_pdf()

        client = PoliteHttpClient(
            transport=fake_transport,
            request_interval=0.0,
            sleeper=lambda s: None,
        )
        source = CninfoAnnouncementSource(
            http_client=client,
            pdf_extractor=_fake_pdf_extractor_ok,
        )

        query = NewsQuery(
            vt_symbol="300750.SZSE",
            start=date(2026, 1, 1),
            end=date(2026, 1, 31),
        )

        result = source.fetch(query)

        assert result.status is Status.SUCCESS
        assert len(result.items) == 1
        assert result.items[0].source is Source.CNINFO

    def test_search_http_failure_records_error(self) -> None:
        """Search HTTP failure records error and returns empty items."""
        calls: list[dict[str, object]] = []

        def fake_transport(**kwargs: object) -> HttpResponse:
            calls.append(kwargs)  # type: ignore[arg-type]
            url = str(kwargs.get("url", ""))
            if "topSearch" in url:
                return _response_json(_ORG_FIXTURE)
            if "hisAnnouncement" in url:
                return HttpResponse(status_code=503, text="Service Unavailable", headers={})
            return _response_pdf()

        client = PoliteHttpClient(
            transport=fake_transport,
            request_interval=0.0,
            sleeper=lambda s: None,
        )
        source = CninfoAnnouncementSource(http_client=client)

        query = NewsQuery(
            vt_symbol="300750.SZSE",
            start=date(2026, 1, 1),
            end=date(2026, 1, 31),
        )

        result = source.fetch(query)

        assert result.status is Status.FAILED
        assert len(result.items) == 0
        assert result.error != ""
