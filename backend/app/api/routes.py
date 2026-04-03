from datetime import datetime, UTC
import io
import json
import re
from collections import Counter
from typing import Any
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


class ResumeAnalysisPayload(BaseModel):
    force: bool = False


class AdminInterviewRolePayload(BaseModel):
    targetRole: str | None = None
    adminOverrideRole: str | None = None


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
    metadata_role = (user.get("user_metadata") or {}).get("role")
    if metadata_role == "admin":
        return True
    email = user.get("email") or ""
    return "admin" in email


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

    created_rows = _supabase_request(
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

    return created_rows[0] if isinstance(created_rows, list) else created_rows


def _build_storage_signed_upload_url(path: str) -> dict[str, str]:
    encoded_path = quote(path, safe="/")
    try:
        payload = _supabase_request(
            f"/storage/v1/object/upload/sign/resumes/{encoded_path}",
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
                "id": "resumes",
                "name": "resumes",
                "public": True,
            },
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )

        payload = _supabase_request(
            f"/storage/v1/object/upload/sign/resumes/{encoded_path}",
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
    }


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

    slots = _supabase_request(
        f"/rest/v1/interview_slots?candidate_id=eq.{quote(candidate['id'])}&select=*&order=slot_time.asc",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    latest_started = slots[0] if isinstance(slots, list) and slots else None
    interview_role, _ = _resolve_interview_role(candidate)

    return {
        "slots": slots if isinstance(slots, list) else [],
        "latestStarted": latest_started,
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
