from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from myQuant.news_ingestion.contracts import NewsQuery, Source, SourceCategory, Status
from myQuant.news_ingestion.sources.base import HttpResponse, PoliteHttpClient
from myQuant.news_ingestion.sources.cls import ClsTelegraphSource, compute_cls_signature


_FIRST_CTIME = 1_704_067_200
_NOW_TS = 1_704_153_600

_TELEGRAPH_FIXTURE = {
    "data": {
        "roll_data": [
            {
                "id": 123456,
                "title": "财联社1月1日电，测试标题",
                "content": "测试内容显示市场重要变化。",
                "ctime": _FIRST_CTIME,
                "shareurl": "https://www.cls.cn/detail/123456",
            }
        ]
    }
}

_EMPTY_FIXTURE = {"data": {"roll_data": []}}


def _response_json(data: Any, status_code: int = 200) -> HttpResponse:
    return HttpResponse(
        status_code=status_code,
        text=json.dumps(data, ensure_ascii=False),
        headers={"Content-Type": "application/json"},
    )


def _query() -> NewsQuery:
    return NewsQuery(
        vt_symbol="300750.SZSE",
        start=date(2024, 1, 1),
        end=date(2024, 1, 2),
    )


def test_cls_signature_is_deterministic() -> None:
    assert compute_cls_signature(last_time=1_704_067_200, rn=20) == "565646a51ea82027ab976a31a76099a7"


class TestClsTelegraphSource:
    def test_parses_fixture_response(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_transport(**kwargs: object) -> HttpResponse:
            calls.append(kwargs)  # type: ignore[arg-type]
            if len(calls) == 1:
                return _response_json(_TELEGRAPH_FIXTURE)
            return _response_json(_EMPTY_FIXTURE)

        client = PoliteHttpClient(
            transport=fake_transport,
            request_interval=0.0,
            sleeper=lambda s: None,
        )
        source = ClsTelegraphSource(http_client=client, clock=lambda: _NOW_TS)

        result = source.fetch(_query())

        assert result.status is Status.SUCCESS
        assert result.error == ""
        assert len(result.items) == 1

        item = result.items[0]
        assert item.source is Source.CLS_TELEGRAPH
        assert item.source_category is SourceCategory.FLASH
        assert item.source_item_id == "123456"
        assert item.title == "财联社1月1日电，测试标题"
        assert item.content == "测试内容显示市场重要变化。"
        assert item.published_at == datetime.fromtimestamp(_FIRST_CTIME)
        assert item.url == "https://www.cls.cn/detail/123456"
        assert item.body_status == "inline"
        assert item.raw_payload["id"] == 123456
        assert item.content_hash == hashlib.sha256((item.title + item.content).encode("utf-8")).hexdigest()

        first_params = calls[0]["params"]
        assert isinstance(first_params, Mapping)
        assert first_params["app"] == "CailianpressWeb"
        assert first_params["os"] == "web"
        assert first_params["sv"] == "7.7.5"
        assert first_params["rn"] == "20"
        assert first_params["last_time"] == str(_NOW_TS)
        assert first_params["sign"] == compute_cls_signature(last_time=_NOW_TS, rn=20)

        second_params = calls[1]["params"]
        assert isinstance(second_params, Mapping)
        assert second_params["last_time"] == str(_FIRST_CTIME)

    def test_cls_malformed_response_records_failure(self) -> None:
        def fake_transport(**kwargs: object) -> HttpResponse:
            return _response_json({"data": {"unexpected": []}})

        client = PoliteHttpClient(
            transport=fake_transport,
            request_interval=0.0,
            sleeper=lambda s: None,
        )
        source = ClsTelegraphSource(http_client=client, clock=lambda: _NOW_TS)

        result = source.fetch(_query())

        assert result.status is Status.FAILED
        assert result.items == ()
        assert "parse" in result.error.lower()
        assert result.coverage_status == "failed"
