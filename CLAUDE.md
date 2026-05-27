# CLAUDE.md — vnpy/myQuant Agent Trading

> 所有任务默认遵守。非关键工作可自行判断，关键工作和破坏性操作必须走完流程。

## Rule 1 — Think Before Coding
- 明确假设，不确定就问，别猜。
- 歧义时列出多种解读，让用户选。
- 有更简单的方案就提出来，不要默默实现复杂的。
- 卡住就说卡住了。讲清楚到底哪里不懂。

## Rule 2 — Simplicity First
- 最少代码解决问题，不加推测性功能。
- 不实现用户没要的东西。单次使用的代码不抽象。
- 自测：一个资深工程师看了会说「搞复杂了」？是就简化。

## Rule 3 — Surgical Changes
- 只碰你要改的。清理也只清你自己造成的。
- 不"顺手优化"相邻代码、注释、格式。
- 不重构没坏的东西。风格对齐现有代码。

## Rule 4 — Goal-Driven Execution
- 先定成功标准，再循环直到达标。
- 不是按步骤机械执行，而是盯着目标迭代。
- 强成功标准 = 能独立判断是否完成，不需要用户来验。

## Rule 5 — Agent for Judgment, Code for Determinism
- 用 AI 做：分类、起草、总结、提取、架构决策。
- 用代码/工具做：路由、重试、确定性变换、批量操作。
- 能用 `grep`/`python` 一行解决的事，不要上 agent。

## Rule 6 — Context Budget Awareness
- 主会话上下文有限。并行工作用 `task(run_in_background=true)`。
- 探索类工作优先丢给 `explore`/`librarian` agent。

## Rule 7 — Surface Conflicts, Don't Average
- 两个模式矛盾时，选一个（偏更新的/更经过验证的）。
- 解释为什么选它，标记另一个待清理。
- 不糅合矛盾的方案。

## Rule 8 — Read Before You Write
- 加代码前，先读：exports、直接调用方、共享工具函数。
- "看起来应该不相关"很危险。不确定为什么代码是当前结构，就问。

## Rule 9 — Tests Verify Intent
- 测试要编码 WHY（业务逻辑为什么这样），不只是 WHAT（代码做了什么）。
- 业务逻辑变了但测试不挂 → 测试写错了。

## Rule 10 — Checkpoint After Every Significant Step
- 每完成一个逻辑单元：总结做了什么、验证了什么、还剩什么。
- 用 todowrite 跟踪进度，不要让用户猜你在干嘛。
- 如果你自己都说不清当前状态 → 停下来理清楚。

## Rule 11 — Match the Codebase, Even If You Disagree
- 内部代码：一致性 > 个人品味。
- 如果你真心认为某条约定有害，提出来讨论。不要默默另搞一套。

## Rule 12 — Fail Loud
- "完成"但悄悄跳过了什么 → 不算完成。
- "测试通过"但跳过了一些 → 不算通过。
- 默认暴露不确定性，不要藏。

---

## Project-Specific Constraints

### Database Safety
- **Iron Law**: 任何 DELETE/DROP/TRUNCATE 必须先 (1) 备份 → (2) SELECT COUNT 预览 → (3) 用户确认。
- 生产库路径: `~/.vntrader/agent_news*.db`。参考 `safe-db-operations` skill。
- 备份机制: `AgentNewsSqliteRepository` 构造时自动备份（10 分钟限流），备份存 `~/.vntrader/backups/`。

### Environment
- Conda env: `vnpy43`, Python 3.12
- 命令前缀: `PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43`
- pandas 固定 2.2.3

### Codebase Boundaries
- `vnpy/` — 上游框架，不改。
- `myQuant/` — 我们的代码。
- `.sisyphus/plans/` — 实施计划，实施前先看。

### Agent Delegation
- 多步骤任务 → 先写计划（`.sisyphus/plans/`），再委托。
- 探索类 → `explore`/`librarian` agent，后台并行。
- 实现类 → `unspecified-high` category + 相关 skills。
- 架构决策 → `oracle` agent。
