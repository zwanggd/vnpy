"""
MACD strategy with configurable position sizing and pyramiding.
  pos_ratio=0.3  → entry uses 30% of capital
  pos_ratio=0.5  → entry uses 50% of capital
  pyramid_mode=True → each golden cross adds 1 unit; death cross exits all
"""
from vnpy_ctastrategy import (
    CtaTemplate, BarData, TradeData, OrderData, StopOrder, ArrayManager,
)


class MacdStrategy(CtaTemplate):

    author = "Sisyphus"
    fast: int = 12
    slow: int = 26
    signal_period: int = 9
    pos_ratio: float = 0.5
    pyramid_mode: bool = False
    unit_shares: int = 100
    init_capital: float = 1_000_000
    parameters = ["fast", "slow", "signal_period", "pos_ratio", "pyramid_mode", "unit_shares", "init_capital"]
    variables = ["dif_val", "dea_val"]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        self.am = ArrayManager(size=max(self.slow * 3, 100))
        self.dif_val: float = 0
        self.dea_val: float = 0
        self._prev_dif: float = 0
        self._prev_dea: float = 0

    def on_init(self) -> None:
        self.load_bar(50)

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

        golden = self._prev_dif <= self._prev_dea and dif > dea
        death = self._prev_dif >= self._prev_dea and dif < dea

        if self.pyramid_mode:
            if golden:
                self.buy(bar.close_price, self.unit_shares)
            elif death and self.pos > 0:
                self.sell(bar.close_price, abs(self.pos))
        else:
            if self.pos == 0 and golden:
                target_val = self.init_capital * self.pos_ratio
                shares = int(target_val / bar.close_price / 100) * 100
                lots = shares // 100
                if lots > 0:
                    self.buy(bar.close_price, lots)
            elif self.pos > 0 and death:
                self.sell(bar.close_price, abs(self.pos))

        self._prev_dif = dif
        self._prev_dea = dea

    def on_trade(self, trade: TradeData) -> None: return
    def on_order(self, order: OrderData) -> None: return
    def on_stop_order(self, stop_order: StopOrder) -> None: return
