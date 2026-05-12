from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from urllib.parse import urlparse

from myQuant.news_ingestion.contracts import (
    RawNewsItem,
    RecallStrength,
    RelationType,
    StockProfile,
)


GENERIC_MACRO_KEYWORDS = (
    "政策",
    "宏观",
    "货币政策",
    "财政政策",
    "稳增长",
    "降准",
    "降息",
    "监管",
    "地缘政治",
)


@dataclass
class MappedNews:
    raw_news_id: int
    vt_symbol: str
    symbol: str
    exchange: str
    relation_hint: RelationType
    mapping_method: str
    mapping_confidence: float
    keywords_matched: tuple[str, ...]
    available_at: datetime


@dataclass(frozen=True)
class _Match:
    relation_hint: RelationType
    mapping_method: str
    mapping_confidence: float
    keywords_matched: tuple[str, ...]


class RecallEngine:
    def __init__(self, profiles: dict[str, StockProfile]) -> None:
        self.profiles = profiles

    def filter_and_map(
        self,
        news_items: list[RawNewsItem],
        strength: RecallStrength,
    ) -> list[MappedNews]:
        unique_items = self._deduplicate(news_items)
        mapped_news: list[MappedNews] = []

        for raw_news_id, news_item in unique_items:
            available_at = self._available_at(news_item.published_at)
            if available_at is None:
                continue

            text = self._search_text(news_item)
            for profile in self.profiles.values():
                match = self._match_profile(profile, text, strength)
                if match is None:
                    continue
                mapped_news.append(
                    MappedNews(
                        raw_news_id=raw_news_id,
                        vt_symbol=profile.vt_symbol,
                        symbol=profile.symbol,
                        exchange=profile.exchange,
                        relation_hint=match.relation_hint,
                        mapping_method=match.mapping_method,
                        mapping_confidence=match.mapping_confidence,
                        keywords_matched=match.keywords_matched,
                        available_at=available_at,
                    )
                )

        return mapped_news

    def _deduplicate(self, news_items: list[RawNewsItem]) -> list[tuple[int, RawNewsItem]]:
        seen_source_ids: set[tuple[object, str]] = set()
        seen_hashes: set[tuple[object, str]] = set()
        unique_items: list[tuple[int, RawNewsItem]] = []

        for index, item in enumerate(news_items, start=1):
            source_id_key = (item.source, item.source_item_id)
            if item.source_item_id and source_id_key in seen_source_ids:
                continue
            if item.source_item_id:
                seen_source_ids.add(source_id_key)

            hash_key = (item.source, item.content_hash)
            if item.content_hash and hash_key in seen_hashes:
                continue
            if item.content_hash:
                seen_hashes.add(hash_key)

            unique_items.append((index, item))

        return self._near_deduplicate(unique_items)

    def _near_deduplicate(self, items: list[tuple[int, RawNewsItem]]) -> list[tuple[int, RawNewsItem]]:
        seen: set[tuple[str, date | None, str]] = set()
        result: list[tuple[int, RawNewsItem]] = []
        for index, item in items:
            key = (
                self._normalize_title(item.title)[:40].lower(),
                item.published_at.date() if isinstance(item.published_at, datetime) else item.published_at,
                urlparse(item.url).hostname or "",
            )
            if key in seen:
                continue
            seen.add(key)
            result.append((index, item))
        return result

    def _match_profile(
        self,
        profile: StockProfile,
        text: str,
        strength: RecallStrength,
    ) -> _Match | None:
        direct_keywords = tuple(keyword for keyword in (profile.name, profile.symbol) if keyword)
        direct_matches = self._matched_keywords(direct_keywords, text)
        if direct_matches:
            return _Match(
                relation_hint=RelationType.DIRECT_COMPANY,
                mapping_method="direct",
                mapping_confidence=1.0,
                keywords_matched=direct_matches,
            )

        alias_matches = self._matched_keywords(profile.aliases, text)
        if alias_matches:
            return _Match(
                relation_hint=RelationType.DIRECT_COMPANY,
                mapping_method="alias",
                mapping_confidence=0.9,
                keywords_matched=alias_matches,
            )

        if strength is RecallStrength.LOW:
            return None

        supply_chain_matches = self._matched_keywords(
            (*profile.products, *profile.upstream, *profile.downstream, *profile.risk_keywords),
            text,
        )
        if supply_chain_matches:
            relation_hint = RelationType.RISK_EVENT if self._matched_keywords(profile.risk_keywords, text) else RelationType.SUPPLY_CHAIN
            return _Match(
                relation_hint=relation_hint,
                mapping_method="keyword",
                mapping_confidence=0.7,
                keywords_matched=supply_chain_matches,
            )

        industry_matches = self._matched_keywords(profile.industry, text)
        if industry_matches:
            return _Match(
                relation_hint=RelationType.INDUSTRY,
                mapping_method="industry",
                mapping_confidence=0.6,
                keywords_matched=industry_matches,
            )

        if strength is not RecallStrength.HIGH:
            return None

        macro_matches = self._matched_keywords(profile.macro_factors, text)
        if not macro_matches:
            return None

        generic_matches = self._matched_keywords(GENERIC_MACRO_KEYWORDS, text)
        return _Match(
            relation_hint=RelationType.MACRO_POLICY,
            mapping_method="macro_policy",
            mapping_confidence=0.5,
            keywords_matched=tuple(dict.fromkeys((*macro_matches, *generic_matches))),
        )

    @staticmethod
    def _available_at(published_at: datetime | date | None) -> datetime | None:
        if published_at is None:
            return None
        if isinstance(published_at, datetime):
            return published_at + timedelta(minutes=5)
        return datetime.combine(published_at, time(15, 0, 0))

    @staticmethod
    def _search_text(news_item: RawNewsItem) -> str:
        return f"{news_item.title}\n{news_item.content}".casefold()

    @staticmethod
    def _matched_keywords(keywords: tuple[str, ...], text: str) -> tuple[str, ...]:
        return tuple(dict.fromkeys(keyword for keyword in keywords if keyword and keyword.casefold() in text))

    @staticmethod
    def _normalize_title(title: str) -> str:
        return "".join(title.casefold().split())
