"""Gemini client protocol, Vertex implementation, and fake test client."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from app.config.settings import Settings, get_settings
from app.llm.failures import LLMError, LLMFailureClassifier
from app.llm.safety import SafetyConfiguration
from app.llm.types import (
    EmbedRequest,
    EmbedResponse,
    GenerateRequest,
    GenerateResponse,
    LLMFailureKind,
    TokenUsage,
    ToolProposal,
)


@runtime_checkable
class GeminiClient(Protocol):
    def generate(self, request: GenerateRequest) -> GenerateResponse: ...

    def embed(self, request: EmbedRequest) -> EmbedResponse: ...


class FakeGeminiClient:
    """Deterministic client for unit tests — no Vertex credentials required."""

    def __init__(self) -> None:
        self.structured_queue: list[str | dict[str, Any] | Exception] = []
        self.tool_queue: list[GenerateResponse | Exception] = []
        self.embed_queue: list[list[list[float]] | Exception] = []
        self.calls: list[GenerateRequest] = []
        self.embed_calls: list[EmbedRequest] = []

    def enqueue_structured(self, payload: str | dict[str, Any] | Exception) -> None:
        self.structured_queue.append(payload)

    def enqueue_tools(self, response: GenerateResponse | Exception) -> None:
        self.tool_queue.append(response)

    def enqueue_embed(self, vectors: list[list[float]] | Exception) -> None:
        self.embed_queue.append(vectors)

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        self.calls.append(request)
        if request.tools and self.tool_queue:
            item = self.tool_queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        if not self.structured_queue:
            text = "{}"
        else:
            item = self.structured_queue.pop(0)
            if isinstance(item, Exception):
                raise item
            text = item if isinstance(item, str) else json.dumps(item)

        return GenerateResponse(
            text=text,
            usage=TokenUsage(
                prompt_tokens=10,
                completion_tokens=20,
                total_tokens=30,
                model_id=request.model_id,
                agent=request.agent,
            ),
            finish_reason="STOP",
        )

    def embed(self, request: EmbedRequest) -> EmbedResponse:
        self.embed_calls.append(request)
        if self.embed_queue:
            item = self.embed_queue.pop(0)
            if isinstance(item, Exception):
                raise item
            vectors = item
        else:
            vectors = [[0.1] * 8 for _ in request.texts]
        return EmbedResponse(
            vectors=vectors,
            usage=TokenUsage(
                prompt_tokens=len(request.texts),
                completion_tokens=0,
                total_tokens=len(request.texts),
                model_id=request.model_id,
            ),
            model_id=request.model_id,
        )


class VertexGeminiClient:
    """Official Google Gen AI Python SDK configured for Vertex AI (ADC / WIF)."""

    def __init__(
        self,
        settings: Settings | None = None,
        safety: SafetyConfiguration | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.safety = safety or SafetyConfiguration()
        self.classifier = LLMFailureClassifier()
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.settings.google_cloud_project:
            raise LLMError(
                "GOOGLE_CLOUD_PROJECT is required for VertexGeminiClient",
                kind=LLMFailureKind.MODEL_UNAVAILABLE,
                retryable=False,
            )
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise LLMError(
                "google-genai SDK is not installed",
                kind=LLMFailureKind.PERMANENT,
                retryable=False,
            ) from exc

        if self.settings.google_application_credentials:
            raw_path = Path(self.settings.google_application_credentials)
            resolved_cred: Path | None = None
            if raw_path.is_absolute() and raw_path.exists():
                resolved_cred = raw_path
            else:
                module_dir = Path(__file__).resolve().parent
                candidates = [
                    Path.cwd() / raw_path,
                    module_dir.parents[3] / raw_path,
                    module_dir.parents[2] / raw_path,
                ]
                for cand in candidates:
                    if cand.exists():
                        resolved_cred = cand.resolve()
                        break
            if resolved_cred:
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(resolved_cred)

        http_options = types.HttpOptions(
            timeout=int(self.settings.gemini_timeout_seconds * 1000)
        )
        self._client = genai.Client(
            vertexai=bool(self.settings.google_genai_use_vertexai),
            project=self.settings.google_cloud_project,
            location=self.settings.google_cloud_location,
            http_options=http_options,
        )
        return self._client

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        try:
            from google.genai import types
        except ImportError as exc:
            raise LLMError(
                "google-genai SDK is not installed",
                kind=LLMFailureKind.PERMANENT,
                retryable=False,
            ) from exc

        client = self._get_client()
        contents = self._to_contents(request, types)
        config_kwargs: dict[str, Any] = {
            "temperature": request.temperature
            if request.temperature is not None
            else self.settings.gemini_temperature,
            "max_output_tokens": request.max_output_tokens
            if request.max_output_tokens is not None
            else self.settings.gemini_max_output_tokens,
            "safety_settings": [
                types.SafetySetting(category=s["category"], threshold=s["threshold"])
                for s in self.safety.to_sdk_dicts()
            ],
            "labels": request.labels or None,
        }
        if request.system_instruction:
            config_kwargs["system_instruction"] = request.system_instruction
        if request.response_mime_type:
            config_kwargs["response_mime_type"] = request.response_mime_type
        if request.response_schema is not None:
            config_kwargs["response_schema"] = request.response_schema
        if request.tools:
            config_kwargs["tools"] = self._to_tools(request.tools, types)
        if request.timeout_seconds is not None:
            config_kwargs["http_options"] = types.HttpOptions(
                timeout=int(request.timeout_seconds * 1000)
            )

        try:
            response = client.models.generate_content(
                model=request.model_id,
                contents=contents,
                config=types.GenerateContentConfig(**config_kwargs),
            )
        except Exception as exc:  # noqa: BLE001
            raise self.classifier.classify(exc) from exc

        return self._parse_generate_response(response, request)

    def embed(self, request: EmbedRequest) -> EmbedResponse:
        client = self._get_client()
        try:
            result = client.models.embed_content(
                model=request.model_id,
                contents=request.texts,
            )
        except Exception as exc:  # noqa: BLE001
            raise self.classifier.classify(exc) from exc

        embeddings = getattr(result, "embeddings", None) or []
        vectors: list[list[float]] = []
        for item in embeddings:
            values = getattr(item, "values", None)
            if values is not None:
                vectors.append(list(values))
        usage = TokenUsage(
            prompt_tokens=len(request.texts),
            completion_tokens=0,
            total_tokens=len(request.texts),
            model_id=request.model_id,
        )
        return EmbedResponse(vectors=vectors, usage=usage, model_id=request.model_id)

    def _to_contents(self, request: GenerateRequest, types: Any) -> list[Any]:
        contents: list[Any] = []
        for message in request.messages:
            role = "user" if message.role == "user" else "model"
            parts: list[Any] = []
            if message.text:
                parts.append(types.Part.from_text(text=message.text))
            for proposal in message.tool_proposals:
                parts.append(
                    types.Part.from_function_call(
                        name=proposal.name,
                        args=proposal.arguments,
                    )
                )
            for result in message.tool_results:
                parts.append(
                    types.Part.from_function_response(
                        name=result.name,
                        response={
                            "ok": result.ok,
                            "result": result.result,
                            "error_code": result.error_code,
                            "error_message": result.error_message,
                        },
                    )
                )
            if parts:
                contents.append(types.Content(role=role, parts=parts))
        return contents

    def _to_tools(self, tools: list[dict[str, Any]], types: Any) -> list[Any]:
        declarations = []
        for tool in tools:
            declarations.append(
                types.FunctionDeclaration(
                    name=tool["name"],
                    description=tool.get("description", ""),
                    parameters=tool.get("parameters"),
                )
            )
        return [types.Tool(function_declarations=declarations)]

    def _parse_generate_response(
        self, response: Any, request: GenerateRequest
    ) -> GenerateResponse:
        # Safety blocks
        prompt_feedback = getattr(response, "prompt_feedback", None)
        block_reason = getattr(prompt_feedback, "block_reason", None) if prompt_feedback else None
        if block_reason:
            raise self.classifier.from_blocked(str(block_reason))

        text: str | None = None
        proposals: list[ToolProposal] = []
        finish_reason: str | None = None
        candidates = getattr(response, "candidates", None) or []
        if candidates:
            candidate = candidates[0]
            finish_reason = str(getattr(candidate, "finish_reason", None) or "")
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None) or []
            text_parts: list[str] = []
            for part in parts:
                function_call = getattr(part, "function_call", None)
                if function_call is not None:
                    proposals.append(
                        ToolProposal(
                            name=str(function_call.name),
                            arguments=dict(getattr(function_call, "args", {}) or {}),
                        )
                    )
                part_text = getattr(part, "text", None)
                if part_text:
                    text_parts.append(part_text)
            text = "".join(text_parts) if text_parts else None

        usage_meta = getattr(response, "usage_metadata", None)
        usage = TokenUsage(
            prompt_tokens=int(getattr(usage_meta, "prompt_token_count", 0) or 0),
            completion_tokens=int(getattr(usage_meta, "candidates_token_count", 0) or 0),
            total_tokens=int(getattr(usage_meta, "total_token_count", 0) or 0),
            model_id=request.model_id,
            agent=request.agent,
        )
        return GenerateResponse(
            text=text,
            tool_proposals=proposals,
            usage=usage,
            finish_reason=finish_reason,
            blocked=False,
            raw={},
        )


def create_gemini_client(
    settings: Settings | None = None,
    *,
    force_fake: bool = False,
) -> GeminiClient:
    settings = settings or get_settings()
    mode = settings.gemini_client_mode
    if force_fake or mode == "fake" or settings.app_env == "test":
        return FakeGeminiClient()
    if mode == "vertex" or (mode == "auto" and settings.gemini_configured()):
        return VertexGeminiClient(settings=settings)
    return FakeGeminiClient()
