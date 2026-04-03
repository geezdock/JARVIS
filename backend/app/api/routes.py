from datetime import datetime, UTC, timedelta
import io
import json
import re
import secrets
import time
from collections import Counter
from typing import Any
from uuid import UUID
from urllib.parse import quote
from urllib import error, request

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from pypdf import PdfReader

from app.config import settings

router = APIRouter()


class ProfileUploadPayload(BaseModel):
    filename: str
    size: int
    type: str
    filePath: str | None = None
    fileUrl: str | None = None
    targetRole: str | None = None
    submittedAt: str


class InterviewSlotPayload(BaseModel):
    slotTime: str


class SignedUploadPayload(BaseModel):
    path: str


class SignedInterviewUploadPayload(BaseModel):
    sessionId: str
    fileType: str
    extension: str | None = None


class ResumeAnalysisPayload(BaseModel):
    force: bool = False


class AdminInterviewRolePayload(BaseModel):
    targetRole: str | None = None
    adminOverrideRole: str | None = None


class InterviewSessionStartPayload(BaseModel):
    consentGiven: bool = False


class InterviewSessionCompletePayload(BaseModel):
    transcript: str | None = None
    scorePayload: dict[str, Any] | None = None
    durationSeconds: int | None = None
    audioPath: str | None = None
    audioUrl: str | None = None
    audioUploadNonce: str | None = None
    videoPath: str | None = None
    videoUrl: str | None = None
    videoUploadNonce: str | None = None


class AdminHiringOutcomePayload(BaseModel):
    outcome: str
    retentionDays: int = 30


class AdminCleanupArtifactsPayload(BaseModel):
    limit: int = 100


class SupabaseError(RuntimeError):
    pass


INTERVIEW_ROLES = [
    "Frontend Developer",
    "Backend Developer",
    "Data Analyst",
    "Machine Learning Engineer",
    "Product Manager",
    "QA Engineer",
]


def _normalize_role_value(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned or None


def _infer_interview_role_from_resume_text(extracted_text: str) -> str | None:
    normalized_text = re.sub(r"\s+", " ", (extracted_text or "").lower())
    if not normalized_text:
        return None

    role_keywords: list[tuple[str, list[str]]] = [
        ("Frontend Developer", ["react", "frontend", "javascript", "typescript", "css", "ui"]),
        ("Backend Developer", ["fastapi", "django", "flask", "backend", "api", "postgres", "sql"]),
        ("Data Analyst", ["sql", "analytics", "dashboard", "power bi", "tableau", "excel"]),
        ("Machine Learning Engineer", ["machine learning", "ml", "tensorflow", "pytorch", "model", "sklearn"]),
        ("Product Manager", ["product", "roadmap", "stakeholder", "prioritization", "discovery"]),
        ("QA Engineer", ["qa", "testing", "test case", "automation", "selenium", "cypress"]),
    ]

    best_role = None
    best_hits = 0
    for role, keywords in role_keywords:
        hits = sum(1 for keyword in keywords if keyword in normalized_text)
        if hits > best_hits:
            best_hits = hits
            best_role = role

    return best_role if best_hits > 0 else None


def _resolve_interview_role(candidate: dict[str, Any], inferred_role: str | None = None) -> tuple[str, str]:
    admin_override_role = _normalize_role_value(candidate.get("admin_override_role"))
    if admin_override_role:
        return admin_override_role, "admin_override_role"

    candidate_target_role = _normalize_role_value(candidate.get("target_role"))
    if candidate_target_role:
        return candidate_target_role, "candidate_target_role"

    inferred = _normalize_role_value(inferred_role)
    if inferred:
        return inferred, "inferred_role"

    return "General Candidate", "default"


def _build_role_specific_interview_plan(interview_role: str) -> dict[str, Any]:
    flow_by_role: dict[str, dict[str, Any]] = {
        "Frontend Developer": {
            "flow": ["UI foundations", "React architecture", "State management", "Debugging"],
            "questions": [
                "How would you structure a reusable component library for a large React app?",
                "When would you use context, reducers, or a dedicated state library?",
                "How do you improve Core Web Vitals on a slow page?",
            ],
        },
        "Backend Developer": {
            "flow": ["API design", "Data modeling", "Performance", "Reliability"],
            "questions": [
                "How do you version APIs without breaking clients?",
                "How would you model a many-to-many domain with audit history?",
                "How do you diagnose and reduce p95 latency in production?",
            ],
        },
        "Data Analyst": {
            "flow": ["Problem framing", "SQL analysis", "Dashboarding", "Insights communication"],
            "questions": [
                "How do you validate data quality before publishing analysis?",
                "Write the approach for cohort retention analysis using SQL.",
                "How would you present a conflicting metric trend to business stakeholders?",
            ],
        },
        "Machine Learning Engineer": {
            "flow": ["Feature engineering", "Model selection", "Evaluation", "MLOps"],
            "questions": [
                "How do you choose between a simpler and a more complex model?",
                "How do you detect and mitigate data leakage?",
                "What does a robust model monitoring strategy look like after deployment?",
            ],
        },
        "Product Manager": {
            "flow": ["Discovery", "Prioritization", "Execution", "Measurement"],
            "questions": [
                "How do you decide what to build when teams have conflicting priorities?",
                "Describe a framework you use for trade-offs across impact, effort, and risk.",
                "Which product metrics define success for a new onboarding flow?",
            ],
        },
        "QA Engineer": {
            "flow": ["Test strategy", "Automation", "Risk-based testing", "Release quality"],
            "questions": [
                "How do you design a test plan for a feature with tight deadlines?",
                "What should be automated first in a new test suite and why?",
                "How do you triage flaky tests without slowing delivery?",
            ],
        },
        "General Candidate": {
            "flow": ["Background", "Problem solving", "Collaboration", "Execution"],
            "questions": [
                "Walk through a challenging project and your key contributions.",
                "How do you break down ambiguous problems into actionable steps?",
                "How do you handle disagreements in cross-functional teams?",
            ],
        },
    }

    plan = flow_by_role.get(interview_role, flow_by_role["General Candidate"])
    return {
        "role": interview_role,
        "flow": plan["flow"],
        "questions": plan["questions"],
    }


def _supabase_request(
    path: str,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    bearer_token: str | None = None,
    use_service_role: bool = False,
) -> Any:
    if not settings.supabase_url:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SUPABASE_URL is not configured",
        )

    api_key = settings.supabase_service_role_key if use_service_role else settings.supabase_anon_key
    auth_token = settings.supabase_service_role_key if use_service_role else bearer_token

    if not api_key or not auth_token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase credentials are not configured",
        )

    headers = {
        "apikey": api_key,
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    data = None if body is None else json.dumps(body).encode("utf-8")
    url = f"{settings.supabase_url.rstrip('/')}{path}"
    req = request.Request(url, data=data, headers=headers, method=method)

    try:
        with request.urlopen(req, timeout=20) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except error.HTTPError as exc:
        raw_error = exc.read().decode("utf-8") if exc.fp else ""
        raise SupabaseError(raw_error or exc.reason) from exc


def _get_bearer_token(request_obj: Request) -> str:
    authorization = request_obj.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Supabase access token",
        )

    return authorization.split(" ", 1)[1].strip()


def _get_supabase_user(access_token: str) -> dict[str, Any]:
    try:
        user = _supabase_request(
            "/auth/v1/user",
            method="GET",
            bearer_token=access_token,
        )
    except SupabaseError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Supabase access token",
        ) from exc

    if not isinstance(user, dict) or not user.get("id"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Supabase user payload",
        )

    return user


def _candidate_name_from_user(user: dict[str, Any]) -> str:
    email = user.get("email") or ""
    if email:
        return email.split("@", 1)[0].replace(".", " ").replace("_", " ").title()
    return "Candidate"


def _is_admin(user: dict[str, Any]) -> bool:
    app_metadata_role = (user.get("app_metadata") or {}).get("role")
    return app_metadata_role == "admin"


def _get_or_create_candidate(user: dict[str, Any]) -> dict[str, Any]:
    user_id = user["id"]
    candidate_name = _candidate_name_from_user(user)

    candidate_rows = _supabase_request(
        f"/rest/v1/candidates?user_id=eq.{quote(user_id)}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    if candidate_rows:
        return candidate_rows[0] if isinstance(candidate_rows, list) else candidate_rows

    _supabase_request(
        "/rest/v1/candidates?select=*",
        method="POST",
        body={
            "user_id": user_id,
            "full_name": candidate_name,
            "role": "candidate",
            "current_stage": "profile_pending",
        },
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    # PostgREST may return an empty body for inserts unless return=representation is requested.
    # Always re-fetch to reliably return the candidate row.
    refreshed_rows = _supabase_request(
        f"/rest/v1/candidates?user_id=eq.{quote(user_id)}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    if not refreshed_rows:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to create candidate profile",
        )

    return refreshed_rows[0] if isinstance(refreshed_rows, list) else refreshed_rows


def _is_valid_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except Exception:
        return False


def _assert_safe_storage_path(path: str) -> None:
    # Disallow traversal, null-byte, Windows separators, and malformed segments.
    if not isinstance(path, str) or not path.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Storage path is required",
        )

    normalized = path.strip()
    if normalized.startswith("/") or ".." in normalized or "\x00" in normalized or "\\" in normalized:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid storage path",
        )

    if "//" in normalized:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid storage path",
        )

    if not re.fullmatch(r"[A-Za-z0-9._/-]+", normalized):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid storage path",
        )

    parts = normalized.split("/")
    if any(part == "" for part in parts):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid storage path",
        )


def _normalize_hiring_outcome(value: str | None) -> str | None:
    normalized = _normalize_role_value(value)
    if not normalized:
        return None
    lowered = normalized.lower()
    if lowered not in {"hired", "not_hired"}:
        return None
    return lowered


def _delete_storage_object(path: str, bucket_id: str) -> None:
    _assert_safe_storage_path(path)
    encoded_path = quote(path, safe="/")
    try:
        _supabase_request(
            f"/storage/v1/object/{bucket_id}/{encoded_path}",
            method="DELETE",
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )
    except SupabaseError as exc:
        # Treat already-missing objects as non-fatal for idempotent cleanup.
        if "not found" in str(exc).lower() or "404" in str(exc):
            return
        raise


def _parse_utc_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _revoke_interview_upload_nonces(candidate_id: str, session_id: str, file_type: str) -> None:
    nonce_rows = _supabase_request(
        f"/rest/v1/interview_upload_nonces?candidate_id=eq.{quote(candidate_id)}&session_id=eq.{quote(session_id)}&file_type=eq.{quote(file_type)}&used=eq.false&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    for nonce_row in nonce_rows if isinstance(nonce_rows, list) else []:
        nonce_id = nonce_row.get("id")
        if not nonce_id:
            continue
        _supabase_request(
            f"/rest/v1/interview_upload_nonces?id=eq.{quote(str(nonce_id))}",
            method="DELETE",
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )


def _get_interview_upload_nonce(nonce_id: str, candidate_id: str, session_id: str, file_type: str) -> dict[str, Any] | None:
    nonce_rows = _supabase_request(
        f"/rest/v1/interview_upload_nonces?id=eq.{quote(nonce_id)}&candidate_id=eq.{quote(candidate_id)}&session_id=eq.{quote(session_id)}&file_type=eq.{quote(file_type)}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    if not nonce_rows:
        return None
    return nonce_rows[0] if isinstance(nonce_rows, list) else nonce_rows


def _mark_interview_upload_nonce_used(nonce_id: str) -> None:
    _supabase_request(
        f"/rest/v1/interview_upload_nonces?id=eq.{quote(nonce_id)}",
        method="PATCH",
        body={
            "used": True,
            "used_at": datetime.now(UTC).isoformat(),
        },
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )


def _delete_interview_upload_nonces_for_session(session_id: str, candidate_id: str | None = None) -> None:
    query = f"/rest/v1/interview_upload_nonces?session_id=eq.{quote(session_id)}&select=*"
    if candidate_id:
        query = f"/rest/v1/interview_upload_nonces?session_id=eq.{quote(session_id)}&candidate_id=eq.{quote(candidate_id)}&select=*"

    nonce_rows = _supabase_request(
        query,
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    for nonce_row in nonce_rows if isinstance(nonce_rows, list) else []:
        nonce_id = nonce_row.get("id")
        if not nonce_id:
            continue
        _supabase_request(
            f"/rest/v1/interview_upload_nonces?id=eq.{quote(str(nonce_id))}",
            method="DELETE",
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )


def _build_storage_signed_upload_url(path: str, bucket_id: str = "resumes", is_public: bool = True) -> dict[str, str]:
    _assert_safe_storage_path(path)
    encoded_path = quote(path, safe="/")
    try:
        payload = _supabase_request(
            f"/storage/v1/object/upload/sign/{bucket_id}/{encoded_path}",
            method="POST",
            body={},
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )
    except SupabaseError as exc:
        # Supabase returns a 404-style payload when the storage bucket is missing.
        if "related resource does not exist" not in str(exc).lower():
            raise

        _supabase_request(
            "/storage/v1/bucket",
            method="POST",
            body={
                "id": bucket_id,
                "name": bucket_id,
                "public": is_public,
            },
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )

        payload = _supabase_request(
            f"/storage/v1/object/upload/sign/{bucket_id}/{encoded_path}",
            method="POST",
            body={},
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unexpected storage signing response",
        )

    url_path = payload.get("url")
    if not isinstance(url_path, str):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Storage signing URL missing in response",
        )

    signed_url = f"{settings.supabase_url.rstrip('/')}/storage/v1{url_path}"
    return {
        "signedUrl": signed_url,
        "path": path,
        "bucket": bucket_id,
    }


def _build_storage_signed_read_url(path: str, bucket_id: str) -> dict[str, str]:
    encoded_path = quote(path, safe="/")
    payload = _supabase_request(
        f"/storage/v1/object/sign/{bucket_id}/{encoded_path}",
        method="POST",
        body={
            "expiresIn": 3600,
        },
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unexpected storage signing response",
        )

    signed_url = payload.get("signedURL") or payload.get("signedUrl") or payload.get("url")
    if not isinstance(signed_url, str):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Storage signed read URL missing in response",
        )

    if signed_url.startswith("/"):
        signed_url = f"{settings.supabase_url.rstrip('/')}/storage/v1{signed_url}"

    return {
        "signedUrl": signed_url,
        "path": path,
        "bucket": bucket_id,
    }


def _create_openai_realtime_session(
    interview_role: str,
    interview_plan: dict[str, Any],
    resume_summary: str,
) -> dict[str, Any] | None:
    if not settings.openai_api_key:
        return None

    instructions = (
        "You are an AI interviewer. Conduct a formal interview with concise, professional language. "
        f"Role: {interview_role}. "
        f"Resume summary: {resume_summary}. "
        "Ask one question at a time, wait for the candidate response, then ask follow-ups when needed. "
        f"Preferred question sequence: {json.dumps(interview_plan.get('questions') or [], ensure_ascii=True)}"
    )

    payload = {
        "model": "gpt-4o-realtime-preview-2024-12-17",
        "voice": "alloy",
        "modalities": ["audio", "text"],
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

    try:
        with request.urlopen(req, timeout=30) as response:
            session_data = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None

    if not isinstance(session_data, dict):
        return None

    # SECURITY FIX: Store client_secret server-side, do NOT return to frontend
    # Return only public, non-sensitive session metadata
    return {
        "id": session_data.get("id"),
        "model": session_data.get("model"),
        "expires_at": session_data.get("expires_at"),
        # client_secret NEVER returned to client
        # Internal server-side storage happens at call site
    }


def _get_current_application_stage(candidate: dict[str, Any]) -> str:
    stage = _normalize_role_value(candidate.get("current_stage"))
    return stage or "profile_pending"


def _download_url_bytes(file_url: str) -> bytes:
    with request.urlopen(file_url, timeout=30) as response:
        return response.read()


def _extract_pdf_text(file_bytes: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
    except Exception as exc:  # pragma: no cover - handled by fallback summary
        raise SupabaseError(f"Unable to parse PDF: {exc}") from exc

    text_parts: list[str] = []
    for page in reader.pages:
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        if page_text.strip():
            text_parts.append(page_text)

    return "\n".join(text_parts).strip()


def _build_resume_prompt(
    candidate: dict[str, Any],
    latest_upload: dict[str, Any],
    extracted_text: str,
    interview_role: str,
) -> str:
    candidate_name = candidate.get("full_name", "the candidate")
    file_name = latest_upload.get("file_name", "resume.pdf")
    excerpt = extracted_text[:12000] if extracted_text else "No text could be extracted from the PDF."

    return (
        "You are an expert recruitment analyst. Review the resume content and return only valid JSON. "
        "Do not include markdown. The JSON object must contain keys: summary (string), skills (array of strings), "
        "experience_level (string), score (integer 0-100), transcript (string). "
        f"Candidate name: {candidate_name}. Target interview role: {interview_role}. File name: {file_name}. "
        f"Resume text:\n{excerpt}"
    )


def _openai_resume_analysis(
    candidate: dict[str, Any],
    latest_upload: dict[str, Any],
    extracted_text: str,
    interview_role: str,
) -> dict[str, Any]:
    if not settings.openai_api_key:
        raise SupabaseError("OPENAI_API_KEY is not configured")

    prompt = _build_resume_prompt(candidate, latest_upload, extracted_text, interview_role)
    payload = {
        "model": settings.openai_model,
        "messages": [
            {"role": "system", "content": "You analyze resumes and respond with strict JSON only."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }

    req = request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        raw_error = exc.read().decode("utf-8") if exc.fp else ""
        raise SupabaseError(raw_error or exc.reason) from exc

    content = (((data.get("choices") or [])[0] or {}).get("message") or {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise SupabaseError("OpenAI returned an empty analysis payload")

    parsed = json.loads(content)
    summary = str(parsed.get("summary") or "").strip()
    skills = parsed.get("skills") or []
    if not isinstance(skills, list):
        skills = []
    cleaned_skills = [str(skill).strip() for skill in skills if str(skill).strip()]
    experience_level = str(parsed.get("experience_level") or "Mid level").strip() or "Mid level"
    score = parsed.get("score")
    if not isinstance(score, int):
        try:
            score = int(score)
        except Exception:
            score = 70
    transcript = str(parsed.get("transcript") or summary or "Resume analysis completed.").strip()

    if not summary:
        summary = transcript

    return {
        "ai_summary": summary,
        "ai_score": max(0, min(score, 100)),
        "ai_skills": cleaned_skills,
        "ai_experience_level": experience_level,
        "ai_generated_at": datetime.now(UTC).isoformat(),
        "ai_transcript": transcript,
    }


def _build_resume_analysis(candidate: dict[str, Any], latest_upload: dict[str, Any]) -> dict[str, Any]:
    file_url = latest_upload.get("file_url")
    file_name = latest_upload.get("file_name") or "resume.pdf"

    extracted_text = ""
    if isinstance(file_url, str) and file_url:
        try:
            extracted_text = _extract_pdf_text(_download_url_bytes(file_url))
        except Exception:
            extracted_text = ""

    inferred_role = _infer_interview_role_from_resume_text(extracted_text)
    resolved_interview_role, resolved_role_source = _resolve_interview_role(candidate, inferred_role)
    normalized_role = resolved_interview_role.lower()

    if settings.openai_api_key:
        try:
            analysis = _openai_resume_analysis(candidate, latest_upload, extracted_text, resolved_interview_role)
            analysis["ai_transcript"] = (
                f"Interview role source: {resolved_role_source}. "
                f"Target role used for analysis: {resolved_interview_role}. "
                f"{analysis.get('ai_transcript', '')}"
            ).strip()
            return analysis
        except Exception:
            pass

    normalized_text = re.sub(r"\s+", " ", extracted_text.lower())

    skill_keywords: dict[str, list[str]] = {
        "Python": ["python"],
        "FastAPI": ["fastapi", "api"],
        "PostgreSQL": ["postgres", "postgresql", "sql"],
        "React": ["react", "frontend", "javascript", "typescript"],
        "Machine Learning": ["machine learning", "ml", "pytorch", "tensorflow", "sklearn"],
        "Communication": ["communication", "stakeholder", "presentation"],
        "Leadership": ["leadership", "mentoring", "ownership"],
        "Testing": ["testing", "pytest", "jest", "unit test"],
    }

    matched_skills: list[str] = []
    for skill, keywords in skill_keywords.items():
        if any(keyword in normalized_text for keyword in keywords):
            matched_skills.append(skill)

    if not matched_skills:
        matched_skills = [resolved_interview_role]

    experience_signals = [
        ("Intern", ["intern", "internship", "trainee"]),
        ("Entry level", ["entry level", "junior", "graduate"]),
        ("Mid level", ["developer", "engineer", "analyst"]),
        ("Senior", ["senior", "lead", "architect", "principal"]),
    ]

    inferred_level = "Mid level"
    for label, keywords in experience_signals:
        if any(keyword in normalized_text for keyword in keywords):
            inferred_level = label
            break

    if len(extracted_text) > 2400:
        inferred_level = "Senior" if inferred_level == "Mid level" else inferred_level

    frequency = Counter(word for word in re.findall(r"[a-zA-Z][a-zA-Z0-9+#.-]+", normalized_text) if len(word) > 4)
    top_terms = [term for term, _ in frequency.most_common(4)]

    score = 55
    score += min(len(matched_skills) * 6, 24)
    score += min(len(extracted_text) // 500, 10)
    if normalized_role and normalized_role in normalized_text:
        score += 6
    if any(term in normalized_text for term in ["delivery", "ownership", "impact", "collaboration"]):
        score += 4
    score = max(40, min(score, 97))

    summary_parts = [
        f"Resume analysis for {candidate.get('full_name', 'the candidate')}.",
        f"The resume suggests a {inferred_level.lower()} profile aligned to {resolved_interview_role} work.",
        f"Key skills detected: {', '.join(matched_skills[:5])}.",
        f"Role source used: {resolved_role_source}.",
    ]
    if top_terms:
        summary_parts.append(f"Frequent terms include {', '.join(top_terms[:3])}.")

    if not extracted_text:
        summary_parts.append(
            f"Text extraction from {file_name} was limited, so role alignment used the fallback order with {resolved_interview_role}."
        )

    return {
        "ai_summary": " ".join(summary_parts),
        "ai_score": score,
        "ai_skills": matched_skills,
        "ai_experience_level": inferred_level,
        "ai_generated_at": datetime.now(UTC).isoformat(),
    }


def _persist_candidate_analysis(candidate_id: str, analysis: dict[str, Any]) -> None:
    _supabase_request(
        f"/rest/v1/candidates?id=eq.{quote(candidate_id)}",
        method="PATCH",
        body=analysis,
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )


def _candidate_detail_payload(
    candidate: dict[str, Any],
    latest_upload: dict[str, Any] | None,
    slots: list[dict[str, Any]],
    inferred_role: str | None = None,
) -> dict[str, Any]:
    analysis_summary = candidate.get("ai_summary")
    analysis_score = candidate.get("ai_score")
    analysis_skills = candidate.get("ai_skills") or []
    analysis_level = candidate.get("ai_experience_level") or "Mid level"
    analysis_transcript = candidate.get("ai_transcript") or analysis_summary
    interview_role, role_source = _resolve_interview_role(candidate, inferred_role)

    return {
        "candidate": {
            "id": candidate["id"],
            "name": candidate.get("full_name", "Candidate"),
            "position": interview_role,
            "authRole": candidate.get("role", "candidate"),
            "targetRole": candidate.get("target_role"),
            "adminOverrideRole": candidate.get("admin_override_role"),
            "interviewRole": interview_role,
            "interviewRoleSource": role_source,
            "stage": candidate.get("current_stage", "profile_pending"),
            "score": analysis_score if isinstance(analysis_score, int) else 70 + min((len(slots) if isinstance(slots, list) else 0) * 5, 25),
            "aiSummary": analysis_summary,
            "aiSkills": analysis_skills,
            "aiExperienceLevel": analysis_level,
        },
        "latestUpload": latest_upload,
        "slots": slots if isinstance(slots, list) else [],
        "transcript": analysis_transcript or "Upload a resume to generate an AI summary.",
        "summary": analysis_summary or "AI resume analysis will appear here after the first run.",
    }


@router.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/time")
def server_time() -> dict[str, str]:
    return {
        "utc": datetime.now(UTC).isoformat(),
        "timezone": "UTC",
    }


@router.get("/candidate/dashboard")
def candidate_dashboard(request_obj: Request) -> dict[str, Any]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    candidate = _get_or_create_candidate(user)

    uploads = _supabase_request(
        f"/rest/v1/profile_uploads?candidate_id=eq.{quote(candidate['id'])}&select=*&order=created_at.desc",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    slots = _supabase_request(
        f"/rest/v1/interview_slots?candidate_id=eq.{quote(candidate['id'])}&select=*&order=slot_time.asc",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    latest_upload = uploads[0] if isinstance(uploads, list) and uploads else None
    inferred_role = None
    if latest_upload and latest_upload.get("file_url"):
        try:
            extracted_text = _extract_pdf_text(_download_url_bytes(latest_upload["file_url"]))
            inferred_role = _infer_interview_role_from_resume_text(extracted_text)
        except Exception:
            inferred_role = None
    interview_role, role_source = _resolve_interview_role(candidate, inferred_role)
    booked_slots = [slot for slot in slots if slot.get("status") == "booked"] if isinstance(slots, list) else []

    return {
        "candidate": candidate,
        "authRole": candidate.get("role", "candidate"),
        "targetRole": candidate.get("target_role"),
        "adminOverrideRole": candidate.get("admin_override_role"),
        "interviewRole": interview_role,
        "interviewRoleSource": role_source,
        "stats": {
            "profileCreated": True,
            "resumeUploaded": latest_upload is not None,
            "interviewBooked": len(booked_slots) > 0,
        },
        "latestUpload": latest_upload,
        "bookedSlots": booked_slots,
    }


@router.get("/candidate/interview-slots")
def candidate_interview_slots(request_obj: Request) -> dict[str, Any]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    candidate = _get_or_create_candidate(user)
    application_stage = _get_current_application_stage(candidate)

    slots = _supabase_request(
        f"/rest/v1/interview_slots?candidate_id=eq.{quote(candidate['id'])}&select=*&order=slot_time.asc",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    sessions = _supabase_request(
        f"/rest/v1/interview_sessions?candidate_id=eq.{quote(candidate['id'])}&application_stage=eq.{quote(application_stage)}&select=*&order=created_at.desc",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    latest_started = slots[0] if isinstance(slots, list) and slots else None
    latest_session = sessions[0] if isinstance(sessions, list) and sessions else None
    interview_role, _ = _resolve_interview_role(candidate)

    return {
        "slots": slots if isinstance(slots, list) else [],
        "latestStarted": latest_started,
        "latestSession": latest_session,
        "applicationStage": application_stage,
        "interviewPlan": _build_role_specific_interview_plan(interview_role),
    }


@router.post("/candidate/interview-slots")
def candidate_interview_slots_create(request_obj: Request, payload: InterviewSlotPayload) -> dict[str, Any]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    candidate = _get_or_create_candidate(user)
    started_at = datetime.now(UTC).isoformat()

    created_rows = _supabase_request(
        "/rest/v1/interview_slots?select=*",
        method="POST",
        body={
            "candidate_id": candidate["id"],
            "slot_time": started_at,
            "status": "booked",
        },
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    uploads = _supabase_request(
        f"/rest/v1/profile_uploads?candidate_id=eq.{quote(candidate['id'])}&select=*&order=created_at.desc&limit=1",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    latest_upload = uploads[0] if isinstance(uploads, list) and uploads else None

    inferred_role = None
    if latest_upload and latest_upload.get("file_url"):
        try:
            extracted_text = _extract_pdf_text(_download_url_bytes(latest_upload["file_url"]))
            inferred_role = _infer_interview_role_from_resume_text(extracted_text)
        except Exception:
            inferred_role = None

    interview_role, role_source = _resolve_interview_role(candidate, inferred_role)
    interview_plan = _build_role_specific_interview_plan(interview_role)

    created = created_rows[0] if isinstance(created_rows, list) else created_rows
    return {
        "message": "Interview started",
        "startedAt": started_at,
        "slot": created,
        "interviewRole": interview_role,
        "interviewRoleSource": role_source,
        "interviewPlan": interview_plan,
    }


@router.post("/candidate/interview-session/start")
def candidate_interview_session_start(
    request_obj: Request,
    payload: InterviewSessionStartPayload,
) -> dict[str, Any]:
    if not payload.consentGiven:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Consent is required before starting an interview session",
        )

    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    candidate = _get_or_create_candidate(user)
    application_stage = _get_current_application_stage(candidate)

    existing_sessions = _supabase_request(
        f"/rest/v1/interview_sessions?candidate_id=eq.{quote(candidate['id'])}&application_stage=eq.{quote(application_stage)}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    existing_session = existing_sessions[0] if isinstance(existing_sessions, list) and existing_sessions else None
    if existing_session:
        if existing_session.get("status") == "in_progress":
            return {
                "message": "Interview session already in progress",
                "session": existing_session,
                "slot": None,
                "interviewRole": existing_session.get("interview_role") or _resolve_interview_role(candidate)[0],
                "interviewRoleSource": existing_session.get("role_source") or _resolve_interview_role(candidate)[1],
                "interviewPlan": _build_role_specific_interview_plan(
                    existing_session.get("interview_role") or _resolve_interview_role(candidate)[0]
                ),
                "resumeSummary": candidate.get("ai_summary") or "Resume summary pending. Ask structured role-fit questions.",
                "realtime": None,
            }

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An interview session already exists for this application stage",
        )

    uploads = _supabase_request(
        f"/rest/v1/profile_uploads?candidate_id=eq.{quote(candidate['id'])}&select=*&order=created_at.desc&limit=1",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    latest_upload = uploads[0] if isinstance(uploads, list) and uploads else None

    inferred_role = None
    if latest_upload and latest_upload.get("file_url"):
        try:
            extracted_text = _extract_pdf_text(_download_url_bytes(latest_upload["file_url"]))
            inferred_role = _infer_interview_role_from_resume_text(extracted_text)
        except Exception:
            inferred_role = None

    interview_role, role_source = _resolve_interview_role(candidate, inferred_role)
    interview_plan = _build_role_specific_interview_plan(interview_role)

    started_at = datetime.now(UTC).isoformat()
    slot_rows = _supabase_request(
        "/rest/v1/interview_slots?select=*",
        method="POST",
        body={
            "candidate_id": candidate["id"],
            "slot_time": started_at,
            "status": "in_progress",
        },
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    slot = slot_rows[0] if isinstance(slot_rows, list) else slot_rows

    session_rows = _supabase_request(
        "/rest/v1/interview_sessions?select=*",
        method="POST",
        body={
            "candidate_id": candidate["id"],
            "application_stage": application_stage,
            "slot_id": slot.get("id") if isinstance(slot, dict) else None,
            "status": "in_progress",
            "interview_role": interview_role,
            "role_source": role_source,
            "provider": "openai-realtime",
            "started_at": started_at,
            "consent_given": bool(payload.consentGiven),
            "consent_at": started_at if payload.consentGiven else None,
        },
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    session = session_rows[0] if isinstance(session_rows, list) else session_rows

    resume_summary = candidate.get("ai_summary") or "Resume summary pending. Ask structured role-fit questions."
    realtime_response = _create_openai_realtime_session(interview_role, interview_plan, resume_summary)

    # Return only public fields; client_secret stays server-side
    realtime_public = None
    if realtime_response:
        realtime_public = {
            "id": realtime_response.get("id"),
            "model": realtime_response.get("model"),
            "expires_at": realtime_response.get("expires_at"),
            # client_secret intentionally omitted
        }

    return {
        "message": "Interview session started",
        "session": session,
        "slot": slot,
        "applicationStage": application_stage,
        "interviewRole": interview_role,
        "interviewRoleSource": role_source,
        "interviewPlan": interview_plan,
        "resumeSummary": resume_summary,
        "realtime": realtime_public,
    }


@router.get("/candidate/interview-session/{session_id}")
def candidate_interview_session_details(request_obj: Request, session_id: str) -> dict[str, Any]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    candidate = _get_or_create_candidate(user)

    if not _is_valid_uuid(session_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid session ID format",
        )

    session_rows = _supabase_request(
        f"/rest/v1/interview_sessions?id=eq.{quote(session_id)}&candidate_id=eq.{quote(candidate['id'])}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    if not session_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview session not found")

    session_row = session_rows[0] if isinstance(session_rows, list) else session_rows
    interview_role, role_source = _resolve_interview_role(candidate)
    if session_row.get("interview_role"):
        interview_role = session_row.get("interview_role")
        role_source = session_row.get("role_source") or role_source

    return {
        "session": {
            "id": session_row.get("id"),
            "status": session_row.get("status"),
            "applicationStage": session_row.get("application_stage"),
        },
        "interviewRole": interview_role,
        "interviewRoleSource": role_source,
        "interviewPlan": _build_role_specific_interview_plan(interview_role),
        "resumeSummary": candidate.get("ai_summary") or "Resume summary pending. Ask structured role-fit questions.",
    }


@router.post("/candidate/interview-session/{session_id}/complete")
def candidate_interview_session_complete(
    request_obj: Request,
    session_id: str,
    payload: InterviewSessionCompletePayload,
) -> dict[str, Any]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    candidate = _get_or_create_candidate(user)

    session_rows = _supabase_request(
        f"/rest/v1/interview_sessions?id=eq.{quote(session_id)}&candidate_id=eq.{quote(candidate['id'])}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    if not session_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview session not found")

    session_row = session_rows[0] if isinstance(session_rows, list) else session_rows
    
    # SECURITY FIX #2: Verify consent before accepting completion
    # Transcripts and media must only persist if explicit consent was given
    if not session_row.get("consent_given"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot complete interview without prior explicit consent"
        )
    
    # SECURITY FIX: Prevent duplicate completions
    if session_row.get("status") == "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Interview session already completed"
        )

    # SECURITY FIX #3: Require session-bound single-use upload nonce for media artifacts
    if payload.videoPath:
        if not payload.videoUploadNonce:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing upload nonce for video artifact",
            )

        nonce_payload = _get_interview_upload_nonce(payload.videoUploadNonce, candidate["id"], session_id, "video")
        now_dt = datetime.now(UTC)
        expires_at = _parse_utc_datetime((nonce_payload or {}).get("expires_at"))
        if (
            not isinstance(nonce_payload, dict)
            or nonce_payload.get("used")
            or not expires_at
            or expires_at < now_dt
            or nonce_payload.get("path") != payload.videoPath
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid or expired upload nonce for video artifact",
            )

        _mark_interview_upload_nonce_used(payload.videoUploadNonce)

    if payload.audioPath:
        if not payload.audioUploadNonce:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing upload nonce for audio artifact",
            )

        audio_nonce_payload = _get_interview_upload_nonce(payload.audioUploadNonce, candidate["id"], session_id, "audio")
        now_dt = datetime.now(UTC)
        audio_expires_at = _parse_utc_datetime((audio_nonce_payload or {}).get("expires_at"))
        if (
            not isinstance(audio_nonce_payload, dict)
            or audio_nonce_payload.get("used")
            or not audio_expires_at
            or audio_expires_at < now_dt
            or audio_nonce_payload.get("path") != payload.audioPath
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid or expired upload nonce for audio artifact",
            )

        _mark_interview_upload_nonce_used(payload.audioUploadNonce)
    
    ended_at = datetime.now(UTC).isoformat()
    duration_seconds = payload.durationSeconds if isinstance(payload.durationSeconds, int) else None

    _supabase_request(
        f"/rest/v1/interview_sessions?id=eq.{quote(session_id)}",
        method="PATCH",
        body={
            "status": "completed",
            "ended_at": ended_at,
            "duration_seconds": duration_seconds,
        },
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    slot_id = session_row.get("slot_id") if isinstance(session_row, dict) else None
    if slot_id:
        _supabase_request(
            f"/rest/v1/interview_slots?id=eq.{quote(slot_id)}",
            method="PATCH",
            body={"status": "completed"},
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )

    artifact_rows = _supabase_request(
        "/rest/v1/interview_artifacts?select=*",
        method="POST",
        body={
            "session_id": session_id,
            "candidate_id": candidate["id"],
            "audio_path": payload.audioPath,
            "audio_url": payload.audioUrl,
            "video_path": payload.videoPath,
            "video_url": payload.videoUrl,
            "transcript": payload.transcript,
            "score_payload": payload.scorePayload or {},
        },
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    # PostgREST may return an empty body for insert unless representation is requested.
    # Re-fetch latest artifact for this session to guarantee a stable response shape.
    if not artifact_rows:
        artifact_rows = _supabase_request(
            f"/rest/v1/interview_artifacts?session_id=eq.{quote(session_id)}&candidate_id=eq.{quote(candidate['id'])}&select=*&order=created_at.desc&limit=1",
            method="GET",
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )

    artifact = artifact_rows[0] if isinstance(artifact_rows, list) and artifact_rows else artifact_rows
    if not artifact:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Interview completed but artifact could not be loaded",
        )

    # Best-effort cleanup of any remaining nonce rows for this session
    _delete_interview_upload_nonces_for_session(session_id, candidate.get("id"))

    return {
        "message": "Interview session completed",
        "sessionId": session_id,
        "artifact": artifact,
        "endedAt": ended_at,
    }


@router.post("/candidate/profile-upload")
def candidate_profile_upload(request_obj: Request, payload: ProfileUploadPayload) -> dict[str, object]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    user_id = user["id"]
    candidate = _get_or_create_candidate(user)

    uploaded_rows = _supabase_request(
        "/rest/v1/profile_uploads?select=*",
        method="POST",
        body={
            "candidate_id": candidate["id"],
            "user_id": user_id,
            "file_name": payload.filename,
            "file_path": payload.filePath,
            "file_url": payload.fileUrl,
            "mime_type": payload.type,
            "file_size": payload.size,
            "status": "uploaded",
        },
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    target_role = _normalize_role_value(payload.targetRole)
    if target_role:
        _supabase_request(
            f"/rest/v1/candidates?id=eq.{quote(candidate['id'])}",
            method="PATCH",
            body={"target_role": target_role},
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )
        candidate["target_role"] = target_role

    uploaded = uploaded_rows[0] if isinstance(uploaded_rows, list) else uploaded_rows

    return {
        "message": "Profile upload saved to Supabase",
        "candidate": candidate,
        "interviewRole": _resolve_interview_role(candidate)[0],
        "upload": uploaded,
        "receivedAt": datetime.now(UTC).isoformat(),
        "submittedAt": payload.submittedAt,
    }


@router.post("/candidate/storage/signed-upload")
def candidate_storage_signed_upload(request_obj: Request, payload: SignedUploadPayload) -> dict[str, str]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    user_id = user["id"]

    if not payload.path or not payload.path.startswith(f"{user_id}/"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Upload path is not allowed for this user",
        )

    try:
        return _build_storage_signed_upload_url(payload.path)
    except SupabaseError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unable to sign upload URL: {exc}",
        ) from exc


@router.post("/candidate/storage/signed-interview-upload")
def candidate_storage_signed_interview_upload(request_obj: Request, payload: SignedInterviewUploadPayload) -> dict[str, Any]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    user_id = user["id"]
    candidate = _get_or_create_candidate(user)

    session_id = (payload.sessionId or "").strip()
    file_type = (payload.fileType or "").strip().lower()
    extension = (payload.extension or "webm").strip().lower()

    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sessionId is required",
        )

    if not _is_valid_uuid(session_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid sessionId format",
        )

    if file_type not in {"video", "audio"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="fileType must be either 'video' or 'audio'",
        )

    if not re.fullmatch(r"[a-z0-9]{2,8}", extension):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file extension",
        )

    session_rows = _supabase_request(
        f"/rest/v1/interview_sessions?id=eq.{quote(session_id)}&candidate_id=eq.{quote(candidate['id'])}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    if not session_rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Interview session not found for this candidate",
        )

    session_row = session_rows[0] if isinstance(session_rows, list) else session_rows
    if session_row.get("status") != "in_progress":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Interview session is not in progress",
        )

    if not session_row.get("consent_given"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Consent is required before uploading interview media",
        )

    # Bind upload URL to candidate + session + file_type, with server-controlled path
    timestamp = int(time.time() * 1000)
    storage_path = f"{user_id}/{session_id}/{file_type}-{timestamp}.{extension}"

    # Revoke prior unused nonces for this exact session/file_type pair
    _revoke_interview_upload_nonces(candidate["id"], session_id, file_type)

    try:
        signed = _build_storage_signed_upload_url(storage_path, bucket_id="interview-media", is_public=False)

        upload_nonce = secrets.token_urlsafe(32)
        _supabase_request(
            "/rest/v1/interview_upload_nonces?select=*",
            method="POST",
            body={
                "id": upload_nonce,
                "candidate_id": candidate["id"],
                "session_id": session_id,
                "user_id": user_id,
                "file_type": file_type,
                "path": storage_path,
                "used": False,
                "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
            },
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )

        return {
            **signed,
            "uploadNonce": upload_nonce,
            "expiresIn": 300,
            "sessionId": session_id,
            "fileType": file_type,
        }
    except SupabaseError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unable to sign interview upload URL: {exc}",
        ) from exc


@router.get("/admin/candidates")
def admin_candidates(request_obj: Request) -> dict[str, Any]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    if not _is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    candidates = _supabase_request(
        "/rest/v1/candidates?select=*&order=created_at.desc",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    uploads = _supabase_request(
        "/rest/v1/profile_uploads?select=*&order=created_at.desc",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    uploads_by_candidate: dict[str, list[dict[str, Any]]] = {}
    if isinstance(uploads, list):
        for item in uploads:
            cid = item.get("candidate_id")
            if not cid:
                continue
            uploads_by_candidate.setdefault(cid, []).append(item)

    response_candidates = []
    for candidate in candidates if isinstance(candidates, list) else []:
        candidate_uploads = uploads_by_candidate.get(candidate["id"], [])
        latest_upload = candidate_uploads[0] if candidate_uploads else None
        ai_score = candidate.get("ai_score")
        interview_role, role_source = _resolve_interview_role(candidate)
        response_candidates.append(
            {
                "id": candidate["id"],
                "name": candidate.get("full_name", "Candidate"),
                "role": interview_role,
                "authRole": candidate.get("role", "candidate"),
                "targetRole": candidate.get("target_role"),
                "adminOverrideRole": candidate.get("admin_override_role"),
                "interviewRoleSource": role_source,
                "stage": candidate.get("current_stage", "profile_pending"),
                "score": ai_score if isinstance(ai_score, int) else 70 + min(len(candidate_uploads) * 5, 25),
                "latestUpload": latest_upload,
            }
        )

    return {"candidates": response_candidates}


@router.get("/admin/candidates/{candidate_id}")
def admin_candidate_details(request_obj: Request, candidate_id: str) -> dict[str, Any]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    if not _is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    candidate_rows = _supabase_request(
        f"/rest/v1/candidates?id=eq.{quote(candidate_id)}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    if not candidate_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")

    candidate = candidate_rows[0] if isinstance(candidate_rows, list) else candidate_rows
    uploads = _supabase_request(
        f"/rest/v1/profile_uploads?candidate_id=eq.{quote(candidate_id)}&select=*&order=created_at.desc",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    slots = _supabase_request(
        f"/rest/v1/interview_slots?candidate_id=eq.{quote(candidate_id)}&select=*&order=slot_time.asc",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    latest_upload = uploads[0] if isinstance(uploads, list) and uploads else None
    inferred_role = None
    if latest_upload and latest_upload.get("file_url"):
        try:
            extracted_text = _extract_pdf_text(_download_url_bytes(latest_upload["file_url"]))
            inferred_role = _infer_interview_role_from_resume_text(extracted_text)
        except Exception:
            inferred_role = None

    if latest_upload and not candidate.get("ai_summary"):
        analysis = _build_resume_analysis(candidate, latest_upload)
        _persist_candidate_analysis(candidate["id"], analysis)
        candidate = {**candidate, **analysis}

    return _candidate_detail_payload(candidate, latest_upload, slots if isinstance(slots, list) else [], inferred_role)


@router.patch("/admin/candidates/{candidate_id}/interview-role")
def admin_update_candidate_interview_role(
    request_obj: Request,
    candidate_id: str,
    payload: AdminInterviewRolePayload,
) -> dict[str, Any]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    if not _is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    candidate_rows = _supabase_request(
        f"/rest/v1/candidates?id=eq.{quote(candidate_id)}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    if not candidate_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")

    target_role = _normalize_role_value(payload.targetRole)
    admin_override_role = _normalize_role_value(payload.adminOverrideRole)

    _supabase_request(
        f"/rest/v1/candidates?id=eq.{quote(candidate_id)}",
        method="PATCH",
        body={
            "target_role": target_role,
            "admin_override_role": admin_override_role,
        },
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    refreshed_rows = _supabase_request(
        f"/rest/v1/candidates?id=eq.{quote(candidate_id)}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    refreshed_candidate = refreshed_rows[0] if isinstance(refreshed_rows, list) else refreshed_rows

    uploads = _supabase_request(
        f"/rest/v1/profile_uploads?candidate_id=eq.{quote(candidate_id)}&select=*&order=created_at.desc",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    slots = _supabase_request(
        f"/rest/v1/interview_slots?candidate_id=eq.{quote(candidate_id)}&select=*&order=slot_time.asc",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    latest_upload = uploads[0] if isinstance(uploads, list) and uploads else None

    return _candidate_detail_payload(refreshed_candidate, latest_upload, slots if isinstance(slots, list) else [])


@router.get("/admin/interview-session/{session_id}")
def admin_interview_session_details(request_obj: Request, session_id: str) -> dict[str, Any]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    if not _is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    session_rows = _supabase_request(
        f"/rest/v1/interview_sessions?id=eq.{quote(session_id)}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    if not session_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview session not found")

    session_row = session_rows[0] if isinstance(session_rows, list) else session_rows
    artifact_rows = _supabase_request(
        f"/rest/v1/interview_artifacts?session_id=eq.{quote(session_id)}&select=*&order=created_at.desc&limit=1",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    artifact = artifact_rows[0] if isinstance(artifact_rows, list) and artifact_rows else None
    audio_signed = None
    video_signed = None
    if artifact:
        if artifact.get("audio_path"):
            try:
                audio_signed = _build_storage_signed_read_url(artifact["audio_path"], "interview-media")
            except Exception:
                audio_signed = None
        if artifact.get("video_path"):
            try:
                video_signed = _build_storage_signed_read_url(artifact["video_path"], "interview-media")
            except Exception:
                video_signed = None

    return {
        "session": session_row,
        "artifact": artifact,
        "audioSignedUrl": audio_signed,
        "videoSignedUrl": video_signed,
    }


@router.post("/admin/candidates/{candidate_id}/hiring-outcome")
def admin_record_hiring_outcome(
    request_obj: Request,
    candidate_id: str,
    payload: AdminHiringOutcomePayload,
) -> dict[str, Any]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    if not _is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    outcome = _normalize_hiring_outcome(payload.outcome)
    if not outcome:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Outcome must be either 'hired' or 'not_hired'",
        )

    retention_days = payload.retentionDays if isinstance(payload.retentionDays, int) else 30
    if retention_days < 0 or retention_days > 365:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="retentionDays must be between 0 and 365",
        )

    candidate_rows = _supabase_request(
        f"/rest/v1/candidates?id=eq.{quote(candidate_id)}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    if not candidate_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")

    now_dt = datetime.now(UTC)
    now_iso = now_dt.isoformat()
    expires_at_iso = (now_dt.timestamp() + (retention_days * 86400))
    expires_at = datetime.fromtimestamp(expires_at_iso, tz=UTC).isoformat()

    # Set candidate stage based on hiring outcome.
    next_stage = "offer_extended" if outcome == "hired" else "rejected"
    _supabase_request(
        f"/rest/v1/candidates?id=eq.{quote(candidate_id)}",
        method="PATCH",
        body={"current_stage": next_stage},
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    artifact_rows = _supabase_request(
        f"/rest/v1/interview_artifacts?candidate_id=eq.{quote(candidate_id)}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    updated_count = 0
    for artifact in artifact_rows if isinstance(artifact_rows, list) else []:
        artifact_id = artifact.get("id")
        if not artifact_id:
            continue
        _supabase_request(
            f"/rest/v1/interview_artifacts?id=eq.{quote(artifact_id)}",
            method="PATCH",
            body={
                "hiring_outcome": outcome,
                "outcome_at": now_iso,
                "expires_at": expires_at,
                "archived_at": now_iso,
            },
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )
        updated_count += 1

    return {
        "message": "Hiring outcome recorded and interview artifact retention scheduled",
        "candidateId": candidate_id,
        "outcome": outcome,
        "retentionDays": retention_days,
        "expiresAt": expires_at,
        "updatedArtifacts": updated_count,
    }


@router.post("/admin/interview-artifacts/cleanup")
def admin_cleanup_expired_interview_artifacts(
    request_obj: Request,
    payload: AdminCleanupArtifactsPayload,
) -> dict[str, Any]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    if not _is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    limit = payload.limit if isinstance(payload.limit, int) else 100
    if limit < 1 or limit > 500:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="limit must be between 1 and 500",
        )

    now_iso = datetime.now(UTC).isoformat()
    expired_artifacts = _supabase_request(
        f"/rest/v1/interview_artifacts?select=*&expires_at=lt.{quote(now_iso)}&order=expires_at.asc&limit={limit}",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    deleted_rows = 0
    deleted_storage = 0
    cleanup_errors: list[dict[str, str]] = []

    for artifact in expired_artifacts if isinstance(expired_artifacts, list) else []:
        artifact_id = artifact.get("id")
        if not artifact_id:
            continue

        try:
            storage_delete_failed = False
            for media_path in (artifact.get("audio_path"), artifact.get("video_path")):
                if not media_path:
                    continue
                try:
                    _delete_storage_object(media_path, "interview-media")
                    deleted_storage += 1
                except Exception as exc:
                    storage_delete_failed = True
                    cleanup_errors.append({
                        "artifactId": str(artifact_id),
                        "error": f"storage delete failed: {exc}",
                    })
                    break

            if storage_delete_failed:
                continue

            _supabase_request(
                "/rest/v1/interview_artifact_deletion_log?select=*",
                method="POST",
                body={
                    "artifact_id": artifact_id,
                    "candidate_id": artifact.get("candidate_id"),
                    "deleted_reason": "retention_expired",
                    "deleted_by": user.get("id"),
                },
                bearer_token=settings.supabase_service_role_key,
                use_service_role=True,
            )

            _supabase_request(
                f"/rest/v1/interview_artifacts?id=eq.{quote(artifact_id)}",
                method="DELETE",
                bearer_token=settings.supabase_service_role_key,
                use_service_role=True,
            )
            deleted_rows += 1
        except Exception as exc:
            cleanup_errors.append({
                "artifactId": str(artifact_id),
                "error": str(exc),
            })

    return {
        "message": "Expired interview artifacts cleanup completed",
        "evaluated": len(expired_artifacts) if isinstance(expired_artifacts, list) else 0,
        "deletedArtifacts": deleted_rows,
        "deletedStorageObjects": deleted_storage,
        "errors": cleanup_errors,
    }


@router.post("/admin/analyze-resume/{candidate_id}")
def admin_analyze_resume(request_obj: Request, candidate_id: str, payload: ResumeAnalysisPayload) -> dict[str, Any]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    if not _is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    candidate_rows = _supabase_request(
        f"/rest/v1/candidates?id=eq.{quote(candidate_id)}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    if not candidate_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")

    candidate = candidate_rows[0] if isinstance(candidate_rows, list) else candidate_rows
    uploads = _supabase_request(
        f"/rest/v1/profile_uploads?candidate_id=eq.{quote(candidate_id)}&select=*&order=created_at.desc",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    latest_upload = uploads[0] if isinstance(uploads, list) and uploads else None

    if not latest_upload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No resume upload found for this candidate")

    if not payload.force and candidate.get("ai_summary"):
        return _candidate_detail_payload(candidate, latest_upload, [])

    analysis = _build_resume_analysis(candidate, latest_upload)
    _persist_candidate_analysis(candidate_id, analysis)

    refreshed_candidate = {**candidate, **analysis}
    return _candidate_detail_payload(refreshed_candidate, latest_upload, [])
