# CATL News Agent Analysis

宁德时代 (300750.SZSE) 新闻事件驱动信号研究。

## 数据来源

- **新闻**: 东方财富 CATL 相关公告，1,514 条，2020-2026
- **行情**: CATL 日线，2020-01-02 至 2026-05-12
- **模型**: DeepSeek V4 Flash (API) + Qwen3.6-35B-A3B (本地 llama.cpp)

## 文件

| 文件 | 说明 |
|------|------|
| `final_report.md` | 双模型全量对比报告 (1,514条, 91%方向一致) |
| `event_study_agent_signals.csv` | 10个信号事件研究原始数据 |
| `event_study_agent_signals.md` | 事件研究汇总表 |
| `signal_recommendation.md` | 信号推荐结论 + 后续建议 |

## 结论

当前 Agent 信号在 CATL 单一标的上**未展示 alpha 预测能力**。主要原因：

1. CATL 2020-2026 强势牛市，几乎所有事件日后都上涨
2. Agent 将配售/转让等事件误判为 negative，但市场解读为利好
3. 仅覆盖单一标的，缺乏横截面分化能力

进入策略回测前建议：扩大标的范围、引入市场中性化、升级模型。
