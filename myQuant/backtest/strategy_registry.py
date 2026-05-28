""""""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from vnpy_ctastrategy import CtaTemplate
from strategies.macd_agent_strategy import MacdAgentStrategy
from strategies.tech_agent_strategy import TechAgentStrategy
from strategies.buy_and_hold_strategy import BuyAndHoldStrategy


@dataclass
class StrategySpec:
    name: str
    family: str
    description: str
    strategy_class: type[CtaTemplate]
    parameters: dict[str, Any] = field(default_factory=dict)
    required_indicators: list[str] = field(default_factory=list)
    uses_agent_signal: bool = False
    uses_technical_signal: bool = False
    enabled: bool = True
    disabled_reason: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("StrategySpec.name is required")
        if not self.description:
            raise ValueError(f"StrategySpec.description is required for {self.name}")


def _macd_params(**overrides: Any) -> dict[str, Any]:
    base = {
        "fast": 12, "slow": 26, "signal_period": 9,
        "pos_ratio": 0.5, "agent_threshold": 0.05, "init_capital": 1_000_000,
        "agent_db_path": "",
    }
    base.update(overrides)
    return base


REGISTRY: dict[str, StrategySpec] = {
    # ── Technical: MACD modes ────────────────────────────────────────────
    "macd_only": StrategySpec(
        name="macd_only", family="technical",
        description="Pure MACD golden/death cross.",
        strategy_class=MacdAgentStrategy,
        parameters=_macd_params(signal_mode="macd_only"),
        uses_technical_signal=True,
    ),
    # ── Agent-only modes ─────────────────────────────────────────────────
    "agent_only": StrategySpec(
        name="agent_only", family="agent_only",
        description="Pure agent signal (direction + threshold).",
        strategy_class=MacdAgentStrategy,
        parameters=_macd_params(signal_mode="agent_only"),
        uses_agent_signal=True,
    ),
    "agent_buy_only": StrategySpec(
        name="agent_buy_only", family="agent_only",
        description="MACD or agent buy; MACD sell only.",
        strategy_class=MacdAgentStrategy,
        parameters=_macd_params(signal_mode="agent_buy_only"),
        uses_agent_signal=True, uses_technical_signal=True,
    ),
    "agent_sell_only": StrategySpec(
        name="agent_sell_only", family="hybrid_exit",
        description="MACD buy; MACD or agent sell. Agent for exit only.",
        strategy_class=MacdAgentStrategy,
        parameters=_macd_params(signal_mode="agent_sell_only"),
        uses_agent_signal=True, uses_technical_signal=True,
    ),
    # ── Hybrid: consensus ────────────────────────────────────────────────
    "both_consensus": StrategySpec(
        name="both_consensus", family="hybrid_consensus",
        description="MACD golden AND agent buy; sell on either.",
        strategy_class=MacdAgentStrategy,
        parameters=_macd_params(signal_mode="both_consensus"),
        uses_agent_signal=True, uses_technical_signal=True,
    ),
    "macd_confirmed": StrategySpec(
        name="macd_confirmed", family="hybrid_consensus",
        description="MACD golden, agent confirms; skip if agent disagrees.",
        strategy_class=MacdAgentStrategy,
        parameters=_macd_params(signal_mode="macd_confirmed"),
        uses_agent_signal=True, uses_technical_signal=True,
    ),
    # ── Hybrid: entry filter ─────────────────────────────────────────────
    "macd_agent_entry_filter": StrategySpec(
        name="macd_agent_entry_filter", family="hybrid_entry",
        description="MACD golden AND NOT agent sell; MACD death sell.",
        strategy_class=MacdAgentStrategy,
        parameters=_macd_params(signal_mode="macd_agent_entry_filter"),
        uses_agent_signal=True, uses_technical_signal=True,
    ),
    "either_signal": StrategySpec(
        name="either_signal", family="hybrid_entry",
        description="MACD golden OR agent buy; sell on either.",
        strategy_class=MacdAgentStrategy,
        parameters=_macd_params(signal_mode="either_signal"),
        uses_agent_signal=True, uses_technical_signal=True,
    ),
    "either_safe": StrategySpec(
        name="either_safe", family="hybrid_risk",
        description="(MACD or agent buy) AND NOT agent sell; sell on either.",
        strategy_class=MacdAgentStrategy,
        parameters=_macd_params(signal_mode="either_safe"),
        uses_agent_signal=True, uses_technical_signal=True,
    ),
}

# ── Disabled strategies ─────────────────────────────────────────────────
DISABLED: dict[str, StrategySpec] = {
    "rsi_only": StrategySpec(
        name="rsi_only", family="technical",
        description="RSI oversold/overbought mean reversion.",
        strategy_class=TechAgentStrategy,
        parameters={**_macd_params(signal_mode="tech_only"), "indicator_name": "rsi"},
        uses_technical_signal=True,
        enabled=False,
        disabled_reason="Indicator requires TechAgentStrategy, not MacdAgentStrategy — needs matrix runner support",
    ),
}


def get_all_specs() -> list[StrategySpec]:
    return list(REGISTRY.values())


def get_enabled_specs() -> list[StrategySpec]:
    return [s for s in REGISTRY.values() if s.enabled]


def get_spec(name: str) -> StrategySpec | None:
    return REGISTRY.get(name)


def get_disabled_specs() -> list[StrategySpec]:
    return [s for s in DISABLED.values() if not s.enabled]
