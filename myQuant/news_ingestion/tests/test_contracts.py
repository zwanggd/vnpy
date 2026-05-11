from datetime import datetime

import pytest

from myQuant.news_ingestion import (
    AgentSignal,
    ImpactDirection,
    RelationType,
    Source,
    TimeHorizon,
    parse_vt_symbol,
    generate_vt_symbol,
)


def test_agent_signal_contract_accepts_valid_signal() -> None:
    signal = AgentSignal(
        raw_news_id=1,
        llm_run_id=1,
        vt_symbol="300750.SZSE",
        event="宁德时代发布新电池技术",
        relation_type=RelationType.DIRECT_COMPANY,
        impact_direction=ImpactDirection.POSITIVE,
        impact_strength=0.72,
        time_horizon=TimeHorizon.SHORT,
        confidence=0.68,
        reason="新技术有望提升产品竞争力",
        evidence=["公告提及新电池技术"],
        published_at=datetime(2026, 5, 8, 10, 0),
        available_at=datetime(2026, 5, 8, 10, 5),
        trading_date="2026-05-08",
        source=Source.CNINFO,
        source_item_id="cninfo-1",
        prompt_version="news_impact_v1",
        schema_version="agent_signal_v1",
    )

    assert signal.symbol == "300750"
    assert signal.exchange == "SZSE"
    assert signal.vt_symbol == "300750.SZSE"
    assert signal.impact_strength == 0.72
    assert signal.confidence == 0.68
    assert signal.impact_direction is ImpactDirection.POSITIVE


def test_agent_signal_contract_rejects_confidence_outside_zero_one() -> None:
    with pytest.raises(ValueError, match="confidence"):
        AgentSignal(
            raw_news_id=1,
            llm_run_id=1,
            vt_symbol="300750.SZSE",
            event="宁德时代发布新电池技术",
            relation_type=RelationType.DIRECT_COMPANY,
            impact_direction=ImpactDirection.POSITIVE,
            impact_strength=0.72,
            time_horizon=TimeHorizon.SHORT,
            confidence=1.5,
            reason="新技术有望提升产品竞争力",
            evidence=["公告提及新电池技术"],
            published_at=datetime(2026, 5, 8, 10, 0),
            available_at=datetime(2026, 5, 8, 10, 5),
            trading_date="2026-05-08",
            source=Source.CNINFO,
            source_item_id="cninfo-1",
            prompt_version="news_impact_v1",
            schema_version="agent_signal_v1",
        )


def test_agent_signal_contract_rejects_invalid_enum_value() -> None:
    with pytest.raises(ValueError, match="impact_direction"):
        AgentSignal(
            raw_news_id=1,
            llm_run_id=1,
            vt_symbol="300750.SZSE",
            event="宁德时代发布新电池技术",
            relation_type=RelationType.DIRECT_COMPANY,
            impact_direction="bullish",
            impact_strength=0.72,
            time_horizon=TimeHorizon.SHORT,
            confidence=0.68,
            reason="新技术有望提升产品竞争力",
            evidence=["公告提及新电池技术"],
            published_at=datetime(2026, 5, 8, 10, 0),
            available_at=datetime(2026, 5, 8, 10, 5),
            trading_date="2026-05-08",
            source=Source.CNINFO,
            source_item_id="cninfo-1",
            prompt_version="news_impact_v1",
            schema_version="agent_signal_v1",
        )


def test_vt_symbol_parse_and_regenerate_round_trip() -> None:
    symbol, exchange = parse_vt_symbol("300750.SZSE")

    assert symbol == "300750"
    assert exchange == "SZSE"
    assert generate_vt_symbol(symbol, exchange) == "300750.SZSE"
