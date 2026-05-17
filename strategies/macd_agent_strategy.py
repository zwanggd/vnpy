"""
MACD + Agent combined strategy with multiple signal modes.

Modes (signal_mode parameter):
  macd_only     — pure MACD golden/death cross
  agent_only    — daily_agent_signal >= threshold (direction only, no technical)
  both_consensus — MACD golden cross AND agent positive → buy
  either_signal  — MACD golden cross OR agent positive → buy
  macd_confirmed — MACD golden cross, agent positive confirms (skip if agent disagrees)
"""
import json
from datetime import date
from vnpy_ctastrategy import (
    CtaTemplate, BarData, TradeData, OrderData, StopOrder, ArrayManager,
)


MODES = ["macd_only", "agent_only", "both_consensus", "either_signal", "macd_confirmed", "agent_sell_only", "agent_buy_only", "macd_agent_entry_filter", "either_safe"]


def load_agent_signals(agent_db_path: str = None):
    import sqlite3
    from pathlib import Path
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


class MacdAgentStrategy(CtaTemplate):

    author = "Sisyphus"
    fast: int = 12
    slow: int = 26
    signal_period: int = 9
    signal_mode: str = "macd_only"
    pos_ratio: float = 0.5
    agent_threshold: float = 0.05
    init_capital: float = 1_000_000
    parameters = [
        "fast", "slow", "signal_period", "signal_mode",
        "pos_ratio", "agent_threshold", "init_capital",
    ]
    variables = ["dif_val", "dea_val"]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        if self.signal_mode not in MODES:
            self.signal_mode = "macd_only"
        self.am = ArrayManager(size=max(self.slow * 3, 100))
        self.dif_val: float = 0
        self.dea_val: float = 0
        self._prev_dif: float = 0
        self._prev_dea: float = 0
        self._agent_signals: dict = {}
        self._trade_log: list = []
        self._last_entry_macd: bool = False
        self._last_entry_agent: bool = False

    def on_init(self) -> None:
        self._agent_signals = load_agent_signals()
        self.write_log(f"MACD-Agent init — mode={self.signal_mode}, "
                       f"agent_days={len(self._agent_signals)}")
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
        result = self.am.macd(self.fast, self.slow, self.signal_period)
        if result is None:
            return
        dif, dea, hist = result
        if dif is None or dea is None:
            return
        self.dif_val = float(dif)
        self.dea_val = float(dea)
        bar_date = bar.datetime.date()

        macd_golden = self._prev_dif <= self._prev_dea and dif > dea
        macd_death = self._prev_dif >= self._prev_dea and dif < dea
        agent_buy = self._agent_buy(bar_date)
        agent_sell = self._agent_sell(bar_date)

        should_buy = False
        should_sell = False

        if self.signal_mode == "macd_only":
            should_buy = macd_golden
            should_sell = macd_death
        elif self.signal_mode == "agent_only":
            should_buy = agent_buy
            should_sell = agent_sell
        elif self.signal_mode == "both_consensus":
            should_buy = macd_golden and agent_buy
            should_sell = macd_death or agent_sell
        elif self.signal_mode == "either_signal":
            should_buy = macd_golden or agent_buy
            should_sell = macd_death or agent_sell
        elif self.signal_mode == "macd_confirmed":
            if macd_golden:
                should_buy = agent_buy
            else:
                should_buy = False
            should_sell = macd_death or agent_sell
        elif self.signal_mode == "agent_sell_only":
            should_buy = macd_golden
            should_sell = macd_death or agent_sell
        elif self.signal_mode == "agent_buy_only":
            should_buy = macd_golden or agent_buy
            should_sell = macd_death
        elif self.signal_mode == "macd_agent_entry_filter":
            should_buy = macd_golden and not agent_sell
            should_sell = macd_death
        elif self.signal_mode == "either_safe":
            should_buy = (macd_golden or agent_buy) and not agent_sell
            should_sell = macd_death or agent_sell

        if should_buy and self.pos == 0:
            self._last_entry_macd = macd_golden
            self._last_entry_agent = agent_buy
            target_val = self.init_capital * self.pos_ratio
            shares = int(target_val / bar.close_price / 100) * 100
            lots = shares // 100
            if lots > 0:
                self.buy(bar.close_price, lots)
        elif should_sell and self.pos > 0:
            entry_src = "both" if self._last_entry_macd and self._last_entry_agent else ("MACD" if self._last_entry_macd else "Agent")
            exit_src = "both" if macd_death and agent_sell else ("MACD" if macd_death else "Agent")
            self._trade_log.append({"entry_date": str(bar.datetime.date()), "entry_src": entry_src, "exit_src": exit_src})
            self.sell(bar.close_price, abs(self.pos))

        self._prev_dif = dif
        self._prev_dea = dea

    def on_trade(self, trade: TradeData) -> None: return
    def on_order(self, order: OrderData) -> None: return
    def on_stop_order(self, stop_order: StopOrder) -> None: return
