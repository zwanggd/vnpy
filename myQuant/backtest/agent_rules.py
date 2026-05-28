""""""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuleDef:
    name: str
    description: str
    formula: str = ""
    category: str = ""


ENTRY_RULES: dict[str, RuleDef] = {
    "tech_entry": RuleDef(
        name="tech_entry",
        description="T+: Technical buy only",
        formula="T+",
        category="entry",
    ),
    "agent_entry": RuleDef(
        name="agent_entry",
        description="A+: Agent buy only",
        formula="A+",
        category="entry",
    ),
    "either_entry": RuleDef(
        name="either_entry",
        description="T+ OR A+: Either signals buy",
        formula="T+ OR A+",
        category="entry",
    ),
    "consensus_entry": RuleDef(
        name="consensus_entry",
        description="T+ AND A+: Both must agree to buy",
        formula="T+ AND A+",
        category="entry",
    ),
    "agent_veto_entry": RuleDef(
        name="agent_veto_entry",
        description="T+ AND NOT A-: Tech buy, agent veto negative entries",
        formula="T+ AND NOT A-",
        category="entry",
    ),
    "either_entry_with_veto": RuleDef(
        name="either_entry_with_veto",
        description="(T+ OR A+) AND NOT A-: Either triggers, agent veto negative",
        formula="(T+ OR A+) AND NOT A-",
        category="entry",
    ),
}

EXIT_RULES: dict[str, RuleDef] = {
    "tech_exit": RuleDef(
        name="tech_exit",
        description="T-: Technical sell only",
        formula="T-",
        category="exit",
    ),
    "agent_exit": RuleDef(
        name="agent_exit",
        description="A-: Agent sell only",
        formula="A-",
        category="exit",
    ),
    "either_exit": RuleDef(
        name="either_exit",
        description="T- OR A-: Either signals sell",
        formula="T- OR A-",
        category="exit",
    ),
    "consensus_exit": RuleDef(
        name="consensus_exit",
        description="T- AND A-: Both must agree to sell",
        formula="T- AND A-",
        category="exit",
    ),
    "agent_veto_exit": RuleDef(
        name="agent_veto_exit",
        description="T- AND NOT A+: Tech sell, agent veto exit when bullish",
        formula="T- AND NOT A+",
        category="exit",
    ),
    "either_exit_with_veto": RuleDef(
        name="either_exit_with_veto",
        description="(T- OR A-) AND NOT A+: Either triggers, agent blocks when bullish",
        formula="(T- OR A-) AND NOT A+",
        category="exit",
    ),
}


DEFAULT_COMBOS: list[str] = [
    "tech_entry__tech_exit",
    "agent_veto_entry__tech_exit",
    "tech_entry__either_exit",
    "consensus_entry__either_exit",
]


def evaluate_entry(
    rule_name: str, tech_buy: bool, agent_buy: bool, agent_sell: bool
) -> bool:
    if rule_name == "tech_entry":
        return tech_buy
    if rule_name == "agent_entry":
        return agent_buy
    if rule_name == "either_entry":
        return tech_buy or agent_buy
    if rule_name == "consensus_entry":
        return tech_buy and agent_buy
    if rule_name == "agent_veto_entry":
        return tech_buy and not agent_sell
    if rule_name == "either_entry_with_veto":
        return (tech_buy or agent_buy) and not agent_sell
    return False


def evaluate_exit(
    rule_name: str, tech_sell: bool, agent_buy: bool, agent_sell: bool
) -> bool:
    if rule_name == "tech_exit":
        return tech_sell
    if rule_name == "agent_exit":
        return agent_sell
    if rule_name == "either_exit":
        return tech_sell or agent_sell
    if rule_name == "consensus_exit":
        return tech_sell and agent_sell
    if rule_name == "agent_veto_exit":
        return tech_sell and not agent_buy
    if rule_name == "either_exit_with_veto":
        return (tech_sell or agent_sell) and not agent_buy
    return False


def generate_all_combos() -> list[str]:
    combos: list[str] = []
    for er in ENTRY_RULES:
        for xr in EXIT_RULES:
            combos.append(f"{er}__{xr}")
    return combos


def generate_default_combos() -> list[str]:
    return DEFAULT_COMBOS


OLD_ALIAS_MAP: dict[str, str] = {
    "buy_and_hold": "buy_and_hold",
    "macd_only": "macd__tech_entry__tech_exit",
    "agent_only": "agent_direction__agent_entry__agent_exit",
    "agent_sell_only": "macd__tech_entry__either_exit",
    "agent_buy_only": "macd__either_entry__tech_exit",
    "both_consensus": "macd__consensus_entry__either_exit",
    "macd_confirmed": "macd__consensus_entry__either_exit",
    "either_signal": "macd__either_entry__either_exit",
    "either_safe": "macd__either_entry_with_veto__either_exit",
    "macd_agent_entry_filter": "macd__agent_veto_entry__tech_exit",
}
