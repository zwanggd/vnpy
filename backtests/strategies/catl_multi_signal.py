"""
CATL Multi-Signal Strategy: RSI + MACD + Volume Breakout.

Uses VNPY CtaSignal + TargetPosTemplate pattern.
Each signal contributes -1/0/1, combined target = sum of signals.
For A-shares (no short), target_pos clamped to [0, max_pos].
"""
from vnpy_ctastrategy import (
    CtaSignal,
    TargetPosTemplate,
    BarData,
    ArrayManager,
)


class RsiSignal(CtaSignal):
    """RSI: oversold → long, overbought → exit."""

    def __init__(self, rsi_window: int, rsi_oversold: int, rsi_overbought: int):
        super().__init__()
        self.rsi_window = rsi_window
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.am = ArrayManager(size=max(rsi_window * 2, 50))

    def on_bar(self, bar: BarData) -> None:
        self.am.update_bar(bar)
        if not self.am.inited:
            self.set_signal_pos(0)
            return
        rsi = self.am.rsi(self.rsi_window)
        if rsi is None or rsi > 80 or rsi < 5:
            self.set_signal_pos(0)
            return
        if rsi <= self.rsi_oversold:
            self.set_signal_pos(1)
        elif rsi >= self.rsi_overbought:
            self.set_signal_pos(-1)
        else:
            self.set_signal_pos(0)


class MacdSignal(CtaSignal):
    """MACD: DIFF crosses above DEA → long, crosses below → exit."""

    def __init__(self, fast: int, slow: int, signal_period: int):
        super().__init__()
        self.fast = fast
        self.slow = slow
        self.signal_period = signal_period
        self.am = ArrayManager(size=max(slow * 2, 100))
        self._prev_dif = None
        self._prev_dea = None

    def on_bar(self, bar: BarData) -> None:
        self.am.update_bar(bar)
        if not self.am.inited:
            self.set_signal_pos(0)
            return

        result = self.am.macd(self.fast, self.slow, self.signal_period)
        if result is None:
            self.set_signal_pos(0)
            return

        dif, dea, _hist = result
        if dif is None or dea is None:
            self.set_signal_pos(0)
            return

        if self._prev_dif is not None and self._prev_dea is not None:
            if dif > dea and self._prev_dif <= self._prev_dea:
                self.set_signal_pos(1)
            elif dif < dea and self._prev_dif >= self._prev_dea:
                self.set_signal_pos(-1)
            else:
                self.set_signal_pos(0)

        self._prev_dif = dif
        self._prev_dea = dea


class VolBreakoutSignal(CtaSignal):
    """Volume breakout: volume > N × SMA(volume) → momentum signal."""

    def __init__(self, vol_window: int, vol_mult: float):
        super().__init__()
        self.vol_window = vol_window
        self.vol_mult = vol_mult
        self.am = ArrayManager(size=max(vol_window * 2, 50))

    def on_bar(self, bar: BarData) -> None:
        self.am.update_bar(bar)
        if not self.am.inited:
            self.set_signal_pos(0)
            return

        vol_ma = self.am.sma(self.vol_window, array=True)
        if vol_ma is None or len(vol_ma) < 2:
            self.set_signal_pos(0)
            return

        current_vol = vol_ma[-1]
        avg_vol = vol_ma[:-1].mean() if len(vol_ma) > 1 else current_vol

        if current_vol > avg_vol * self.vol_mult:
            price_change = (bar.close_price - bar.open_price) / bar.open_price if bar.open_price > 0 else 0
            if price_change > 0.01:
                self.set_signal_pos(1)
            elif price_change < -0.01:
                self.set_signal_pos(-1)
            else:
                self.set_signal_pos(0)
        else:
            self.set_signal_pos(0)


class CatlMultiSignalStrategy(TargetPosTemplate):
    """RSI + MACD + Volume Breakout multi-signal strategy for CATL."""

    author = "Sisyphus"

    # Strategy parameters — tunable in backtest
    rsi_window: int = 14
    rsi_oversold: int = 35
    rsi_overbought: int = 70
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    vol_window: int = 20
    vol_mult: float = 2.0
    max_pos: int = 1

    parameters = [
        "rsi_window", "rsi_oversold", "rsi_overbought",
        "macd_fast", "macd_slow", "macd_signal",
        "vol_window", "vol_mult", "max_pos",
    ]

    def on_init(self) -> None:
        self.rsi_signal = RsiSignal(self.rsi_window, self.rsi_oversold, self.rsi_overbought)
        self.macd_signal = MacdSignal(self.macd_fast, self.macd_slow, self.macd_signal)
        self.vol_signal = VolBreakoutSignal(self.vol_window, self.vol_mult)
        self.set_target_pos(0)
        self.load_bar(50)

    def on_bar(self, bar: BarData) -> None:
        super().on_bar(bar)

        self.rsi_signal.on_bar(bar)
        self.macd_signal.on_bar(bar)
        self.vol_signal.on_bar(bar)

        target = (
            self.rsi_signal.get_signal_pos()
            + self.macd_signal.get_signal_pos()
            + self.vol_signal.get_signal_pos()
        )
        target = max(0, min(self.max_pos, target))
        self.set_target_pos(target)
