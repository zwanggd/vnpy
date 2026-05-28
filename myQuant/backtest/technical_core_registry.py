""""""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from vnpy_ctastrategy import ArrayManager


@dataclass
class TechSignal:
    tech_buy: bool = False
    tech_sell: bool = False
    tech_score: float = 0.0
    technical_signal: str = ""
    debug_info: dict = field(default_factory=dict)


@dataclass
class TechnicalCoreSpec:
    name: str
    description: str
    compute: Callable[[Any, ArrayManager], TechSignal]
    params: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    disabled_reason: str = ""


# ── Core compute functions ──────────────────────────────────────────────

def _macd_core(bar, am: ArrayManager) -> TechSignal:
    r = am.macd(12, 26, 9)
    if r is None or r[0] is None:
        return TechSignal()
    dif, dea, hist = float(r[0]), float(r[1]), float(r[2]) if r[2] else 0
    golden = getattr(_macd_core, "_prev_dif", 0.0) <= getattr(_macd_core, "_prev_dea", 0.0) and dif > dea
    death = getattr(_macd_core, "_prev_dif", 0.0) >= getattr(_macd_core, "_prev_dea", 0.0) and dif < dea
    _macd_core._prev_dif = dif  # type: ignore[attr-defined]
    _macd_core._prev_dea = dea  # type: ignore[attr-defined]
    return TechSignal(tech_buy=golden, tech_sell=death, tech_score=hist,
                      technical_signal="golden" if golden else ("death" if death else ""),
                      debug_info={"dif": dif, "dea": dea, "hist": hist})


def _ma_cross_core(bar, am: ArrayManager) -> TechSignal:
    ma20 = am.sma(20)
    ma60 = am.sma(60)
    if ma20 is None or ma60 is None:
        return TechSignal()
    m20, m60 = float(ma20), float(ma60)
    prev_m20 = getattr(_ma_cross_core, "_prev_ma20", m20)
    prev_m60 = getattr(_ma_cross_core, "_prev_ma60", m60)
    buy = prev_m20 <= prev_m60 and m20 > m60
    sell = prev_m20 >= prev_m60 and m20 < m60
    _ma_cross_core._prev_ma20 = m20  # type: ignore[attr-defined]
    _ma_cross_core._prev_ma60 = m60  # type: ignore[attr-defined]
    score = (m20 / m60 - 1) * 100
    return TechSignal(tech_buy=buy, tech_sell=sell, tech_score=score,
                      technical_signal="golden" if buy else ("death" if sell else ""),
                      debug_info={"ma20": m20, "ma60": m60})


def _ma_trend_core(bar, am: ArrayManager) -> TechSignal:
    close = float(bar.close_price)
    ma20 = am.sma(20)
    ma60 = am.sma(60)
    if ma20 is None or ma60 is None:
        return TechSignal()
    m20, m60 = float(ma20), float(ma60)
    trending = close > m60 and m20 > m60
    return TechSignal(tech_buy=trending, tech_sell=not trending,
                      tech_score=(close / m60 - 1) * 100,
                      technical_signal="trend" if trending else "not_trend",
                      debug_info={"close": close, "ma20": m20, "ma60": m60})


def _adx_trend_core(bar, am: ArrayManager) -> TechSignal:
    adx = am.adx(14)
    plus_di = am.plus_di(14)
    minus_di = am.minus_di(14)
    if adx is None or plus_di is None or minus_di is None:
        return TechSignal()
    a, p, m = float(adx), float(plus_di), float(minus_di)
    buy = a > 20 and p > m
    sell = a > 20 and p < m
    return TechSignal(tech_buy=buy, tech_sell=sell, tech_score=a - 20,
                      technical_signal="bull_trend" if buy else ("bear_trend" if sell else ""),
                      debug_info={"adx": a, "+di": p, "-di": m})


def _rsi_reversion_core(bar, am: ArrayManager) -> TechSignal:
    rsi = am.rsi(14)
    if rsi is None:
        return TechSignal()
    r = float(rsi)
    prev = getattr(_rsi_reversion_core, "_prev_rsi", 50.0)
    buy = prev <= 30 and r > 30
    sell = prev >= 70 and r < 70
    _rsi_reversion_core._prev_rsi = r  # type: ignore[attr-defined]
    return TechSignal(tech_buy=buy, tech_sell=sell, tech_score=r - 50,
                      technical_signal="oversold" if buy else ("overbought" if sell else ""),
                      debug_info={"rsi": r})


def _bollinger_reversion_core(bar, am: ArrayManager) -> TechSignal:
    r = am.boll(20, 2.0)
    ma = am.sma(20)
    if r is None or ma is None:
        return TechSignal()
    upper, lower = float(r[0]), float(r[1])
    middle = float(ma)
    close = float(bar.close_price)
    buy = close < lower
    sell = close > middle
    return TechSignal(tech_buy=buy, tech_sell=sell, tech_score=(close - middle) / middle * 100,
                      technical_signal="below_lower" if buy else ("above_mid" if sell else ""),
                      debug_info={"upper": upper, "lower": lower, "mid": middle, "close": close})


def _breakout_20d_core(bar, am: ArrayManager) -> TechSignal:
    high = am.highest(20)
    low = am.lowest(20)
    if high is None or low is None:
        return TechSignal()
    close = float(bar.close_price)
    buy = close > float(high)
    sell = close < float(low)
    return TechSignal(tech_buy=buy, tech_sell=sell, tech_score=0,
                      technical_signal="breakout_20" if buy else ("breakdown_20" if sell else ""),
                      debug_info={"high": float(high), "low": float(low), "close": close})


def _breakout_60d_core(bar, am: ArrayManager) -> TechSignal:
    high = am.highest(60)
    low = am.lowest(60)
    if high is None or low is None:
        return TechSignal()
    close = float(bar.close_price)
    buy = close > float(high)
    sell = close < float(low)
    return TechSignal(tech_buy=buy, tech_sell=sell, tech_score=0,
                      technical_signal="breakout_60" if buy else ("breakdown_60" if sell else ""),
                      debug_info={"high": float(high), "low": float(low), "close": close})


def _atr_trailing_stop_core(bar, am: ArrayManager) -> TechSignal:
    return TechSignal(technical_signal="disabled")


def _volume_confirmed_breakout_core(bar, am: ArrayManager) -> TechSignal:
    return TechSignal(technical_signal="disabled")


# ── Registry ────────────────────────────────────────────────────────────

TECHNICAL_CORES: dict[str, TechnicalCoreSpec] = {
    "macd": TechnicalCoreSpec(
        name="macd", description="MACD golden cross buy, death cross sell",
        compute=_macd_core,
        params={"fast": 12, "slow": 26, "signal_period": 9},
    ),
    "ma_cross": TechnicalCoreSpec(
        name="ma_cross", description="MA20 crosses above MA60 buy, below sell",
        compute=_ma_cross_core,
        params={"ma_fast": 20, "ma_slow": 60},
    ),
    "ma_trend": TechnicalCoreSpec(
        name="ma_trend", description="Close > MA60 and MA20 > MA60 = buy/hold, else sell",
        compute=_ma_trend_core,
        params={"ma": 60},
    ),
    "adx_trend": TechnicalCoreSpec(
        name="adx_trend", description="ADX > 20 with +DI > -DI buy, -DI > +DI sell",
        compute=_adx_trend_core,
        params={"adx_period": 14, "adx_threshold": 20},
    ),
    "rsi_reversion": TechnicalCoreSpec(
        name="rsi_reversion", description="RSI < 30 buy, RSI > 70 sell",
        compute=_rsi_reversion_core,
        params={"period": 14, "oversold": 30, "overbought": 70},
    ),
    "bollinger_reversion": TechnicalCoreSpec(
        name="bollinger_reversion", description="Close < lower band buy, close > middle sell",
        compute=_bollinger_reversion_core,
        params={"period": 20, "dev": 2.0},
    ),
    "breakout_20d": TechnicalCoreSpec(
        name="breakout_20d", description="Close > highest(20) buy, close < lowest(20) sell",
        compute=_breakout_20d_core,
        params={"period": 20},
    ),
    "breakout_60d": TechnicalCoreSpec(
        name="breakout_60d", description="Close > highest(60) buy, close < lowest(60) sell",
        compute=_breakout_60d_core,
        params={"period": 60},
    ),
    "atr_trailing_stop": TechnicalCoreSpec(
        name="atr_trailing_stop", description="Trend entry with ATR trailing stop",
        compute=_atr_trailing_stop_core,
        enabled=False,
        disabled_reason="Missing ATR trailing stop implementation",
    ),
    "volume_confirmed_breakout": TechnicalCoreSpec(
        name="volume_confirmed_breakout", description="Price breakout with volume confirmation",
        compute=_volume_confirmed_breakout_core,
        enabled=False,
        disabled_reason="Missing volume data access in ArrayManager",
    ),
}


def get_enabled_cores() -> list[TechnicalCoreSpec]:
    return [c for c in TECHNICAL_CORES.values() if c.enabled]


def get_all_cores() -> list[TechnicalCoreSpec]:
    return list(TECHNICAL_CORES.values())
