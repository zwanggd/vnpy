"""Offline backfill pipeline orchestrating source fetch → recall → LLM evaluation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from collections.abc import Callable
from typing import Any

from myQuant.news_ingestion.contracts import (
    NewsQuery,
    RawNewsItem,
    RecallStrength,
    Source,
    Status,
    StockProfile,
)
from myQuant.news_ingestion.profiles import get_stock_profile
from myQuant.news_ingestion.recall import RecallEngine
from myQuant.news_ingestion.sources.base import BaseNewsSource, SourceFetchResult
from myQuant.news_ingestion.storage import AgentNewsSqliteRepository


@dataclass
class PipelineResult:
    """Summary returned by BackfillPipeline.run()."""

    run_id: str
    raw_count: int = 0
    mapped_count: int = 0
    signal_count: int = 0
    errors: list[str] = field(default_factory=list)
    llm_run_count: int = 0
    invalid_signals: int = 0
    signals: list[dict] = field(default_factory=list)
    source_coverage: dict[str, dict] = field(default_factory=dict)


SourceFactory = Callable[[Source], BaseNewsSource]


def _default_source_factory(source: Source) -> BaseNewsSource:
    """Create source adapter instances for live runs."""
    from myQuant.news_ingestion.sources.cninfo import CninfoAnnouncementSource
    from myQuant.news_ingestion.sources.cls import ClsTelegraphSource
    from myQuant.news_ingestion.sources.eastmoney import EastmoneyNewsSource

    if source == Source.CNINFO:
        return CninfoAnnouncementSource()
    if source == Source.CLS_TELEGRAPH:
        return ClsTelegraphSource()
    if source == Source.EASTMONEY:
        return EastmoneyNewsSource()
    raise ValueError(f"Unknown source: {source}")


class _NoOpSource(BaseNewsSource):
    """Fixture source returning empty results for dry-run mode."""

    source = Source.CNINFO

    def fetch(self, query: NewsQuery) -> SourceFetchResult:
        return SourceFetchResult(
            source=self.source,
            status=Status.SUCCESS,
            items=(),
            coverage_status="dry_run",
        )


def _resolve_dry_run_source(source: Source) -> BaseNewsSource:
    inst = _NoOpSource()
    inst.source = source
    return inst


class BackfillPipeline:
    """Orchestrates the full backfill pipeline for one run window."""

    def __init__(
        self,
        repo: AgentNewsSqliteRepository,
        source_factory: SourceFactory | None = None,
        recall_engine: RecallEngine | None = None,
        evaluator: Any = None,
        dry_run: bool = False,
    ) -> None:
        self.repo = repo
        self._source_factory = source_factory or _default_source_factory
        self._recall_engine = recall_engine
        self._evaluator = evaluator
        self.dry_run = dry_run

    def _resolve_run_id(
        self,
        *,
        resume: bool,
        start: date,
        end: date,
        symbols: list[str],
        sources: tuple[Source, ...],
    ) -> str:
        """Return an existing run_id if resume=True and a matching SUCCESS run is found."""
        if resume:
            existing = self.repo.find_backfill_run_id(
                start=start.isoformat(),
                end=end.isoformat(),
                symbols=symbols,
                sources=tuple(s.value for s in sources),
            )
            if existing:
                return existing
        return f"backfill-{uuid.uuid4().hex[:12]}"

    def run(
        self,
        *,
        start: date,
        end: date,
        symbols: list[str],
        sources: tuple[Source, ...],
        recall_strength: RecallStrength,
        max_llm_items: int = 0,
        skip_llm: bool = False,
        resume: bool = False,
    ) -> PipelineResult:
        """Execute the pipeline and return a summary."""
        run_id = self._resolve_run_id(resume=resume, start=start, end=end, symbols=symbols, sources=sources)
        errors: list[str] = []

        # -- 1. Init schema & create run record --------------------------------
        self.repo.initialize_schema()
        self.repo.save_backfill_run(
            run_id=run_id,
            started_at=datetime.now(),
            status=Status.PENDING,
            config={
                "start": start.isoformat(),
                "end": end.isoformat(),
                "symbols": symbols,
                "sources": [s.value for s in sources],
                "recall_strength": recall_strength.value,
                "dry_run": self.dry_run,
                "skip_llm": skip_llm,
            },
        )

        # -- 2. Build stock profiles -------------------------------------------
        profiles: dict[str, StockProfile] = {}
        for vt_symbol in symbols:
            try:
                profiles[vt_symbol] = get_stock_profile(vt_symbol)
            except ValueError:
                errors.append(f"Missing profile for {vt_symbol}")

        # -- 3. Fetch from each source per symbol ------------------------------
        all_items: list[RawNewsItem] = []
        source_factory = _resolve_dry_run_source if self.dry_run else self._source_factory
        source_coverage: dict[str, dict] = {}

        for source_enum in sources:
            source_adapter = source_factory(source_enum)
            src_items = 0
            src_errors = 0
            src_status = "full"
            for vt_symbol in symbols:
                profile = profiles.get(vt_symbol)
                if profile is None:
                    continue
                query = NewsQuery(
                    vt_symbol=vt_symbol,
                    start=start,
                    end=end,
                    sources=(source_enum,),
                    recall_strength=recall_strength,
                )
                try:
                    result = source_adapter.fetch(query)
                except Exception as exc:
                    errors.append(f"Source fetch error [{source_enum.value}][{vt_symbol}]: {exc}")
                    src_errors += 1
                    self.repo.save_fetch_attempt(
                        run_id=run_id,
                        source=source_enum,
                        vt_symbol=vt_symbol,
                        status=Status.FAILED,
                        error=str(exc),
                        started_at=datetime.now(),
                        finished_at=datetime.now(),
                    )
                    continue

                self.repo.save_fetch_attempt(
                    run_id=run_id,
                    source=source_enum,
                    vt_symbol=vt_symbol,
                    window_start=datetime.combine(start, datetime.min.time()),
                    window_end=datetime.combine(end, datetime.min.time()),
                    status=result.status,
                    error=result.error,
                    items_found=len(result.items),
                    started_at=datetime.now(),
                    finished_at=datetime.now(),
                )

                for item in result.items:
                    if resume and self.repo.is_raw_news_saved(
                        source_item_id=item.source_item_id or "",
                        source=item.source.value,
                    ):
                        continue
                    self.repo.save_raw_news(item)
                    all_items.append(item)
                src_items += len(result.items)
                if getattr(result, "coverage_status", "full") == "partial":
                    src_status = "partial"

            source_coverage[source_enum.value] = {
                "items": src_items,
                "errors": src_errors,
                "coverage_status": src_status,
            }

        raw_count = len(all_items)

        # -- 4. Save raw news & build DB id maps -------------------------------
        db_id_for_position: dict[int, int] = {}
        db_id_to_item: dict[int, RawNewsItem] = {}
        for i, item in enumerate(all_items, start=1):
            db_id = self.repo.save_raw_news(item)
            db_id_for_position[i] = db_id
            db_id_to_item[db_id] = item

        # -- 5. Recall / filter / deduplicate ----------------------------------
        engine = self._recall_engine or RecallEngine(profiles)
        mapped_news = engine.filter_and_map(all_items, recall_strength)

        # Remap raw_news_id from list position (1-based) → DB id
        for mapping in mapped_news:
            mapping.raw_news_id = db_id_for_position.get(mapping.raw_news_id, mapping.raw_news_id)

        # Persist mapped_news to DB
        for mapping in mapped_news:
            self.repo.save_mapped_news(mapping)

        mapped_count = len(mapped_news)

        # -- 6. LLM evaluation -------------------------------------------------
        signal_count = 0
        evaluated = 0
        signals_data: list[dict] = []
        if self.dry_run or skip_llm or self._evaluator is None:
            pass  # No LLM in dry-run or skip mode
        else:
            for mapping in mapped_news:
                if max_llm_items > 0 and evaluated >= max_llm_items:
                    break
                news_item = db_id_to_item.get(mapping.raw_news_id)
                if news_item is None:
                    errors.append(
                        f"No raw news item found for DB id {mapping.raw_news_id}"
                        f" [{mapping.vt_symbol}]"
                    )
                    continue
                try:
                    llm_run, llm_output, signal = self._evaluator.evaluate(mapping, news_item)
                    llm_run.run_id = run_id
                    run_db_id = self.repo.save_llm_run(llm_run)
                    llm_output.llm_run_id = run_db_id
                    self.repo.save_llm_output(llm_output)
                    evaluated += 1
                    # Persist earlier retry attempts (all but the final one already saved)
                    attempts = getattr(self._evaluator, "attempt_records", [])
                    if len(attempts) > 1:
                        for prev_run, prev_output in attempts[:-1]:
                            prev_run.run_id = run_id
                            prev_run.input_hash = f"{prev_run.input_hash}-retry-{prev_run.run_id}"
                            prev_db_id = self.repo.save_llm_run(prev_run)
                            prev_output.llm_run_id = prev_db_id
                            self.repo.save_llm_output(prev_output)
                    if signal is not None:
                        signal.llm_run_id = run_db_id
                        self.repo.save_signal(signal)
                        signal_count += 1
                        signals_data.append({
                            "vt_symbol": signal.vt_symbol,
                            "event": signal.event,
                            "impact_direction": signal.impact_direction.value,
                            "impact_strength": signal.impact_strength,
                            "confidence": signal.confidence,
                        })
                except Exception as exc:
                    errors.append(f"LLM error: {exc}")

            self.repo.save_fetch_attempt(
                run_id=run_id,
                source="llm",
                status=Status.SUCCESS,
                items_found=evaluated,
                items_saved=signal_count,
            )

        invalid_signals = evaluated - signal_count

        # -- 7. Finalize run ---------------------------------------------------
        self.repo.save_backfill_run(
            run_id=run_id,
            finished_at=datetime.now(),
            status=Status.FAILED if errors else Status.SUCCESS,
            summary={
                "raw_count": raw_count,
                "mapped_count": mapped_count,
                "signal_count": signal_count,
                "error_count": len(errors),
            },
            error="; ".join(errors) if errors else "",
        )

        return PipelineResult(
            run_id=run_id,
            raw_count=raw_count,
            mapped_count=mapped_count,
            signal_count=signal_count,
            errors=errors,
            llm_run_count=evaluated,
            invalid_signals=invalid_signals,
            signals=signals_data,
            source_coverage=source_coverage,
        )
