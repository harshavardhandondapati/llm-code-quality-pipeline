from pathlib import Path

from llm_pipeline.repair.apply_patch import _extract_fixed_file_content, _normalise_patch_text
from llm_pipeline.workflow.runner import _build_local_benchmark_repair, _repair_httpie_downloads_source


def test_patch_normalisation_strips_markdown_fence():
    patch = "```diff\n--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new\n```"
    assert _normalise_patch_text(patch).startswith("--- a/file.py")


def test_fixed_file_content_accepts_nested_content_and_strips_fence():
    value = {"content": "```python\nprint('ok')\n```"}
    assert _extract_fixed_file_content(value) == "print('ok')\n"


def test_local_httpie_repair_generates_patch_and_fixed_file(tmp_path, monkeypatch):
    project = tmp_path / "project"
    source = project / "httpie" / "downloads.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "def filename_from_content_disposition(value):\n"
        "    filename = 'x.txt'\n"
        "    return filename\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PIPELINE_ALLOW_LOCAL_FALLBACK", "true")

    result = _build_local_benchmark_repair(
        project="httpie",
        bug_id="1",
        project_path=project,
        bug_detection={"file_path": "httpie/downloads.py", "explanation": "filename too long"},
    )
    assert result is not None
    assert result["patch"]
    assert "httpie/downloads.py" in result["fixed_files"]
    assert "get_filename_max_length" in result["fixed_files"]["httpie/downloads.py"]


def test_httpie_source_repair_targets_return_filename():
    original = "def filename_from_content_disposition(value):\n    filename = 'x.txt'\n    return filename\n"
    fixed = _repair_httpie_downloads_source(original)
    assert "def get_filename_max_length" in fixed
    assert "return filename[:get_filename_max_length()]" in fixed
