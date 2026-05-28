import json
from dataclasses import asdict
from datetime import datetime
from typing import Any

import pytest

from myQuant.news_ingestion import (
    ImpactDirection,
    RawNewsItem,
    RelationType,
    Source,
    SourceCategory,
    Status,
    TimeHorizon,
)
from myQuant.news_ingestion.llm import DeepSeekNewsEvaluator
from myQuant.news_ingestion.recall.engine import MappedNews


class FakeRateLimitError(Exception):
    status_code = 429


class FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = FakeMessage(content)


class FakeUsage:
    def __init__(self) -> None:
        self.prompt_tokens = 11
        self.completion_tokens = 7
        self.total_tokens = 18


class FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [FakeChoice(content)]
        self.usage = FakeUsage()


class FakeCompletions:
    def __init__(self, outcomes: list[str | Exception]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> FakeResponse:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(outcome)


class FakeChat:
    def __init__(self, outcomes: list[str | Exception]) -> None:
        self.completions = FakeCompletions(outcomes)


class FakeClient:
    def __init__(self, outcomes: list[str | Exception]) -> None:
        self.chat = FakeChat(outcomes)


def valid_payload() -> str:
    return json.dumps(
        {
            "event": "宁德时代发布新电池技术",
            "relation_type": "direct_company",
            "impact_direction": "positive",
            "impact_strength": 0.72,
            "time_horizon": "short",
            "confidence": 0.68,
            "reason": "新技术有望提升产品竞争力",
            "evidence": "公告提及新电池技术",
        },
        ensure_ascii=False,
    )


@pytest.fixture
def news_item() -> RawNewsItem:
    return RawNewsItem(
        source=Source.CNINFO,
        source_category=SourceCategory.ANNOUNCEMENT,
        source_item_id="cninfo-300750-1",
        url="https://example.test/cninfo-300750-1.pdf",
        title="宁德时代发布新电池技术公告",
        content="宁德时代公告提及新电池技术，能量密度提升。",
        published_at=datetime(2026, 5, 8, 10, 0),
        available_at=datetime(2026, 5, 8, 10, 5),
        content_hash="hash-cninfo-300750-1",
    )


@pytest.fixture
def mapped_news() -> MappedNews:
    return MappedNews(
        raw_news_id=1,
        vt_symbol="300750.SZSE",
        symbol="300750",
        exchange="SZSE",
        relation_hint=RelationType.DIRECT_COMPANY,
        mapping_method="direct",
        mapping_confidence=1.0,
        keywords_matched=("宁德时代",),
        available_at=datetime(2026, 5, 8, 10, 5),
    )


def record_blob(*records: object) -> str:
    return json.dumps([asdict(record) for record in records], ensure_ascii=False, default=str)


def test_valid_deepseek_json_creates_signal(mapped_news: MappedNews, news_item: RawNewsItem) -> None:
    client = FakeClient([valid_payload()])
    evaluator = DeepSeekNewsEvaluator(client=client)

    run, output, signal = evaluator.evaluate(mapped_news, news_item)

    assert signal is not None
    assert run.status is Status.SUCCESS
    assert output.validation_status is Status.SUCCESS
    assert signal.impact_direction is ImpactDirection.POSITIVE
    assert signal.impact_strength == 0.72
    assert signal.confidence == 0.68
    assert signal.relation_type is RelationType.DIRECT_COMPANY
    assert signal.time_horizon is TimeHorizon.SHORT
    assert signal.evidence == ["公告提及新电池技术"]
    assert client.chat.completions.calls[0]["model"] == "deepseek-v4-flash"
    assert client.chat.completions.calls[0]["response_format"] == {"type": "json_object"}
    assert client.chat.completions.calls[0]["extra_body"] == {"thinking": {"type": "disabled"}}


def test_invalid_json_persists_output_without_signal(mapped_news: MappedNews, news_item: RawNewsItem) -> None:
    client = FakeClient(["not-json", "still-not-json"])
    evaluator = DeepSeekNewsEvaluator(client=client)

    run, output, signal = evaluator.evaluate(mapped_news, news_item)

    assert signal is None
    assert run.status is Status.FAILED
    assert output.raw_response == "still-not-json"
    assert output.validation_status is Status.FAILED
    assert output.validation_errors
    assert client.chat.completions.calls[1]["messages"][-1]["content"] == (
        "The previous response was not valid JSON. Please respond with valid JSON only."
    )


def test_retry_on_http_429(mapped_news: MappedNews, news_item: RawNewsItem) -> None:
    client = FakeClient([FakeRateLimitError("rate limited"), FakeRateLimitError("rate limited"), valid_payload()])
    evaluator = DeepSeekNewsEvaluator(client=client)

    run, output, signal = evaluator.evaluate(mapped_news, news_item)

    assert signal is not None
    assert run.status is Status.SUCCESS
    assert output.validation_status is Status.SUCCESS
    assert len(client.chat.completions.calls) == 3


def test_secret_hygiene(monkeypatch: pytest.MonkeyPatch, mapped_news: MappedNews, news_item: RawNewsItem) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test123")
    evaluator = DeepSeekNewsEvaluator(client=FakeClient([valid_payload()]))

    run, output, signal = evaluator.evaluate(mapped_news, news_item)

    assert signal is not None
    assert "sk-test123" not in record_blob(run, output, signal)


def test_missing_api_key_no_crash(monkeypatch: pytest.MonkeyPatch, mapped_news: MappedNews, news_item: RawNewsItem) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    evaluator = DeepSeekNewsEvaluator(client=FakeClient([valid_payload()]))

    run, output, signal = evaluator.evaluate(mapped_news, news_item)

    assert signal is not None
    assert run.status is Status.SUCCESS
    assert output.validation_status is Status.SUCCESS


# ---------------------------------------------------------------------------
# Fake classes for completions (llama.cpp) mode
# ---------------------------------------------------------------------------


class FakeCompletionChoice:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeCompletionResponse:
    def __init__(self, text: str) -> None:
        self.choices = [FakeCompletionChoice(text)]
        self.usage = FakeUsage()


class FakeCompletionsEndpoint:
    def __init__(self, outcomes: list[str | Exception]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> FakeCompletionResponse:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeCompletionResponse(outcome)


class FakeLlamaCppClient:
    def __init__(self, outcomes: list[str | Exception]) -> None:
        self.completions = FakeCompletionsEndpoint(outcomes)


# ---------------------------------------------------------------------------
# llama.cpp tests
# ---------------------------------------------------------------------------


def test_llama_cpp_completions_api(mapped_news: MappedNews, news_item: RawNewsItem) -> None:
    client = FakeLlamaCppClient([valid_payload()])
    evaluator = DeepSeekNewsEvaluator(
        client=client,
        model="Qwen3.6-35B-A3B-Q4_K_M.gguf",
        use_completions_api=True,
        strip_thinking=True,
        provider="llama_cpp",
    )

    run, output, signal = evaluator.evaluate(mapped_news, news_item)

    assert signal is not None
    assert run.status is Status.SUCCESS
    assert output.validation_status is Status.SUCCESS
    assert signal.impact_direction is ImpactDirection.POSITIVE

    # Verify completions API was called (not chat completions)
    assert len(client.completions.calls) == 1
    call = client.completions.calls[0]
    assert call["model"] == "Qwen3.6-35B-A3B-Q4_K_M.gguf"
    assert "max_tokens" in call
    assert "temperature" in call
    assert "prompt" in call
    assert "response_format" not in call
    assert call.get("max_tokens") == 2048  # llama.cpp completions use higher limit for think blocks

    # Verify provider in run record
    assert run.provider == "llama_cpp"
    assert "response_format" not in run.parameters


def test_llama_cpp_strips_thinking(mapped_news: MappedNews, news_item: RawNewsItem) -> None:
    think_payload = "<think>Let me analyze...\nThe news seems positive.</think>\n" + valid_payload()
    client = FakeLlamaCppClient([think_payload])
    evaluator = DeepSeekNewsEvaluator(
        client=client,
        model="Qwen3.6-35B-A3B-Q4_K_M.gguf",
        use_completions_api=True,
        strip_thinking=True,
        provider="llama_cpp",
    )

    run, output, signal = evaluator.evaluate(mapped_news, news_item)

    assert signal is not None
    assert run.status is Status.SUCCESS
    assert output.validation_status is Status.SUCCESS
    # Verify think tag was stripped from raw response
    assert "<think>" not in output.raw_response
    assert output.raw_response.strip().startswith("{")


def test_prompt_contains_stock_profile(mapped_news: MappedNews, news_item: RawNewsItem) -> None:
    from myQuant.news_ingestion.contracts import StockProfile
    profile = StockProfile(
        vt_symbol="300750.SZSE",
        name="宁德时代",
        aliases=("CATL",),
        industry=("新能源", "动力电池"),
        products=("动力电池", "储能电池"),
        upstream=("碳酸锂",),
        downstream=("新能源汽车",),
    )
    client = FakeClient([valid_payload()])
    evaluator = DeepSeekNewsEvaluator(client=client)
    prompt = evaluator._build_prompt(mapped_news, news_item, profile=profile)
    assert "宁德时代" in prompt
    assert "新能源" in prompt
    assert "动力电池" in prompt
    assert "碳酸锂" in prompt
    assert "新能源汽车" in prompt
    assert "未知" not in prompt


def test_prompt_without_profile_has_unknown(mapped_news: MappedNews, news_item: RawNewsItem) -> None:
    client = FakeClient([valid_payload()])
    evaluator = DeepSeekNewsEvaluator(client=client)
    prompt = evaluator._build_prompt(mapped_news, news_item, profile=None)
    assert "未知" in prompt


def test_prompt_with_archetype_includes_snippet(mapped_news: MappedNews, news_item: RawNewsItem) -> None:
    """Profile with cyclical_chemical archetype → prompt contains chemical-specific guidance."""
    from myQuant.news_ingestion.contracts import StockProfile

    profile = StockProfile(
        vt_symbol="600309.SSE",
        name="万华化学",
        company_archetype="cyclical_chemical",
    )
    client = FakeClient([valid_payload()])
    evaluator = DeepSeekNewsEvaluator(client=client)
    prompt = evaluator._build_prompt(mapped_news, news_item, profile=profile)

    assert "公司类型：cyclical_chemical" in prompt
    assert "公司类型版本" in prompt
    assert "该类型公司新闻评估重点" in prompt
    assert "产品价格" in prompt
    assert "价差" in prompt
    # Original JSON fields still present
    assert "event" in prompt
    assert "relation_type" in prompt
    assert "impact_direction" in prompt
    assert "impact_strength" in prompt
    assert "time_horizon" in prompt
    assert "confidence" in prompt
    assert "reason" in prompt
    assert "evidence" in prompt


def test_prompt_archetype_fallback_to_generic(mapped_news: MappedNews, news_item: RawNewsItem) -> None:
    """Unknown archetype → prompt uses generic snippet."""
    from myQuant.news_ingestion.contracts import StockProfile

    profile = StockProfile(
        vt_symbol="TEST.SSE",
        name="Test",
        company_archetype="nonexistent_type_xyz",
    )
    client = FakeClient([valid_payload()])
    evaluator = DeepSeekNewsEvaluator(client=client)
    prompt = evaluator._build_prompt(mapped_news, news_item, profile=profile)

    assert "公司类型：nonexistent_type_xyz" in prompt
    # Should have generic snippet content
    assert "直接业务关联" in prompt


def test_prompt_with_profile_no_archetype_uses_generic(mapped_news: MappedNews, news_item: RawNewsItem) -> None:
    """Profile without explicit company_archetype → uses generic."""
    from myQuant.news_ingestion.contracts import StockProfile

    profile = StockProfile(vt_symbol="TEST.SSE", name="Test")
    client = FakeClient([valid_payload()])
    evaluator = DeepSeekNewsEvaluator(client=client)
    prompt = evaluator._build_prompt(mapped_news, news_item, profile=profile)

    assert "公司类型：generic" in prompt
    assert "直接业务关联" in prompt


def test_prompt_archetype_prompt_version(mapped_news: MappedNews, news_item: RawNewsItem) -> None:
    """Evaluator with archetype-aware prompt has updated prompt_version."""
    from myQuant.news_ingestion.contracts import StockProfile

    profile = StockProfile(
        vt_symbol="600309.SSE",
        name="万华化学",
        company_archetype="cyclical_chemical",
    )
    client = FakeClient([valid_payload()])
    evaluator = DeepSeekNewsEvaluator(client=client)
    assert "archetype" in evaluator.prompt_version

    run, _, signal = evaluator.evaluate(mapped_news, news_item, profile=profile)
    assert "archetype" in run.prompt_version


def test_prompt_without_profile_no_archetype_block(mapped_news: MappedNews, news_item: RawNewsItem) -> None:
    """Profile=None → prompt should NOT contain archetype block."""
    client = FakeClient([valid_payload()])
    evaluator = DeepSeekNewsEvaluator(client=client)
    prompt = evaluator._build_prompt(mapped_news, news_item, profile=None)

    assert "公司类型" not in prompt
    assert "公司类型版本" not in prompt
    assert "该类型公司新闻评估重点" not in prompt
    # Original JSON fields still present
    assert "event" in prompt
