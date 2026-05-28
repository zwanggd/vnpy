from __future__ import annotations

import hashlib
import json
import os
from myQuant.news_ingestion.calendar import available_at_to_trading_date
import re
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from myQuant.news_ingestion.contracts import (
    AgentSignal,
    ImpactDirection,
    LLMOutputRecord,
    LLMRunRecord,
    RawNewsItem,
    RelationType,
    Status,
    StockProfile,
    TimeHorizon,
)
from myQuant.news_ingestion.recall.engine import MappedNews


REPAIR_PROMPT = "The previous response was not valid JSON. Please respond with valid JSON only."
RETRYABLE_HTTP_STATUS = {429, 500, 502, 503}
REQUIRED_FIELDS = (
    "event",
    "relation_type",
    "impact_direction",
    "impact_strength",
    "time_horizon",
    "confidence",
    "reason",
    "evidence",
)


class DeepSeekNewsEvaluator:
    def __init__(
        self,
        client: Any | None = None,
        model: str = "deepseek-v4-flash",
        temperature: float = 0.0,
        max_tokens: int = 1024,
        prompt_version: str = "news_impact_v1_archetype_v0.1",
        schema_version: str = "agent_signal_v1",
        use_completions_api: bool = False,
        strip_thinking: bool = False,
        provider: str = "deepseek",
        skip_json_response_format: bool = False,
        skip_thinking_disabled: bool = False,
        enable_thinking_false: bool = False,
    ) -> None:
        self.client = client or self._default_client()
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.prompt_version = prompt_version
        self.schema_version = schema_version
        self.use_completions_api = use_completions_api
        self.strip_thinking = strip_thinking
        self.provider = provider
        self.skip_json_response_format = skip_json_response_format
        self.skip_thinking_disabled = skip_thinking_disabled
        self.enable_thinking_false = enable_thinking_false
        self.attempt_records: list[tuple[LLMRunRecord, LLMOutputRecord]] = []

    @staticmethod
    def _default_client() -> Any:
        from openai import OpenAI

        return OpenAI(
            api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
            base_url="https://api.deepseek.com",
        )

    @classmethod
    def for_llama_cpp(
        cls,
        base_url: str = "http://127.0.0.1:8080/v1",
        model: str = "Qwen3.6-35B-A3B-Q4_K_M.gguf",
        **kwargs: Any,
    ) -> DeepSeekNewsEvaluator:
        from openai import OpenAI

        kwargs.setdefault("use_completions_api", True)
        kwargs.setdefault("strip_thinking", True)
        kwargs.setdefault("provider", "llama_cpp")
        return cls(
            client=OpenAI(base_url=base_url, api_key="not-needed"),
            model=model,
            **kwargs,
        )

    @classmethod
    def for_opencode_go(
        cls,
        model: str = "qwen3.5-plus",
        **kwargs: Any,
    ) -> DeepSeekNewsEvaluator:
        """Factory for OpenCode Go API — all models on OpenAI-compatible endpoint."""
        api_key = os.environ.get("OPENCODE_GO_API_KEY", "")
        if not api_key:
            raise ValueError("OPENCODE_GO_API_KEY environment variable is not set")

        from openai import OpenAI

        is_deepseek = model.startswith("deepseek")
        is_qwen = "qwen" in model
        kwargs.setdefault("skip_json_response_format", model.startswith("minimax"))
        kwargs.setdefault("skip_thinking_disabled", not is_deepseek)
        kwargs.setdefault("provider", "opencode-go")
        kwargs.setdefault("enable_thinking_false", is_qwen)
        return cls(
            client=OpenAI(
                base_url="https://opencode.ai/zen/go/v1",
                api_key=api_key,
            ),
            model=model,
            **kwargs,
        )

    def evaluate(
        self,
        mapped_news: MappedNews,
        news_item: RawNewsItem,
        profile: StockProfile | None = None,
    ) -> tuple[LLMRunRecord, LLMOutputRecord, AgentSignal | None]:
        self.attempt_records = []
        prompt = self._build_prompt(mapped_news, news_item, profile=profile)
        messages: list[dict[str, str]] = [{"role": "user", "content": prompt}]
        full_prompt = prompt
        input_hash = self._hash_text(prompt)
        http_attempts = 0
        repaired_invalid_json = False

        while True:
            http_attempts += 1
            started_at = datetime.now()
            try:
                if self.use_completions_api:
                    response = self.client.completions.create(
                        model=self.model,
                        prompt=full_prompt,
                        max_tokens=2048,
                        temperature=self.temperature,
                    )
                    raw_response = str(response.choices[0].text or "")
                    if self.strip_thinking:
                        raw_response = re.sub(
                            r"<think>.*?</think>",
                            "",
                            raw_response,
                            flags=re.DOTALL,
                        )
                else:
                    create_kwargs: dict[str, Any] = {
                        "model": self.model,
                        "messages": messages,
                        "temperature": self.temperature,
                        "max_tokens": self.max_tokens,
                    }
                    if not self.skip_json_response_format:
                        create_kwargs["response_format"] = {"type": "json_object"}
                    if not self.skip_thinking_disabled:
                        create_kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
                    elif self.enable_thinking_false:
                        create_kwargs["extra_body"] = {"enable_thinking": False}
                    response = self.client.chat.completions.create(**create_kwargs)
                    raw_response = str(response.choices[0].message.content or "")

                token_usage = self._extract_usage(response)
                parsed_json, errors = self._parse_and_validate(raw_response)
                if errors and not repaired_invalid_json:
                    run, output = self._make_records(
                        mapped_news=mapped_news,
                        input_hash=input_hash,
                        raw_response=raw_response,
                        parsed_json=parsed_json,
                        validation_errors=errors,
                        token_usage=token_usage,
                        started_at=started_at,
                        status=Status.FAILED,
                    )
                    self.attempt_records.append((run, output))
                    if self.use_completions_api:
                        full_prompt = (
                            f"{prompt}\n\n"
                            f"Previous response was not valid JSON.\n"
                            f"{REPAIR_PROMPT}"
                        )
                    else:
                        messages.append({"role": "assistant", "content": raw_response})
                        messages.append({"role": "user", "content": REPAIR_PROMPT})
                    repaired_invalid_json = True
                    continue

                status = Status.FAILED if errors else Status.SUCCESS
                run, output = self._make_records(
                    mapped_news=mapped_news,
                    input_hash=input_hash,
                    raw_response=raw_response,
                    parsed_json=parsed_json,
                    validation_errors=errors,
                    token_usage=token_usage,
                    started_at=started_at,
                    status=status,
                )
                self.attempt_records.append((run, output))
                if errors:
                    return run, output, None
                return run, output, self._make_signal(mapped_news, news_item, parsed_json)
            except Exception as exc:
                status_code = self._http_status_code(exc)
                retryable = status_code in RETRYABLE_HTTP_STATUS and http_attempts <= 3
                run, output = self._make_records(
                    mapped_news=mapped_news,
                    input_hash=input_hash,
                    raw_response="",
                    parsed_json={},
                    validation_errors=(f"HTTP error {status_code}: {exc}",),
                    token_usage={},
                    started_at=started_at,
                    status=Status.FAILED,
                    error=f"HTTP error {status_code}: {exc}",
                )
                self.attempt_records.append((run, output))
                if retryable:
                    continue
                return run, output, None

    def _build_prompt(self, mapped_news: MappedNews, news_item: RawNewsItem, profile: StockProfile | None = None) -> str:
        name = profile.name if profile else "未知"
        industry = ", ".join(profile.industry) if profile and profile.industry else "未知"
        products = ", ".join(profile.products) if profile and profile.products else "未知"
        if profile:
            up = ", ".join(profile.upstream) if profile.upstream else ""
            down = ", ".join(profile.downstream) if profile.downstream else ""
            supply = f"{up} | {down}" if up or down else "未知"
        else:
            supply = "未知"

        lines: list[str] = [
            "你是A股新闻影响评估助手。请只输出合法JSON，不要输出Markdown。",
            "任务：分析新闻对指定股票的影响，字段名必须使用英文。",
            f"新闻标题：{news_item.title}",
            f"新闻内容：{news_item.content}",
            f"股票vt_symbol：{mapped_news.vt_symbol}",
            f"股票代码：{mapped_news.symbol}",
            f"交易所：{mapped_news.exchange}",
            f"股票名称：{name}",
            f"行业：{industry}",
            f"产品：{products}",
            f"上游/下游：{supply}",
            f"召回关系提示：{mapped_news.relation_hint.value}",
        ]

        if profile is not None:
            from myQuant.agent.prompt_variants import get_archetype_prompt_snippet  # noqa: E402

            archetype = getattr(profile, "company_archetype", "generic") or "generic"
            archetype_version = getattr(profile, "company_archetype_version", "company_archetype_v0.1") or "company_archetype_v0.1"
            snippet = get_archetype_prompt_snippet(archetype)
            lines.extend([
                f"公司类型：{archetype}",
                f"公司类型版本：{archetype_version}",
                f"该类型公司新闻评估重点：\n{snippet}",
            ])

        lines.extend([
            "输出JSON字段：event, relation_type, impact_direction, impact_strength, time_horizon, confidence, reason, evidence。",
            "relation_type只能是direct_company|supply_chain|industry|macro_policy|market_sentiment|risk_event|unknown。",
            "impact_direction只能是positive|negative|neutral|mixed|unknown。",
            "time_horizon只能是intraday|short|medium|long|unknown。",
            "impact_strength和confidence必须是0.0到1.0之间的数字。reason用简短中文解释，evidence填写新闻中的关键句。",
        ])

        return "\n".join(lines)

    def _make_records(
        self,
        mapped_news: MappedNews,
        input_hash: str,
        raw_response: str,
        parsed_json: dict[str, Any],
        validation_errors: tuple[str, ...],
        token_usage: dict[str, Any],
        started_at: datetime,
        status: Status,
        error: str = "",
    ) -> tuple[LLMRunRecord, LLMOutputRecord]:
        run_id = f"{self.provider}-{uuid.uuid4().hex}"
        finished_at = datetime.now()
        if self.use_completions_api:
            params: dict[str, Any] = {
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            }
        else:
            params = {
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            }
            if not self.skip_json_response_format:
                params["response_format"] = {"type": "json_object"}
            if not self.skip_thinking_disabled:
                params["extra_body"] = {"thinking": {"type": "disabled"}}
        run = LLMRunRecord(
            run_id=run_id,
            raw_news_id=mapped_news.raw_news_id,
            provider=self.provider,
            model=self.model,
            prompt_version=self.prompt_version,
            schema_version=self.schema_version,
            parameters=params,
            input_hash=input_hash,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            error=error,
        )
        output = LLMOutputRecord(
            llm_run_id=0,
            raw_response=raw_response,
            parsed_json=parsed_json,
            validation_status=Status.SUCCESS if status is Status.SUCCESS else Status.FAILED,
            validation_errors=validation_errors,
            output_hash=self._hash_text(raw_response),
            token_usage=token_usage,
        )
        return run, output

    def _make_signal(
        self,
        mapped_news: MappedNews,
        news_item: RawNewsItem,
        parsed_json: dict[str, Any],
    ) -> AgentSignal:
        published_at = news_item.published_at or mapped_news.available_at
        available_at = news_item.available_at or mapped_news.available_at
        return AgentSignal(
            raw_news_id=mapped_news.raw_news_id,
            llm_run_id=0,
            vt_symbol=mapped_news.vt_symbol,
            event=str(parsed_json["event"]),
            relation_type=RelationType(parsed_json["relation_type"]),
            impact_direction=ImpactDirection(parsed_json["impact_direction"]),
            impact_strength=float(parsed_json["impact_strength"]),
            time_horizon=TimeHorizon(parsed_json["time_horizon"]),
            confidence=float(parsed_json["confidence"]),
            reason=str(parsed_json["reason"]),
            evidence=[str(parsed_json["evidence"])],
            published_at=published_at,
            available_at=available_at,
            trading_date=available_at_to_trading_date(available_at),
            source=news_item.source,
            source_item_id=news_item.source_item_id,
            prompt_version=self.prompt_version,
            schema_version=self.schema_version,
        )

    @staticmethod
    def _extract_json(text: str) -> str:
        """Extract JSON from potentially noisy model output.

        Handles: markdown code fences, leading/trailing text, empty response.
        """
        stripped = text.strip()
        if not stripped:
            return ""

        # Strip markdown code fences: ```json ... ``` or ``` ... ```
        fence_match = re.match(r"```(?:json)?\s*\n?(.*?)\n?```", stripped, re.DOTALL)
        if fence_match:
            stripped = fence_match.group(1).strip()

        # Find the first JSON object in the text
        brace_start = stripped.find("{")
        brace_end = stripped.rfind("}")
        if brace_start != -1 and brace_end > brace_start:
            return stripped[brace_start : brace_end + 1]

        return stripped

    def _parse_and_validate(self, raw_response: str) -> tuple[dict[str, Any], tuple[str, ...]]:
        errors: list[str] = []
        clean = self._extract_json(raw_response)
        if not clean:
            return {}, ("empty response after extraction",)
        try:
            parsed = json.loads(clean)
        except json.JSONDecodeError as exc:
            return {}, (f"invalid JSON: {exc.msg}",)
        if not isinstance(parsed, dict):
            return {}, ("JSON root must be an object",)

        for field in REQUIRED_FIELDS:
            if field not in parsed:
                errors.append(f"missing field: {field}")
        if errors:
            return parsed, tuple(errors)

        self._validate_enum(parsed, "relation_type", RelationType, errors)
        self._validate_enum(parsed, "impact_direction", ImpactDirection, errors)
        self._validate_enum(parsed, "time_horizon", TimeHorizon, errors)
        self._validate_unit_interval(parsed, "impact_strength", errors)
        self._validate_unit_interval(parsed, "confidence", errors)
        for field in ("event", "reason", "evidence"):
            if not isinstance(parsed[field], str) or not parsed[field].strip():
                errors.append(f"{field} must be a non-empty string")
        return parsed, tuple(errors)

    @staticmethod
    def _validate_enum(
        parsed: dict[str, Any],
        field: str,
        enum_type: type[Enum],
        errors: list[str],
    ) -> None:
        try:
            enum_type(parsed[field])
        except ValueError:
            allowed = [item.value for item in enum_type]
            errors.append(f"{field} must be one of {allowed}")

    @staticmethod
    def _validate_unit_interval(parsed: dict[str, Any], field: str, errors: list[str]) -> None:
        try:
            number = float(parsed[field])
        except (TypeError, ValueError):
            errors.append(f"{field} must be a number between 0.0 and 1.0")
            return
        if not 0.0 <= number <= 1.0:
            errors.append(f"{field} must be between 0.0 and 1.0")

    @staticmethod
    def _extract_usage(response: Any) -> dict[str, Any]:
        usage = getattr(response, "usage", None)
        if usage is None:
            return {}
        if isinstance(usage, dict):
            return dict(usage)
        if is_dataclass(usage):
            return asdict(usage)
        return {
            key: getattr(usage, key)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            if hasattr(usage, key)
        }

    @staticmethod
    def _http_status_code(exc: Exception) -> int | None:
        value = getattr(exc, "status_code", None) or getattr(exc, "status", None)
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _hash_text(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
