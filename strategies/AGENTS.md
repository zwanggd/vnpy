# AGENTS.md — Strategies Package

> standalone 策略包 (source-only). 扩展 VNPY CtaTemplate, 融合技术指标与代理信号.

## OVERVIEW
Trading strategy implementations (~5 files) extending VNPY `CtaTemplate`. Two strategy families: MACD-specific (`MacdAgentStrategy`, 8 signal modes) and generic tech-indicator (`TechAgentStrategy`, 14 modes, pluggable indicator). Both fuse technical signals with agent news sentiment from `~/.vntrader/agent_news.db`.

## STRUCTURE
```
strategies/
├── __init__.py                  # 导出: MacdAgentStrategy, TechAgentStrategy, indicators, MODES
├── macd_agent_strategy.py       # MACD + Agent 信号融合 (8种模式)
├── tech_agent_strategy.py       # 通用指标 + Agent 信号融合 (14种模式, 可插拔指标)
├── technical_indicators.py      # 8个具体 BaseIndicator 子类
└── technical_signal.py          # TechnicalSignal dataclass + BaseIndicator 抽象基类
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| 策略模板 | `macd_agent_strategy.py` | 最简策略: parameters/variables/on_bar/信号加载 |
| 通用策略 | `tech_agent_strategy.py` | 可插拔指标, signal_mode 参数选择 |
| 添加新指标 | `technical_indicators.py` | 继承 BaseIndicator, 实现 update() → TechnicalSignal |
| 信号数据类型 | `technical_signal.py` | TechnicalSignal(buy_signal, sell_signal, debug_info) |
| 代理信号加载 | macd_agent/tech_agent | `load_agent_signals()` 从 `agent_daily_signal` 表读取 |
...
- **代理信号源**: `load_agent_signals()` 从 `~/.vntrader/agent_news.db` 读取 `agent_daily_signal`

## SIGNAL FUSION MODES
- `tech_confirm_veto`: 代理确认或否决技术信号
- `tech_veto_only`: 代理仅否决 (不主动开仓)
- `agent_overlay`: 代理信号加减技术信号
- `legacy_either_safe`: 原始 either_safe (MACD金叉 OR 代理买入)

## ANTI-PATTERNS
- **禁止**: 在 `on_init/on_load` 回调中下单
- **禁止**: 重复使用其他策略的类名
- **避免**: 盘中暂停/重启策略
- **避免**: 仅凭感觉调整参数 — 必须回测验证
- **注意**: `buy(price, volume)` 中 `volume` 以**手**为单位, 非股数
- **注意**: ArrayManager 默认 size=100, 无法计算 SMA(120/200) — 需手动扩大

## NOTES
- `__pycache__` 包含 `catl_multi_signal` 和 `macd_strategy` 的残留 .pyc (已删除源码)
- 策略引擎从 `~/.vntrader/strategies/` 扫描, 非项目 `strategies/` 目录
- `strategies/` 不在 pyproject.toml build 中 — 仅源码存在
- 回测时需通过 `BacktestingEngine` (vnpy.alpha) 运行, 信号通过临时SQLite注入
