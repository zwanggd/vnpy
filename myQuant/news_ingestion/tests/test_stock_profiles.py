import json
import sqlite3
from pathlib import Path

import pytest

from myQuant.news_ingestion.profiles.stock_profiles import (
    DEFAULT_STOCK_PROFILES,
    discover_vt_symbols_from_market_db,
    persist_discovered_stock_profiles,
)
from myQuant.news_ingestion.storage import AgentNewsSqliteRepository


EXPECTED_VT_SYMBOLS = [
    "000333.SZSE",
    "002475.SZSE",
    "002594.SZSE",
    "300750.SZSE",
    "600036.SSE",
    "600276.SSE",
    "600309.SSE",
    "600519.SSE",
    "601318.SSE",
    "601899.SSE",
]


def create_market_db(db_path: Path, rows: list[tuple[str, str, str]]) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "create table dbbaroverview (symbol text, exchange text, interval text)"
        )
        connection.executemany(
            "insert into dbbaroverview (symbol, exchange, interval) values (?, ?, ?)",
            rows,
        )


def decode_json_column(row: dict[str, str], column_name: str) -> list[str]:
    return json.loads(row[column_name])


def test_discover_symbols_from_market_db_overview(tmp_path: Path) -> None:
    market_db_path = tmp_path / "database.db"
    create_market_db(
        market_db_path,
        [
            ("600519", "SSE", "d"),
            ("000333", "SZSE", "d"),
            ("300750", "SZSE", "d"),
            ("600519", "SSE", "1m"),
            ("601899", "SSE", "d"),
            ("600276", "SSE", "d"),
            ("002475", "SZSE", "d"),
            ("600309", "SSE", "d"),
            ("002594", "SZSE", "d"),
            ("601318", "SSE", "d"),
            ("600036", "SSE", "d"),
        ],
    )

    vt_symbols = discover_vt_symbols_from_market_db(market_db_path)

    assert vt_symbols == EXPECTED_VT_SYMBOLS


def test_all_seed_profiles_can_be_saved_and_retrieved(tmp_path: Path) -> None:
    market_db_path = tmp_path / "database.db"
    agent_db_path = tmp_path / "agent_news.db"
    create_market_db(
        market_db_path,
        [(vt_symbol.split(".")[0], vt_symbol.split(".")[1], "d") for vt_symbol in EXPECTED_VT_SYMBOLS],
    )
    repository = AgentNewsSqliteRepository(db_path=agent_db_path)

    saved_symbols = persist_discovered_stock_profiles(repository, market_db_path)

    assert saved_symbols == EXPECTED_VT_SYMBOLS
    assert repository.count("agent_stock_profile") == 10
    for vt_symbol in EXPECTED_VT_SYMBOLS:
        row = repository.get_stock_profile(vt_symbol)
        assert row is not None
        assert row["vt_symbol"] == vt_symbol
        assert row["name"] == DEFAULT_STOCK_PROFILES[vt_symbol].name


def test_catl_profile_includes_requested_keywords(tmp_path: Path) -> None:
    agent_db_path = tmp_path / "agent_news.db"
    repository = AgentNewsSqliteRepository(db_path=agent_db_path)
    repository.save_stock_profile(DEFAULT_STOCK_PROFILES["300750.SZSE"])

    row = repository.get_stock_profile("300750.SZSE")

    assert row is not None
    assert row["name"] == "宁德时代"
    assert "宁德时代" in decode_json_column(row, "aliases_json")
    assert "CATL" in decode_json_column(row, "aliases_json")
    assert "碳酸锂" in decode_json_column(row, "upstream_json")
    assert "价格战" in decode_json_column(row, "risk_keywords_json")


def test_missing_profile_reports_symbol(tmp_path: Path) -> None:
    market_db_path = tmp_path / "database.db"
    create_market_db(
        market_db_path,
        [(vt_symbol.split(".")[0], vt_symbol.split(".")[1], "d") for vt_symbol in EXPECTED_VT_SYMBOLS],
    )
    incomplete_profiles = {
        vt_symbol: profile
        for vt_symbol, profile in DEFAULT_STOCK_PROFILES.items()
        if vt_symbol != "300750.SZSE"
    }

    with pytest.raises(ValueError, match="300750\\.SZSE"):
        persist_discovered_stock_profiles(
            AgentNewsSqliteRepository(db_path=tmp_path / "agent_news.db"),
            market_db_path,
            profiles=incomplete_profiles,
        )
