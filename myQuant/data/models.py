"""Peewee ORM models for Agent News pipeline."""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any

from peewee import (
    DateTimeField,
    FloatField,
    IntegerField,
    Model,
    SQL,
    TextField,
)


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
