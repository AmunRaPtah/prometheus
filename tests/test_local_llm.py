"""Local LLM client config resolution + request/response shaping (offline, no calls)."""

from __future__ import annotations

from prometheus import local_llm


def test_config_defaults(monkeypatch):
    monkeypatch.delenv("PROMETHEUS_LOCAL_LLM_URL", raising=False)
    monkeypatch.delenv("PROMETHEUS_LOCAL_LLM_MODEL", raising=False)
    cfg = local_llm.config()
    assert cfg["base"] == "http://127.0.0.1:8080/v1"
    assert cfg["model"] == "granite-4.0-h-1b"


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("PROMETHEUS_LOCAL_LLM_URL", "http://127.0.0.1:9999/v1")
    monkeypatch.setenv("PROMETHEUS_LOCAL_LLM_MODEL", "qwen3-4b")
    cfg = local_llm.config()
    assert cfg["base"] == "http://127.0.0.1:9999/v1" and cfg["model"] == "qwen3-4b"


def test_available_false_when_unreachable(monkeypatch):
    monkeypatch.setenv("PROMETHEUS_LOCAL_LLM_URL", "http://127.0.0.1:1/v1")  # nothing listens
    assert local_llm.available(timeout=0.2) is False


def test_build_request_shape():
    body = local_llm._build("hi", "be brief", "granite-4.0-h-1b", 10, 0.2)
    assert body["model"] == "granite-4.0-h-1b"
    assert body["messages"][0] == {"role": "system", "content": "be brief"}
    assert body["messages"][1] == {"role": "user", "content": "hi"}


def test_build_request_without_system():
    body = local_llm._build("hi", None, "m", 10, 0.2)
    assert len(body["messages"]) == 1 and body["messages"][0]["role"] == "user"


def test_parse_openai_shape():
    data = {"choices": [{"message": {"content": " [] "}}]}
    assert local_llm._parse(data) == "[]"


def test_parse_empty_choices():
    assert local_llm._parse({"choices": []}) == ""


def test_complete_raises_when_unreachable(monkeypatch):
    monkeypatch.setenv("PROMETHEUS_LOCAL_LLM_URL", "http://127.0.0.1:1/v1")
    try:
        local_llm.complete("hi", retries=1, timeout=0.2)
        assert False, "expected LocalLLMUnavailable"
    except local_llm.LocalLLMUnavailable:
        pass
