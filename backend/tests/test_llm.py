import json

import httpx
import pytest

from app.llm import LLMError, LLMSettings, OpenAIProvider


def response_payload():
    return {"status": "completed", "output": [{"type": "message", "content": [{
        "type": "output_text", "text": json.dumps({"answer": "Not enough evidence.", "insufficient_evidence": True, "citations": []}),
    }]}]}


def provider(handler):
    return OpenAIProvider(LLMSettings(api_key="fictional-key", model="test-model"),
                          transport=httpx.MockTransport(handler), sleep=lambda _: None)


@pytest.mark.parametrize("failure, expected", [
    ("timeout", 504), ("connect", 503), (500, 503), (401, 503), (403, 503), (404, 503), (400, 502), (429, 429),
])
def test_failures_have_bounded_retries_and_sanitized_errors(failure, expected):
    calls = []

    def handler(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("secret-upstream-text", request=request)
        if failure == "connect":
            raise httpx.ConnectError("secret-upstream-text", request=request)
        return httpx.Response(failure, text="secret-upstream-text")

    with pytest.raises(LLMError) as raised:
        provider(handler).generate("instructions", "context")
    assert raised.value.status_code == expected
    assert "secret-upstream-text" not in str(raised.value)
    assert len(calls) == (2 if failure in ("timeout", "connect", 500) else 1)


def test_retry_can_recover():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503) if len(calls) == 1 else httpx.Response(200, json=response_payload())

    assert provider(handler).generate("instructions", "context").insufficient_evidence
    assert len(calls) == 2


@pytest.mark.parametrize("payload", [
    {"status": "incomplete", "output": []}, {"status": "completed", "output": []},
    {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "not json"}]}]},
    {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": '{"answer":"Missing fields"}'}]}]},
])
def test_invalid_and_incomplete_model_output_is_rejected(payload):
    with pytest.raises(LLMError) as raised:
        provider(lambda _: httpx.Response(200, json=payload)).generate("instructions", "context")
    assert raised.value.status_code == 502


def test_dotenv_loading_uses_process_precedence_without_mutating_environment(tmp_path, monkeypatch):
    for name in ["OPENAI_API_KEY", "LLM_MODEL", "LLM_PROVIDER", "LLM_TIMEOUT_SECONDS", "LLM_MAX_OUTPUT_TOKENS"]:
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / ".env"
    path.write_text('OPENAI_API_KEY="fictional-local-key"\nLLM_MODEL=local-model\nLLM_TIMEOUT_SECONDS=12\n')
    monkeypatch.setenv("LLM_MODEL", "process-model")
    settings = LLMSettings.load(path)
    assert settings.model == "process-model"
    assert settings.timeout_seconds == 12
    assert settings.api_key.get_secret_value() == "fictional-local-key"
    assert "fictional-local-key" not in repr(settings)
    import os
    assert "OPENAI_API_KEY" not in os.environ
