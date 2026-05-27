"""
Generic Technical + Agent combined strategy.

Accepts any TechnicalIndicator (via indicator parameter) and combines
with Agent signals using the standard signal_mode logic.

Modes:
  tech_only  — pure technical indicator signals
  agent_only — pure agent signals (daily_direction)
  either_safe — (tech_buy OR agent_buy) AND NOT agent_sell / tech_sell OR agent_sell
  veto_only  — tech_buy AND NOT agent_sell / tech_sell OR agent_sell (NEW)
"""
from __future__ import annotations
import sqlite3
from datetime import date
from pathlib import Path

from vnpy_ctastrategy import (
    CtaTemplate, BarData, TradeData, OrderData, StopOrder, ArrayManager,
)

from .technical_signal import TechnicalSignal, BaseIndicator
from .technical_indicators import (
    MacdIndicator, MaAdxIndicator, DonchianIndicator,
    BollingerIndicator, RsiIndicator,
    MacdAdxIndicator, DonchianAtrIndicator, BollingerMaIndicator,
)

MODES = [
    "tech_only", "agent_only",
    "both_consensus", "either_signal", "tech_confirmed",
    "agent_sell_only", "agent_buy_only", "tech_agent_entry_filter",
    "either_safe", "veto_only",
    "tech_confirm_veto", "tech_veto_only", "agent_overlay", "legacy_either_safe",
]


def load_agent_signals(agent_db_path: str = None) -> dict:
    if agent_db_path is None:
        agent_db_path = str(Path.home() / ".vntrader" / "agent_news.db")
    db = sqlite3.connect(agent_db_path)
    rows = db.execute(
        "SELECT entry_date, daily_agent_signal, daily_direction FROM daily_agent_signal"
    ).fetchall()
    db.close()
    result = {}
    for entry_date_str, sig, direction in rows:
        if sig is None:
            continue
        d = date.fromisoformat(entry_date_str[:10])
        result[d] = {"signal": sig, "direction": direction}
    return result


class TechAgentStrategy(CtaTemplate):
    author = "Sisyphus"
    fast: int = 12
    slow: int = 26
    signal_period: int = 9
    signal_mode: str = "tech_only"
    pos_ratio: float = 0.5
    agent_threshold: float = 0.05
    init_capital: float = 1_000_000
    agent_db_path: str = ""
    indicator_name: str = "macd"
    parameters = [
        "fast", "slow", "signal_period", "signal_mode",
        "pos_ratio", "agent_threshold", "init_capital", "agent_db_path",
        "indicator_name",
    ]
    variables = ["dif_val", "dea_val"]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        if self.signal_mode not in MODES:
            self.signal_mode = "tech_only"
        indicator_map = {
            "macd": MacdIndicator(fast=self.fast, slow=self.slow, signal_period=self.signal_period),
            "ma_adx": MaAdxIndicator(),
            "donchian": DonchianIndicator(),
            "bollinger": BollingerIndicator(),
            "rsi": RsiIndicator(),
            "macd_adx": MacdAdxIndicator(fast=self.fast, slow=self.slow, signal_period=self.signal_period),
            "donchian_atr": DonchianAtrIndicator(),
            "bollinger_ma": BollingerMaIndicator(),
        }
        self._indicator = indicator_map.get(self.indicator_name, MacdIndicator(
            fast=self.fast, slow=self.slow, signal_period=self.signal_period
        ))
        self.am = ArrayManager(size=max(self.slow * 3, 100))
        self.dif_val: float = 0
        self.dea_val: float = 0
        self._agent_signals: dict = {}
        self._last_entry_tech: bool = False
        self._last_entry_agent: bool = False

    def on_init(self) -> None:
        self._agent_signals = load_agent_signals(self.agent_db_path if self.agent_db_path else None)
        self._indicator.reset()
        self.write_log(
            f"TechAgent init — indicator={self._indicator.name}, mode={self.signal_mode}, "
            f"agent_days={len(self._agent_signals)}"
        )
        self.load_bar(50)

    def _agent_buy(self, bar_date: date) -> bool:
        sig = self._agent_signals.get(bar_date)
        if sig is None:
            return False
        if self.signal_mode == "agent_only":
            return sig["signal"] >= self.agent_threshold
        return sig["direction"] == "positive"

    def _agent_sell(self, bar_date: date) -> bool:
        sig = self._agent_signals.get(bar_date)
        if sig is None:
            return False
        if self.signal_mode == "agent_only":
            return sig["signal"] <= -self.agent_threshold
        return sig["direction"] == "negative"

    def on_bar(self, bar: BarData) -> None:
        self.am.update_bar(bar)
        if not self.am.inited:
            return

        ts = self._indicator.update(bar, self.am)
        bar_date = bar.datetime.date()

        tech_buy = ts.buy_signal
        tech_sell = ts.sell_signal
        agent_buy = self._agent_buy(bar_date)
        agent_sell = self._agent_sell(bar_date)

        # Populate dif_val/dea_val for backward compat (from debug_info)
        if "dif" in ts.debug_info:
            self.dif_val = ts.debug_info["dif"]
        if "dea" in ts.debug_info:
            self.dea_val = ts.debug_info["dea"]

        should_buy = False
        should_sell = False
        mode = self.signal_mode

        if mode == "tech_only":
            should_buy = tech_buy
            should_sell = tech_sell
        elif mode == "agent_only":
            should_buy = agent_buy
            should_sell = agent_sell
        elif mode == "both_consensus":
            should_buy = tech_buy and agent_buy
            should_sell = tech_sell or agent_sell
        elif mode == "either_signal":
            should_buy = tech_buy or agent_buy
            should_sell = tech_sell or agent_sell
        elif mode == "tech_confirmed":
            should_buy = tech_buy and agent_buy
            should_sell = tech_sell or agent_sell
        elif mode == "agent_sell_only":
            should_buy = tech_buy
            should_sell = tech_sell or agent_sell
        elif mode == "agent_buy_only":
            should_buy = tech_buy or agent_buy
            should_sell = tech_sell
        elif mode == "tech_agent_entry_filter":
            should_buy = tech_buy and not agent_sell
            should_sell = tech_sell
        elif mode == "either_safe":
            should_buy = (tech_buy or agent_buy) and not agent_sell
            should_sell = tech_sell or agent_sell
        elif mode == "veto_only":
            should_buy = tech_buy and not agent_sell
            should_sell = tech_sell or agent_sell
        elif mode == "tech_confirm_veto":
            should_buy = tech_buy and not agent_sell
            should_sell = tech_sell or agent_sell
        elif mode == "tech_veto_only":
            should_buy = tech_buy and not agent_sell
            should_sell = tech_sell
        elif mode == "agent_overlay":
            should_buy = agent_buy
            should_sell = agent_sell
        elif mode == "legacy_either_safe":
            should_buy = (tech_buy or agent_buy) and not agent_sell
            should_sell = tech_sell or agent_sell

        if should_buy and self.pos == 0:
            self._last_entry_tech = tech_buy
            self._last_entry_agent = agent_buy
            target_val = self.init_capital * self.pos_ratio
            shares = int(target_val / bar.close_price / 100) * 100
            lots = shares // 100
            if lots > 0:
                self.buy(bar.close_price, lots)
        elif should_sell and self.pos > 0:
            self.sell(bar.close_price, abs(self.pos))

    def on_trade(self, trade: TradeData) -> None:
        return
    def on_order(self, order: OrderData) -> None:
        return
    def on_stop_order(self, stop_order: StopOrder) -> None:
        return
