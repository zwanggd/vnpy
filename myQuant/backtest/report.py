""""""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from vnpy.trader.constant import Direction


@dataclass
class StrategySummary:
    strategy_name: str = ""
    strategy_family: str = ""
    backtest_engine: str = "vnpy"
    vt_symbol: str = ""
    start_date: str = ""
    end_date: str = ""
    initial_capital: float = 1_000_000
    final_capital: float = 0
    total_return: float = 0
    annual_return: float = 0
    buy_hold_return: float = 0
    excess_return_vs_buy_hold: float = 0
    sharpe_ratio: float = 0
    sortino_ratio: float = 0
    calmar_ratio: float = 0
    max_drawdown: float = 0
    max_drawdown_start: str = ""
    max_drawdown_end: str = ""
    volatility: float = 0
    trade_count: int = 0
    win_rate: float = 0
    avg_trade_return: float = 0
    avg_holding_days: float = 0
    turnover: float = 0
    total_fee: float = 0
    total_slippage: float = 0
    exposure_ratio: float = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class DailyEquity:
    trading_date: str = ""
    vt_symbol: str = ""
    strategy_name: str = ""
    close: float = 0
    position: float = 0
    cash: float = 0
    market_value: float = 0
    total_equity: float = 0
    daily_return: float = 0
    cumulative_return: float = 0
    buy_hold_cumulative_return: float = 0
    drawdown: float = 0
    daily_agent_signal: float = 0
    daily_direction: str = ""
    technical_signal: str = ""
    final_signal: str = ""


def extract_summary(stats: dict, trades: list, daily_df, bh_total_return: float) -> StrategySummary:
    ann = stats.get("annual_return", 0) or 0
    dd = abs(stats.get("max_ddpercent", 0) or 0)
    calmar = abs(ann) / max(dd, 1e-6) if ann else 0
    total_return = stats.get("total_return", 0) or 0

    win_trades = 0
    for t in trades:
        if hasattr(t, "direction") and str(t.direction) == "Direction.LONG" and hasattr(t, "offset"):
            pass
    # vn.py TradeData: Long=entry, Short=exit or vice versa
    win_trades = len([t for t in trades if getattr(t, "direction", None) == Direction.LONG])

    trade_count = stats.get("total_trade_count", 0) or 0
    exposure = 0.0
    if daily_df is not None and len(daily_df) > 0:
        try:
            pos = daily_df.get("end_pos", daily_df.get("position", 0))
            exposure = float((pos != 0).mean()) if hasattr(pos, "mean") else 0
        except Exception:
            pass

    return StrategySummary(
        strategy_name="",
        backtest_engine="vnpy",
        final_capital=round(stats.get("end_balance", 0) or 0, 2),
        total_return=round(total_return, 2),
        annual_return=round(ann, 2),
        buy_hold_return=round(bh_total_return, 2),
        excess_return_vs_buy_hold=round(total_return - bh_total_return, 2),
        sharpe_ratio=round(stats.get("sharpe_ratio", 0) or 0, 3),
        calmar_ratio=round(calmar, 2),
        max_drawdown=round(dd, 2),
        trade_count=trade_count,
        total_fee=round(stats.get("total_commission", 0) or 0, 2),
        total_slippage=round(stats.get("total_slippage", 0) or 0, 2),
        turnover=round(stats.get("total_turnover", 0) or 0, 2),
        exposure_ratio=round(exposure, 4),
        start_date=str(stats.get("start_date", "")),
        end_date=str(stats.get("end_date", "")),
        initial_capital=stats.get("capital", 1_000_000),
        volatility=round(stats.get("return_std", 0) or 0, 6),
    )


def extract_daily_equity(
    daily_df, bh_df, agent_signals: dict | None = None
) -> list[DailyEquity]:
    results: list[DailyEquity] = []
    if daily_df is None or len(daily_df) == 0:
        return results

    cum_ret = 0.0
    bh_cum_ret = 0.0
    bh_rows = {str(d): r for d, r in zip(bh_df.index, bh_df.itertuples())} if bh_df is not None else {}

    for idx, row in daily_df.iterrows():
        dt_str = str(idx)[:10] if hasattr(idx, "strftime") else str(idx)
        close = float(row.get("close_price", row.get("close", 0)) or 0)
        balance = float(row.get("balance", 0) or 0)
        pos = float(row.get("end_pos", 0) or 0)
        bal = balance

        ret = float(row.get("return", 0) or 0)
        cum_ret += ret
        dd = float(row.get("ddpercent", row.get("drawdown", 0)) or 0)

        if dt_str in bh_rows:
            bh_row = bh_rows[dt_str]
            bh_bal = float(getattr(bh_row, "balance", 0) or 0)
            bh_cum_ret = (bh_bal / 1_000_000 - 1) * 100 if bh_bal else 0

        sig = agent_signals.get(date.fromisoformat(dt_str), {}) if agent_signals else {}
        results.append(DailyEquity(
            trading_date=dt_str,
            close=round(close, 2),
            position=round(pos, 2),
            total_equity=round(bal, 2),
            daily_return=round(ret * 100, 6) if ret else 0,
            cumulative_return=round(cum_ret * 100, 6) if cum_ret else 0,
            buy_hold_cumulative_return=round(bh_cum_ret, 2),
            drawdown=round(dd, 2),
            daily_agent_signal=round(sig.get("signal", 0), 4),
            daily_direction=str(sig.get("direction", "")),
        ))
    return results


def generate_reports(
    summaries: list[StrategySummary],
    all_daily_equity: list[list[DailyEquity]],
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. summary_by_strategy.csv
    if summaries:
        fields = [f.name for f in StrategySummary.__dataclass_fields__.values()]
        _write_csv(summaries, output_dir / "summary_by_strategy.csv", fields)

    # 2. daily_equity_by_strategy.csv
    flat_daily: list[DailyEquity] = []
    for de_list in all_daily_equity:
        flat_daily.extend(de_list)
    if flat_daily:
        fields = [f.name for f in DailyEquity.__dataclass_fields__.values()]
        _write_csv(flat_daily, output_dir / "daily_equity_by_strategy.csv", fields)

    # 3. trade_records.csv
    trades_path = output_dir / "trade_records.csv"
    if not trades_path.exists():
        trades_path.write_text(
            "trade_id,strategy_name,vt_symbol,entry_date,exit_date,side,"
            "entry_price,exit_price,holding_days,"
            "entry_signal,exit_signal,entry_agent_signal,exit_agent_signal,"
            "entry_technical_signal,exit_technical_signal,"
            "gross_return,net_return,fee,slippage,"
            "max_favorable_return,max_adverse_return\n"
        )

    # 4. signal_diagnostics.csv
    sig_path = output_dir / "signal_diagnostics.csv"
    if not sig_path.exists():
        sig_path.write_text(
            "trading_date,vt_symbol,daily_agent_signal,daily_direction,"
            "technical_signal,final_signal,close,"
            "next_1d_return,next_5d_return,next_20d_return,"
            "news_count,event_count,model_count,risk_penalty,strategy_action\n"
        )

    # 5. strategy_rank.md
    _write_rank_md(summaries, output_dir / "strategy_rank.md")


def _write_csv(items: list, path: Path, fieldnames: list[str]) -> None:
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for item in items:
            w.writerow(item if isinstance(item, dict) else item.__dict__)


def _write_rank_md(summaries: list[StrategySummary], path: Path) -> None:
    if not summaries:
        return

    lines: list[str] = [
        f"# {summaries[0].vt_symbol} Strategy Matrix Report",
        "",
        f"**Date Range**: {summaries[0].start_date} to {summaries[0].end_date}",
        f"**Backtest Engine**: vnpy",
        f"**Fees/Slippage**: handled by vn.py",
        f"**Total Strategies**: {len(summaries)}",
        "",
        "## Warnings",
        "",
    ]

    # Duplicate detection
    seen: dict[str, StrategySummary] = {}
    duplicates: list[tuple[str, str]] = []
    for s in summaries:
        key = f"{s.total_return:.4f}_{s.sharpe_ratio:.4f}_{s.max_drawdown:.2f}_{s.trade_count}"
        if key in seen:
            duplicates.append((seen[key].strategy_name, s.strategy_name))
        else:
            seen[key] = s

    if duplicates:
        for a, b in duplicates:
            lines.append(f"- ⚠️ **WARNING**: `{a}` and `{b}` have identical results — may be duplicate logic.")

    # Either-safe check
    either_sig = next((s for s in summaries if s.strategy_name == "either_signal"), None)
    either_safe = next((s for s in summaries if s.strategy_name == "either_safe"), None)
    if either_sig and either_safe:
        if (abs(either_sig.total_return - either_safe.total_return) < 0.01
                and either_sig.trade_count == either_safe.trade_count):
            lines.append("- ⚠️ **WARNING**: `either_signal` and `either_safe` produce identical results "
                         "— agent sell filter may never trigger for this stock.")

    # MaxDD warnings
    for s in summaries:
        if s.max_drawdown < -30 and s.family == "agent_only":
            lines.append(f"- ⚠️ **HIGH RISK**: `{s.strategy_name}` max DD = {s.max_drawdown}% (agent-only modes)")
            break

    # Buy-and-hold comparison
    bh = next((s for s in summaries if s.strategy_name == "buy_and_hold"), None)
    if not bh:
        lines.append("- ❌ **ERROR**: buy_and_hold benchmark missing!")
    else:
        lines.extend([
            "",
            "## Buy & Hold",
            f"- Total Return: {bh.total_return}%",
            f"- Annual Return: {bh.annual_return}%",
            f"- Max Drawdown: {bh.max_drawdown}%",
            f"- Sharpe: {bh.sharpe_ratio}",
        ])
        below_bh = [s for s in summaries if s.strategy_name != "buy_and_hold" and s.total_return < bh.total_return]
        if below_bh:
            names = ", ".join(s.strategy_name for s in below_bh[:5])
            lines.append(f"- Strategies below buy_and_hold: {names}")

    # Rankings
    sorted_by_return = sorted(summaries, key=lambda s: s.total_return, reverse=True)
    sorted_by_sharpe = sorted(summaries, key=lambda s: s.sharpe_ratio, reverse=True)
    sorted_by_dd = sorted(summaries, key=lambda s: s.max_drawdown)

    lines.extend([
        "",
        "## Top 10 by Total Return",
        "| Rank | Strategy | Return % | Sharpe | MaxDD % | Trades | Excess vs B&H % |",
        "|------|----------|----------|--------|---------|--------|-----------------|",
    ])
    for i, s in enumerate(sorted_by_return[:10], 1):
        lines.append(f"| {i} | {s.strategy_name} | {s.total_return:.1f} | {s.sharpe_ratio:.2f} | "
                     f"{s.max_drawdown:.1f} | {s.trade_count} | {s.excess_return_vs_buy_hold:+.1f} |")

    lines.extend([
        "",
        "## Top 10 by Sharpe Ratio",
        "| Rank | Strategy | Sharpe | Return % | MaxDD % |",
        "|------|----------|--------|----------|---------|",
    ])
    for i, s in enumerate(sorted_by_sharpe[:10], 1):
        lines.append(f"| {i} | {s.strategy_name} | {s.sharpe_ratio:.2f} | {s.total_return:.1f} | {s.max_drawdown:.1f} |")

    lines.extend([
        "",
        "## Top 10 by Drawdown Control",
        "| Rank | Strategy | MaxDD % | Return % | Sharpe |",
        "|------|----------|---------|----------|--------|",
    ])
    for i, s in enumerate(sorted_by_dd[:10], 1):
        lines.append(f"| {i} | {s.strategy_name} | {s.max_drawdown:.1f} | {s.total_return:.1f} | {s.sharpe_ratio:.2f} |")

    path.write_text("\n".join(lines))
