import sqlite3
from datetime import datetime
from pathlib import Path

from myQuant.news_ingestion import (
    AgentSignal,
    ImpactDirection,
    RawNewsItem,
    RelationType,
    Source,
    SourceCategory,
    StockProfile,
    TimeHorizon,
)
from myQuant.news_ingestion.storage import AgentNewsSqliteRepository


REQUIRED_TABLES = {
    "agent_backfill_run",
    "agent_stock_profile",
    "agent_raw_news",
    "agent_news_symbol",
    "agent_fetch_attempt",
    "agent_llm_run",
    "agent_llm_output",
    "agent_signal",
    "agent_source_cursor",
}

REQUIRED_COLUMNS = {
    "agent_backfill_run": {
        "run_id": "TEXT",
        "started_at": "DATETIME",
        "finished_at": "DATETIME",
        "status": "TEXT",
        "config_json": "TEXT",
        "summary_json": "TEXT",
        "error": "TEXT",
    },
    "agent_stock_profile": {
        "vt_symbol": "TEXT",
        "symbol": "TEXT",
        "exchange": "TEXT",
        "name": "TEXT",
        "aliases_json": "TEXT",
        "industry_json": "TEXT",
        "products_json": "TEXT",
        "upstream_json": "TEXT",
        "downstream_json": "TEXT",
        "macro_factors_json": "TEXT",
        "risk_keywords_json": "TEXT",
        "profile_version": "TEXT",
        "updated_at": "DATETIME",
    },
    "agent_raw_news": {
        "id": "INTEGER",
        "source": "TEXT",
        "source_category": "TEXT",
        "source_item_id": "TEXT",
        "url": "TEXT",
        "title": "TEXT",
        "content": "TEXT",
        "summary": "TEXT",
        "published_at": "DATETIME",
        "discovered_at": "DATETIME",
        "fetched_at": "DATETIME",
        "available_at": "DATETIME",
        "raw_payload_json": "TEXT",
        "content_hash": "TEXT",
        "body_status": "TEXT",
        "language": "TEXT",
        "created_at": "DATETIME",
    },
    "agent_news_symbol": {
        "id": "INTEGER",
        "raw_news_id": "INTEGER",
        "vt_symbol": "TEXT",
        "symbol": "TEXT",
        "exchange": "TEXT",
        "relation_hint": "TEXT",
        "mapping_method": "TEXT",
        "mapping_confidence": "REAL",
        "keywords_matched_json": "TEXT",
    },
    "agent_fetch_attempt": {
        "id": "INTEGER",
        "run_id": "TEXT",
        "source": "TEXT",
        "vt_symbol": "TEXT",
        "symbol": "TEXT",
        "exchange": "TEXT",
        "window_start": "DATETIME",
        "window_end": "DATETIME",
        "request_fingerprint": "TEXT",
        "status": "TEXT",
        "http_status": "INTEGER",
        "error": "TEXT",
        "attempt_no": "INTEGER",
        "started_at": "DATETIME",
        "finished_at": "DATETIME",
        "items_found": "INTEGER",
        "items_saved": "INTEGER",
    },
    "agent_llm_run": {
        "id": "INTEGER",
        "run_id": "TEXT",
        "raw_news_id": "INTEGER",
        "provider": "TEXT",
        "model": "TEXT",
        "prompt_version": "TEXT",
        "schema_version": "TEXT",
        "parameters_json": "TEXT",
        "input_hash": "TEXT",
        "started_at": "DATETIME",
        "finished_at": "DATETIME",
        "status": "TEXT",
        "error": "TEXT",
    },
    "agent_llm_output": {
        "id": "INTEGER",
        "llm_run_id": "INTEGER",
        "raw_response": "TEXT",
        "parsed_json": "TEXT",
        "validation_status": "TEXT",
        "validation_errors_json": "TEXT",
        "output_hash": "TEXT",
        "token_usage_json": "TEXT",
    },
    "agent_signal": {
        "id": "INTEGER",
        "raw_news_id": "INTEGER",
        "llm_run_id": "INTEGER",
        "vt_symbol": "TEXT",
        "symbol": "TEXT",
        "exchange": "TEXT",
        "event": "TEXT",
        "relation_type": "TEXT",
        "impact_direction": "TEXT",
        "impact_strength": "REAL",
        "time_horizon": "TEXT",
        "confidence": "REAL",
        "reason": "TEXT",
        "evidence_json": "TEXT",
        "published_at": "DATETIME",
        "available_at": "DATETIME",
        "trading_date": "TEXT",
        "source": "TEXT",
        "source_item_id": "TEXT",
        "prompt_version": "TEXT",
        "schema_version": "TEXT",
        "created_at": "DATETIME",
    },
    "agent_source_cursor": {
        "id": "INTEGER",
        "source": "TEXT",
        "scope_key": "TEXT",
        "window_start": "DATETIME",
        "window_end": "DATETIME",
        "cursor_state_json": "TEXT",
        "last_success_at": "DATETIME",
        "status": "TEXT",
        "updated_at": "DATETIME",
    },
}

REQUIRED_INDEX_COLUMNS = {
    "agent_raw_news": {("published_at",)},
    "agent_news_symbol": {("vt_symbol",)},
    "agent_signal": {("vt_symbol", "available_at"), ("trading_date",)},
    "agent_fetch_attempt": {("run_id", "source", "status")},
}

REQUIRED_UNIQUE_INDEX_COLUMNS = {
    "agent_raw_news": {("source", "source_item_id"), ("source", "content_hash")},
    "agent_news_symbol": {("raw_news_id", "vt_symbol")},
    "agent_llm_run": {("raw_news_id", "model", "prompt_version", "schema_version", "input_hash")},
    "agent_llm_output": {("llm_run_id",)},
    "agent_signal": {("raw_news_id", "llm_run_id", "vt_symbol", "event", "relation_type")},
    "agent_source_cursor": {("source", "scope_key", "window_start", "window_end")},
}


def table_names(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "select name from sqlite_master where type='table' and name like 'agent_%'"
        )
    return {row[0] for row in rows}


def row_count(db_path: Path, table_name: str) -> int:
    with sqlite3.connect(db_path) as connection:
        return connection.execute(f"select count(*) from {table_name}").fetchone()[0]


def table_columns(db_path: Path, table_name: str) -> dict[str, str]:
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(f"pragma table_info({table_name})").fetchall()
    return {row[1]: row[2] for row in rows}


def table_column_metadata(db_path: Path, table_name: str) -> dict[str, tuple[int, str | None]]:
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(f"pragma table_info({table_name})").fetchall()
    return {row[1]: (row[3], row[4]) for row in rows}


def index_columns(db_path: Path, table_name: str) -> set[tuple[str, ...]]:
    columns = set()
    with sqlite3.connect(db_path) as connection:
        indexes = connection.execute(f"pragma index_list({table_name})").fetchall()
        for index in indexes:
            index_name = index[1]
            index_columns_rows = connection.execute(f"pragma index_info({index_name})").fetchall()
            columns.add(tuple(row[2] for row in index_columns_rows))
    return columns


def unique_index_columns(db_path: Path, table_name: str) -> set[tuple[str, ...]]:
    columns = set()
    with sqlite3.connect(db_path) as connection:
        indexes = connection.execute(f"pragma index_list({table_name})").fetchall()
        for index in indexes:
            if not index[2]:
                continue
            index_name = index[1]
            index_columns_rows = connection.execute(f"pragma index_info({index_name})").fetchall()
            columns.add(tuple(row[2] for row in index_columns_rows))
    return columns


def raw_news_fixture() -> RawNewsItem:
    return RawNewsItem(
        source=Source.CNINFO,
        source_category=SourceCategory.ANNOUNCEMENT,
        source_item_id="cninfo-300750-1",
        url="https://example.test/cninfo-300750-1.pdf",
        title="宁德时代发布新电池技术公告",
        content="公告正文",
        summary="公告摘要",
        published_at=datetime(2026, 5, 8, 10, 0),
        discovered_at=datetime(2026, 5, 8, 10, 1),
        fetched_at=datetime(2026, 5, 8, 10, 2),
        available_at=datetime(2026, 5, 8, 10, 5),
        raw_payload={"source": "fixture"},
        content_hash="hash-cninfo-300750-1",
        body_status="success",
    )


def signal_fixture(raw_news_id: int, llm_run_id: int) -> AgentSignal:
    return AgentSignal(
        raw_news_id=raw_news_id,
        llm_run_id=llm_run_id,
        vt_symbol="300750.SZSE",
        event="宁德时代发布新电池技术",
        relation_type=RelationType.DIRECT_COMPANY,
        impact_direction=ImpactDirection.POSITIVE,
        impact_strength=0.72,
        time_horizon=TimeHorizon.SHORT,
        confidence=0.68,
        reason="新技术有望提升竞争力",
        evidence=["公告提及新电池技术"],
        published_at=datetime(2026, 5, 8, 10, 0),
        available_at=datetime(2026, 5, 8, 10, 5),
        trading_date="2026-05-08",
        source=Source.CNINFO,
        source_item_id="cninfo-300750-1",
        prompt_version="news_impact_v1",
        schema_version="agent_signal_v1",
    )


def test_schema_init_creates_required_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "agent_news.db"
    repository = AgentNewsSqliteRepository(db_path=db_path)

    repository.initialize_schema()

    assert db_path.exists()
    assert table_names(db_path) == REQUIRED_TABLES
    assert repository.get_table_names() == REQUIRED_TABLES


def test_schema_init_creates_required_columns_and_indexes(tmp_path: Path) -> None:
    db_path = tmp_path / "agent_news.db"
    repository = AgentNewsSqliteRepository(db_path=db_path)

    repository.initialize_schema()

    for table_name, columns in REQUIRED_COLUMNS.items():
        assert table_columns(db_path, table_name) == columns
    for table_name, required_indexes in REQUIRED_INDEX_COLUMNS.items():
        assert required_indexes <= index_columns(db_path, table_name)
    for table_name, required_unique_indexes in REQUIRED_UNIQUE_INDEX_COLUMNS.items():
        assert required_unique_indexes <= unique_index_columns(db_path, table_name)


def test_raw_news_schema_required_constraints_match_plan(tmp_path: Path) -> None:
    db_path = tmp_path / "agent_news.db"
    repository = AgentNewsSqliteRepository(db_path=db_path)

    repository.initialize_schema()

    metadata = table_column_metadata(db_path, "agent_raw_news")
    assert metadata["title"] == (1, None)
    assert metadata["content_hash"] == (1, None)
    assert metadata["language"] == (0, "'zh'")


def test_raw_news_upsert_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "agent_news.db"
    repository = AgentNewsSqliteRepository(db_path=db_path)
    repository.initialize_schema()
    raw_news = raw_news_fixture()

    first_id = repository.save_raw_news(raw_news)
    second_id = repository.save_raw_news(raw_news)

    assert second_id == first_id
    assert row_count(db_path, "agent_raw_news") == 1


def test_raw_news_without_source_item_id_deduplicates_by_content_hash(tmp_path: Path) -> None:
    db_path = tmp_path / "agent_news.db"
    repository = AgentNewsSqliteRepository(db_path=db_path)
    repository.initialize_schema()
    first_item = raw_news_fixture()
    first_item.source_item_id = ""
    first_item.content_hash = "hash-without-id-1"
    second_item = raw_news_fixture()
    second_item.source_item_id = ""
    second_item.content_hash = "hash-without-id-2"
    duplicate_item = raw_news_fixture()
    duplicate_item.source_item_id = ""
    duplicate_item.content_hash = first_item.content_hash

    first_id = repository.save_raw_news(first_item)
    second_id = repository.save_raw_news(second_item)
    duplicate_id = repository.save_raw_news(duplicate_item)

    assert second_id != first_id
    assert duplicate_id == first_id
    assert row_count(db_path, "agent_raw_news") == 2


def test_raw_news_upsert_deduplicates_changed_source_item_id_by_content_hash(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "agent_news.db"
    repository = AgentNewsSqliteRepository(db_path=db_path)
    repository.initialize_schema()
    first_item = raw_news_fixture()
    second_item = raw_news_fixture()
    second_item.source_item_id = "cninfo-renumbered-1"

    first_id = repository.save_raw_news(first_item)
    second_id = repository.save_raw_news(second_item)

    assert second_id == first_id
    assert row_count(db_path, "agent_raw_news") == 1


def test_signal_upsert_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "agent_news.db"
    repository = AgentNewsSqliteRepository(db_path=db_path)
    repository.initialize_schema()
    raw_news_id = repository.save_raw_news(raw_news_fixture())
    llm_run_id = repository.save_llm_run(
        run_id="run-1",
        raw_news_id=raw_news_id,
        provider="deepseek",
        model="deepseek-v4-flash",
        prompt_version="news_impact_v1",
        schema_version="agent_signal_v1",
        input_hash="input-hash-1",
        status="success",
    )
    signal = signal_fixture(raw_news_id=raw_news_id, llm_run_id=llm_run_id)

    first_id = repository.save_signal(signal)
    second_id = repository.save_signal(signal)

    assert second_id == first_id
    assert row_count(db_path, "agent_signal") == 1


def test_explicit_temp_db_path_is_used_and_market_db_is_not_modified(tmp_path: Path) -> None:
    agent_db_path = tmp_path / "nested" / "agent_news.db"
    market_db_path = Path.home() / ".vntrader" / "database.db"
    before_mtime = market_db_path.stat().st_mtime_ns if market_db_path.exists() else None
    repository = AgentNewsSqliteRepository(db_path=agent_db_path)

    repository.initialize_schema()
    repository.save_stock_profile(
        StockProfile(
            vt_symbol="300750.SZSE",
            name="宁德时代",
            aliases=("CATL", "300750"),
            industry=("动力电池",),
            products=("锂电池",),
        )
    )

    assert agent_db_path.exists()
    assert table_names(agent_db_path) == REQUIRED_TABLES
    after_mtime = market_db_path.stat().st_mtime_ns if market_db_path.exists() else None
    assert after_mtime == before_mtime


def test_repository_instances_keep_separate_temp_databases(tmp_path: Path) -> None:
    first_db_path = tmp_path / "first" / "agent_news.db"
    second_db_path = tmp_path / "second" / "agent_news.db"
    first_repository = AgentNewsSqliteRepository(db_path=first_db_path)
    second_repository = AgentNewsSqliteRepository(db_path=second_db_path)
    first_repository.initialize_schema()
    second_repository.initialize_schema()

    first_repository.save_raw_news(raw_news_fixture())

    assert row_count(first_db_path, "agent_raw_news") == 1
    assert row_count(second_db_path, "agent_raw_news") == 0
