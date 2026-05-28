""""""
from vnpy_ctastrategy import CtaTemplate, BarData, TradeData, OrderData, StopOrder


class BuyAndHoldStrategy(CtaTemplate):
    """Buy on first valid bar, hold until last bar."""

    author = "Sisyphus"
    pos_ratio: float = 1.0
    init_capital: float = 1_000_000
    parameters = ["pos_ratio", "init_capital"]
    variables: list[str] = []

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        self._entered = False

    def on_init(self) -> None:
        self._entered = False
        self.write_log("BuyAndHold — init")

    def on_start(self) -> None:
        pass

    def on_bar(self, bar: BarData) -> None:
        if not self._entered:
            self._entered = True
            target = self.init_capital * self.pos_ratio
            lots = int(target / bar.close_price / 100)
            lots = max(lots, 1)
            self.buy(bar.close_price, lots)

    def on_trade(self, trade: TradeData) -> None:
        pass

    def on_order(self, order: OrderData) -> None:
        pass

    def on_stop_order(self, stop_order: StopOrder) -> None:
        pass
