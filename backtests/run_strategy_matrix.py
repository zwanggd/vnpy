""""""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from vnpy.trader.constant import Interval
from vnpy_ctastrategy.backtesting import BacktestingEngine
from strategies.buy_and_hold_strategy import BuyAndHoldStrategy
from strategies.tech_agent_matrix_strategy import TechAgentMatrixStrategy
from myQuant.backtest.agent_rules import (
    ENTRY_RULES, EXIT_RULES, DEFAULT_COMBOS,
    generate_all_combos, OLD_ALIAS_MAP,
)
from myQuant.backtest.technical_core_registry import (
    TECHNICAL_CORES, get_enabled_cores, get_all_cores,
)
from myQuant.backtest.report import extract_summary


def run_single(vt_symbol: str, start: date, end: date,
               params: dict, strategy_class=TechAgentMatrixStrategy) -> tuple[dict, list, object]:
    engine = BacktestingEngine()
    engine.output = lambda msg: None
    engine.set_parameters(
        vt_symbol=vt_symbol, interval=Interval.DAILY,
        start=datetime(start.year, start.month, start.day),
        end=datetime(end.year, end.month, end.day),
        rate=0.0003, slippage=0.01, size=100, pricetick=0.01,
        capital=1_000_000,
    )
    engine.add_strategy(strategy_class, params)
    engine.load_data()
    engine.run_backtesting()
    daily_df = engine.calculate_result()
    stats = engine.calculate_statistics(daily_df, output=False)
    trades = engine.get_all_trades()
    return stats, trades, daily_df


def main():
    parser = argparse.ArgumentParser(description="v0.26 Strategy Matrix Runner")
    parser.add_argument("--vt-symbol", required=True)
    parser.add_argument("--db-path", default="~/.vntrader/agent_news.db")
    parser.add_argument("--signal-source", default="db", choices=["db", "json"])
    parser.add_argument("--signal-json-path", default=None)
    parser.add_argument("--signal-version", default=None)
    parser.add_argument("--start-date", default="2020-01-01")
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--agent-combo-set", default="default", choices=["default", "full"])
    parser.add_argument("--signal-shift-days", type=int, default=0)
    args = parser.parse_args()

    vt_symbol = args.vt_symbol
    db_path = str(Path(args.db_path).expanduser())
    start_date = date.fromisoformat(args.start_date)
    end_date = date.fromisoformat(args.end_date) if args.end_date else date.today()
    output_dir = Path(args.output_dir) if args.output_dir else (
        _PROJECT_ROOT / "backtests" / "results" / "v0.26" / vt_symbol
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    cores = get_all_cores()
    enabled_cores = get_enabled_cores()
    combos = generate_all_combos() if args.agent_combo_set == "full" else DEFAULT_COMBOS
    is_full = args.agent_combo_set == "full"

    info = {
        "total_cores": len(cores),
        "enabled_cores": len(enabled_cores),
        "total_combos": len(combos),
        "is_full": is_full,
        "total_candidate": len(enabled_cores) * len(combos),
    }
    print(f"[matrix] {vt_symbol} — {info['enabled_cores']} enabled cores × "
          f"{info['total_combos']} combos = {info['total_candidate']} candidates")

    # ── Build catalog ────────────────────────────────────────────────────
    catalog_rows: list[dict] = []
    for core in cores:
        for combo in combos:
            er, xr = combo.split("__", 1)
            uses_agent = er != "tech_entry" or xr != "tech_exit"
            runnable = core.enabled
            row = {
                "strategy_name": f"{core.name}__{combo}",
                "technical_core": core.name,
                "entry_rule": er, "exit_rule": xr,
                "entry_formula": ENTRY_RULES[er].formula,
                "exit_formula": EXIT_RULES[xr].formula,
                "uses_agent_signal": uses_agent,
                "uses_technical_signal": True,
                "is_default_combo": combo in DEFAULT_COMBOS,
                "is_full_combo": is_full,
                "technical_core_enabled": core.enabled,
                "runnable": runnable,
                "disabled_reason": core.disabled_reason if not core.enabled else "",
                "description": f"{core.description} | {ENTRY_RULES[er].description} | {EXIT_RULES[xr].description}",
            }
            catalog_rows.append(row)

    # Write catalog
    _write_csv(catalog_rows, output_dir / "strategy_matrix_catalog.csv")
    print(f"[catalog] {len(catalog_rows)} rows → strategy_matrix_catalog.csv")

    # ── Run buy_and_hold ─────────────────────────────────────────────────
    bh_stats, bh_trades, bh_daily = run_single(
        vt_symbol, start_date, end_date,
        {"pos_ratio": 1.0, "init_capital": 1_000_000},
        BuyAndHoldStrategy,
    )
    bh_return = bh_stats.get("total_return", 0) or 0
    print(f"[bh] return={bh_return:.1f}% maxDD={abs(bh_stats.get('max_ddpercent', 0)):.1f}%")

    # ── Run matrix ───────────────────────────────────────────────────────
    results: list[dict] = []
    base_params = {
        "pos_ratio": 0.5, "init_capital": 1_000_000,
        "agent_db_path": db_path,
        "agent_signal_version": args.signal_version or "",
        "signal_shift_days": args.signal_shift_days,
    }

    for core in enabled_cores:
        for combo in combos:
            er, xr = combo.split("__", 1)
            name = f"{core.name}__{combo}"
            params = dict(base_params)
            params["technical_core"] = core.name
            params["entry_rule"] = er
            params["exit_rule"] = xr

            try:
                stats, trades, daily = run_single(vt_symbol, start_date, end_date, params)
                s = extract_summary(stats, trades, daily, bh_return)
                result = {
                    "strategy_name": name,
                    "technical_core": core.name,
                    "entry_rule": er, "exit_rule": xr,
                    "backtest_engine": "vnpy",
                    "vt_symbol": vt_symbol,
                    "start_date": s.start_date, "end_date": s.end_date,
                    "initial_capital": s.initial_capital,
                    "final_capital": s.final_capital,
                    "total_return": s.total_return,
                    "annual_return": s.annual_return,
                    "buy_hold_return": s.buy_hold_return,
                    "excess_return_vs_buy_hold": s.excess_return_vs_buy_hold,
                    "sharpe_ratio": s.sharpe_ratio,
                    "calmar_ratio": s.calmar_ratio,
                    "max_drawdown": s.max_drawdown,
                    "trade_count": s.trade_count,
                    "total_fee": s.total_fee,
                    "total_slippage": s.total_slippage,
                    "turnover": s.turnover,
                    "exposure_ratio": s.exposure_ratio,
                }
                results.append(result)
                over_bh = "+" if s.total_return > bh_return else ""
                print(f"  {name:<45s} ret={s.total_return:>6.1f}% exc={s.excess_return_vs_buy_hold:+5.1f}% "
                      f"sharpe={s.sharpe_ratio:.2f} maxDD={s.max_drawdown:.1f}% trades={s.trade_count} {over_bh}")
            except Exception as exc:
                print(f"  {name} ERROR: {exc}")

    # Add buy_and_hold row
    bh_row = extract_summary(bh_stats, bh_trades, bh_daily, bh_return)
    results.append({
        "strategy_name": "buy_and_hold",
        "technical_core": "", "entry_rule": "", "exit_rule": "",
        "backtest_engine": "vnpy", "vt_symbol": vt_symbol,
        "start_date": bh_row.start_date, "end_date": bh_row.end_date,
        "initial_capital": bh_row.initial_capital,
        "final_capital": bh_row.final_capital,
        "total_return": bh_row.total_return,
        "annual_return": bh_row.annual_return,
        "buy_hold_return": bh_return,
        "excess_return_vs_buy_hold": 0.0,
        "sharpe_ratio": bh_row.sharpe_ratio,
        "calmar_ratio": bh_row.calmar_ratio,
        "max_drawdown": bh_row.max_drawdown,
        "trade_count": bh_row.trade_count,
        "total_fee": bh_row.total_fee,
        "total_slippage": bh_row.total_slippage,
        "turnover": bh_row.turnover,
        "exposure_ratio": bh_row.exposure_ratio,
    })

    # Write results
    fields = list(results[0].keys()) if results else []
    _write_csv(results, output_dir / "strategy_matrix_results.csv")
    print(f"[results] {len(results)} rows → strategy_matrix_results.csv")

    # ── Rank MD ──────────────────────────────────────────────────────────
    _write_rank_md(results, info, output_dir / "strategy_rank.md")

    # Console ranking
    ranked = sorted([r for r in results if r["strategy_name"] != "buy_and_hold"],
                    key=lambda r: r["total_return"], reverse=True)
    print(f"\n{'─'*30} Top 10 by Total Return {'─'*30}")
    for i, r in enumerate(ranked[:10], 1):
        print(f"  {i:2d}. {r['strategy_name']:<45s} {r['total_return']:>6.1f}%  "
              f"Sharpe={r['sharpe_ratio']:.2f}  MaxDD={r['max_drawdown']:.1f}%  "
              f"excess={r['excess_return_vs_buy_hold']:+.1f}%")

    best_excess = max([r for r in results if r["strategy_name"] != "buy_and_hold"],
                      key=lambda r: r["excess_return_vs_buy_hold"], default=None)
    if best_excess:
        print(f"\nBest excess over buy_and_hold ({bh_return:.1f}%): "
              f"{best_excess['strategy_name']} = {best_excess['excess_return_vs_buy_hold']:+.1f}%")

    return 0


def _write_csv(rows: list[dict], path: Path) -> None:
    if not rows:
        return
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def _write_rank_md(results: list[dict], info: dict, path: Path) -> None:
    lines = [
        f"# Strategy Matrix Report — v0.26",
        "",
        f"- **Agent Combo Set**: {'full' if info['is_full'] else 'default'}",
        f"- **Total Candidates**: {info['total_cores']} cores × {info['total_combos']} combos = {info['total_candidate']}",
        f"- **Enabled Cores**: {info['enabled_cores']}",
        f"- **Backtest Engine**: vnpy",
        f"- **Default Combos**: {', '.join(DEFAULT_COMBOS)}",
        "",
    ]

    ranked = sorted(results, key=lambda r: r.get("excess_return_vs_buy_hold", 0), reverse=True)
    lines.append("## Top 10 by Excess vs Buy & Hold")
    lines.append("| Rank | Strategy | Return % | Excess % | Sharpe | MaxDD % |")
    lines.append("|------|----------|----------|----------|--------|---------|")
    for i, r in enumerate(ranked[:10], 1):
        lines.append(f"| {i} | {r['strategy_name']} | {r['total_return']:.1f} | "
                     f"{r['excess_return_vs_buy_hold']:+.1f} | {r['sharpe_ratio']:.2f} | {r['max_drawdown']:.1f} |")

    path.write_text("\n".join(lines))


if __name__ == "__main__":
    raise SystemExit(main())
