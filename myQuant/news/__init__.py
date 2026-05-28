"""News processing: sources, ingestion, cleaning, dedup."""
from myQuant.news_ingestion.sources import (
    BaseNewsSource,
    PoliteHttpClient,
    SourceFetchResult,
)
from myQuant.news_ingestion.sources.cls import ClsTelegraphSource
from myQuant.news_ingestion.sources.cninfo import CninfoAnnouncementSource
from myQuant.news_ingestion.sources.eastmoney import EastmoneyNewsSource
from myQuant.news_ingestion.recall.engine import MappedNews, RecallEngine

__all__ = [
    "BaseNewsSource",
    "PoliteHttpClient",
    "SourceFetchResult",
    "ClsTelegraphSource",
    "CninfoAnnouncementSource",
    "EastmoneyNewsSource",
    "MappedNews",
    "RecallEngine",
]
