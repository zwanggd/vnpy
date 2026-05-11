from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from pathlib import Path

from myQuant.news_ingestion.contracts import StockProfile, generate_vt_symbol
from myQuant.news_ingestion.storage import AgentNewsSqliteRepository


MARKET_DB_SYMBOL_QUERY = (
    "SELECT symbol, exchange FROM dbbaroverview WHERE interval='d' ORDER BY symbol;"
)

DEFAULT_STOCK_PROFILES: dict[str, StockProfile] = {
    "000333.SZSE": StockProfile(
        vt_symbol="000333.SZSE",
        name="美的集团",
        aliases=("美的", "Midea", "000333"),
        industry=("家电", "智能制造", "机器人"),
        products=("空调", "家电", "工业机器人"),
        upstream=("铜", "铝", "芯片", "压缩机"),
        downstream=("地产", "消费电子", "家电渠道"),
        macro_factors=("地产政策", "消费刺激", "出口汇率"),
        risk_keywords=("原材料涨价", "海外需求下滑", "汇率波动"),
    ),
    "002475.SZSE": StockProfile(
        vt_symbol="002475.SZSE",
        name="立讯精密",
        aliases=("立讯", "Luxshare", "002475"),
        industry=("消费电子", "苹果产业链", "连接器"),
        products=("连接器", "AirPods", "精密制造"),
        upstream=("铜", "电子元件", "芯片"),
        downstream=("苹果", "消费电子", "汽车电子"),
        macro_factors=("苹果销量", "消费电子周期", "出口管制"),
        risk_keywords=("客户集中", "苹果砍单", "毛利率下滑"),
    ),
    "002594.SZSE": StockProfile(
        vt_symbol="002594.SZSE",
        name="比亚迪",
        aliases=("BYD", "比亚迪股份", "002594"),
        industry=("新能源汽车", "动力电池", "汽车"),
        products=("新能源汽车", "刀片电池", "动力电池"),
        upstream=("锂矿", "碳酸锂", "芯片"),
        downstream=("汽车销售", "出口", "储能"),
        macro_factors=("新能源补贴", "双碳", "欧洲电动车政策"),
        risk_keywords=("价格战", "产能过剩", "出口关税"),
    ),
    "300750.SZSE": StockProfile(
        vt_symbol="300750.SZSE",
        name="宁德时代",
        aliases=("宁德时代", "CATL", "300750"),
        industry=("新能源", "动力电池", "储能", "锂电池"),
        products=("动力电池", "储能电池", "麒麟电池"),
        upstream=("碳酸锂", "锂矿", "正极材料", "负极材料", "隔膜", "电解液"),
        downstream=("新能源汽车", "特斯拉", "比亚迪", "蔚来", "理想", "小鹏", "储能电站"),
        macro_factors=("新能源补贴", "双碳", "出口管制", "欧洲电动车政策"),
        risk_keywords=("价格战", "产能过剩", "毛利率下滑", "电池安全", "客户流失"),
    ),
    "600036.SSE": StockProfile(
        vt_symbol="600036.SSE",
        name="招商银行",
        aliases=("招行", "CMB", "600036"),
        industry=("银行", "零售金融"),
        products=("零售贷款", "信用卡", "财富管理"),
        upstream=("资金成本", "存款"),
        downstream=("居民消费", "房地产", "企业信贷"),
        macro_factors=("利率政策", "房地产政策", "存款利率"),
        risk_keywords=("不良贷款", "净息差收窄", "地产风险"),
    ),
    "600276.SSE": StockProfile(
        vt_symbol="600276.SSE",
        name="恒瑞医药",
        aliases=("恒瑞", "Hengrui", "600276"),
        industry=("医药", "创新药"),
        products=("抗肿瘤药", "麻醉药", "创新药"),
        upstream=("原料药", "临床试验"),
        downstream=("医院", "医保", "药店"),
        macro_factors=("医保谈判", "集采", "药监审批"),
        risk_keywords=("集采降价", "研发失败", "专利到期"),
    ),
    "600309.SSE": StockProfile(
        vt_symbol="600309.SSE",
        name="万华化学",
        aliases=("万华", "Wanhua", "600309"),
        industry=("化工", "聚氨酯", "MDI"),
        products=("MDI", "TDI", "聚氨酯", "石化材料"),
        upstream=("煤炭", "原油", "天然气"),
        downstream=("建筑", "家电", "汽车", "鞋服"),
        macro_factors=("地产政策", "油价", "环保限产"),
        risk_keywords=("化工品价格下跌", "需求下滑", "安全事故"),
    ),
    "600519.SSE": StockProfile(
        vt_symbol="600519.SSE",
        name="贵州茅台",
        aliases=("茅台", "Kweichow Moutai", "600519"),
        industry=("白酒", "高端消费"),
        products=("飞天茅台", "茅台酒"),
        upstream=("高粱", "包材"),
        downstream=("经销商", "消费", "宴席"),
        macro_factors=("消费政策", "反腐", "居民收入"),
        risk_keywords=("批价下跌", "渠道库存", "消费降级"),
    ),
    "601318.SSE": StockProfile(
        vt_symbol="601318.SSE",
        name="中国平安",
        aliases=("平安", "Ping An", "601318"),
        industry=("保险", "金融"),
        products=("寿险", "财险", "银行", "资管"),
        upstream=("利率", "资本市场"),
        downstream=("居民保障", "企业保险"),
        macro_factors=("利率政策", "资本市场", "房地产"),
        risk_keywords=("投资亏损", "保费下滑", "地产敞口"),
    ),
    "601899.SSE": StockProfile(
        vt_symbol="601899.SSE",
        name="紫金矿业",
        aliases=("紫金", "Zijin", "601899"),
        industry=("有色金属", "黄金", "铜矿"),
        products=("黄金", "铜", "锂", "锌"),
        upstream=("矿山", "能源", "设备"),
        downstream=("铜需求", "新能源", "贵金属投资"),
        macro_factors=("金价", "铜价", "美元", "地缘政治"),
        risk_keywords=("矿山安全", "资源国政策", "金属价格下跌"),
    ),
}


def discover_vt_symbols_from_market_db(market_db_path: str | Path) -> list[str]:
    with sqlite3.connect(f"file:{Path(market_db_path).expanduser()}?mode=ro", uri=True) as connection:
        rows = connection.execute(MARKET_DB_SYMBOL_QUERY).fetchall()
    return [generate_vt_symbol(symbol, exchange) for symbol, exchange in rows]


def get_stock_profile(
    vt_symbol: str,
    profiles: Mapping[str, StockProfile] = DEFAULT_STOCK_PROFILES,
) -> StockProfile:
    try:
        return profiles[vt_symbol]
    except KeyError as exc:
        raise ValueError(f"Missing stock profile for {vt_symbol}") from exc


def persist_discovered_stock_profiles(
    repository: AgentNewsSqliteRepository,
    market_db_path: str | Path,
    profiles: Mapping[str, StockProfile] = DEFAULT_STOCK_PROFILES,
) -> list[str]:
    vt_symbols = discover_vt_symbols_from_market_db(market_db_path)
    for vt_symbol in vt_symbols:
        repository.save_stock_profile(get_stock_profile(vt_symbol, profiles))
    return vt_symbols
