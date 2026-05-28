""""""

from __future__ import annotations

from myQuant.agent.prompt_variants import (
    ARCHETYPE_PROMPT_SNIPPETS,
    get_archetype_prompt_snippet,
)


def test_all_known_archetypes_have_snippets() -> None:
    from myQuant.core.schema import COMPANY_ARCHETYPE_VALUES

    for archetype in COMPANY_ARCHETYPE_VALUES:
        assert archetype in ARCHETYPE_PROMPT_SNIPPETS, f"Missing snippet for: {archetype}"


def test_get_archetype_snippet_known() -> None:
    snippet = get_archetype_prompt_snippet("cyclical_chemical")
    assert "产品价格" in snippet
    assert "价差" in snippet
    assert "产能投放" in snippet


def test_get_archetype_snippet_unknown_fallback() -> None:
    snippet = get_archetype_prompt_snippet("totally_unknown_type")
    assert "直接业务关联" in snippet  # generic content


def test_get_archetype_snippet_generic_explicit() -> None:
    snippet = get_archetype_prompt_snippet("generic")
    assert "直接业务关联" in snippet
    assert "影响强度评估应保守" in snippet


def test_snippet_does_not_include_json_schema() -> None:
    for archetype, snippet in ARCHETYPE_PROMPT_SNIPPETS.items():
        assert "event" not in snippet, f"{archetype} snippet contains 'event'"
        assert "relation_type" not in snippet, f"{archetype} snippet contains 'relation_type'"
        assert "impact_direction" not in snippet, f"{archetype} snippet contains 'impact_direction'"


def test_snippet_content_per_archetype() -> None:
    assert "大宗商品价格" in get_archetype_prompt_snippet("cyclical_resource")
    assert "品牌力" in get_archetype_prompt_snippet("consumer_moat")
    assert "利率政策" in get_archetype_prompt_snippet("financial")
    assert "来水量" in get_archetype_prompt_snippet("utility_defensive")
    assert "商业化进展" in get_archetype_prompt_snippet("growth_concept")
    assert "大客户订单" in get_archetype_prompt_snippet("advanced_manufacturing")
    assert "新能源汽车销量" in get_archetype_prompt_snippet("new_energy_chain")
    assert "临床试验" in get_archetype_prompt_snippet("healthcare_innovation")
