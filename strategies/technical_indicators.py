"""Concrete technical indicator implementations."""
from __future__ import annotations
from .technical_signal import TechnicalSignal, BaseIndicator


class MacdIndicator(BaseIndicator):
    name = "macd"
    params = {"fast": 12, "slow": 26, "signal_period": 9}

    def __init__(self, fast=12, slow=26, signal_period=9):
        self.params = {"fast": fast, "slow": slow, "signal_period": signal_period}
        self._prev_dif: float = 0.0
        self._prev_dea: float = 0.0

    def reset(self):
        self._prev_dif = 0.0
        self._prev_dea = 0.0

    def update(self, bar, am) -> TechnicalSignal:
        result = am.macd(self.params["fast"], self.params["slow"], self.params["signal_period"])
        if result is None:
            return TechnicalSignal(indicator_name=self.name)
        dif, dea, hist = result
        if dif is None or dea is None:
            return TechnicalSignal(indicator_name=self.name)
        dif, dea = float(dif), float(dea)
        golden = self._prev_dif <= self._prev_dea and dif > dea
        death = self._prev_dif >= self._prev_dea and dif < dea
        self._prev_dif = dif
        self._prev_dea = dea
        return TechnicalSignal(
            indicator_name=self.name,
            buy_signal=golden,
            sell_signal=death,
            debug_info={"dif": dif, "dea": dea, "hist": float(hist) if hist is not None else 0},
        )


class MaAdxIndicator(BaseIndicator):
    name = "ma_adx"
    params = {"ma_period": 20, "adx_period": 14, "adx_threshold": 25}

    def __init__(self, ma_period=20, adx_period=14, adx_threshold=25):
        self.params = {"ma_period": ma_period, "adx_period": adx_period, "adx_threshold": adx_threshold}
        self._prev_close: float = 0.0
        self._prev_ma: float = 0.0

    def reset(self):
        self._prev_close = 0.0
        self._prev_ma = 0.0

    def update(self, bar, am) -> TechnicalSignal:
        ma = am.sma(self.params["ma_period"])
        adx = am.adx(self.params["adx_period"])
        if ma is None or adx is None:
            return TechnicalSignal(indicator_name=self.name)
        ma_val, adx_val = float(ma), float(adx)
        close_val = float(bar.close_price)
        buy_sig = close_val > ma_val and adx_val > self.params["adx_threshold"]
        sell_sig = close_val < ma_val
        return TechnicalSignal(
            indicator_name=self.name,
            buy_signal=buy_sig,
            sell_signal=sell_sig,
            debug_info={"ma": ma_val, "adx": adx_val, "close": close_val},
        )


class DonchianIndicator(BaseIndicator):
    name = "donchian"
    params = {"period": 20}

    def __init__(self, period=20):
        self.params = {"period": period}
        self._prev_upper: float = 0.0
        self._prev_lower: float = 0.0

    def reset(self):
        self._prev_upper = 0.0
        self._prev_lower = 0.0

    def update(self, bar, am) -> TechnicalSignal:
        result = am.donchian(self.params["period"])
        if result is None:
            return TechnicalSignal(indicator_name=self.name)
        upper, lower = result
        if upper is None or lower is None:
            return TechnicalSignal(indicator_name=self.name)
        upper_val, lower_val = float(upper), float(lower)
        close = float(bar.close_price)
        buy_sig = close > upper_val
        sell_sig = close < lower_val
        self._prev_upper = upper_val
        self._prev_lower = lower_val
        return TechnicalSignal(
            indicator_name=self.name,
            buy_signal=buy_sig,
            sell_signal=sell_sig,
            debug_info={"upper": upper_val, "lower": lower_val, "close": close},
        )


class BollingerIndicator(BaseIndicator):
    name = "bollinger"
    params = {"period": 20, "dev": 2.0}

    def __init__(self, period=20, dev=2.0):
        self.params = {"period": period, "dev": dev}
        self._prev_upper: float = 0.0
        self._prev_lower: float = 0.0

    def reset(self):
        self._prev_upper = 0.0
        self._prev_lower = 0.0

    def update(self, bar, am) -> TechnicalSignal:
        result = am.boll(self.params["period"], self.params["dev"])
        if result is None:
            return TechnicalSignal(indicator_name=self.name)
        upper, lower = result
        if upper is None or lower is None:
            return TechnicalSignal(indicator_name=self.name)
        upper_val, lower_val = float(upper), float(lower)
        close = float(bar.close_price)
        buy_sig = close < lower_val
        sell_sig = close > upper_val
        return TechnicalSignal(
            indicator_name=self.name,
            buy_signal=buy_sig,
            sell_signal=sell_sig,
            debug_info={"upper": upper_val, "lower": lower_val, "close": close},
        )


class MacdAdxIndicator(BaseIndicator):
    name = "macd_adx"
    params = {"fast": 12, "slow": 26, "signal_period": 9, "adx_period": 14, "adx_min": 20}

    def __init__(self, fast=12, slow=26, signal_period=9, adx_period=14, adx_min=20):
        self.params = {"fast": fast, "slow": slow, "signal_period": signal_period, "adx_period": adx_period, "adx_min": adx_min}
        self._prev_dif: float = 0.0
        self._prev_dea: float = 0.0

    def reset(self):
        self._prev_dif = 0.0
        self._prev_dea = 0.0

    def update(self, bar, am) -> TechnicalSignal:
        macd_r = am.macd(self.params["fast"], self.params["slow"], self.params["signal_period"])
        adx_v = am.adx(self.params["adx_period"])
        if macd_r is None or adx_v is None:
            return TechnicalSignal(indicator_name=self.name)
        dif, dea, hist = macd_r
        if dif is None or dea is None:
            return TechnicalSignal(indicator_name=self.name)
        dif, dea = float(dif), float(dea)
        adx = float(adx_v)
        golden = self._prev_dif <= self._prev_dea and dif > dea and adx > self.params["adx_min"]
        death = self._prev_dif >= self._prev_dea and dif < dea
        self._prev_dif = dif
        self._prev_dea = dea
        return TechnicalSignal(indicator_name=self.name, buy_signal=golden, sell_signal=death,
                               debug_info={"dif": dif, "dea": dea, "adx": adx})


class DonchianAtrIndicator(BaseIndicator):
    name = "donchian_atr"
    params = {"dc_period": 20, "atr_period": 14, "atr_filter": 0.5}

    def __init__(self, dc_period=20, atr_period=14, atr_filter=0.5):
        self.params = {"dc_period": dc_period, "atr_period": atr_period, "atr_filter": atr_filter}
        self._prev_upper: float = 0.0
        self._prev_lower: float = 0.0
        self._prev_atr: float = 0.0

    def reset(self):
        self._prev_upper = self._prev_lower = self._prev_atr = 0.0

    def update(self, bar, am) -> TechnicalSignal:
        dc = am.donchian(self.params["dc_period"])
        atr = am.atr(self.params["atr_period"])
        if dc is None or atr is None:
            return TechnicalSignal(indicator_name=self.name)
        upper, lower = dc
        if upper is None or lower is None:
            return TechnicalSignal(indicator_name=self.name)
        upper_v, lower_v, atr_v = float(upper), float(lower), float(atr)
        breakout_size = upper_v - self._prev_upper if self._prev_upper > 0 else 0
        buy_sig = float(bar.close_price) > upper_v and breakout_size > atr_v * self.params["atr_filter"]
        sell_sig = float(bar.close_price) < lower_v
        self._prev_upper = upper_v
        self._prev_lower = lower_v
        return TechnicalSignal(indicator_name=self.name, buy_signal=buy_sig, sell_signal=sell_sig,
                               debug_info={"upper": upper_v, "lower": lower_v, "atr": atr_v})


class BollingerMaIndicator(BaseIndicator):
    name = "bollinger_ma"
    params = {"boll_period": 20, "boll_dev": 2.0, "ma_period": 50}

    def __init__(self, boll_period=20, boll_dev=2.0, ma_period=50):
        self.params = {"boll_period": boll_period, "boll_dev": boll_dev, "ma_period": ma_period}

    def update(self, bar, am) -> TechnicalSignal:
        boll = am.boll(self.params["boll_period"], self.params["boll_dev"])
        sma_v = am.sma(self.params["ma_period"])
        if boll is None or sma_v is None:
            return TechnicalSignal(indicator_name=self.name)
        upper, lower = boll
        if upper is None or lower is None:
            return TechnicalSignal(indicator_name=self.name)
        upper_v, lower_v = float(upper), float(lower)
        close = float(bar.close_price)
        ma = float(sma_v)
        buy_sig = close < lower_v and close > ma
        sell_sig = close > upper_v
        return TechnicalSignal(indicator_name=self.name, buy_signal=buy_sig, sell_signal=sell_sig,
                               debug_info={"upper": upper_v, "lower": lower_v, "ma": ma})


class RsiIndicator(BaseIndicator):
    name = "rsi"
    params = {"period": 14, "oversold": 30, "overbought": 70}

    def __init__(self, period=14, oversold=30, overbought=70):
        self.params = {"period": period, "oversold": oversold, "overbought": overbought}
        self._prev_rsi: float = 50.0

    def reset(self):
        self._prev_rsi = 50.0

    def update(self, bar, am) -> TechnicalSignal:
        rsi_val = am.rsi(self.params["period"])
        if rsi_val is None:
            return TechnicalSignal(indicator_name=self.name)
        rsi = float(rsi_val)
        buy_sig = self._prev_rsi < self.params["oversold"] and rsi >= self.params["oversold"]
        sell_sig = self._prev_rsi > self.params["overbought"] and rsi <= self.params["overbought"]
        self._prev_rsi = rsi
        return TechnicalSignal(
            indicator_name=self.name,
            buy_signal=buy_sig,
            sell_signal=sell_sig,
            debug_info={"rsi": rsi},
        )
