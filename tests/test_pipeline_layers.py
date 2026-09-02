import json
from pathlib import Path

from llm_pipeline.evaluation import create_evaluation_metrics, create_post_fix_evaluation
from llm_pipeline.approval import create_human_approval
from llm_pipeline.model import MockLLMClient, save_model_outputs
from llm_pipeline.prompts import build_bug_detection_prompt, build_fix_generation_prompt, save_prompt
from llm_pipeline.ui.interactive_review import review_python_source, write_interactive_review_artifacts


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
        "    '    attempt = 0\\n'\n"
        "    '    while True:\\n'\n"
        "    '        suffix = \"-\" + str(attempt) if attempt > 0 else \"\"\\n'\n"
        "    '        try:\\n'\n"
        "    '            candidate = filename + suffix\\n'\n"
        "    '            if not exists(candidate):\\n'\n"
        "    '                return candidate\\n'\n"
        "    '        except OSError as e:\\n'\n"
        "    '            if e.errno != errno.ENAMETOOLONG:\\n'\n"
        "    '                raise\\n'\n"
        "    '            filename = filename[:-1]\\n'\n"
        "    '        attempt += 1\\n',\n"
        "    encoding='utf-8',\n"
        ")\n"
    )
    script.chmod(0o755)
    return bin_dir


def test_prompt_and_mock_detection(tmp_path):
    context = {
        "project": "httpie",
        "bug_id": "1",
        "language": "python",
        "failure_output": "tests/test_downloads.py failed",
        "failing_tests": ["tests/test_downloads.py"],
        "snippets": [
            {
                "file_path": "httpie/downloads.py",
                "start_line": 1,
                "end_line": 3,
                "content": "def filename_from_content_disposition(value):\n    return filename\n",
            }
        ],
    }
    prompt = build_bug_detection_prompt(context)
    json_path, text_path = save_prompt(prompt, tmp_path, "bug_detection_prompt")
    assert json_path.exists()
    assert text_path.exists()

    response = MockLLMClient().complete(prompt)
    assert response.content["bug_found"] is True
    assert response.content["file_path"] == "httpie/downloads.py"
    save_model_outputs(response, tmp_path, "bug_detection")
    assert (tmp_path / "bug_detection_result.json").exists()


def test_mock_fix_generation_contains_fixed_file(tmp_path, monkeypatch):
    project = tmp_path / "httpie_project"
    source = project / "httpie" / "downloads.py"
    source.parent.mkdir(parents=True)
    source.write_text("import os\n\ndef get_unique_filename(filename, exists=os.path.exists):\n    return filename\n", encoding="utf-8")
    monkeypatch.setenv("PIPELINE_BUGSINPY_EXECUTABLE_DIRECTORY", str(_write_fake_bugsinpy_checkout(tmp_path)))

    context = {
        "project": "httpie",
        "bug_id": "1",
        "language": "python",
        "failure_output": "failure",
        "failing_tests": ["tests/test_downloads.py"],
        "snippets": [
            {
                "file_path": "httpie/downloads.py",
                "start_line": 1,
                "end_line": 5,
                "content": "import os\n\ndef filename_from_content_disposition(value):\n    return filename\n",
            }
        ],
    }
    detection = {"bug_found": True, "file_path": "httpie/downloads.py", "explanation": "long filename"}
    prompt = build_fix_generation_prompt(context, detection)
    prompt.setdefault("metadata", {})["project_path"] = str(project)
    response = MockLLMClient().complete(prompt)
    assert "except OSError" in response.content["patch"]
    assert "httpie/downloads.py" in response.content["fixed_files"]


def test_human_approval_and_metrics(tmp_path):
    record = {
        "project": "httpie",
        "bug_id": "1",
        "status": "accepted",
        "target_python": "3.8.20",
        "baseline_failure_observed": True,
    }
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "bug_detection_result.json").write_text(json.dumps({"bug_found": True, "file_path": "httpie/downloads.py", "confidence": 0.82}), encoding="utf-8")
    (outputs / "fix_generation_result.json").write_text(json.dumps({"patch": "diff", "files_modified": ["httpie/downloads.py"]}), encoding="utf-8")
    validation = {"patch_applied": True, "compilation_passed": True, "triggering_tests_passed": True, "changed_files": ["httpie/downloads.py"]}
    (outputs / "validation_result.json").write_text(json.dumps(validation), encoding="utf-8")

    post_fix = create_post_fix_evaluation(candidate_record=record, validation=validation, outputs_dir=outputs)
    assert post_fix["repair_status"] == "successful_repair"
    approval = create_human_approval(candidate_record=record, outputs_dir=outputs, decision="approved", reviewer="Hari")
    assert approval["allows_progress"] is True
    metrics = create_evaluation_metrics(candidate_record=record, outputs_dir=outputs)
    assert metrics["overall_status"] == "successful"


def test_interactive_review_writes_fixed_python_file(tmp_path):
    source = "def divide(a, b):\n    return a / b\n"
    result = review_python_source(source, filename="sample_bug.py")
    paths = write_interactive_review_artifacts(result, original_source=source, output_dir=tmp_path)
    fixed = Path(paths["fixed_file"])
    assert fixed.exists()
    assert "if b == 0" in fixed.read_text(encoding="utf-8")
    assert Path(paths["markdown_report"]).exists()

from llm_pipeline.workflow.runner import _baseline_failed
from llm_pipeline.schemas import CommandResult
from llm_pipeline.model.mock_client import MockLLMClient


def test_baseline_failed_detects_attribute_error_with_zero_exit(tmp_path):
    result = CommandResult(
        command=["bugsinpy-test"],
        working_directory=tmp_path,
        return_code=0,
        stdout="AttributeError: <module 'httpie.downloads'> does not have the attribute 'get_filename_max_length'",
        stderr="",
        execution_time_seconds=1.0,
    )

    assert _baseline_failed(result) is True


def test_mock_httpie_fix_reads_project_file_when_available(tmp_path, monkeypatch):
    project = tmp_path / "httpie_project"
    source = project / "httpie" / "downloads.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "def filename_from_content_disposition(value):\n"
        "    filename = 'file.txt'\n"
        "    return filename\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("PIPELINE_BUGSINPY_EXECUTABLE_DIRECTORY", str(_write_fake_bugsinpy_checkout(tmp_path)))

    prompt = {
        "task": "fix_generation",
        "metadata": {"project": "httpie", "bug_id": "1", "project_path": str(project)},
        "messages": [{"role": "user", "content": "Affected file: httpie/downloads.py"}],
    }

    response = MockLLMClient().complete(prompt)

    assert response.content["patch"]
    assert response.content["repair_source"] == "mock_bugsinpy_official_fixed_version"
    fixed = response.content["fixed_files"]["httpie/downloads.py"]
    assert "except OSError" in fixed
    assert "ENAMETOOLONG" in fixed
    assert "return candidate" in fixed


def test_real_llm_prompt_uses_generic_validation_guidance():
    context = {
        "project": "httpie",
        "bug_id": "1",
        "language": "python",
        "failure_output": "ImportError inside pytest runner",
        "failing_tests": ["tests/test_downloads.py"],
        "snippets": [
            {
                "file_path": "httpie/downloads.py",
                "start_line": 1,
                "end_line": 3,
                "content": "def filename_from_content_disposition(value):\n    return filename\n",
            }
        ],
        "additional_context": {
            "selected_files": ["httpie/downloads.py"],
        },
    }

    prompt = build_bug_detection_prompt(context, real_llm=True, retry=True)
    prompt_text = "\n".join(message["content"] for message in prompt["messages"])

    assert "accepted as a reproducible python benchmark application bug" in prompt_text
    assert "Do not classify the issue as a pytest" in prompt_text
    assert "httpie/downloads.py" in prompt_text
    assert "This is a retry" in prompt_text
    assert "Known benchmark focus" not in prompt_text
    assert "filesystem filename-length limits" not in prompt_text

from llm_pipeline.prompts.builder import build_fix_generation_prompt


def test_fix_prompt_includes_focused_complete_file_for_real_llm():
    context = {
        "project": "httpie",
        "bug_id": "1",
        "language": "python",
        "failure_output": "pytest noise",
        "failing_tests": ["tests/test_downloads.py"],
        "snippets": [
            {
                "file_path": "httpie/downloads.py",
                "start_line": 1,
                "end_line": 2,
                "content": "def filename_from_content_disposition(value):\n    return filename\n",
            }
        ],
        "additional_context": {
            "focused_file_path": "httpie/downloads.py",
            "focused_file_content": "FULL FILE CONTENT\nreturn filename\n",
            "real_llm_candidate_files": ["httpie/downloads.py"],
            "selected_files": ["httpie/downloads.py"],
        },
    }
    bug = {
        "bug_found": True,
        "file_path": "httpie/downloads.py",
        "function_name": "get_unique_filename",
        "explanation": "filename too long",
    }

    prompt = build_fix_generation_prompt(context, bug, real_llm=True, retry=True)
    text = "\n".join(message["content"] for message in prompt["messages"])

    assert "Complete affected source file for repair" in text
    assert "complete corrected content for this same relative path" in text
    assert "Complete affected source file for repair" in text
    assert "FULL FILE CONTENT" in text
    assert prompt["metadata"]["retry"] is True
