""""""
from __future__ import annotations

from datetime import date

from vnpy_ctastrategy import CtaTemplate, BarData, TradeData, OrderData, StopOrder, ArrayManager

from myQuant.backtest.technical_core_registry import TECHNICAL_CORES
from myQuant.backtest.agent_rules import evaluate_entry, evaluate_exit
from myQuant.backtest.agent_signal_provider import AgentSignalProvider, NewsAgentSignalProvider


class TechAgentMatrixStrategy(CtaTemplate):
    """Universal strategy: TechnicalCore × EntryRule × ExitRule."""

    author = "Sisyphus"

    technical_core: str = "macd"
    entry_rule: str = "tech_entry"
    exit_rule: str = "tech_exit"
    pos_ratio: float = 0.5
    init_capital: float = 1_000_000
    agent_db_path: str = ""
    agent_signal_version: str = ""
    signal_shift_days: int = 0

    parameters = [
        "technical_core", "entry_rule", "exit_rule",
        "pos_ratio", "init_capital", "agent_db_path",
        "agent_signal_version", "signal_shift_days",
    ]
    variables: list[str] = []

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        self.am = ArrayManager(size=200)
        self._core_spec = TECHNICAL_CORES.get(self.technical_core)
        self._agent: AgentSignalProvider | None = None
        self._entered = False
        self._last_entry_tech = False
        self._last_entry_agent = False

    def on_init(self) -> None:
        if self.agent_db_path and self.entry_rule != "tech_entry":
            try:
                self._agent = NewsAgentSignalProvider(
                    db_path=self.agent_db_path,
                    signal_version=self.agent_signal_version or None,
                )
            except Exception:
                self._agent = None
        self.write_log(
            f"TechAgentMatrix init — core={self.technical_core} entry={self.entry_rule} exit={self.exit_rule}"
        )

    def on_bar(self, bar: BarData) -> None:
        self.am.update_bar(bar)
        if not self.am.inited:
            return

        if self._core_spec is None:
            return

        ts = self._core_spec.compute(bar, self.am)
        T_plus = ts.tech_buy
        T_minus = ts.tech_sell

        bar_date = bar.datetime.date()
        agent_sig = self._agent.get_signal(bar_date) if self._agent else None
        A_plus = agent_sig.is_positive if agent_sig else False
        A_minus = agent_sig.is_negative if agent_sig else False

        should_buy = evaluate_entry(self.entry_rule, T_plus, A_plus, A_minus)
        should_sell = evaluate_exit(self.exit_rule, T_minus, A_plus, A_minus)

        if should_buy and self.pos == 0:
            self._last_entry_tech = T_plus
            self._last_entry_agent = A_plus
            target_val = self.init_capital * self.pos_ratio
            shares = int(target_val / bar.close_price / 100) * 100
            lots = shares // 100
            if lots > 0:
                self.buy(bar.close_price, lots)
        elif should_sell and self.pos > 0:
            self.sell(bar.close_price, abs(self.pos))

    def on_trade(self, trade: TradeData) -> None:
        pass

    def on_order(self, order: OrderData) -> None:
        pass

    def on_stop_order(self, stop_order: StopOrder) -> None:
        pass
