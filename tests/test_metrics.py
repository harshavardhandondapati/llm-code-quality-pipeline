from llm_pipeline.evaluation.metrics import create_evaluation_metrics


def test_metrics_accepts_local_fallback_repair_without_llm_patch(tmp_path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "bug_detection_result.json").write_text('{"bug_found": true, "file_path": "httpie/downloads.py", "confidence": 0.9}', encoding="utf-8")
    (outputs / "fix_generation_result.json").write_text('{"patch": "", "files_modified": [], "fixed_files": {}}', encoding="utf-8")
    (outputs / "local_repair_fallback_result.json").write_text('{"patch": "diff --git a/httpie/downloads.py b/httpie/downloads.py", "files_modified": ["httpie/downloads.py"], "repair_source": "local_benchmark_fallback_after_real_llm_detection"}', encoding="utf-8")
    (outputs / "validation_result.json").write_text('{"patch_applied": true, "compilation_passed": true, "triggering_tests_passed": true, "changed_files": ["httpie/downloads.py"], "repair_source": "local_benchmark_fallback_after_llm_validation_failure"}', encoding="utf-8")
    (outputs / "post_fix_evaluation_result.json").write_text('{"improved": true, "repair_status": "successful_repair"}', encoding="utf-8")
    (outputs / "human_approval_decision.json").write_text('{"allows_progress": true, "decision": "approved", "reviewer": "Hari"}', encoding="utf-8")

    candidate = {"project": "httpie", "bug_id": "1", "status": "accepted", "baseline_failure_observed": True}

    metrics = create_evaluation_metrics(candidate_record=candidate, outputs_dir=outputs)

    assert metrics["overall_status"] == "successful"
    assert metrics["patch_present"] is True
    assert metrics["patch_applied"] is True
    assert metrics["post_fix_improved"] is True
    assert metrics["local_fallback_used"] is True
    assert metrics["repair_source"] == "local_benchmark_fallback_after_llm_validation_failure"
