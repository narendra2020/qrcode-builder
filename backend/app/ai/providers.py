"""
Multimodal page analysis through the platform's configured LLM provider
(settings.LLM_PROVIDER, shared with portfolio-builder): Anthropic Claude
or Azure OpenAI. Each provider returns the parsed PAGE_SCHEMA dict or
raises AiError with `retryable` set, so the job runner owns retry policy.

Anthropic: structured outputs (output_config.format json_schema) for a
schema-valid JSON reply, adaptive thinking at a configurable effort, and
the server-side refusal fallback. The response is read as raw JSON via
with_raw_response so the pinned SDK version doesn't need to know newer
content-block types.
"""
import base64
import json
import re
from typing import Protocol

import anthropic
import openai

from app.ai.schema import PAGE_SCHEMA, USER_INSTRUCTION, system_prompt
from app.core.config import settings


class AiError(Exception):
    def __init__(self, code: str, message: str, retryable: bool):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class PageAnalyzer(Protocol):
    provider: str
    model: str

    def analyze_page(self, image_bytes: bytes, media_type: str) -> dict:
        ...


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


_TRAILING_COMMA_RE = re.compile(r'"(?:[^"\\]|\\.)*"|,(\s*[}\]])')


def _strip_trailing_commas(text: str) -> str:
    # Models occasionally emit `,}` / `,]`; string literals are matched first so their contents are left alone.
    return _TRAILING_COMMA_RE.sub(lambda m: m.group(1) if m.group(1) else m.group(0), text)


def _parse_json(text: str) -> dict:
    cleaned = _FENCE_RE.sub("", text.strip())
    try:
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            data = json.loads(_strip_trailing_commas(cleaned))
    except (json.JSONDecodeError, TypeError) as exc:
        raise AiError("bad_output", "The AI returned an unreadable response.", retryable=True) from exc
    if not isinstance(data, dict):
        raise AiError("bad_output", "The AI returned an unexpected response.", retryable=True)
    return data


class AnthropicAnalyzer:
    provider = "anthropic"

    def __init__(self):
        self.model = settings.QR_AI_MODEL
        # Retries are owned by the job runner (explicit attempts + backoff).
        self._client = anthropic.Anthropic(
            api_key=settings.ANTHROPIC_API_KEY or None,
            base_url=settings.ANTHROPIC_BASE_URL or None,
            timeout=settings.AI_TIMEOUT_SECONDS,
            max_retries=0,
        )

    def analyze_page(self, image_bytes: bytes, media_type: str) -> dict:
        body: dict = {
            "thinking": {"type": "adaptive"},
            "output_config": {
                "effort": settings.QR_AI_EFFORT,
                "format": {"type": "json_schema", "schema": PAGE_SCHEMA},
            },
        }
        headers: dict = {}
        if settings.QR_AI_REFUSAL_FALLBACK:
            body["fallbacks"] = "default"
            headers["anthropic-beta"] = "server-side-fallback-2026-07-01"
        content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.standard_b64encode(image_bytes).decode("ascii"),
                },
            },
            {"type": "text", "text": USER_INSTRUCTION},
        ]
        try:
            raw = self._client.messages.with_raw_response.create(
                model=self.model,
                max_tokens=settings.QR_AI_MAX_TOKENS,
                system=system_prompt(),
                messages=[{"role": "user", "content": content}],
                extra_body=body,
                extra_headers=headers or None,
            )
            data = raw.http_response.json()
        except anthropic.APITimeoutError as exc:
            raise AiError("timeout", "The AI took too long to respond.", retryable=True) from exc
        except anthropic.APIConnectionError as exc:
            raise AiError("connection", "Could not reach the AI service.", retryable=True) from exc
        except anthropic.RateLimitError as exc:
            raise AiError("rate_limited", "The AI service is busy.", retryable=True) from exc
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            raise AiError("not_configured", "The AI service is not configured correctly.", retryable=False) from exc
        except anthropic.BadRequestError as exc:
            raise AiError("bad_request", "The AI service rejected this image.", retryable=False) from exc
        except anthropic.APIStatusError as exc:
            retryable = exc.status_code >= 500 or exc.status_code in (408, 409, 529)
            raise AiError("provider_error", "The AI service returned an error.", retryable=retryable) from exc

        stop_reason = data.get("stop_reason")
        if stop_reason == "refusal":
            raise AiError("refused", "The AI declined to process this image.", retryable=False)
        if stop_reason == "max_tokens":
            raise AiError("too_long", "This page has too many items to read in one pass. Try photographing it in two halves.", retryable=False)
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        if not text.strip():
            raise AiError("bad_output", "The AI returned an empty response.", retryable=True)
        return _parse_json(text)


class AzureOpenAIAnalyzer:
    provider = "azure_openai"

    def __init__(self):
        self.model = settings.AZURE_OPENAI_DEPLOYMENT
        self._client = openai.AzureOpenAI(
            api_key=settings.AZURE_OPENAI_API_KEY,
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_version=settings.AZURE_OPENAI_API_VERSION,
            timeout=settings.AI_TIMEOUT_SECONDS,
            max_retries=0,
        )

    def analyze_page(self, image_bytes: bytes, media_type: str) -> dict:
        data_uri = f"data:{media_type};base64,{base64.standard_b64encode(image_bytes).decode('ascii')}"
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                max_tokens=16000,
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "menu_page", "strict": True, "schema": PAGE_SCHEMA},
                },
                messages=[
                    {"role": "system", "content": system_prompt()},
                    {"role": "user", "content": [
                        {"type": "image_url", "image_url": {"url": data_uri, "detail": "high"}},
                        {"type": "text", "text": USER_INSTRUCTION},
                    ]},
                ],
            )
        except openai.APITimeoutError as exc:
            raise AiError("timeout", "The AI took too long to respond.", retryable=True) from exc
        except openai.APIConnectionError as exc:
            raise AiError("connection", "Could not reach the AI service.", retryable=True) from exc
        except openai.RateLimitError as exc:
            raise AiError("rate_limited", "The AI service is busy.", retryable=True) from exc
        except openai.BadRequestError as exc:
            raise AiError("bad_request", "The AI service rejected this image.", retryable=False) from exc
        except openai.APIStatusError as exc:
            raise AiError("provider_error", "The AI service returned an error.", retryable=exc.status_code >= 500) from exc

        choice = response.choices[0] if response.choices else None
        if not choice or not choice.message or not choice.message.content:
            raise AiError("bad_output", "The AI returned an empty response.", retryable=True)
        if choice.finish_reason == "length":
            raise AiError("too_long", "This page has too many items to read in one pass. Try photographing it in two halves.", retryable=False)
        return _parse_json(choice.message.content)


_override: PageAnalyzer | None = None


def set_analyzer_override(analyzer: PageAnalyzer | None) -> None:
    """Tests inject a fake analyzer here — no live AI calls in the suite."""
    global _override
    _override = analyzer


def get_analyzer() -> PageAnalyzer:
    if _override is not None:
        return _override
    if settings.LLM_PROVIDER == "azure_openai":
        if not (settings.AZURE_OPENAI_API_KEY and settings.AZURE_OPENAI_ENDPOINT and settings.AZURE_OPENAI_DEPLOYMENT):
            raise AiError("not_configured", "AI extraction is not configured on this server.", retryable=False)
        return AzureOpenAIAnalyzer()
    if settings.LLM_PROVIDER == "anthropic":
        if not settings.ANTHROPIC_API_KEY:
            raise AiError("not_configured", "AI extraction is not configured on this server.", retryable=False)
        return AnthropicAnalyzer()
    raise AiError("not_configured", "AI extraction is turned off on this server. Add your items manually.", retryable=False)
