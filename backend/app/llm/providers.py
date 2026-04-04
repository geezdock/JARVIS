from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from urllib import error, request

from app.config import settings


class LLMProviderError(Exception):
    def __init__(self, message: str, retryable: bool = False, code: str | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.code = code


@dataclass
class BaseLLMProvider:
    provider_name: str

    def is_configured(self) -> bool:
        raise NotImplementedError

    def chat_completion(self, payload: dict[str, Any], timeout_seconds: int = 60) -> dict[str, Any]:
        raise NotImplementedError

    def create_realtime_session(
        self,
        interview_role: str,
        interview_plan: dict[str, Any],
        resume_summary: str,
        include_client_secret: bool = False,
    ) -> dict[str, Any] | None:
        return None


class OpenRouterProvider(BaseLLMProvider):
    def __init__(self) -> None:
        super().__init__(provider_name="openrouter")

    def is_configured(self) -> bool:
        return bool(settings.openrouter_api_key)

    def chat_completion(self, payload: dict[str, Any], timeout_seconds: int = 60) -> dict[str, Any]:
        if not self.is_configured():
            raise LLMProviderError("OPENROUTER_API_KEY is not configured", retryable=False, code="missing_key")

        provider_payload = dict(payload)
        provider_payload.setdefault("model", settings.llm_model or "openai/gpt-4o-mini")

        headers = {
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if settings.openrouter_site_url:
            headers["HTTP-Referer"] = settings.openrouter_site_url
        if settings.openrouter_app_name:
            headers["X-Title"] = settings.openrouter_app_name

        req = request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps(provider_payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        return _perform_json_request(req, timeout_seconds)


class OpenAIProvider(BaseLLMProvider):
    def __init__(self) -> None:
        super().__init__(provider_name="openai")

    def is_configured(self) -> bool:
        return bool(settings.openai_api_key)

    def chat_completion(self, payload: dict[str, Any], timeout_seconds: int = 60) -> dict[str, Any]:
        if not self.is_configured():
            raise LLMProviderError("OPENAI_API_KEY is not configured", retryable=False, code="missing_key")

        provider_payload = dict(payload)
        provider_payload.setdefault("model", settings.llm_model or "gpt-4o-mini")

        req = request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(provider_payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        return _perform_json_request(req, timeout_seconds)

    def create_realtime_session(
        self,
        interview_role: str,
        interview_plan: dict[str, Any],
        resume_summary: str,
        include_client_secret: bool = False,
    ) -> dict[str, Any] | None:
        if not self.is_configured():
            raise LLMProviderError("OPENAI_API_KEY is not configured", retryable=False, code="missing_key")

        realtime_cfg = interview_plan.get("realtime") if isinstance(interview_plan, dict) else {}
        max_questions = 6
        if isinstance(realtime_cfg, dict):
            configured_max = realtime_cfg.get("maxQuestions")
            if isinstance(configured_max, int) and configured_max > 0:
                max_questions = configured_max

        flow = interview_plan.get("flow") if isinstance(interview_plan, dict) else []
        role_question_bank = interview_plan.get("questions") if isinstance(interview_plan, dict) else []
        job_context = interview_plan.get("job_context") if isinstance(interview_plan, dict) else {}
        job_title = job_context.get("title") if isinstance(job_context, dict) else None
        required_skills = job_context.get("required_skills") if isinstance(job_context, dict) else []

        instructions = (
            "You are a professional technical interviewer conducting a live one-on-one interview. "
            f"Target role: {interview_role}. "
            f"Ask exactly one question at a time and keep it under 30 words. "
            f"Ask exactly {max_questions} questions total. "
            "Prefix each question with Q<number>/<total>:. "
            "Do not answer for the candidate. Do not ask multiple questions in one turn. "
            "After asking the last question and receiving the candidate response, say exactly: INTERVIEW_COMPLETE. "
            "Use the resume summary and job context to personalize each follow-up question and avoid repeating topics. "
            f"Resume summary: {resume_summary or 'Not provided'}. "
            f"Interview flow topics: {', '.join(flow) if isinstance(flow, list) else ''}. "
            f"Seed question bank: {' | '.join(role_question_bank) if isinstance(role_question_bank, list) else ''}. "
            f"Job title: {job_title or 'Not provided'}. "
            f"Required skills: {', '.join(required_skills) if isinstance(required_skills, list) else ''}."
        )

        payload = {
            "model": settings.interview_realtime_model or "gpt-4o-realtime-preview-2024-12-17",
            "voice": settings.interview_realtime_voice or "alloy",
            "modalities": ["text", "audio"],
            "instructions": instructions,
        }

        req = request.Request(
            "https://api.openai.com/v1/realtime/sessions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        session_payload = _perform_json_request(req, timeout_seconds=20)

        if not include_client_secret and isinstance(session_payload, dict) and "client_secret" in session_payload:
            session_payload = dict(session_payload)
            session_payload.pop("client_secret", None)

        return session_payload


class GroqProvider(BaseLLMProvider):
    def __init__(self) -> None:
        super().__init__(provider_name="groq")

    def is_configured(self) -> bool:
        return bool(settings.groq_api_key)

    def chat_completion(self, payload: dict[str, Any], timeout_seconds: int = 60) -> dict[str, Any]:
        if not self.is_configured():
            raise LLMProviderError("GROQ_API_KEY is not configured", retryable=False, code="missing_key")

        provider_payload = dict(payload)
        provider_payload.setdefault("model", settings.llm_model or "llama-3.1-8b-instant")

        req = request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=json.dumps(provider_payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {settings.groq_api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        return _perform_json_request(req, timeout_seconds)


def get_llm_provider_by_name(provider_name: str) -> BaseLLMProvider:
    normalized = (provider_name or "openrouter").strip().lower()
    if normalized == "openai":
        return OpenAIProvider()
    if normalized == "groq":
        return GroqProvider()
    return OpenRouterProvider()


def get_llm_provider_chain(primary: str, fallbacks_csv: str) -> list[BaseLLMProvider]:
    ordered_names: list[str] = []
    if primary:
        ordered_names.append(primary)
    if fallbacks_csv:
        ordered_names.extend([chunk.strip() for chunk in fallbacks_csv.split(",") if chunk.strip()])

    deduped: list[str] = []
    for name in ordered_names:
        normalized = name.lower()
        if normalized not in deduped:
            deduped.append(normalized)

    return [get_llm_provider_by_name(name) for name in deduped]


def _messages_to_text(messages: Any) -> str:
    if not isinstance(messages, list):
        return ""
    lines: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user")
        content = str(message.get("content") or "")
        lines.append(f"[{role}] {content}")
    return "\n".join(lines).strip()


def _perform_json_request(req: request.Request, timeout_seconds: int) -> dict[str, Any]:
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            parsed = json.loads(response.read().decode("utf-8"))
            if not isinstance(parsed, dict):
                raise LLMProviderError("Provider returned unexpected payload", retryable=False)
            return parsed
    except error.HTTPError as exc:
        raw_error = exc.read().decode("utf-8") if exc.fp else ""
        status_code = getattr(exc, "code", None)
        retryable = status_code in {408, 409, 425, 429, 500, 502, 503, 504}
        error_code, error_message = _extract_error(raw_error)
        raise LLMProviderError(error_message or raw_error or str(exc.reason), retryable=retryable, code=error_code) from exc
    except LLMProviderError:
        raise
    except Exception as exc:
        raise LLMProviderError(str(exc), retryable=True) from exc


def _extract_error(raw_error: str) -> tuple[str | None, str | None]:
    if not raw_error:
        return None, None

    try:
        parsed = json.loads(raw_error)
    except Exception:
        normalized = raw_error.lower()
        if "insufficient_quota" in normalized:
            return "insufficient_quota", None
        return None, raw_error

    if not isinstance(parsed, dict):
        return None, raw_error

    # OpenAI-compatible
    error_obj = parsed.get("error")
    if isinstance(error_obj, dict):
        code = error_obj.get("code") if isinstance(error_obj.get("code"), str) else None
        message = error_obj.get("message") if isinstance(error_obj.get("message"), str) else None
        return code, message

    # Gemini-style
    if isinstance(parsed.get("error"), dict):
        gemini_error = parsed["error"]
        code = str(gemini_error.get("status") or "") or None
        message = str(gemini_error.get("message") or "") or None
        return code, message

    return None, raw_error


@lru_cache(maxsize=1)
def get_llm_provider() -> BaseLLMProvider:
    provider = (settings.llm_provider or "openrouter").strip().lower()
    return get_llm_provider_by_name(provider)
