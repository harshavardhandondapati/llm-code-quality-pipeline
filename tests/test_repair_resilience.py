from pathlib import Path

from llm_pipeline.repair.apply_patch import _extract_fixed_file_content, _normalise_patch_text
from llm_pipeline.workflow.runner import _build_local_benchmark_repair


def _write_fake_bugsinpy_checkout(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "fake_bugsinpy"
    bin_dir.mkdir(parents=True)
    script = bin_dir / "bugsinpy-checkout"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "work = Path(args[args.index('-w') + 1])\n"
        "project = args[args.index('-p') + 1]\n"
        "target = work / project / 'httpie'\n"
        "target.mkdir(parents=True, exist_ok=True)\n"
        "(target / 'downloads.py').write_text(\n"
        "    'import errno\\nimport os\\n\\n'\n"
        "    'def get_unique_filename(filename, exists=os.path.exists):\\n'\n"
        "    '    try:\\n'\n"
        "    '        if not exists(filename):\\n'\n"
        "    '            return filename\\n'\n"
        "    '    except OSError as e:\\n'\n"
        "    '        if e.errno != errno.ENAMETOOLONG:\\n'\n"
        "    '            raise\\n',\n"
        "    encoding='utf-8',\n"
        ")\n"
    )
    script.chmod(0o755)
    return bin_dir


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
    monkeypatch.setenv("PIPELINE_BUGSINPY_EXECUTABLE_DIRECTORY", str(_write_fake_bugsinpy_checkout(tmp_path)))

    result = _build_local_benchmark_repair(
        project="httpie",
        bug_id="1",
        project_path=project,
        bug_detection={"file_path": "httpie/downloads.py", "explanation": "filename too long"},
    )
    assert result is not None
    assert result["patch"]
    assert "httpie/downloads.py" in result["fixed_files"]
    assert "except OSError" in result["fixed_files"]["httpie/downloads.py"]
    assert "ENAMETOOLONG" in result["fixed_files"]["httpie/downloads.py"]


