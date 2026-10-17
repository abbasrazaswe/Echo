"""Provider boundary for structured replies; no credentials or transcripts in logs."""

import time
from pathlib import Path
from typing import Literal, Protocol

import httpx
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    message_id: str = Field(min_length=1)
    quote: str = Field(min_length=1, max_length=500)


class ModelAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    answer: str = Field(min_length=1, max_length=8000)
    insufficient_evidence: bool
    citations: list[Citation] = Field(max_length=10)
    live_citations: list["LiveCitation"] = Field(max_length=10)
    follow_up_question: str | None = Field(max_length=220)


class LiveCitation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    memory_id: str = Field(min_length=1)
    quote: str = Field(min_length=1, max_length=220)


ModelAnswer.model_rebuild()


class LLMProvider(Protocol):
    model: str

    def generate(self, instructions: str, context: str) -> ModelAnswer: ...


class LLMError(RuntimeError):
    def __init__(self, status_code: int, message: str, retry_after: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class ModelRefused(RuntimeError):
    pass


class LLMSettings(BaseModel):
    provider: Literal["openai"] = "openai"
    api_key: SecretStr = SecretStr("")
    model: str = ""
    timeout_seconds: float = Field(default=20, ge=1, le=60)
    max_output_tokens: int = Field(default=1600, ge=256, le=4096)

    @classmethod
    def load(cls, path: Path):
        import os

        local = dotenv_values(path) if path.exists() else {}

        def value(name, default):
            return os.environ.get(name, local.get(name) or default)

        return cls(
            provider=value("LLM_PROVIDER", "openai"), api_key=value("OPENAI_API_KEY", ""),
            model=value("LLM_MODEL", ""), timeout_seconds=value("LLM_TIMEOUT_SECONDS", 20),
            max_output_tokens=value("LLM_MAX_OUTPUT_TOKENS", 1600),
        )


class OpenAIProvider:
    def __init__(self, settings: LLMSettings, *, transport=None, sleep=time.sleep):
        self.settings = settings
        self.model = settings.model
        self.transport = transport
        self.sleep = sleep

    def generate(self, instructions: str, context: str) -> ModelAnswer:
        if not self.settings.api_key.get_secret_value() or not self.model.strip():
            raise LLMError(503, "Configure OPENAI_API_KEY and LLM_MODEL in backend/.env, then restart the server.")
        body = {
            "model": self.model, "instructions": instructions,
            "input": [{"role": "user", "content": context}], "store": False,
            "max_output_tokens": self.settings.max_output_tokens,
            "text": {"format": {
                "type": "json_schema", "name": "echo_grounded_reply", "strict": True,
                "schema": ModelAnswer.model_json_schema(),
            }},
        }
        with httpx.Client(timeout=self.settings.timeout_seconds, transport=self.transport, trust_env=False) as client:
            for attempt in range(2):
                try:
                    response = client.post(
                        "https://api.openai.com/v1/responses", json=body,
                        headers={"Authorization": "Bearer " + self.settings.api_key.get_secret_value()},
                    )
                except httpx.TimeoutException as error:
                    if attempt == 0:
                        self.sleep(0.25)
                        continue
                    raise LLMError(504, "The model provider timed out. Try again later.") from error
                except httpx.RequestError as error:
                    if attempt == 0:
                        self.sleep(0.25)
                        continue
                    raise LLMError(503, "Cannot connect to the model provider. Try again later.") from error
                if response.status_code == 429:
                    retry = response.headers.get("Retry-After", "30")
                    retry = str(max(1, min(3600, int(retry)))) if retry.isdigit() else "30"
                    raise LLMError(429, "The model provider is rate limited. Try again later.", retry)
                if response.status_code >= 500:
                    if attempt == 0:
                        self.sleep(0.25)
                        continue
                    raise LLMError(503, "The model provider is temporarily unavailable.")
                if response.status_code in (401, 403, 404):
                    raise LLMError(503, "The model provider rejected the credentials or configured model. Check backend/.env.")
                if not response.is_success:
                    raise LLMError(502, "The model provider rejected the request. Check model compatibility and server configuration.")
                break
        try:
            payload = response.json()
            if payload.get("status") != "completed":
                raise ValueError("Incomplete model response")
            texts = []
            for item in payload.get("output", []):
                if item.get("type") != "message":
                    continue
                for content in item.get("content", []):
                    if content.get("type") == "refusal":
                        raise ModelRefused()
                    if content.get("type") == "output_text":
                        texts.append(content["text"])
            return ModelAnswer.model_validate_json("".join(texts))
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise LLMError(502, "The model returned an incomplete or invalid structured reply.") from error
