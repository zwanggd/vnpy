# Agent Signal Alpha Validation — 工作规划

## TL;DR
> **目标**: 验证10个Agent信号的alpha效应，为后续回测筛选最优信号
> **数据**: news_analysis (DeepSeek+Qwen全量) + dbbardata (CATL日线) + agent_raw_news (发布日期)
> **交付物**: news_signal_wide表 + event study结果 + daily_agent_signal表 + 信号推荐
> **预估耗时**: ~10分钟 (纯计算, 无API调用)

---

## Context

### 关键数据资产
- **信号**: `agent_news.db` → `news_analysis`, prompt_version='v1', 3,028条 (DS+QW各1,514)
- **新闻**: `agent_news.db` → `agent_raw_news`, published_at字段
- **行情**: `~/.vntrader/database.db` → `dbbardata`, CATL daily, 2020-2026
- **交易日历**: 从 dbbardata 推导 (所有有行情记录的日期)

### 核心设计原则
1. 所有信号从 **下一交易日** 开始生效 (published_at → 下一个trade_date)
2. 不引入未来函数
3. 纯SQL + 轻量Python, 结果可复现

### 10个待测信号
| ID | 名称 | 逻辑 |
|:---:|------|------|
| S1 | DS score >= 0.25 | deepseek_score >= 0.25 |
| S2 | QW score >= 0.25 | qwen_score >= 0.25 |
| S3 | avg score >= 0.25 | avg_score >= 0.25 |
| S4 | DS direction=positive | deepseek_direction = 'positive' |
| S5 | QW direction=positive | qwen_direction = 'positive' |
| S6 | Either positive | DS=positive OR QW=positive |
| S7 | Both positive (consensus) | DS=positive AND QW=positive |
| S8 | DS score <= -0.25 | deepseek_score <= -0.25 |
| S9 | QW score <= -0.25 | qwen_score <= -0.25 |
| S10 | avg score <= -0.25 | avg_score <= -0.25 |

---

## Work Objectives

### Deliverables
1. `news_signal_wide` — 宽表/view，含双方信号 + entry_date + forward returns
2. `event_study_agent_signals.csv/.md` — 10个信号的事件研究结果
3. `daily_agent_signal` — 日频信号表 (每个trade_date取abs(avg_score)最大的一条)
4. 信号推荐结论

### 硬验收
- entry_date > published_at (无未来函数)
- forward returns on entry_date计算正确
- 每个signal的sample_count >= 10 (过少则标记)
- T+5 win_rate / t_stat 计算正确
- daily_agent_signal 每个trade_date仅一条

---

## TODOs

- [ ] 1. 创建 news_signal_wide 视图

  **What to do**:
  - ATTACH `~/.vntrader/database.db` AS price_db
  - JOIN `news_analysis` (DS), `news_analysis` (QW), `agent_raw_news` (published_at), `dbbardata` (next trading day)
  - 字段: news_id, title, published_at, entry_date, ds_direction, ds_score, ds_confidence, ds_signal_strength, qw_direction, qw_score, qw_confidence, qw_signal_strength, avg_score, score_diff, direction_agree, consensus_direction
  - entry_date: published_at之后dbbardata中最早的datetime
  - 创建为VIEW或物化为TABLE (建议TABLE, 后续回测复用)

  **Recommended Agent Profile**: `unspecified-high` | **Skills**: `[]`

  **Acceptance**:
  - [ ] entry_date > published_at (所有行)
  - [ ] 所有news_id有对应entry_date

- [ ] 2. 计算 forward returns

  **What to do**:
  - 对每条news_signal_wide记录, 在entry_date当天收盘价基础上计算:
    - T+1 return: (close_{entry_date+1} - close_{entry_date}) / close_{entry_date}
    - T+3, T+5, T+10 同理
  - 使用LEAD窗口函数或Python pandas
  - 如果某个horizon没有足够行情, 记为NULL (不填0)

  **Recommended Agent Profile**: `unspecified-high` | **Skills**: `[]`

  **Acceptance**:
  - [ ] 每个horizon的return值合理 (非极端异常)
  - [ ] NULL处理正确 (数据不足时不填充)

- [ ] 3. 测试10个信号 + 输出event study

  **What to do**:
  - 对每个信号S1-S10:
    - 筛选满足条件的news_signal_wide行
    - 计算: sample_count, T+1/T+3/T+5/T+10 mean return, T+5 median return, T+5 win_rate, T+5 t_stat
  - t_stat = mean / (std / sqrt(n))
  - win_rate = count(return > 0) / count(return IS NOT NULL) 在对应horizon
  - 输出到 `results_v2/event_study_agent_signals.csv` 和 `.md`

  **Recommended Agent Profile**: `unspecified-high` | **Skills**: `[]`

  **Acceptance**:
  - [ ] 10个信号全部计算
  - [ ] t_stat公式正确
  - [ ] CSV和MD均生成

- [ ] 4. 创建 daily_agent_signal 表

  **What to do**:
  - 按entry_date分组, 取abs(avg_score)最大的那条news_signal_wide记录
  - 字段: trade_date, news_id, title, deepseek_score, qwen_score, avg_score, agent_direction, agent_signal_strength, source_signal
  - agent_direction: consensus_direction或avg_score符号决定
  - source_signal: 记录来源(DS+QW共识/单方)
  - 创建为TABLE在agent_news.db中

  **Recommended Agent Profile**: `unspecified-high` | **Skills**: `[]`

  **Acceptance**:
  - [ ] 每个trade_date仅一条
  - [ ] abs(avg_score)确实是当天最大

- [ ] 5. 信号推荐

  **What to do**:
  - 根据event study结果:
    - sample_count >= 30优先
    - T+3/T+5方向明确 (同正或同负)
    - win_rate > 50%
    - t_stat绝对值 > 0.5 (方向一致)
  - 推荐1-2个最值得回测的信号
  - 如果positive和negative信号都弱, 明确说明 "不建议进入策略回测"
  - 写入推荐结论到 `results_v2/signal_recommendation.md`

  **Recommended Agent Profile**: `unspecified-high` | **Skills**: `[]`

  **Acceptance**:
  - [ ] 推荐有理有据 (引用具体数值)
  - [ ] 弱信号明确说不进入回测
