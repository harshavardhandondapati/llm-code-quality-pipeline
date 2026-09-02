"""Regression check for the Run Summary repair explanation."""

from pathlib import Path


def test_code_comparison_prefers_repair_explanation() -> None:
    source = Path("src/llm_pipeline/ui/dashboard.py").read_text(encoding="utf-8")

    assert '(data.get("fix_generation") or {}).get("explanation")' in source
    assert 'or (data.get("bug_detection") or {}).get("explanation")' in source
