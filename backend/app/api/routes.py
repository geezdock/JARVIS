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
    submittedAt: str


class InterviewSlotPayload(BaseModel):
    slotTime: str


class SignedUploadPayload(BaseModel):
    path: str


class ResumeAnalysisPayload(BaseModel):
    force: bool = False


class SupabaseError(RuntimeError):
    pass


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


def _build_resume_analysis(candidate: dict[str, Any], latest_upload: dict[str, Any]) -> dict[str, Any]:
    file_url = latest_upload.get("file_url")
    file_name = latest_upload.get("file_name") or "resume.pdf"
    candidate_role = (candidate.get("role") or "candidate").strip().lower()

    extracted_text = ""
    if isinstance(file_url, str) and file_url:
        try:
          extracted_text = _extract_pdf_text(_download_url_bytes(file_url))
        except Exception:
            extracted_text = ""

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
        matched_skills = [candidate.get("role", "candidate").title()]

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
    if candidate_role and candidate_role in normalized_text:
        score += 6
    if any(term in normalized_text for term in ["delivery", "ownership", "impact", "collaboration"]):
        score += 4
    score = max(40, min(score, 97))

    summary_parts = [
        f"Resume analysis for {candidate.get('full_name', 'the candidate')}.",
        f"The resume suggests a {inferred_level.lower()} profile aligned to {candidate_role or 'general'} work.",
        f"Key skills detected: {', '.join(matched_skills[:5])}.",
    ]
    if top_terms:
        summary_parts.append(f"Frequent terms include {', '.join(top_terms[:3])}.")

    if not extracted_text:
        summary_parts.append(f"Text extraction from {file_name} was limited, so the summary is based on the uploaded file metadata and candidate role.")

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


def _candidate_detail_payload(candidate: dict[str, Any], latest_upload: dict[str, Any] | None, slots: list[dict[str, Any]]) -> dict[str, Any]:
    analysis_summary = candidate.get("ai_summary")
    analysis_score = candidate.get("ai_score")
    analysis_skills = candidate.get("ai_skills") or []
    analysis_level = candidate.get("ai_experience_level") or "Mid level"

    return {
        "candidate": {
            "id": candidate["id"],
            "name": candidate.get("full_name", "Candidate"),
            "position": candidate.get("role", "candidate"),
            "stage": candidate.get("current_stage", "profile_pending"),
            "score": analysis_score if isinstance(analysis_score, int) else 70 + min((len(slots) if isinstance(slots, list) else 0) * 5, 25),
            "aiSummary": analysis_summary,
            "aiSkills": analysis_skills,
            "aiExperienceLevel": analysis_level,
        },
        "latestUpload": latest_upload,
        "slots": slots if isinstance(slots, list) else [],
        "transcript": analysis_summary or "Upload a resume to generate an AI summary.",
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
    booked_slots = [slot for slot in slots if slot.get("status") == "booked"] if isinstance(slots, list) else []

    return {
        "candidate": candidate,
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

    return {
        "slots": slots if isinstance(slots, list) else [],
        "latestStarted": latest_started,
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

    created = created_rows[0] if isinstance(created_rows, list) else created_rows
    return {"message": "Interview started", "startedAt": started_at, "slot": created}


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

    uploaded = uploaded_rows[0] if isinstance(uploaded_rows, list) else uploaded_rows

    return {
        "message": "Profile upload saved to Supabase",
        "candidate": candidate,
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
        response_candidates.append(
            {
                "id": candidate["id"],
                "name": candidate.get("full_name", "Candidate"),
                "role": candidate.get("role", "candidate"),
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
    if latest_upload and not candidate.get("ai_summary"):
        analysis = _build_resume_analysis(candidate, latest_upload)
        _persist_candidate_analysis(candidate["id"], analysis)
        candidate = {**candidate, **analysis}

    return _candidate_detail_payload(candidate, latest_upload, slots if isinstance(slots, list) else [])


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
