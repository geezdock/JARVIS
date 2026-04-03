from fastapi.testclient import TestClient

from app.main import app
from app.api import routes


client = TestClient(app)


def test_health_endpoint_returns_ok():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_is_admin_checks_metadata_and_email():
    assert routes._is_admin({"app_metadata": {"role": "admin"}})
    assert routes._is_admin({"user_metadata": {"role": "admin"}})
    assert routes._is_admin({"email": "lead.admin@example.com"})
    assert not routes._is_admin({"email": "candidate@example.com"})


def test_admin_candidates_filters_by_stage(monkeypatch):
    def fake_get_supabase_user(_access_token):
        return {"id": "admin-1", "email": "admin@example.com", "app_metadata": {"role": "admin"}}

    def fake_supabase_request(path, method="GET", body=None, bearer_token=None, use_service_role=False):
        if path.startswith("/rest/v1/candidates?select=*&order=created_at.desc"):
            return [
                {
                    "id": "candidate-1",
                    "full_name": "Alice Candidate",
                    "role": "candidate",
                    "current_stage": "profile_pending",
                    "ai_score": 72,
                    "ai_skills": ["React"],
                },
                {
                    "id": "candidate-2",
                    "full_name": "Bob Builder",
                    "role": "candidate",
                    "current_stage": "rejected",
                    "ai_score": 35,
                    "ai_skills": ["Testing"],
                },
            ]
        if path.startswith("/rest/v1/profile_uploads?select=*&order=created_at.desc"):
            return []
        if path.startswith("/rest/v1/interview_artifacts?select=*&order=created_at.desc"):
            return [
                {"candidate_id": "candidate-1", "score_payload": {"overallScore": 81, "scoringStatus": "completed"}},
                {"candidate_id": "candidate-2", "score_payload": {"overallScore": 10, "scoringStatus": "pending"}},
            ]
        raise AssertionError(f"Unexpected request: {path}")

    monkeypatch.setattr(routes, "_get_supabase_user", fake_get_supabase_user)
    monkeypatch.setattr(routes, "_supabase_request", fake_supabase_request)

    response = client.get("/admin/candidates?stage=profile_pending", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200
    payload = response.json()["candidates"]
    assert len(payload) == 1
    assert payload[0]["id"] == "candidate-1"
    assert payload[0]["score"] == 81
    assert payload[0]["stage"] == "profile_pending"


def test_admin_update_candidate_stage_updates_existing_candidate(monkeypatch):
    state = {
        "candidate-1": {
            "id": "candidate-1",
            "full_name": "Alice Candidate",
            "role": "candidate",
            "current_stage": "profile_pending",
        }
    }
    audit_log_calls = []

    def fake_get_supabase_user(_access_token):
        return {"id": "admin-1", "email": "admin@example.com", "app_metadata": {"role": "admin"}}

    def fake_supabase_request(path, method="GET", body=None, bearer_token=None, use_service_role=False):
        if path.startswith("/rest/v1/candidates?id=eq.candidate-1&select=*") and method == "GET":
            return [state["candidate-1"]]
        if path.startswith("/rest/v1/candidates?id=eq.candidate-1") and method == "PATCH":
            state["candidate-1"] = {**state["candidate-1"], **(body or {})}
            return None
        if path.startswith("/rest/v1/profile_uploads?candidate_id=eq.candidate-1&select=*&order=created_at.desc"):
            return []
        if path.startswith("/rest/v1/interview_slots?candidate_id=eq.candidate-1&select=*&order=slot_time.asc"):
            return []
        if path.startswith("/rest/v1/interview_artifacts?candidate_id=eq.candidate-1&select=*"):
            return []
        if path.startswith("/rest/v1/admin_audit_logs?select=*") and method == "POST":
            audit_log_calls.append(body or {})
            return None
        raise AssertionError(f"Unexpected request: {path}")

    monkeypatch.setattr(routes, "_get_supabase_user", fake_get_supabase_user)
    monkeypatch.setattr(routes, "_supabase_request", fake_supabase_request)

    response = client.patch(
        "/admin/candidates/candidate-1/stage",
        headers={"Authorization": "Bearer test-token"},
        json={"stage": "under_review"},
    )

    assert response.status_code == 200
    assert response.json()["candidate"]["stage"] == "under_review"
    assert state["candidate-1"]["current_stage"] == "under_review"
    assert audit_log_calls[0]["action"] == "candidate_stage_updated"
    assert audit_log_calls[0]["entity_type"] == "candidate"


def test_admin_analyze_resume_can_queue_background_job(monkeypatch):
    def fake_get_supabase_user(_access_token):
        return {"id": "admin-1", "email": "admin@example.com", "app_metadata": {"role": "admin"}}

    submitted = {}

    def fake_submit_background_job(job_type, handler, **context):
        submitted["job_type"] = job_type
        submitted["context"] = context
        return {"id": "job-123", "status": "queued", "type": job_type}

    monkeypatch.setattr(routes, "_get_supabase_user", fake_get_supabase_user)
    monkeypatch.setattr(routes, "_submit_background_job", fake_submit_background_job)

    response = client.post(
        "/admin/analyze-resume/candidate-1",
        headers={"Authorization": "Bearer test-token"},
        json={"force": True, "runInBackground": True},
    )

    assert response.status_code == 200
    assert response.json() == {"jobId": "job-123", "status": "queued", "type": "resume_analysis"}
    assert submitted["job_type"] == "resume_analysis"
    assert submitted["context"]["candidateId"] == "candidate-1"


def test_admin_audit_logs_endpoint_paginates(monkeypatch):
    def fake_get_supabase_user(_access_token):
        return {"id": "admin-1", "email": "admin@example.com", "app_metadata": {"role": "admin"}}

    def fake_supabase_request(path, method="GET", body=None, bearer_token=None, use_service_role=False):
        if path.startswith("/rest/v1/admin_audit_logs?select=*&order=created_at.desc"):
            return [
                {"id": "log-1", "action": "candidate_stage_updated", "entity_type": "candidate", "entity_id": "candidate-1", "actor_user_id": "admin-1", "actor_email": "admin@example.com", "metadata": {"stage": "under_review"}, "created_at": "2026-04-04T00:00:00Z"},
                {"id": "log-2", "action": "resume_analysis_completed", "entity_type": "candidate", "entity_id": "candidate-2", "actor_user_id": "admin-1", "actor_email": "admin@example.com", "metadata": {}, "created_at": "2026-04-04T00:01:00Z"},
            ]
        raise AssertionError(f"Unexpected request: {path}")

    monkeypatch.setattr(routes, "_get_supabase_user", fake_get_supabase_user)
    monkeypatch.setattr(routes, "_supabase_request", fake_supabase_request)

    response = client.get("/admin/audit-logs?page=1&pageSize=1", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["pagination"]["total"] == 2
    assert payload["pagination"]["totalPages"] == 2
    assert len(payload["logs"]) == 1
    assert payload["logs"][0]["id"] == "log-1"


def test_admin_analyze_resume_can_queue_background_job(monkeypatch):
    def fake_get_supabase_user(_access_token):
        return {"id": "admin-1", "email": "admin@example.com", "app_metadata": {"role": "admin"}}

    submitted = {}

    def fake_submit_background_job(job_type, handler, **context):
        submitted["job_type"] = job_type
        submitted["context"] = context
        return {"id": "job-123", "status": "queued", "type": job_type}

    monkeypatch.setattr(routes, "_get_supabase_user", fake_get_supabase_user)
    monkeypatch.setattr(routes, "_submit_background_job", fake_submit_background_job)

    response = client.post(
        "/admin/analyze-resume/candidate-1",
        headers={"Authorization": "Bearer test-token"},
        json={"force": True, "runInBackground": True},
    )

    assert response.status_code == 200
    assert response.json() == {"jobId": "job-123", "status": "queued", "type": "resume_analysis"}
    assert submitted["job_type"] == "resume_analysis"
    assert submitted["context"]["candidateId"] == "candidate-1"


def test_admin_background_job_status_returns_job(monkeypatch):
    def fake_get_supabase_user(_access_token):
        return {"id": "admin-1", "email": "admin@example.com", "app_metadata": {"role": "admin"}}

    monkeypatch.setattr(routes, "_get_supabase_user", fake_get_supabase_user)
    monkeypatch.setattr(
        routes,
        "_get_background_job",
        lambda job_id: {"id": job_id, "status": "completed", "type": "resume_analysis"},
    )

    response = client.get("/admin/background-jobs/job-123", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200
    assert response.json()["id"] == "job-123"
    assert response.json()["status"] == "completed"