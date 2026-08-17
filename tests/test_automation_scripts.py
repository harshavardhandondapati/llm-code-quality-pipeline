from pathlib import Path


def test_backend_check_calls_mock_not_openrouter():
    script = Path("scripts/run_backend_check.sh").read_text(encoding="utf-8")
    assert "bash scripts/run_mock_pipeline.sh" in script
    assert "run_openrouter_pipeline.sh" not in script


def test_openrouter_script_checks_pipeline_success():
    script = Path("scripts/run_openrouter_pipeline.sh").read_text(encoding="utf-8")
    assert "check_latest_pipeline_status.py" in script
    assert "3/4 Checking repair status" in script
