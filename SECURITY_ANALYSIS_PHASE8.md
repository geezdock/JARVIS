# Phase 8 Vulnerability Analysis: Video Interview Recording

## Executive Summary

Phase 8 introduces critical interview media handling with 6 identifiable vulnerabilities ranging from **CRITICAL** to **MEDIUM** severity. The implementation includes proper consent gating and storage access controls, but has gaps in data validation, session resumption, media expiry, and token handling.

## Post-Fix Priority Review (April 3, 2026)

After implementing fixes for vulnerabilities #1-#6, an additional review identified four follow-up risks.

1. ✅ FIXED (CRITICAL): Admin privilege escalation via weak email-based role fallback
    - Location: [backend/app/api/routes.py](backend/app/api/routes.py#L301)
    - Issue: Any email containing "admin" could pass admin checks.
    - Fix: Admin checks now rely only on trusted Supabase metadata roles (`user_metadata.role` or `app_metadata.role`).

2. ✅ FIXED (HIGH): Audio artifact integrity gap
    - Location: [backend/app/api/routes.py](backend/app/api/routes.py#L1188)
    - Issue: `audioPath` could be persisted without validating `audioUploadNonce`.
    - Fix: Added full audio nonce/session/path validation matching video validation.

3. ✅ FIXED (MEDIUM): Cleanup consistency risk
    - Location: [backend/app/api/routes.py](backend/app/api/routes.py#L1752)
    - Issue: DB artifacts could be deleted even when storage deletion failed.
    - Fix: Cleanup now skips DB deletion when storage object deletion fails; only idempotent missing-object responses are tolerated.

4. ✅ FIXED IN REPO (CRITICAL): Secret exposure in local environment file
    - Location: [backend/.env](backend/.env)
    - Issue: Live Supabase and DB credentials were present in plaintext.
    - Fix: Secrets scrubbed from tracked `.env` files and ignore rules tightened in [.gitignore](.gitignore).
    - Required manual action: rotate previously exposed keys/passwords in Supabase/OpenAI and re-issue fresh values locally.

## Secret Rotation Runbook (Required)

Use this checklist to fully close the exposed-secret incident.

1. Rotate Supabase keys in project settings.
        - Regenerate anon key.
        - Regenerate service role key.
        - Note: rotating JWT keys will invalidate active sessions/tokens.

2. Rotate database credentials.
        - Change the Postgres password used by application integrations.
        - Rebuild the value used for `SUPABASE_DB_URL`.

3. Rotate OpenAI API key.
        - Revoke the exposed key.
        - Create a new key scoped to this environment.

4. Update local environment files with new values.
        - Set backend values in [backend/.env](backend/.env):
            - `SUPABASE_URL`
            - `SUPABASE_ANON_KEY`
            - `SUPABASE_SERVICE_ROLE_KEY`
            - `SUPABASE_DB_URL`
            - `OPENAI_API_KEY`
        - Set frontend values in [frontend/.env](frontend/.env):
            - `VITE_SUPABASE_URL`
            - `VITE_SUPABASE_ANON_KEY`
            - `VITE_API_BASE_URL`

5. Invalidate stale credentials in all environments.
        - Remove old values from CI/CD secrets.
        - Remove old values from cloud host environment variables.
        - Restart backend/frontend deployments after update.

6. Verify rotation success.
        - Backend health check:
            - `Invoke-RestMethod -Method GET -Uri http://127.0.0.1:8000/health`
        - Backend auth check (expect 401 without token):
            - `Invoke-RestMethod -Method GET -Uri http://127.0.0.1:8000/candidate/interview-slots`
        - Candidate flow smoke test:
            - start session -> signed upload URL -> complete session.

7. Confirm repository hygiene.
        - Ensure [.gitignore](.gitignore) still includes `.env` patterns.
        - Ensure no secrets appear in tracked files.

8. Incident follow-up.
        - Audit recent logs for usage of old keys.
        - Record rotation timestamp and operator in internal notes.
        - Set recurring secret rotation policy (for example every 90 days).

---

## Vulnerabilities Identified

### 1. ✅ FIXED: OpenAI Realtime Token Exposure in API Response

**STATUS:** RESOLVED (April 3, 2026)

```python
return {
    "message": "Interview session started",
    "session": session,
    "slot": slot,
    ...
    "realtime": realtime_session,  # Contains client_secret
}
```

```python
def _create_openai_realtime_session(...) -> dict[str, Any]:
    ...
    return {
        "id": session_data.get("id"),
        "model": session_data.get("model"),
        "expires_at": session_data.get("expires_at"),
        "client_secret": (session_data.get("client_secret") or {}).get("value"),  # EXPOSED
    }
```

**Risk:**
- If logs, proxies, or network traffic are compromised, attackers can reuse the `client_secret` to impersonate the candidate's interview session
- The token is valid for 60 minutes (OpenAI default), allowing unauthorized access to the realtime API
- Can be harvested from: browser DevTools, network logs, error traces, CDN caches, WAF logs

**Impact:** CRITICAL
- Unauthorized interview session hijacking
- Candidate impersonation during live interview
- Potential recording manipulation or exfiltration

**Remediation:**
1. **Never return `client_secret` to the frontend** — store it server-side only
2. Implement a WebSocket relay or polling endpoint where:
   - Backend maintains Realtime connection
   - Frontend communicates with backend, not OpenAI directly
3. If direct frontend connection is required, use token refresh tokens server-side:
   ```python
   # Store token server-side, indexed by session
   REALTIME_SESSIONS[session_id] = {
       "token_id": realtime_session.get("id"),
       "expires_at": realtime_session.get("expires_at"),
       # client_secret NEVER stored or returned
   }
   
   return {
       "sessionId": session_id,
       "realtimeSessionId": realtime_session.get("id"),
       "wsUrl": f"/candidate/interview/realtime/{session_id}"  # Backend relay
   }
   ```

---

### 2. ✅ FIXED: No Consent Verification at Session Completion

**STATUS:** RESOLVED (April 3, 2026)

```python
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
        ...
    )
    
    # NO CHECK: if existing_session.consent_given != True
    # Simply updates the session
```

**Risk:**
- If an attacker somehow creates a session without consent but manages to call `/complete`, it persists invalid interview data
- If session creation is bypassed via SQL injection or RLS policy misconfiguration, completion still works
- Violates compliance requirements that transcript/video must only exist if consent was explicit

**Impact:** CRITICAL (Compliance)
- Invalid interview artifacts without consent evidence
- Regulatory violation (GDPR, CCPA, FERPA)
- Liability for undocumented consent

**Remediation:**
```python
@router.post("/candidate/interview-session/{session_id}/complete")
def candidate_interview_session_complete(...):
    ...
    session_row = session_rows[0] if isinstance(session_rows, list) else session_rows
    
    # VERIFY CONSENT BEFORE ACCEPTING COMPLETION
    if not session_row.get("consent_given"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot complete interview without prior consent"
        )
    
    if session_row.get("status") == "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Interview session already completed"
        )
    
    # Continue with completion...
```

---

### 3. ✅ FIXED: Signed URL Token Reuse and Replay Attacks

**STATUS:** RESOLVED (April 3, 2026)

**Location:** [backend/app/api/routes.py](backend/app/api/routes.py) - `candidate_storage_signed_interview_upload()` endpoint (line ~1025)

**Description:**
The endpoint returns a signed upload URL that persists for 1 hour without tracking usage or sessions:

```python
@router.post("/candidate/storage/signed-interview-upload")
def candidate_storage_signed_interview_upload(...) -> dict[str, str]:
    ...
    return _build_storage_signed_upload_url(payload.path, bucket_id="interview-media", is_public=False)

def _build_storage_signed_upload_url(path: str, bucket_id: str, ...) -> dict[str, str]:
    ...
    payload = _supabase_request(
        f"/storage/v1/object/upload/{bucket_id}?path={encoded_path}",
        ...
    )
    return {
        "signedUrl": signed_url,  # Valid for 3600 seconds
        "path": path,
        "bucket": bucket_id,
    }
```

**Risk:**
- Signed URL valid for 1 hour; if leaked or intercepted, attacker can:
  - Upload arbitrary binary data to the path (replacing legitimate interview video)
  - Upload malicious files with same path prefix
  - No audit trail of who uploaded what blob
  - Multiple uploads to same path overwrite each other silently

- No session binding: URL is tied only to candidate_id + path, not the specific interview session
- No rate limiting on URL generation: candidate can request unlimited signed URLs and store them offline

**Impact:** CRITICAL
- Interview recording replacement/tampering
- Malware injection via storage bucket
- Bypass of upload validation logic

**Remediation:**
1. **Bind signed URLs to sessions:**
   ```python
   POST /candidate/storage/signed-interview-upload
   Payload: { session_id, file_type: "video" | "audio" }
   
   # Server validates:
   # - Session exists and belongs to candidate
   # - Session status is "in_progress"
   # - No prior upload for session + file_type
   
   # Return URL with server-tracked nonce:
   upload_nonce = secrets.token_urlsafe(32)
   UPLOAD_TRACKING[upload_nonce] = {
       "session_id": session_id,
       "candidate_id": candidate_id,
       "file_type": file_type,
       "created_at": now(),
       "used": False
   }
   
   return {
       "signedUrl": signed_url,
       "uploadNonce": upload_nonce  # Required in completion payload
   }
   ```

2. **Validate in completion endpoint:**
   ```python
   def candidate_interview_session_complete(...):
       nonce = payload.uploadNonce
       if nonce not in UPLOAD_TRACKING or UPLOAD_TRACKING[nonce]["used"]:
           raise HTTPException(403, "Invalid or already-used upload token")
       
       UPLOAD_TRACKING[nonce]["used"] = True
   ```

3. **Short-lived URLs:** Reduce TTL to 5 minutes per upload attempt

---

### 4. ✅ FIXED: Traversal Risk in Video Path Construction

**STATUS:** RESOLVED (April 3, 2026)

**Location:** [frontend/src/pages/candidate/Interview.jsx](frontend/src/pages/candidate/Interview.jsx) - `buildInterviewPath()` and file upload (lines ~15-45)

**Description:**
The video path is constructed client-side with predictable segments:

```javascript
const buildInterviewPath = (userId, sessionId, extension) => {
  const timestamp = Date.now();
  return `${userId}/${sessionId}/${timestamp}.${extension}`;  // Non-validated input
};

// Later:
const videoPath = buildInterviewPath(userId, sessionId, 'webm');
const storedVideoPath = await uploadBlobToSignedUrl(recordingBlob, videoPath);
```

**Risk:**
- `sessionId` from `location.state` is never validated; a crafted URL could inject `../` path traversal:
  - `<userId>/../<attacker>/<timestamp>.webm` → upload outside user's directory
  - `<userId>/<sessionId>/../../admin.webm` → layer violation
  
- Backend path validation is loose:
  ```python
  if not payload.path or not payload.path.startswith(f"{user_id}/"):
      raise HTTPException(403, "Upload path is not allowed for this user")
  ```
  This check can be bypassed with:
  - `payload.path = "<user_id>/<sessionId>/../../../other_user.webm"` (bypasses check, path passes validation)
  - `payload.path = "<user_id>/\x00../../../other_user.webm"` (null byte injection if path not sanitized)

**Impact:** HIGH
- Candidate can overwrite another candidate's video
- Cross-candidate data leakage and tampering
- Privilege escalation to admin paths

**Remediation:**
```python
# Backend: Validate path strictly
import os

@router.post("/candidate/storage/signed-interview-upload")
def candidate_storage_signed_interview_upload(...):
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    user_id = user["id"]
    
    # Normalize and validate path
    if not payload.path:
        raise HTTPException(403, "Path required")
    
    # Reject absolute paths and traversal
    if payload.path.startswith("/") or ".." in payload.path or "\x00" in payload.path:
        raise HTTPException(403, "Invalid path characters")
    
    # Reconstruct expected path from validated components
    session_id = payload.sessionId  # Must be UUID
    file_type = payload.fileType    # "video" | "audio"
    
    if not _is_valid_uuid(session_id):
        raise HTTPException(400, "Invalid session ID")
    
    if file_type not in ["video", "audio"]:
        raise HTTPException(400, "Invalid file type")
    
    # Whitelist path pattern
    expected_path = f"{user_id}/{session_id}/{file_type}"
    if payload.path != expected_path:
        raise HTTPException(403, "Path does not match expected format")
    
    # Continue...
```

---

### 5. ✅ FIXED: No Session State Validation During Resume

**STATUS:** RESOLVED (April 3, 2026)

**Location:** [frontend/src/pages/candidate/Interview.jsx](frontend/src/pages/candidate/Interview.jsx) - `useEffect` hooks (lines ~60-95)

**Description:**
The component attempts to resume a session from `location.state`, but doesn't validate it against the backend:

```javascript
const [sessionData, setSessionData] = useState(location.state?.sessionData ?? null);

useEffect(() => {
    const fetchInterviewContext = async () => {
        try {
            const response = await api.get('/candidate/interview-slots');
            const latestSession = response.data?.latestSession;

            if (latestSession && !sessionData) {
                setSessionData({
                    session: latestSession,  // Trusts latestSession from API
                    ...
                });
            }
        } catch (_error) {
            // keep the notice screen available even if context fetch fails
        }
    };
    fetchInterviewContext();
}, [interviewPlan, sessionData]);
```

**Risk:**
- If `location.state.sessionData` is malicious or stale, it's used to initialize state:
  - Attacker crafts URL with `state = { sessionData: { session: { id: "other_user_session", ...} } }`
  - Frontend loads the wrong session without validation
  - Calls `uploadBlobToSignedUrl()` with attacker-supplied session ID
  
- No verification that the fetched `latestSession` belongs to the current candidate
- Backend's `GET /candidate/interview-slots` endpoint relies on RLS, but if RLS is misconfigured, data leaks

**Impact:** HIGH
- Cross-candidate session hijacking
- Candidate can upload video to another candidate's session
- Data confusion and integrity violation

**Remediation:**
```javascript
// Frontend: Validate session before use
useEffect(() => {
    const fetchInterviewContext = async () => {
        try {
            const response = await api.get('/candidate/interview-slots');
            const latestSession = response.data?.latestSession;
            
            if (latestSession) {
                // Validate session ownership
                const { data: { session: authSession } } = await supabase.auth.getSession();
                const userId = authSession?.user?.id;
                
                // Fetch fresh session from backend to verify ownership
                const sessionCheckRes = await api.get(`/candidate/interview-session/${latestSession.id}`);
                
                if (sessionCheckRes.status !== 200) {
                    throw new Error("Invalid session");
                }
                
                // Only then set it
                setSessionData({
                    session: sessionCheckRes.data.session,
                    ...
                });
            }
        } catch (error) {
            // Clear sessionData on any validation error
            setSessionData(null);
            setHasAcknowledgedNotice(false);
        }
    };
    fetchInterviewContext();
}, [interviewPlan, sessionData]);
```

```python
# Backend: Add session fetch endpoint
@router.get("/candidate/interview-session/{session_id}")
def candidate_interview_session(request_obj: Request, session_id: str) -> dict[str, Any]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    candidate = _get_or_create_candidate(user)
    
    session_rows = _supabase_request(
        f"/rest/v1/interview_sessions?id=eq.{quote(session_id)}&candidate_id=eq.{quote(candidate['id'])}&select=*",
        ...
    )
    
    if not session_rows:
        raise HTTPException(404, "Session not found")
    
    session = session_rows[0]
    
    # Return minimal public info only
    return {
        "session": {
            "id": session["id"],
            "status": session["status"],
            "application_stage": session["application_stage"],
            # Do NOT return consent_given, timestamps, or sensitive fields
        }
    }
```

---

### 6. ✅ FIXED: No Data Expiry or Cleanup for Interview Artifacts

**STATUS:** RESOLVED (April 3, 2026)

**Location:** [backend/supabase/schema.sql](backend/supabase/schema.sql) - `interview_artifacts` table (lines ~67-78)

**Description:**
The schema defines interview artifacts (transcripts, scores, media paths) but has no retention policy or automatic cleanup:

```sql
create table if not exists public.interview_artifacts (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.interview_sessions(id) on delete cascade,
  candidate_id uuid not null references public.candidates(id) on delete cascade,
  audio_path text,
  audio_url text,
  video_path text,
  video_url text,
  transcript text,
  score_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
  -- NO: expires_at, retention_days, archived_at
);
```

**Risk:**
- Candidate consent states "...deleted once they are either hired or not hired" but there's no mechanism to enforce this
- Artifacts persist indefinitely, increasing:
  - Data breach surface (more data = more targets)
  - Regulatory liability (violated data minimization under GDPR Article 5)
  - Storage costs over time
- No audit logging for deletion; admins can silently delete records

**Impact:** MEDIUM (Compliance, Privacy)
- Non-compliance with privacy notice
- Increased data breach risk
- Regulatory fines (GDPR up to €20M or 4% of revenue)

**Remediation:**
```sql
-- Add retention columns
ALTER TABLE public.interview_artifacts ADD COLUMN (
  hiring_outcome TEXT,  -- 'hired' | 'not_hired' | null
  outcome_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ,   -- Set to outcome_at + 30 days
  archived_at TIMESTAMPTZ
);

-- Add cleanup trigger
CREATE OR REPLACE FUNCTION archive_interview_artifacts_on_outcome()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.hiring_outcome IS NOT NULL AND OLD.hiring_outcome IS NULL THEN
    NEW.expires_at := NOW() + INTERVAL '30 days';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER archive_on_outcome
BEFORE UPDATE ON interview_artifacts
FOR EACH ROW
EXECUTE FUNCTION archive_interview_artifacts_on_outcome();

-- Add scheduled job to delete expired artifacts (run daily via cron)
CREATE EXTENSION IF NOT EXISTS pg_cron;

SELECT cron.schedule(
  'delete_expired_interview_artifacts',
  '0 2 * * *',  -- Daily at 2 AM UTC
  'DELETE FROM interview_artifacts WHERE expires_at < NOW() AND expires_at IS NOT NULL'
);

-- Add audit logging
CREATE TABLE interview_artifact_deletion_log (
  id BIGSERIAL PRIMARY KEY,
  artifact_id UUID NOT NULL,
  deleted_reason TEXT,
  deleted_by TEXT,
  deleted_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Backend API:** Add endpoint to mark outcome and trigger expiry:
```python
@router.post("/admin/candidates/{candidate_id}/hiring-outcome")
def admin_record_outcome(
    request_obj: Request,
    candidate_id: str,
    payload: HiringOutcomePayload,  # { outcome: "hired" | "not_hired", reason? }
) -> dict:
    # Verify admin
    # Update artifacts with outcome + expires_at
    # Log deletion intent
    # Optionally immediately delete if configured
```

---

## Summary Table

| # | Severity | Type | Location | Status |
|---|----------|------|----------|--------|
| 1 | ✅ FIXED | Token Exposure | routes.py:960 | OpenAI client_secret NO LONGER in response |
| 2 | ✅ FIXED | Validation Gap | routes.py:1025 | Consent check enforced at completion |
| 3 | ✅ FIXED | Token Reuse | routes.py:1212 | Session-bound, single-use upload nonces with TTL |
| 4 | ✅ FIXED | Path Traversal | routes.py:329, routes.py:1212 | Server-generated paths + strict path sanitization |
| 5 | ✅ FIXED | State Bypass | routes.py:1066, Interview.jsx:80 | Session ownership verified via backend before resume |
| 6 | ✅ FIXED | Compliance | schema.sql:61, routes.py:1649 | Retention metadata + admin outcome + cleanup with audit log |

---

## Quick Remediation Priority

1. ✅ **COMPLETED:** Fix OpenAI token exposure (#1) — client_secret now stored server-side only
2. ✅ **COMPLETED:** Add consent validation on completion (#2) — validates consent_given before accepting completion
3. ✅ **COMPLETED:** Bind signed URLs to sessions (#3) — session-bound nonce + single-use + 5 minute expiry
4. ✅ **COMPLETED:** Tighten path traversal checks (#4) — server-generated paths and strict path sanitization
5. ✅ **COMPLETED:** Add session validation (#5) — frontend resume now requires backend ownership verification
6. ✅ **COMPLETED:** Implement retention policy (#6) — retention fields + admin outcome endpoint + cleanup endpoint + deletion audit log

---

## Testing Recommendations

### Manual Testing
- [ ] Observe network traffic for `client_secret` in responses
- [ ] Attempt to complete interview without consent_given flag in DB
- [ ] Reuse signed URL after expiry
- [ ] Inject `../` in path variables
- [ ] Hand-craft location state with cross-candidate session ID

### Automated Testing
```python
# test_phase8_security.py

def test_openai_token_not_in_response():
    """Verify client_secret not leaked in response"""
    response = client.post("/candidate/interview-session/start", json={...})
    assert "client_secret" not in response.json()

def test_completion_without_consent_fails():
    """Verify completion rejects non-consented sessions"""
    # Create session with consent_given=False
    # POST /complete with that session
    # Assert 403 Forbidden

def test_path_traversal_rejected():
    """Verify ../../ paths are rejected"""
    payload = {
        "sessionId": "11111111-1111-1111-1111-111111111111",
        "fileType": "video",
        "extension": "../../webm"
    }
    response = client.post("/candidate/storage/signed-interview-upload", json=payload)
    assert response.status_code == 403

def test_cross_candidate_session_denied():
    """Verify candidate cannot access another's session"""
    other_session = create_candidate_session(OTHER_CANDIDATE)
    response = client.get(f"/candidate/interview-session/{other_session.id}")
    assert response.status_code == 404
```

---

## References

- OWASP Top 10 2021: A01:2021 – Broken Access Control, A03:2021 – Injection
- GDPR Article 5: Principles relating to processing of personal data
- CWE-384: Session Fixation
- CWE-434: Unrestricted Upload of File with Dangerous Type

