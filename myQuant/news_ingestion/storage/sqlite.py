from __future__ import annotations

import json
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from peewee import (
    DateTimeField,
    FloatField,
    IntegerField,
    Model,
    SQL,
    SqliteDatabase,
    TextField,
    IntegrityError,
)
from playhouse.shortcuts import model_to_dict

from myQuant.news_ingestion.contracts import (
    AgentSignal,
    LLMOutputRecord,
    LLMRunRecord,
    MappedNews,
    RawNewsItem,
    StockProfile,
    generate_vt_symbol,
    parse_vt_symbol,
)
from vnpy.trader.utility import get_file_path

from myQuant.news_ingestion.storage.backup import backup_agent_db


_last_backup_ts: dict[str, float] = {}
_BACKUP_RATE_LIMIT_SECONDS: int = 600  # 10 minutes

DEFAULT_AGENT_NEWS_DB_PATH = get_file_path("agent_news.db")


def _resolve_db_path(db_path: str | Path | None) -> Path:
    if db_path is None:
        return DEFAULT_AGENT_NEWS_DB_PATH
    return Path(db_path).expanduser()


def _json_dump(value: Any) -> str:
    if value is None:
        return ""
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, tuple):
        value = list(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


class AgentBackfillRun(Model):
    run_id = TextField(primary_key=True)
    started_at = DateTimeField(null=True)
    finished_at = DateTimeField(null=True)
    status = TextField(null=True)
    config_json = TextField(null=True)
    summary_json = TextField(null=True)
    error = TextField(null=True)

    class Meta:
        table_name = "agent_backfill_run"


class AgentStockProfile(Model):
    vt_symbol = TextField(primary_key=True)
    symbol = TextField(null=True)
    exchange = TextField(null=True)
    name = TextField(null=True)
    aliases_json = TextField(null=True)
    industry_json = TextField(null=True)
    products_json = TextField(null=True)
    upstream_json = TextField(null=True)
    downstream_json = TextField(null=True)
    macro_factors_json = TextField(null=True)
    risk_keywords_json = TextField(null=True)
    profile_version = TextField(null=True)
    updated_at = DateTimeField(null=True)

    class Meta:
        table_name = "agent_stock_profile"


class AgentRawNews(Model):
    id = IntegerField(primary_key=True, constraints=[SQL("AUTOINCREMENT")])
    source = TextField(null=True)
    source_category = TextField(null=True)
    source_item_id = TextField(null=True)
    url = TextField(null=True)
    title = TextField()
    content = TextField(null=True)
    summary = TextField(null=True)
    published_at = DateTimeField(null=True, index=True)
    discovered_at = DateTimeField(null=True)
    fetched_at = DateTimeField(null=True)
    available_at = DateTimeField(null=True)
    raw_payload_json = TextField(null=True)
    content_hash = TextField()
    body_status = TextField(null=True)
    language = TextField(null=True, constraints=[SQL("DEFAULT 'zh'")])
    created_at = DateTimeField(null=True)

    class Meta:
        table_name = "agent_raw_news"
        indexes = (
            (("source", "source_item_id"), True),
            (("source", "content_hash"), True),
        )


class AgentNewsSymbol(Model):
    id = IntegerField(primary_key=True, constraints=[SQL("AUTOINCREMENT")])
    raw_news_id = IntegerField(null=True)
    vt_symbol = TextField(null=True, index=True)
    symbol = TextField(null=True)
    exchange = TextField(null=True)
    relation_hint = TextField(null=True)
    mapping_method = TextField(null=True)
    mapping_confidence = FloatField(null=True)
    keywords_matched_json = TextField(null=True)

    class Meta:
        table_name = "agent_news_symbol"
        indexes = ((("raw_news_id", "vt_symbol"), True),)


class AgentFetchAttempt(Model):
    id = IntegerField(primary_key=True, constraints=[SQL("AUTOINCREMENT")])
    run_id = TextField(null=True)
    source = TextField(null=True)
    vt_symbol = TextField(null=True)
    symbol = TextField(null=True)
    exchange = TextField(null=True)
    window_start = DateTimeField(null=True)
    window_end = DateTimeField(null=True)
    request_fingerprint = TextField(null=True)
    status = TextField(null=True)
    http_status = IntegerField(null=True)
    error = TextField(null=True)
    attempt_no = IntegerField(null=True)
    started_at = DateTimeField(null=True)
    finished_at = DateTimeField(null=True)
    items_found = IntegerField(null=True)
    items_saved = IntegerField(null=True)

    class Meta:
        table_name = "agent_fetch_attempt"
        indexes = ((("run_id", "source", "status"), False),)


class AgentLLMRun(Model):
    id = IntegerField(primary_key=True, constraints=[SQL("AUTOINCREMENT")])
    run_id = TextField(null=True)
    raw_news_id = IntegerField(null=True)
    provider = TextField(null=True)
    model = TextField(null=True)
    prompt_version = TextField(null=True)
    schema_version = TextField(null=True)
    parameters_json = TextField(null=True)
    input_hash = TextField(null=True)
    started_at = DateTimeField(null=True)
    finished_at = DateTimeField(null=True)
    status = TextField(null=True)
    error = TextField(null=True)

    class Meta:
        table_name = "agent_llm_run"
        indexes = (
            (("raw_news_id", "model", "prompt_version", "schema_version", "input_hash"), True),
        )


class AgentLLMOutput(Model):
    id = IntegerField(primary_key=True, constraints=[SQL("AUTOINCREMENT")])
    llm_run_id = IntegerField(unique=True, null=True)
    raw_response = TextField(null=True)
    parsed_json = TextField(null=True)
    validation_status = TextField(null=True)
    validation_errors_json = TextField(null=True)
    output_hash = TextField(null=True)
    token_usage_json = TextField(null=True)

    class Meta:
        table_name = "agent_llm_output"


class AgentSignalModel(Model):
    id = IntegerField(primary_key=True, constraints=[SQL("AUTOINCREMENT")])
    raw_news_id = IntegerField(null=True)
    llm_run_id = IntegerField(null=True)
    vt_symbol = TextField(null=True)
    symbol = TextField(null=True)
    exchange = TextField(null=True)
    event = TextField(null=True)
    relation_type = TextField(null=True)
    impact_direction = TextField(null=True)
    impact_strength = FloatField(null=True)
    time_horizon = TextField(null=True)
    confidence = FloatField(null=True)
    reason = TextField(null=True)
    evidence_json = TextField(null=True)
    published_at = DateTimeField(null=True)
    available_at = DateTimeField(null=True)
    trading_date = TextField(null=True, index=True)
    source = TextField(null=True)
    source_item_id = TextField(null=True)
    prompt_version = TextField(null=True)
    schema_version = TextField(null=True)
    signal_version = TextField(null=True)
    created_at = DateTimeField(null=True)

    class Meta:
        table_name = "agent_signal"
        indexes = (
            (("raw_news_id", "llm_run_id", "vt_symbol", "event", "relation_type"), True),
            (("vt_symbol", "available_at"), False),
        )


class AgentSourceCursor(Model):
    id = IntegerField(primary_key=True, constraints=[SQL("AUTOINCREMENT")])
    source = TextField(null=True)
    scope_key = TextField(null=True)
    window_start = DateTimeField(null=True)
    window_end = DateTimeField(null=True)
    cursor_state_json = TextField(null=True)
    last_success_at = DateTimeField(null=True)
    status = TextField(null=True)
    updated_at = DateTimeField(null=True)

    class Meta:
        table_name = "agent_source_cursor"
        indexes = ((("source", "scope_key", "window_start", "window_end"), True),)


class AgentDailySignalModel(Model):
    id = IntegerField(primary_key=True, constraints=[SQL("AUTOINCREMENT")])
    trading_date = TextField(null=True)
    vt_symbol = TextField(null=True)
    signal_version = TextField(null=True)
    daily_agent_signal = FloatField(null=True)
    daily_direction = TextField(null=True)
    agent_label = TextField(null=True)
    raw_daily_signal = FloatField(null=True)
    news_count = IntegerField(null=True)
    event_count = IntegerField(null=True)
    model_count = IntegerField(null=True)
    mixed_intensity = FloatField(null=True)
    risk_penalty = FloatField(null=True)
    created_at = DateTimeField(null=True)

    class Meta:
        table_name = "agent_daily_signal"
        indexes = (
            (("trading_date", "vt_symbol", "signal_version"), True),
        )


AGENT_MODELS = (
    AgentBackfillRun,
    AgentStockProfile,
    AgentRawNews,
    AgentNewsSymbol,
    AgentFetchAttempt,
    AgentLLMRun,
    AgentLLMOutput,
    AgentSignalModel,
    AgentSourceCursor,
    AgentDailySignalModel,
)


class AgentNewsSqliteRepository:
    def __init__(
        self,
        db_path: str | Path | None = None,
        enable_backup: bool = True,
    ) -> None:
        self._in_memory = db_path is None or (isinstance(db_path, str) and db_path == ":memory:")
        self._enable_backup = enable_backup
        if self._in_memory:
            self.db_path: Path | None = None
            self.database = SqliteDatabase(":memory:")
            self.database.connect(reuse_if_open=True)
        else:
            self.db_path = _resolve_db_path(db_path)
            self.database = SqliteDatabase(str(self.db_path))
        self._bind_models()
        self._maybe_backup()

    def _maybe_backup(self) -> None:
        if self._in_memory or not self._enable_backup:
            return
        if self.db_path is None or not self.db_path.exists():
            return

        now = time.time()
        key = str(self.db_path)
        last_ts = _last_backup_ts.get(key, 0)
        if now - last_ts < _BACKUP_RATE_LIMIT_SECONDS:
            return

        backup_agent_db(self.db_path)
        _last_backup_ts[key] = now

    def _bind_models(self) -> None:
        self.database.bind(AGENT_MODELS, bind_refs=False, bind_backrefs=False)

    def initialize_schema(self) -> None:
        if not self._in_memory:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._bind_models()
        if self._in_memory:
            self.database.create_tables(AGENT_MODELS, safe=True)
        else:
            with self.database.connection_context():
                self.database.create_tables(AGENT_MODELS, safe=True)

    def close(self) -> None:
        if not self.database.is_closed():
            self.database.close()

    def save_raw_news(self, item: RawNewsItem) -> int:
        self.initialize_schema()
        created_at = datetime.now()
        data = {
            "source": item.source.value,
            "source_category": item.source_category.value,
            "source_item_id": item.source_item_id or None,
            "url": item.url,
            "title": item.title,
            "content": item.content,
            "summary": item.summary,
            "published_at": item.published_at,
            "discovered_at": item.discovered_at,
            "fetched_at": item.fetched_at,
            "available_at": item.available_at,
            "raw_payload_json": _json_dump(item.raw_payload),
            "content_hash": item.content_hash,
            "body_status": item.body_status,
            "language": item.language,
            "created_at": created_at,
        }
        conflict_target = (AgentRawNews.source, AgentRawNews.source_item_id)
        if not item.source_item_id:
            conflict_target = (AgentRawNews.source, AgentRawNews.content_hash)
        updates = dict(data)
        updates.pop("created_at")
        try:
            AgentRawNews.insert(data).on_conflict(
                conflict_target=conflict_target,
                preserve=[AgentRawNews.created_at],
                update=updates,
            ).execute()
        except IntegrityError:
            AgentRawNews.insert(data).on_conflict(
                conflict_target=(AgentRawNews.source, AgentRawNews.content_hash),
                preserve=[AgentRawNews.created_at],
                update=updates,
            ).execute()
        row = self._get_raw_news(item.source.value, item.source_item_id, item.content_hash)
        return int(row.id)

    def _get_raw_news(self, source: str, source_item_id: str, content_hash: str) -> AgentRawNews:
        query = AgentRawNews.select().where(AgentRawNews.source == source)
        if source_item_id:
            row = query.where(AgentRawNews.source_item_id == source_item_id).first()
            if row:
                return row
        return query.where(AgentRawNews.content_hash == content_hash).get()

    def is_raw_news_saved(self, source_item_id: str, source: str) -> bool:
        """Check if raw news with the given source+source_item_id already exists."""
        if not source_item_id:
            return False
        self.initialize_schema()
        return AgentRawNews.select().where(
            (AgentRawNews.source == source)
            & (AgentRawNews.source_item_id == source_item_id)
        ).exists()

    def save_signal(self, signal: AgentSignal) -> int:
        self.initialize_schema()
        data = {
            "raw_news_id": signal.raw_news_id,
            "llm_run_id": signal.llm_run_id,
            "vt_symbol": signal.vt_symbol,
            "symbol": signal.symbol,
            "exchange": signal.exchange,
            "event": signal.event,
            "relation_type": signal.relation_type.value,
            "impact_direction": signal.impact_direction.value,
            "impact_strength": signal.impact_strength,
            "time_horizon": signal.time_horizon.value,
            "confidence": signal.confidence,
            "reason": signal.reason,
            "evidence_json": _json_dump(signal.evidence),
            "published_at": signal.published_at,
            "available_at": signal.available_at,
            "trading_date": signal.trading_date,
            "source": signal.source.value,
            "source_item_id": signal.source_item_id,
            "prompt_version": signal.prompt_version,
            "schema_version": signal.schema_version,
            "signal_version": signal.signal_version,
            "created_at": signal.created_at,
        }
        updates = dict(data)
        updates.pop("created_at")
        AgentSignalModel.insert(data).on_conflict(
            conflict_target=(
                AgentSignalModel.raw_news_id,
                AgentSignalModel.llm_run_id,
                AgentSignalModel.vt_symbol,
                AgentSignalModel.event,
                AgentSignalModel.relation_type,
            ),
            preserve=[AgentSignalModel.created_at],
            update=updates,
        ).execute()
        row = AgentSignalModel.get(
            (AgentSignalModel.raw_news_id == signal.raw_news_id)
            & (AgentSignalModel.llm_run_id == signal.llm_run_id)
            & (AgentSignalModel.vt_symbol == signal.vt_symbol)
            & (AgentSignalModel.event == signal.event)
            & (AgentSignalModel.relation_type == signal.relation_type.value)
        )
        return int(row.id)

    def save_daily_signal(self, signal: dict) -> int:
        self.initialize_schema()
        data = {
            "trading_date": signal.get("trading_date"),
            "vt_symbol": signal.get("vt_symbol"),
            "signal_version": signal.get("signal_version"),
            "daily_agent_signal": signal.get("daily_agent_signal"),
            "daily_direction": signal.get("daily_direction"),
            "agent_label": signal.get("agent_label"),
            "raw_daily_signal": signal.get("raw_daily_signal"),
            "news_count": signal.get("news_count", 0),
            "event_count": signal.get("event_count", 0),
            "model_count": signal.get("model_count", 0),
            "mixed_intensity": signal.get("mixed_intensity", 0),
            "risk_penalty": signal.get("risk_penalty", 1.0),
            "created_at": datetime.now(),
        }
        AgentDailySignalModel.insert(data).on_conflict(
            conflict_target=(
                AgentDailySignalModel.trading_date,
                AgentDailySignalModel.vt_symbol,
                AgentDailySignalModel.signal_version,
            ),
            update=data,
        ).execute()
        row = AgentDailySignalModel.get(
            (AgentDailySignalModel.trading_date == data["trading_date"])
            & (AgentDailySignalModel.vt_symbol == data["vt_symbol"])
            & (AgentDailySignalModel.signal_version == data["signal_version"])
        )
        return int(row.id)

    def save_stock_profile(self, profile: StockProfile) -> str:
        self.initialize_schema()
        data = {
            "vt_symbol": profile.vt_symbol,
            "symbol": profile.symbol,
            "exchange": profile.exchange,
            "name": profile.name,
            "aliases_json": _json_dump(profile.aliases),
            "industry_json": _json_dump(profile.industry),
            "products_json": _json_dump(profile.products),
            "upstream_json": _json_dump(profile.upstream),
            "downstream_json": _json_dump(profile.downstream),
            "macro_factors_json": _json_dump(profile.macro_factors),
            "risk_keywords_json": _json_dump(profile.risk_keywords),
            "profile_version": profile.profile_version,
            "updated_at": profile.updated_at or datetime.now(),
        }
        AgentStockProfile.insert(data).on_conflict(
            conflict_target=(AgentStockProfile.vt_symbol,),
            update=data,
        ).execute()
        return profile.vt_symbol

    def save_mapped_news(self, mapped_news: MappedNews) -> int:
        self.initialize_schema()
        data = {
            "raw_news_id": mapped_news.raw_news_id,
            "vt_symbol": mapped_news.vt_symbol,
            "symbol": mapped_news.symbol,
            "exchange": mapped_news.exchange,
            "relation_hint": mapped_news.relation_hint.value,
            "mapping_method": mapped_news.mapping_method,
            "mapping_confidence": mapped_news.mapping_confidence,
            "keywords_matched_json": _json_dump(mapped_news.keywords_matched),
        }
        AgentNewsSymbol.insert(data).on_conflict(
            conflict_target=(AgentNewsSymbol.raw_news_id, AgentNewsSymbol.vt_symbol),
            update=data,
        ).execute()
        row = AgentNewsSymbol.get(
            (AgentNewsSymbol.raw_news_id == mapped_news.raw_news_id)
            & (AgentNewsSymbol.vt_symbol == mapped_news.vt_symbol)
        )
        return int(row.id)

    def save_fetch_attempt(self, **kwargs: Any) -> int:
        self.initialize_schema()
        data = {
            "run_id": kwargs.get("run_id"),
            "source": _enum_value(kwargs.get("source")),
            "vt_symbol": kwargs.get("vt_symbol"),
            "symbol": kwargs.get("symbol"),
            "exchange": kwargs.get("exchange"),
            "window_start": kwargs.get("window_start"),
            "window_end": kwargs.get("window_end"),
            "request_fingerprint": kwargs.get("request_fingerprint"),
            "status": _enum_value(kwargs.get("status")),
            "http_status": kwargs.get("http_status"),
            "error": kwargs.get("error"),
            "attempt_no": kwargs.get("attempt_no"),
            "started_at": kwargs.get("started_at"),
            "finished_at": kwargs.get("finished_at"),
            "items_found": kwargs.get("items_found"),
            "items_saved": kwargs.get("items_saved"),
        }
        return int(AgentFetchAttempt.create(**data).id)

    def save_backfill_run(self, **kwargs: Any) -> str:
        self.initialize_schema()
        run_id = kwargs["run_id"]
        data = {
            "run_id": run_id,
            "started_at": kwargs.get("started_at"),
            "finished_at": kwargs.get("finished_at"),
            "status": _enum_value(kwargs.get("status")),
            "config_json": _json_dump(kwargs.get("config")),
            "summary_json": _json_dump(kwargs.get("summary")),
            "error": kwargs.get("error"),
        }
        AgentBackfillRun.insert(data).on_conflict(
            conflict_target=(AgentBackfillRun.run_id,),
            update=data,
        ).execute()
        return str(run_id)

    def save_llm_run(self, record: LLMRunRecord | None = None, **kwargs: Any) -> int:
        self.initialize_schema()
        if record is not None:
            kwargs = {
                "run_id": record.run_id,
                "raw_news_id": record.raw_news_id,
                "provider": record.provider,
                "model": record.model,
                "prompt_version": record.prompt_version,
                "schema_version": record.schema_version,
                "parameters": record.parameters,
                "input_hash": record.input_hash,
                "started_at": record.started_at,
                "finished_at": record.finished_at,
                "status": record.status,
                "error": record.error,
            }
        data = {
            "run_id": kwargs.get("run_id"),
            "raw_news_id": kwargs.get("raw_news_id"),
            "provider": kwargs.get("provider"),
            "model": kwargs.get("model"),
            "prompt_version": kwargs.get("prompt_version"),
            "schema_version": kwargs.get("schema_version"),
            "parameters_json": _json_dump(kwargs.get("parameters")),
            "input_hash": kwargs.get("input_hash"),
            "started_at": kwargs.get("started_at"),
            "finished_at": kwargs.get("finished_at"),
            "status": _enum_value(kwargs.get("status")),
            "error": kwargs.get("error"),
        }
        AgentLLMRun.insert(data).on_conflict(
            conflict_target=(
                AgentLLMRun.raw_news_id,
                AgentLLMRun.model,
                AgentLLMRun.prompt_version,
                AgentLLMRun.schema_version,
                AgentLLMRun.input_hash,
            ),
            update=data,
        ).execute()
        row = AgentLLMRun.get(
            (AgentLLMRun.raw_news_id == data["raw_news_id"])
            & (AgentLLMRun.model == data["model"])
            & (AgentLLMRun.prompt_version == data["prompt_version"])
            & (AgentLLMRun.schema_version == data["schema_version"])
            & (AgentLLMRun.input_hash == data["input_hash"])
        )
        return int(row.id)

    def save_llm_output(self, record: LLMOutputRecord | None = None, **kwargs: Any) -> int:
        self.initialize_schema()
        if record is not None:
            kwargs = {
                "llm_run_id": record.llm_run_id,
                "raw_response": record.raw_response,
                "parsed_json": record.parsed_json,
                "validation_status": record.validation_status,
                "validation_errors": record.validation_errors,
                "output_hash": record.output_hash,
                "token_usage": record.token_usage,
            }
        data = {
            "llm_run_id": kwargs.get("llm_run_id"),
            "raw_response": kwargs.get("raw_response"),
            "parsed_json": _json_dump(kwargs.get("parsed_json")),
            "validation_status": _enum_value(kwargs.get("validation_status")),
            "validation_errors_json": _json_dump(kwargs.get("validation_errors")),
            "output_hash": kwargs.get("output_hash"),
            "token_usage_json": _json_dump(kwargs.get("token_usage")),
        }
        AgentLLMOutput.insert(data).on_conflict(
            conflict_target=(AgentLLMOutput.llm_run_id,),
            update=data,
        ).execute()
        row = AgentLLMOutput.get(AgentLLMOutput.llm_run_id == data["llm_run_id"])
        return int(row.id)

    def save_source_cursor(self, **kwargs: Any) -> int:
        self.initialize_schema()
        data = {
            "source": _enum_value(kwargs.get("source")),
            "scope_key": kwargs.get("scope_key"),
            "window_start": kwargs.get("window_start"),
            "window_end": kwargs.get("window_end"),
            "cursor_state_json": _json_dump(kwargs.get("cursor_state")),
            "last_success_at": kwargs.get("last_success_at"),
            "status": _enum_value(kwargs.get("status")),
            "updated_at": kwargs.get("updated_at") or datetime.now(),
        }
        AgentSourceCursor.insert(data).on_conflict(
            conflict_target=(
                AgentSourceCursor.source,
                AgentSourceCursor.scope_key,
                AgentSourceCursor.window_start,
                AgentSourceCursor.window_end,
            ),
            update=data,
        ).execute()
        row = AgentSourceCursor.get(
            (AgentSourceCursor.source == data["source"])
            & (AgentSourceCursor.scope_key == data["scope_key"])
            & (AgentSourceCursor.window_start == data["window_start"])
            & (AgentSourceCursor.window_end == data["window_end"])
        )
        return int(row.id)

    def get_table_names(self) -> set[str]:
        self.initialize_schema()
        return {
            row[0]
            for row in self.database.execute_sql(
                "select name from sqlite_master where type='table' and name like 'agent_%'"
            )
        }

    def count(self, table_name: str) -> int:
        self.initialize_schema()
        with self.database.connection_context():
            return int(self.database.execute_sql(f"select count(*) from {table_name}").fetchone()[0])

    def find_backfill_run_id(
        self,
        *,
        start: str,
        end: str,
        symbols: list[str],
        sources: tuple[str, ...],
    ) -> str | None:
        self.initialize_schema()
        rows = AgentBackfillRun.select().where(
            (AgentBackfillRun.status == "success")
            & (AgentBackfillRun.config_json.contains(start))
            & (AgentBackfillRun.config_json.contains(end))
        )
        for row in rows:
            try:
                config = json.loads(row.config_json or "{}")
            except json.JSONDecodeError:
                continue
            if (
                config.get("start") == start
                and config.get("end") == end
                and sorted(config.get("symbols", [])) == sorted(symbols)
                and sorted(config.get("sources", [])) == sorted(sources)
            ):
                return str(row.run_id)
        return None

    def get_stock_profile(self, vt_symbol: str) -> dict[str, Any] | None:
        self.initialize_schema()
        symbol, exchange = parse_vt_symbol(vt_symbol)
        normalized_vt_symbol = generate_vt_symbol(symbol, exchange)
        row = AgentStockProfile.select().where(
            AgentStockProfile.vt_symbol == normalized_vt_symbol
        ).first()
        if row is None:
            return None
        return model_to_dict(row)
