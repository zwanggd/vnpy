""""""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import json
import sqlite3


@dataclass
class AgentSignal:
    score: float = 0.0
    direction: str = "neutral"

    @property
    def is_positive(self) -> bool:
        return self.direction == "positive" or self.score > 0

    @property
    def is_negative(self) -> bool:
        return self.direction == "negative" or self.score < 0


class AgentSignalProvider:
    def get_signal(self, trading_date: date) -> AgentSignal:
        raise NotImplementedError


class NewsAgentSignalProvider(AgentSignalProvider):
    def __init__(
        self,
        db_path: str | None = None,
        json_path: str | None = None,
        signal_version: str | None = None,
    ) -> None:
        self._signals: dict[date, AgentSignal] = {}
        if db_path and Path(db_path).exists():
            self._signals = self._from_db(db_path, signal_version)
        elif json_path and Path(json_path).exists():
            self._signals = self._from_json(json_path)

    def get_signal(self, trading_date: date) -> AgentSignal:
        return self._signals.get(trading_date, AgentSignal())

    def _from_db(self, db_path: str, signal_version: str | None) -> dict[date, AgentSignal]:
        db = sqlite3.connect(db_path)
        result: dict[date, AgentSignal] = {}
        try:
            cols = {r[1] for r in db.execute("PRAGMA table_info(agent_daily_signal)")}
            if "trading_date" in cols:
                if signal_version:
                    rows = db.execute(
                        "SELECT trading_date, daily_agent_signal, daily_direction "
                        "FROM agent_daily_signal WHERE signal_version = ?",
                        (signal_version,),
                    ).fetchall()
                else:
                    rows = db.execute(
                        "SELECT trading_date, daily_agent_signal, daily_direction "
                        "FROM agent_daily_signal"
                    ).fetchall()
            else:
                rows = db.execute(
                    "SELECT entry_date, daily_agent_signal, daily_direction "
                    "FROM daily_agent_signal"
                ).fetchall()
            for date_str, score, direction in rows:
                if date_str:
                    d = date.fromisoformat(str(date_str)[:10])
                    result[d] = AgentSignal(
                        score=float(score or 0),
                        direction=str(direction or "neutral"),
                    )
        finally:
            db.close()
        return result

    def _from_json(self, json_path: str) -> dict[date, AgentSignal]:
        data = json.loads(Path(json_path).read_text())
        result: dict[date, AgentSignal] = {}
        for item in data:
            d = date.fromisoformat(item["trading_date"][:10])
            result[d] = AgentSignal(
                score=float(item.get("daily_agent_signal", 0) or 0),
                direction=item.get("daily_direction", "neutral"),
            )
        return result
