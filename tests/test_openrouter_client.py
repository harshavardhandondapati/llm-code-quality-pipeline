from llm_pipeline.model.openrouter_client import OpenRouterLLMClient


def test_openrouter_bug_detection_response_is_normalised():
    def fake_transport(payload, headers, timeout):
        assert payload["model"] == "openrouter/free"
        assert headers["Authorization"] == "Bearer test-key"
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"bug_found": true, "file_path": "httpie/downloads.py", "function_name": "filename_from_content_disposition", "line_start": null, "line_end": null, "explanation": "filename length is not bounded", "confidence": 0.91}'
                    }
                }
            ]
        }

    client = OpenRouterLLMClient(api_key="test-key", model_name="openrouter/free", transport=fake_transport)
    response = client.complete({"task": "bug_detection", "messages": [{"role": "user", "content": "test"}]})

    assert response.provider == "openrouter"
    assert response.content["bug_found"] is True
    assert response.content["file_path"] == "httpie/downloads.py"
    assert response.content["confidence"] == 0.91


def test_openrouter_fix_generation_extracts_json_inside_markdown():
    diff = "--- a/httpie/downloads.py\n+++ b/httpie/downloads.py\n@@ -1 +1 @@\n-return filename\n+return filename[:255]\n"

    def fake_transport(payload, headers, timeout):
        return {
            "choices": [
                {
                    "message": {
                        "content": "```json\n{\"patch\": " + repr(diff).replace("'", '"') + ", \"explanation\": \"limit filename\", \"files_modified\": [\"httpie/downloads.py\"], \"fixed_files\": {}}\n```"
                    }
                }
            ]
        }

    client = OpenRouterLLMClient(api_key="test-key", transport=fake_transport)
    response = client.complete({"task": "fix_generation", "messages": [{"role": "user", "content": "test"}]})

    assert response.content["patch"].startswith("--- a/httpie/downloads.py")
    assert response.content["files_modified"] == ["httpie/downloads.py"]
    assert response.content["fixed_files"] == {}


def test_openrouter_unparseable_response_does_not_crash():
    def fake_transport(payload, headers, timeout):
        return {"choices": [{"message": {"content": "I cannot produce a patch."}}]}

    client = OpenRouterLLMClient(api_key="test-key", transport=fake_transport)
    response = client.complete({"task": "fix_generation", "messages": [{"role": "user", "content": "test"}]})

    assert response.content["patch"] == ""
    assert response.content["parse_error"] is True


def test_openrouter_payload_requests_json_and_excludes_reasoning():
    captured = {}

    def fake_transport(payload, headers, timeout):
        captured.update(payload)
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"patch": "", "explanation": "no patch", "files_modified": [], "fixed_files": {}}'
                    }
                }
            ]
        }

    client = OpenRouterLLMClient(api_key="test-key", transport=fake_transport)
    client.complete({"task": "fix_generation", "messages": [{"role": "user", "content": "test"}]})

    assert captured["response_format"] == {"type": "json_object"}
    assert captured["reasoning"] == {"exclude": True}


def test_openrouter_extracts_reasoning_when_content_is_null():
    def fake_transport(payload, headers, timeout):
        return {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "reasoning": '{"patch": "--- a/httpie/downloads.py\\n+++ b/httpie/downloads.py\\n@@ -1 +1 @@\\n-return filename\\n+return filename[:255]\\n", "explanation": "limit filename", "files_modified": ["httpie/downloads.py"], "fixed_files": {}}',
                    }
                }
            ]
        }

    client = OpenRouterLLMClient(api_key="test-key", transport=fake_transport)
    response = client.complete({"task": "fix_generation", "messages": [{"role": "user", "content": "test"}]})

    assert response.raw_text != "None"
    assert response.content["patch"].startswith("--- a/httpie/downloads.py")
