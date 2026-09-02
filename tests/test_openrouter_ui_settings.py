"""UI configuration checks for OpenRouter credentials."""

from pathlib import Path


def test_streamlit_uses_pipeline_settings_for_openrouter_key() -> None:
    source = Path("app.py").read_text(encoding="utf-8")

    assert "from llm_pipeline.config import Settings" in source
    assert "def _openrouter_api_key() -> str:" in source
    assert "settings = Settings()" in source
    assert "settings.openrouter_api_key or settings.api_key" in source
    assert 'if provider == "openrouter" and not _openrouter_api_key():' in source
    assert 'os.environ.get("PIPELINE_OPENROUTER_API_KEY")' not in source


def test_file_review_uses_same_openrouter_key_helper() -> None:
    source = Path("app.py").read_text(encoding="utf-8")

    if "def _openrouter_key_for_file_review" in source:
        assert "return _openrouter_api_key()" in source
