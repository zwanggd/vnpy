from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any

from vnpy.trader.constant import Exchange
from vnpy.trader.utility import extract_vt_symbol as vnpy_extract_vt_symbol
from vnpy.trader.utility import generate_vt_symbol as vnpy_generate_vt_symbol


class Source(Enum):
    CNINFO = "cninfo"
    CLS_TELEGRAPH = "cls_telegraph"
    EASTMONEY = "eastmoney"
    SINA_FINANCE = "sina_finance"


class SourceCategory(Enum):
    ANNOUNCEMENT = "announcement"
    FLASH = "flash"
    FINANCIAL_NEWS = "financial_news"
    INDUSTRY_POLICY = "industry_policy"
    MACRO_POLICY = "macro_policy"
    UNKNOWN = "unknown"


class RecallStrength(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RelationType(Enum):
    DIRECT_COMPANY = "direct_company"
    SUPPLY_CHAIN = "supply_chain"
    INDUSTRY = "industry"
    MACRO_POLICY = "macro_policy"
    MARKET_SENTIMENT = "market_sentiment"
    RISK_EVENT = "risk_event"
    UNKNOWN = "unknown"


class ImpactDirection(Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class TimeHorizon(Enum):
    INTRADAY = "intraday"
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"
    UNKNOWN = "unknown"


class Status(Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


RecordStatus = Status


def parse_vt_symbol(vt_symbol: str) -> tuple[str, str]:
    symbol, exchange = vnpy_extract_vt_symbol(vt_symbol)
    return symbol, exchange.value


def generate_vt_symbol(symbol: str, exchange: str | Exchange) -> str:
    exchange_value = Exchange(exchange) if isinstance(exchange, str) else exchange
    return vnpy_generate_vt_symbol(symbol, exchange_value)


def _coerce_enum(value: Enum | str, enum_type: type[Enum], field_name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be one of {[item.value for item in enum_type]}") from exc


def _validate_unit_interval(value: float, field_name: str) -> float:
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{field_name} must be between 0.0 and 1.0")
    return number


@dataclass
class NewsQuery:
    vt_symbol: str
    start: date | datetime
    end: date | datetime
    sources: tuple[Source, ...] = (Source.CNINFO, Source.CLS_TELEGRAPH, Source.EASTMONEY)
    recall_strength: RecallStrength = RecallStrength.MEDIUM
    keywords: tuple[str, ...] = ()
    symbol: str = ""
    exchange: str = ""

    def __post_init__(self) -> None:
        self.sources = tuple(_coerce_enum(source, Source, "source") for source in self.sources)
        self.recall_strength = _coerce_enum(
            self.recall_strength,
            RecallStrength,
            "recall_strength",
        )
        parsed_symbol, parsed_exchange = parse_vt_symbol(self.vt_symbol)
        if self.symbol and self.symbol != parsed_symbol:
            raise ValueError("symbol must match vt_symbol")
        if self.exchange and self.exchange != parsed_exchange:
            raise ValueError("exchange must match vt_symbol")
        self.symbol = parsed_symbol
        self.exchange = parsed_exchange
        self.vt_symbol = generate_vt_symbol(self.symbol, self.exchange)


@dataclass
class RawNewsItem:
    source: Source
    source_category: SourceCategory
    title: str
    content_hash: str
    source_item_id: str = ""
    url: str = ""
    content: str = ""
    summary: str = ""
    published_at: datetime | None = None
    discovered_at: datetime | None = None
    fetched_at: datetime | None = None
    available_at: datetime | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)
    body_status: str = ""
    language: str = "zh"

    def __post_init__(self) -> None:
        self.source = _coerce_enum(self.source, Source, "source")
        self.source_category = _coerce_enum(
            self.source_category,
            SourceCategory,
            "source_category",
        )


@dataclass
class StockProfile:
    vt_symbol: str
    name: str
    aliases: tuple[str, ...] = ()
    industry: tuple[str, ...] = ()
    products: tuple[str, ...] = ()
    upstream: tuple[str, ...] = ()
    downstream: tuple[str, ...] = ()
    macro_factors: tuple[str, ...] = ()
    risk_keywords: tuple[str, ...] = ()
    company_archetype: str = "generic"
    company_archetype_version: str = "company_archetype_v0.1"
    profile_version: str = "agent_news_v0.1"
    updated_at: datetime | None = None
    symbol: str = ""
    exchange: str = ""

    def __post_init__(self) -> None:
        parsed_symbol, parsed_exchange = parse_vt_symbol(self.vt_symbol)
        if self.symbol and self.symbol != parsed_symbol:
            raise ValueError("symbol must match vt_symbol")
        if self.exchange and self.exchange != parsed_exchange:
            raise ValueError("exchange must match vt_symbol")
        self.symbol = parsed_symbol
        self.exchange = parsed_exchange
        self.vt_symbol = generate_vt_symbol(self.symbol, self.exchange)


@dataclass
class MappedNews:
    raw_news_id: int
    vt_symbol: str
    relation_hint: RelationType = RelationType.UNKNOWN
    mapping_method: str = ""
    mapping_confidence: float = 0.0
    keywords_matched: tuple[str, ...] = ()
    symbol: str = ""
    exchange: str = ""

    def __post_init__(self) -> None:
        self.relation_hint = _coerce_enum(self.relation_hint, RelationType, "relation_type")
        self.mapping_confidence = _validate_unit_interval(
            self.mapping_confidence,
            "mapping_confidence",
        )
        parsed_symbol, parsed_exchange = parse_vt_symbol(self.vt_symbol)
        if self.symbol and self.symbol != parsed_symbol:
            raise ValueError("symbol must match vt_symbol")
        if self.exchange and self.exchange != parsed_exchange:
            raise ValueError("exchange must match vt_symbol")
        self.symbol = parsed_symbol
        self.exchange = parsed_exchange
        self.vt_symbol = generate_vt_symbol(self.symbol, self.exchange)


@dataclass
class LLMRunRecord:
    run_id: str
    raw_news_id: int
    provider: str
    model: str
    prompt_version: str
    schema_version: str
    input_hash: str
    status: Status = Status.PENDING
    parameters: dict[str, Any] = field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str = ""

    def __post_init__(self) -> None:
        self.status = _coerce_enum(self.status, Status, "status")


@dataclass
class LLMOutputRecord:
    llm_run_id: int
    raw_response: str
    validation_status: Status
    parsed_json: dict[str, Any] = field(default_factory=dict)
    validation_errors: tuple[str, ...] = ()
    output_hash: str = ""
    token_usage: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.validation_status = _coerce_enum(
            self.validation_status,
            Status,
            "status",
        )


@dataclass
class AgentSignal:
    raw_news_id: int
    llm_run_id: int
    vt_symbol: str
    event: str
    relation_type: RelationType
    impact_direction: ImpactDirection
    impact_strength: float
    time_horizon: TimeHorizon
    confidence: float
    reason: str
    evidence: list[str]
    published_at: datetime
    available_at: datetime
    trading_date: str
    source: Source
    source_item_id: str
    prompt_version: str
    schema_version: str
    symbol: str = ""
    exchange: str = ""
    signal_version: str = ""
    created_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self) -> None:
        self.relation_type = _coerce_enum(self.relation_type, RelationType, "relation_type")
        self.impact_direction = _coerce_enum(
            self.impact_direction,
            ImpactDirection,
            "impact_direction",
        )
        self.time_horizon = _coerce_enum(self.time_horizon, TimeHorizon, "time_horizon")
        self.source = _coerce_enum(self.source, Source, "source")
        self.impact_strength = _validate_unit_interval(self.impact_strength, "impact_strength")
        self.confidence = _validate_unit_interval(self.confidence, "confidence")
        parsed_symbol, parsed_exchange = parse_vt_symbol(self.vt_symbol)
        if self.symbol and self.symbol != parsed_symbol:
            raise ValueError("symbol must match vt_symbol")
        if self.exchange and self.exchange != parsed_exchange:
            raise ValueError("exchange must match vt_symbol")
        self.symbol = parsed_symbol
        self.exchange = parsed_exchange
        self.vt_symbol = generate_vt_symbol(self.symbol, self.exchange)


@dataclass
class BackfillConfig:
    start: date
    end: date
    vt_symbols: tuple[str, ...]
    sources: tuple[Source, ...] = (Source.CNINFO, Source.CLS_TELEGRAPH, Source.EASTMONEY)
    recall_strength: RecallStrength = RecallStrength.MEDIUM
    dry_run: bool = False
    skip_llm: bool = False
    max_llm_items: int = 0
    resume: bool = False
    market_db_path: str = "~/.vntrader/database.db"
    agent_db_path: str = "~/.vntrader/agent_news.db"
    report_path: str = ""

    def __post_init__(self) -> None:
        self.sources = tuple(_coerce_enum(source, Source, "source") for source in self.sources)
        self.recall_strength = _coerce_enum(
            self.recall_strength,
            RecallStrength,
            "recall_strength",
        )
        self.vt_symbols = tuple(
            generate_vt_symbol(*parse_vt_symbol(vt_symbol)) for vt_symbol in self.vt_symbols
        )
