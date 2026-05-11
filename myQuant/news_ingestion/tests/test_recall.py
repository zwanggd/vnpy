from datetime import date, datetime, time, timedelta

from myQuant.news_ingestion import RawNewsItem, RecallStrength, Source, SourceCategory, StockProfile
from myQuant.news_ingestion.recall import RecallEngine


def stock_profiles() -> dict[str, StockProfile]:
    profiles = [
        StockProfile(
            vt_symbol="300750.SZSE",
            name="宁德时代",
            aliases=("CATL", "300750"),
            industry=("新能源", "锂电池"),
            products=("动力电池", "储能电池"),
            upstream=("碳酸锂",),
            downstream=("新能源汽车",),
            macro_factors=("新能源补贴",),
            risk_keywords=("电池安全",),
        ),
        StockProfile(
            vt_symbol="600519.SSE",
            name="贵州茅台",
            aliases=("茅台", "600519"),
            industry=("白酒", "高端消费"),
            products=("飞天茅台",),
            upstream=("高粱",),
            downstream=("经销商",),
            macro_factors=("消费政策",),
            risk_keywords=("批价下跌",),
        ),
        StockProfile(
            vt_symbol="601318.SSE",
            name="中国平安",
            aliases=("平安", "601318"),
            industry=("保险", "金融"),
            products=("寿险", "财险"),
            upstream=("利率",),
            downstream=("居民保障",),
            macro_factors=("利率政策", "资本市场"),
            risk_keywords=("地产敞口",),
        ),
    ]
    return {profile.vt_symbol: profile for profile in profiles}


def news_item(
    source_item_id: str,
    title: str,
    content: str = "",
    published_at: datetime | date | None = datetime(2026, 5, 8, 10, 0),
    content_hash: str | None = None,
    url: str = "https://news.example.test/a.html",
) -> RawNewsItem:
    return RawNewsItem(
        source=Source.EASTMONEY,
        source_category=SourceCategory.FINANCIAL_NEWS,
        source_item_id=source_item_id,
        url=url,
        title=title,
        content=content,
        published_at=published_at,
        fetched_at=datetime(2026, 5, 8, 10, 30),
        content_hash=content_hash or source_item_id,
    )


def candidate_ids(mapped_news) -> set[int]:
    return {mapped.raw_news_id for mapped in mapped_news}


def test_recall_strength_levels() -> None:
    engine = RecallEngine(stock_profiles())
    fixtures = [
        news_item("direct-name", "宁德时代发布储能新品"),
        news_item("alias", "CATL欧洲工厂进展顺利"),
        news_item("product", "动力电池装机量持续增长"),
        news_item("industry", "保险行业保费收入改善"),
        news_item("macro-factor", "资本市场波动加剧"),
        news_item("generic-policy", "稳增长政策提振资本市场信心"),
        news_item("unrelated", "电影春节档票房创新高"),
    ]

    low = engine.filter_and_map(fixtures, RecallStrength.LOW)
    medium = engine.filter_and_map(fixtures, RecallStrength.MEDIUM)
    high = engine.filter_and_map(fixtures, RecallStrength.HIGH)

    assert candidate_ids(low) == {1, 2}
    assert candidate_ids(medium) == {1, 2, 3, 4}
    assert candidate_ids(high) == {1, 2, 3, 4, 5, 6}
    assert {candidate.vt_symbol for candidate in high if candidate.raw_news_id == 6} == {"601318.SSE"}


def test_mapping_confidence_and_symbol_fields() -> None:
    engine = RecallEngine(stock_profiles())
    mapped = engine.filter_and_map(
        [
            news_item("direct-name", "宁德时代发布储能新品"),
            news_item("alias", "CATL欧洲工厂进展顺利"),
            news_item("product", "动力电池装机量持续增长"),
            news_item("industry", "保险行业保费收入改善"),
            news_item("macro-factor", "资本市场波动加剧"),
        ],
        RecallStrength.HIGH,
    )

    by_raw_id = {candidate.raw_news_id: candidate for candidate in mapped}

    assert by_raw_id[1].mapping_confidence == 1.0
    assert by_raw_id[1].mapping_method == "direct"
    assert by_raw_id[1].symbol == "300750"
    assert by_raw_id[1].exchange == "SZSE"
    assert by_raw_id[2].mapping_confidence == 0.9
    assert by_raw_id[3].mapping_confidence == 0.7
    assert by_raw_id[4].mapping_confidence == 0.6
    assert by_raw_id[5].mapping_confidence == 0.5


def test_dedup_prevents_duplicate_llm_candidates() -> None:
    engine = RecallEngine(stock_profiles())
    duplicate_a = news_item(
        "same-source-id",
        "宁德时代发布储能新品",
        content_hash="same-hash",
    )
    duplicate_b = news_item(
        "same-source-id",
        "宁德时代发布储能新品重复稿",
        content_hash="different-hash",
    )
    duplicate_c = news_item(
        "different-source-id",
        "宁德时代发布储能新品再次重复",
        content_hash="same-hash",
    )

    mapped = engine.filter_and_map(
        [duplicate_a, duplicate_b, duplicate_c],
        RecallStrength.LOW,
    )

    assert len(mapped) == 1
    assert mapped[0].raw_news_id == 1


def test_available_at_uses_publish_time_not_fetch_time() -> None:
    engine = RecallEngine(stock_profiles())
    timed_news = news_item(
        "timed",
        "宁德时代发布储能新品",
        published_at=datetime(2026, 5, 8, 14, 58),
    )

    mapped = engine.filter_and_map([timed_news], RecallStrength.LOW)

    assert mapped[0].available_at == datetime(2026, 5, 8, 15, 3)
    assert mapped[0].available_at == timed_news.published_at + timedelta(minutes=5)
    assert mapped[0].available_at != timed_news.fetched_at


def test_date_only_publish_time_available_at_is_market_close() -> None:
    engine = RecallEngine(stock_profiles())
    date_only_news = news_item(
        "date-only",
        "宁德时代发布储能新品",
        published_at=date(2026, 5, 8),
    )

    mapped = engine.filter_and_map([date_only_news], RecallStrength.LOW)

    assert mapped[0].available_at == datetime.combine(date(2026, 5, 8), time(15, 0, 0))


def test_unknown_publish_time_does_not_create_mapped_news() -> None:
    engine = RecallEngine(stock_profiles())
    unknown_time_news = news_item(
        "unknown-time",
        "宁德时代发布储能新品",
        published_at=None,
    )

    mapped = engine.filter_and_map([unknown_time_news], RecallStrength.LOW)

    assert mapped == []
