"""TDD tests for BackfillPipeline and CLI."""

from __future__ import annotations

import os
import subprocess
from datetime import date, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from myQuant.news_ingestion import Source, RecallStrength, RelationType
from myQuant.news_ingestion.contracts import (
    RawNewsItem,
    SourceCategory,
    StockProfile,
)
from myQuant.news_ingestion.sources.base import BaseNewsSource, SourceFetchResult
from myQuant.news_ingestion.recall.engine import RecallEngine, MappedNews
from myQuant.news_ingestion.storage import AgentNewsSqliteRepository
from myQuant.news_ingestion.pipeline import BackfillPipeline, PipelineResult

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CLI_SCRIPT = str(PROJECT_ROOT / "backtests" / "scripts" / "run_agent_news_backfill.py")

CONDA_ENV = os.environ.copy()
CONDA_ENV.setdefault("PYTHONPATH", str(PROJECT_ROOT))


def test_pipeline_import() -> None:
    assert BackfillPipeline is not None
    assert PipelineResult is not None


def test_cli_help() -> None:
    result = subprocess.run(
        [
            "conda", "run", "-n", "vnpy43", "python",
            CLI_SCRIPT, "--help",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(PROJECT_ROOT),
        env=CONDA_ENV,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    assert "--start" in result.stdout
    assert "--end" in result.stdout
    assert "--symbols" in result.stdout
    assert "--recall-strength" in result.stdout
    assert "--dry-run" in result.stdout
    assert "--skip-llm" in result.stdout


def test_pipeline_dry_run() -> None:
    """Dry-run pipeline with temp DB produces PipelineResult with run_id and no errors."""
    with NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        repo = AgentNewsSqliteRepository(db_path=db_path)
        repo.initialize_schema()

        pipeline = BackfillPipeline(
            repo=repo,
            dry_run=True,
        )

        result = pipeline.run(
            start=date(2024, 1, 1),
            end=date(2024, 1, 5),
            symbols=["300750.SZSE"],
            sources=(Source.CNINFO,),
            recall_strength=RecallStrength.LOW,
            skip_llm=True,
        )

        assert isinstance(result, PipelineResult)
        assert result.run_id
        assert result.raw_count >= 0
        assert result.signal_count == 0  # dry-run skips LLM
        assert len(result.errors) == 0

    finally:
        Path(db_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Helpers for evaluator wiring tests
# ---------------------------------------------------------------------------


class FakeEvaluator:
    """Tracks calls and returns a fixed result for pipeline wiring tests."""

    def __init__(self) -> None:
        self.calls: list[tuple[MappedNews, RawNewsItem]] = []
        self.attempt_records: list = []

    def evaluate(
        self,
        mapped_news: MappedNews,
        news_item: RawNewsItem,
    ) -> tuple[Any, Any, Any]:
        self.calls.append((mapped_news, news_item))
        from myQuant.news_ingestion.contracts import (
            LLMOutputRecord,
            LLMRunRecord,
            Status,
        )
        import uuid
        # Record a failed attempt first
        failed_run = LLMRunRecord(
            run_id=f"fail-{uuid.uuid4().hex[:8]}",
            raw_news_id=mapped_news.raw_news_id,
            provider="test",
            model="test-model",
            prompt_version="v1",
            schema_version="v1",
            input_hash="abc123",
            status=Status.FAILED,
            error="Invalid JSON",
        )
        failed_output = LLMOutputRecord(
            llm_run_id=0,
            raw_response="{bad json}",
            validation_status=Status.FAILED,
            validation_errors=("invalid JSON",),
        )
        self.attempt_records.append((failed_run, failed_output))
        # Then the success attempt
        run = LLMRunRecord(
            run_id=f"test-{uuid.uuid4().hex[:8]}",
            raw_news_id=mapped_news.raw_news_id,
            provider="test",
            model="test-model",
            prompt_version="v1",
            schema_version="v1",
            input_hash="abc123",
            status=Status.SUCCESS,
        )
        output = LLMOutputRecord(
            llm_run_id=0,
            raw_response="{}",
            validation_status=Status.SUCCESS,
        )
        self.attempt_records.append((run, output))
        return run, output, None  # Return None signal to count invalid_signals


class FakeEvaluatorWithRetries:
    """Evaluator that records 2 attempts (1 failed, 1 success) for retry persistence testing."""

    def __init__(self) -> None:
        self.calls: list[tuple[MappedNews, RawNewsItem]] = []
        self.attempt_records: list = []

    def evaluate(
        self,
        mapped_news: MappedNews,
        news_item: RawNewsItem,
    ) -> tuple[Any, Any, Any]:
        from myQuant.news_ingestion.contracts import (
            LLMOutputRecord,
            LLMRunRecord,
            Status,
        )
        import uuid
        self.calls.append((mapped_news, news_item))
        # First failed attempt
        failed_run = LLMRunRecord(
            run_id=f"fail-{uuid.uuid4().hex[:8]}",
            raw_news_id=mapped_news.raw_news_id,
            provider="test",
            model="test-model",
            prompt_version="v1",
            schema_version="v1",
            input_hash="abc123",
            status=Status.FAILED,
            error="Invalid JSON",
        )
        failed_output = LLMOutputRecord(
            llm_run_id=0,
            raw_response="{bad}",
            validation_status=Status.FAILED,
            validation_errors=("invalid JSON",),
        )
        self.attempt_records.append((failed_run, failed_output))
        # Second success attempt
        run = LLMRunRecord(
            run_id=f"ok-{uuid.uuid4().hex[:8]}",
            raw_news_id=mapped_news.raw_news_id,
            provider="test",
            model="test-model",
            prompt_version="v1",
            schema_version="v1",
            input_hash="abc123",
            status=Status.SUCCESS,
        )
        output = LLMOutputRecord(
            llm_run_id=0,
            raw_response="{}",
            validation_status=Status.SUCCESS,
        )
        self.attempt_records.append((run, output))
        return run, output, None


def _make_fake_news_item(title: str = "测试新闻") -> RawNewsItem:
    return RawNewsItem(
        source=Source.CNINFO,
        source_category=SourceCategory.ANNOUNCEMENT,
        title=title,
        content="测试内容",
        content_hash=f"hash_{title}",
        published_at=datetime(2024, 1, 2, 10, 0),
    )


class _FakeSource(BaseNewsSource):
    """Returns a single fake news item."""

    source = Source.CNINFO

    def fetch(self, query):  # type: ignore[override]
        from myQuant.news_ingestion.contracts import Status as ContractStatus
        return SourceFetchResult(
            source=self.source,
            status=ContractStatus.SUCCESS,
            items=(_make_fake_news_item(),),
            coverage_status="full",
        )


def _fake_source_factory(source: Source) -> BaseNewsSource:
    inst = _FakeSource()
    inst.source = source
    return inst


def _stock_profile(vt_symbol: str) -> StockProfile:
    return StockProfile(
        vt_symbol=vt_symbol,
        name="测试股票",
        aliases=("测试",),
    )


def _build_recall_engine() -> RecallEngine:
    profile = _stock_profile("300750.SZSE")
    return RecallEngine({profile.vt_symbol: profile})


def test_pipeline_evaluator_wiring() -> None:
    """Evaluator is called when passed and skip_llm=False."""
    with NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        repo = AgentNewsSqliteRepository(db_path=db_path)
        fake_eval = FakeEvaluator()
        recall = _build_recall_engine()

        pipeline = BackfillPipeline(
            repo=repo,
            source_factory=_fake_source_factory,
            recall_engine=recall,
            evaluator=fake_eval,
            dry_run=False,
        )

        result = pipeline.run(
            start=date(2024, 1, 1),
            end=date(2024, 1, 5),
            symbols=["300750.SZSE"],
            sources=(Source.CNINFO,),
            recall_strength=RecallStrength.LOW,
            skip_llm=False,
        )

        assert len(fake_eval.calls) > 0, "FakeEvaluator should have been called"
        assert result.llm_run_count > 0
        assert result.invalid_signals == result.llm_run_count  # FakeEvaluator returns None signals

    finally:
        Path(db_path).unlink(missing_ok=True)


def test_pipeline_skip_llm_skips_evaluator() -> None:
    """Evaluator is NOT called when skip_llm=True."""
    with NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        repo = AgentNewsSqliteRepository(db_path=db_path)
        fake_eval = FakeEvaluator()
        recall = _build_recall_engine()

        pipeline = BackfillPipeline(
            repo=repo,
            source_factory=_fake_source_factory,
            recall_engine=recall,
            evaluator=fake_eval,
            dry_run=False,
        )

        result = pipeline.run(
            start=date(2024, 1, 1),
            end=date(2024, 1, 5),
            symbols=["300750.SZSE"],
            sources=(Source.CNINFO,),
            recall_strength=RecallStrength.LOW,
            skip_llm=True,
        )

        assert len(fake_eval.calls) == 0, "FakeEvaluator should NOT have been called"
        assert result.llm_run_count == 0
        assert result.signal_count == 0

    finally:
        Path(db_path).unlink(missing_ok=True)


class _ResumeFakeSource(BaseNewsSource):
    """Returns items with a fixed source_item_id for resume testing."""

    source = Source.CNINFO

    def fetch(self, query):  # type: ignore[override]
        from myQuant.news_ingestion.contracts import Status as ContractStatus
        item = _make_fake_news_item(title="resume test item")
        item.source_item_id = "resume-item-001"
        return SourceFetchResult(
            source=self.source,
            status=ContractStatus.SUCCESS,
            items=(item,),
            coverage_status="full",
        )


def test_resume_skips_saved_raw_news() -> None:
    """Insert a raw news item, run pipeline with resume=True, verify it is NOT re-saved."""
    with NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        repo = AgentNewsSqliteRepository(db_path=db_path)
        recall = _build_recall_engine()

        # Pre-insert a raw news item matching what the fake source returns
        pre_item = _make_fake_news_item(title="resume test item")
        pre_item.source_item_id = "resume-item-001"
        repo.save_raw_news(pre_item)
        assert repo.count("agent_raw_news") == 1

        def _resume_source_factory(source: Source) -> BaseNewsSource:
            inst = _ResumeFakeSource()
            inst.source = source
            return inst

        pipeline = BackfillPipeline(
            repo=repo,
            source_factory=_resume_source_factory,
            recall_engine=recall,
            dry_run=False,
        )

        result = pipeline.run(
            start=date(2024, 1, 1),
            end=date(2024, 1, 5),
            symbols=["300750.SZSE"],
            sources=(Source.CNINFO,),
            recall_strength=RecallStrength.LOW,
            skip_llm=True,
            resume=True,
        )

        assert isinstance(result, PipelineResult)
        assert result.run_id
        assert repo.count("agent_raw_news") == 1, (
            f"Expected 1 raw news (pre-saved), got {repo.count('agent_raw_news')}"
        )

    finally:
        Path(db_path).unlink(missing_ok=True)


def test_dry_run_uses_in_memory_db() -> None:
    """Dry-run with in-memory DB does not create files and works correctly."""
    repo = AgentNewsSqliteRepository(db_path=None)
    pipeline = BackfillPipeline(repo=repo, dry_run=True)

    result = pipeline.run(
        start=date(2024, 1, 1),
        end=date(2024, 1, 5),
        symbols=["300750.SZSE"],
        sources=(Source.CNINFO,),
        recall_strength=RecallStrength.LOW,
        skip_llm=True,
    )

    assert isinstance(result, PipelineResult)
    assert result.run_id
    assert result.raw_count == 0
    assert result.signal_count == 0
    assert len(result.errors) == 0
    assert repo.count("agent_backfill_run") == 1


def test_llm_retry_attempts_persisted() -> None:
    """FakeEvaluatorWithRetries records 2 attempts; pipeline persists both (not just final)."""
    with NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        repo = AgentNewsSqliteRepository(db_path=db_path)
        fake_eval = FakeEvaluatorWithRetries()
        recall = _build_recall_engine()

        pipeline = BackfillPipeline(
            repo=repo,
            source_factory=_fake_source_factory,
            recall_engine=recall,
            evaluator=fake_eval,
            dry_run=False,
        )

        result = pipeline.run(
            start=date(2024, 1, 1),
            end=date(2024, 1, 5),
            symbols=["300750.SZSE"],
            sources=(Source.CNINFO,),
            recall_strength=RecallStrength.LOW,
            skip_llm=False,
        )

        # 1 call to evaluate(), 2 attempts in attempt_records → 2 LLM runs persisted
        assert len(fake_eval.calls) == 1
        assert len(fake_eval.attempt_records) == 2
        assert repo.count("agent_llm_run") == 2, (
            f"Expected 2 LLM runs persisted (1 failed + 1 success), but got {repo.count('agent_llm_run')}"
        )
        assert repo.count("agent_llm_output") == 2, (
            f"Expected 2 LLM outputs persisted, but got {repo.count('agent_llm_output')}"
        )

    finally:
        Path(db_path).unlink(missing_ok=True)
