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
    "600900.SSE",
    "601318.SSE",
    "601899.SSE",
    "688256.SSE",
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
            ("000333", "SZSE", "d"),
            ("002475", "SZSE", "d"),
            ("002594", "SZSE", "d"),
            ("300750", "SZSE", "d"),
            ("600036", "SSE", "d"),
            ("600276", "SSE", "d"),
            ("600309", "SSE", "d"),
            ("600519", "SSE", "d"),
            ("600900", "SSE", "d"),
            ("601318", "SSE", "d"),
            ("601899", "SSE", "d"),
            ("688256", "SSE", "d"),
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
    assert repository.count("agent_stock_profile") == 12
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


def test_stock_profile_backward_compat_no_archetype() -> None:
    """StockProfile without company_archetype defaults to generic."""
    from myQuant.news_ingestion.contracts import StockProfile

    sp = StockProfile(vt_symbol="TEST.SSE", name="Test")
    assert sp.company_archetype == "generic"
    assert sp.company_archetype_version == "company_archetype_v0.1"


def test_all_default_profiles_have_archetype() -> None:
    for vt_symbol, profile in DEFAULT_STOCK_PROFILES.items():
        assert profile.company_archetype != "generic", (
            f"{vt_symbol} ({profile.name}) still has default generic archetype"
        )
        assert profile.company_archetype_version == "company_archetype_v0.1"


def test_profile_archetype_matches_expected() -> None:
    expected = {
        "000333.SZSE": "consumer_moat",
        "002475.SZSE": "advanced_manufacturing",
        "002594.SZSE": "new_energy_chain",
        "300750.SZSE": "new_energy_chain",
        "600036.SSE": "financial",
        "600276.SSE": "healthcare_innovation",
        "600309.SSE": "cyclical_chemical",
        "600519.SSE": "consumer_moat",
        "600900.SSE": "utility_defensive",
        "601318.SSE": "financial",
        "601899.SSE": "cyclical_resource",
        "688256.SSE": "growth_concept",
    }
    for vt_symbol, expected_archetype in expected.items():
        profile = DEFAULT_STOCK_PROFILES[vt_symbol]
        assert profile.company_archetype == expected_archetype, (
            f"{vt_symbol} expected {expected_archetype}, got {profile.company_archetype}"
        )
