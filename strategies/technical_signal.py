"""Unified technical signal interface for decoupled indicator strategies."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class TechnicalSignal:
    indicator_name: str
    buy_signal: bool = False
    sell_signal: bool = False
    debug_info: dict = field(default_factory=dict)


class BaseIndicator:
    name: str = "base"
    params: dict = {}

    def update(self, bar, am) -> TechnicalSignal:
        raise NotImplementedError

    def reset(self) -> None:
        pass
