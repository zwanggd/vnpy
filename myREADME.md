Mac + vn.py 4.3.0
Python 3.12
pandas 固定 2.2.3
vn.py 数据库先用 SQLite
TuShare datafeed 可下载日线
A股交易所代码：SSE/SZSE/BSE

## OpenCode 回测约定

1. 所有回测、数据检查和 vn.py 相关脚本运行都必须使用 `vnpy43` conda 环境，例如：`conda run -n vnpy43 python <script.py>`。
2. 回测脚本统一保存在 `backtests/scripts/`，不要写临时脚本后删除；后续新策略、新参数、新批量任务都在该目录下新增或复用脚本。
3. 每次回测结果统一保存为 Markdown 到 `backtests/results/`，文件名建议使用 `YYYY-MM-DD_<strategy>_<params>_<scope>.md`，内容至少包含回测设置、结果表格和简短结论。
4. 回测结果中的设置必须写清楚：策略类、参数、数据库/数据源、标的范围、时间范围、周期、手续费、滑点、合约乘数/size、pricetick、初始资金。
5. 当前数据库默认位置为 `~/.vntrader/database.db`，当前本地日线数据来自 SQLite。
