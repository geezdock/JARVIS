from dataclasses import replace

from fastapi.testclient import TestClient
from fastapi import HTTPException

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


def test_candidate_realtime_token_returns_client_secret(monkeypatch):
    class FakeRealtimeProvider:
        def is_configured(self):
            return True

        def create_realtime_session(self, interview_role, interview_plan, resume_summary, include_client_secret=False):
            assert include_client_secret is True
            assert interview_role == "Backend Developer"
            assert isinstance(interview_plan, dict)
            assert isinstance(resume_summary, str)
            return {
                "id": "rt_123",
                "model": "gpt-4o-realtime-preview-2024-12-17",
                "expires_at": 1735689600,
                "client_secret": {"value": "ephemeral_secret_123"},
            }

    def fake_get_supabase_user(_access_token):
        return {"id": "user-1", "email": "candidate@example.com"}

    def fake_get_or_create_candidate(_user):
        return {"id": "candidate-1", "ai_summary": "Strong API design and Python experience."}

    def fake_supabase_request(path, method="GET", body=None, bearer_token=None, use_service_role=False):
        if path.startswith("/rest/v1/interview_sessions?") and method == "GET":
            return [{"id": "11111111-1111-1111-1111-111111111111", "status": "in_progress", "interview_role": "Backend Developer"}]
        if path.startswith("/rest/v1/job_specifications?") and method == "GET":
            return []
        raise AssertionError(f"Unexpected request: {path}")

    monkeypatch.setattr(routes, "_get_supabase_user", fake_get_supabase_user)
    monkeypatch.setattr(routes, "_get_or_create_candidate", fake_get_or_create_candidate)
    monkeypatch.setattr(routes, "_supabase_request", fake_supabase_request)
    monkeypatch.setattr(routes, "get_llm_provider_by_name", lambda _provider_name: FakeRealtimeProvider())

    response = client.post(
        "/candidate/interview-session/11111111-1111-1111-1111-111111111111/realtime-token",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    realtime = response.json()["realtime"]
    assert realtime["clientSecret"] == "ephemeral_secret_123"
    assert realtime["maxQuestions"] == 6


def test_candidate_realtime_token_requires_in_progress_session(monkeypatch):
    class FakeRealtimeProvider:
        def is_configured(self):
            return True

        def create_realtime_session(self, interview_role, interview_plan, resume_summary, include_client_secret=False):
            raise AssertionError("Should not create realtime session when session is not in progress")

    def fake_get_supabase_user(_access_token):
        return {"id": "user-1", "email": "candidate@example.com"}

    def fake_get_or_create_candidate(_user):
        return {"id": "candidate-1", "ai_summary": "Summary"}

    def fake_supabase_request(path, method="GET", body=None, bearer_token=None, use_service_role=False):
        if path.startswith("/rest/v1/interview_sessions?") and method == "GET":
            return [{"id": "11111111-1111-1111-1111-111111111111", "status": "completed", "interview_role": "Backend Developer"}]
        raise AssertionError(f"Unexpected request: {path}")

    monkeypatch.setattr(routes, "_get_supabase_user", fake_get_supabase_user)
    monkeypatch.setattr(routes, "_get_or_create_candidate", fake_get_or_create_candidate)
    monkeypatch.setattr(routes, "_supabase_request", fake_supabase_request)
    monkeypatch.setattr(routes, "get_llm_provider_by_name", lambda _provider_name: FakeRealtimeProvider())

    response = client.post(
        "/candidate/interview-session/11111111-1111-1111-1111-111111111111/realtime-token",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 409
    assert "in-progress" in response.json()["detail"]


def test_candidate_complete_endpoint_is_idempotent_for_completed_session(monkeypatch):
    def fake_get_supabase_user(_access_token):
        return {"id": "user-1", "email": "candidate@example.com"}

    def fake_get_or_create_candidate(_user):
        return {"id": "candidate-1"}

    def fake_supabase_request(path, method="GET", body=None, bearer_token=None, use_service_role=False):
        if path.startswith("/rest/v1/interview_sessions?") and method == "GET":
            return [
                {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "status": "completed",
                    "consent_given": True,
                    "ended_at": "2026-04-04T10:00:00Z",
                }
            ]
        raise AssertionError(f"Unexpected request: {path}")

    monkeypatch.setattr(routes, "_get_supabase_user", fake_get_supabase_user)
    monkeypatch.setattr(routes, "_get_or_create_candidate", fake_get_or_create_candidate)
    monkeypatch.setattr(routes, "_supabase_request", fake_supabase_request)

    response = client.post(
        "/candidate/interview-session/11111111-1111-1111-1111-111111111111/complete",
        headers={"Authorization": "Bearer test-token"},
        json={},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["sessionId"] == "11111111-1111-1111-1111-111111111111"


def test_candidate_groq_next_question_returns_dynamic_prompt(monkeypatch):
    def fake_get_supabase_user(_access_token):
        return {"id": "user-1", "email": "candidate@example.com"}

    def fake_get_or_create_candidate(_user):
        return {"id": "candidate-1", "ai_summary": "Strong Python and REST fundamentals."}

    def fake_supabase_request(path, method="GET", body=None, bearer_token=None, use_service_role=False):
        if path.startswith("/rest/v1/interview_sessions?") and method == "GET":
            return [{"id": "11111111-1111-1111-1111-111111111111", "status": "in_progress", "interview_role": "Backend Developer"}]
        if path.startswith("/rest/v1/job_specifications?") and method == "GET":
            return []
        raise AssertionError(f"Unexpected request: {path}")

    monkeypatch.setattr(routes, "_get_supabase_user", fake_get_supabase_user)
    monkeypatch.setattr(routes, "_get_or_create_candidate", fake_get_or_create_candidate)
    monkeypatch.setattr(routes, "_supabase_request", fake_supabase_request)
    monkeypatch.setattr(routes, "settings", replace(routes.settings, interview_realtime_provider="groq"))
    monkeypatch.setattr(routes, "get_llm_provider_by_name", lambda _provider_name: (_ for _ in ()).throw(AssertionError("LLM provider should not be called for LeetCode question selection")))

    response = client.post(
        "/candidate/interview-session/11111111-1111-1111-1111-111111111111/next-question",
        headers={"Authorization": "Bearer test-token"},
        json={"questionsAsked": 1, "transcriptTurns": []},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["completed"] is False
    assert payload["questionNumber"] == 2
    assert payload["maxQuestions"] == 6
    assert payload["question"].startswith("Q2/6:")
    assert "Coding question:" not in payload["question"]
    assert "LeetCode" not in payload["question"]


def test_candidate_groq_next_question_avoids_repeating_same_leetcode_problem(monkeypatch):
    def fake_get_supabase_user(_access_token):
        return {"id": "user-1", "email": "candidate@example.com"}

    def fake_get_or_create_candidate(_user):
        return {"id": "candidate-1", "ai_summary": "Strong Python and REST fundamentals."}

    def fake_supabase_request(path, method="GET", body=None, bearer_token=None, use_service_role=False):
        if path.startswith("/rest/v1/interview_sessions?") and method == "GET":
            return [{"id": "11111111-1111-1111-1111-111111111111", "status": "in_progress", "interview_role": "Backend Developer"}]
        if path.startswith("/rest/v1/job_specifications?") and method == "GET":
            return []
        raise AssertionError(f"Unexpected request: {path}")

    monkeypatch.setattr(routes, "_get_supabase_user", fake_get_supabase_user)
    monkeypatch.setattr(routes, "_get_or_create_candidate", fake_get_or_create_candidate)
    monkeypatch.setattr(routes, "_supabase_request", fake_supabase_request)
    monkeypatch.setattr(routes, "settings", replace(routes.settings, interview_realtime_provider="groq"))

    response = client.post(
        "/candidate/interview-session/11111111-1111-1111-1111-111111111111/next-question",
        headers={"Authorization": "Bearer test-token"},
        json={
            "questionsAsked": 1,
            "transcriptTurns": [
                {
                    "speaker": "ai",
                    "text": "Q1/6: LeetCode 1 - Two Sum (Easy): Describe approach.",
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["questionNumber"] == 2
    assert payload["question"].startswith("Q2/6:")
    assert "Two Sum" not in payload["question"]


def test_candidate_groq_next_question_prefers_backend_relevant_problem(monkeypatch):
    def fake_get_supabase_user(_access_token):
        return {"id": "user-1", "email": "candidate@example.com"}

    def fake_get_or_create_candidate(_user):
        return {"id": "candidate-1", "ai_summary": "Strong Python, Redis caching, and API design fundamentals."}

    def fake_supabase_request(path, method="GET", body=None, bearer_token=None, use_service_role=False):
        if path.startswith("/rest/v1/interview_sessions?") and method == "GET":
            return [{"id": "11111111-1111-1111-1111-111111111111", "status": "in_progress", "interview_role": "Backend Developer"}]
        if path.startswith("/rest/v1/job_specifications?") and method == "GET":
            return []
        raise AssertionError(f"Unexpected request: {path}")

    monkeypatch.setattr(routes, "_get_supabase_user", fake_get_supabase_user)
    monkeypatch.setattr(routes, "_get_or_create_candidate", fake_get_or_create_candidate)
    monkeypatch.setattr(routes, "_supabase_request", fake_supabase_request)
    monkeypatch.setattr(routes, "settings", replace(routes.settings, interview_realtime_provider="groq"))

    response = client.post(
        "/candidate/interview-session/11111111-1111-1111-1111-111111111111/next-question",
        headers={"Authorization": "Bearer test-token"},
        json={"questionsAsked": 1, "transcriptTurns": []},
    )

    assert response.status_code == 200
    assert response.json()["question"].startswith("Q2/6:")


def test_candidate_next_question_switches_to_role_theory_after_three_questions(monkeypatch):
    def fake_get_supabase_user(_access_token):
        return {"id": "user-1", "email": "candidate@example.com"}

    def fake_get_or_create_candidate(_user):
        return {"id": "candidate-1", "ai_summary": "Built backend APIs for analytics workflows."}

    def fake_supabase_request(path, method="GET", body=None, bearer_token=None, use_service_role=False):
        if path.startswith("/rest/v1/interview_sessions?") and method == "GET":
            return [{"id": "11111111-1111-1111-1111-111111111111", "status": "in_progress", "interview_role": "Backend Developer"}]
        if path.startswith("/rest/v1/job_specifications?") and method == "GET":
            return [
                {
                    "parsed_data": {
                        "job_title": "Senior Backend Engineer",
                        "required_skills": ["Python", "System Design"],
                        "key_responsibilities": ["design scalable APIs"],
                    }
                }
            ]
        raise AssertionError(f"Unexpected request: {path}")

    monkeypatch.setattr(routes, "_get_supabase_user", fake_get_supabase_user)
    monkeypatch.setattr(routes, "_get_or_create_candidate", fake_get_or_create_candidate)
    monkeypatch.setattr(routes, "_supabase_request", fake_supabase_request)
    monkeypatch.setattr(routes, "settings", replace(routes.settings, interview_realtime_provider="groq"))

    response = client.post(
        "/candidate/interview-session/11111111-1111-1111-1111-111111111111/next-question",
        headers={"Authorization": "Bearer test-token"},
        json={"questionsAsked": 3, "transcriptTurns": []},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["questionNumber"] == 4
    assert payload["question"].startswith("Q4/6:")
    assert "Senior Backend Engineer" in payload["question"]


def test_candidate_next_question_first_three_coding_questions_are_distinct(monkeypatch):
    def fake_get_supabase_user(_access_token):
        return {"id": "user-1", "email": "candidate@example.com"}

    def fake_get_or_create_candidate(_user):
        return {"id": "candidate-1", "ai_summary": "Backend API and distributed systems experience."}

    def fake_supabase_request(path, method="GET", body=None, bearer_token=None, use_service_role=False):
        if path.startswith("/rest/v1/interview_sessions?") and method == "GET":
            return [{"id": "11111111-1111-1111-1111-111111111111", "status": "in_progress", "interview_role": "Backend Developer"}]
        if path.startswith("/rest/v1/job_specifications?") and method == "GET":
            return []
        raise AssertionError(f"Unexpected request: {path}")

    monkeypatch.setattr(routes, "_get_supabase_user", fake_get_supabase_user)
    monkeypatch.setattr(routes, "_get_or_create_candidate", fake_get_or_create_candidate)
    monkeypatch.setattr(routes, "_supabase_request", fake_supabase_request)
    monkeypatch.setattr(routes, "settings", replace(routes.settings, interview_realtime_provider="groq"))

    q1 = client.post(
        "/candidate/interview-session/11111111-1111-1111-1111-111111111111/next-question",
        headers={"Authorization": "Bearer test-token"},
        json={"questionsAsked": 0, "transcriptTurns": []},
    )
    q2 = client.post(
        "/candidate/interview-session/11111111-1111-1111-1111-111111111111/next-question",
        headers={"Authorization": "Bearer test-token"},
        json={"questionsAsked": 1, "transcriptTurns": []},
    )
    q3 = client.post(
        "/candidate/interview-session/11111111-1111-1111-1111-111111111111/next-question",
        headers={"Authorization": "Bearer test-token"},
        json={"questionsAsked": 2, "transcriptTurns": []},
    )

    assert q1.status_code == 200
    assert q2.status_code == 200
    assert q3.status_code == 200

    q1_text = q1.json()["question"]
    q2_text = q2.json()["question"]
    q3_text = q3.json()["question"]

    assert q1_text != q2_text
    assert q2_text != q3_text
    assert q1_text != q3_text


def test_candidate_next_question_uses_transcript_when_client_counter_is_stale(monkeypatch):
    def fake_get_supabase_user(_access_token):
        return {"id": "user-1", "email": "candidate@example.com"}

    def fake_get_or_create_candidate(_user):
        return {"id": "candidate-1", "ai_summary": "Backend API and distributed systems experience."}

    def fake_supabase_request(path, method="GET", body=None, bearer_token=None, use_service_role=False):
        if path.startswith("/rest/v1/interview_sessions?") and method == "GET":
            return [{"id": "11111111-1111-1111-1111-111111111111", "status": "in_progress", "interview_role": "Backend Developer"}]
        if path.startswith("/rest/v1/job_specifications?") and method == "GET":
            return []
        raise AssertionError(f"Unexpected request: {path}")

    monkeypatch.setattr(routes, "_get_supabase_user", fake_get_supabase_user)
    monkeypatch.setattr(routes, "_get_or_create_candidate", fake_get_or_create_candidate)
    monkeypatch.setattr(routes, "_supabase_request", fake_supabase_request)
    monkeypatch.setattr(routes, "settings", replace(routes.settings, interview_realtime_provider="groq"))

    response = client.post(
        "/candidate/interview-session/11111111-1111-1111-1111-111111111111/next-question",
        headers={"Authorization": "Bearer test-token"},
        json={
            "questionsAsked": 0,
            "transcriptTurns": [
                {"speaker": "ai", "text": "Q1/6: Explain your approach and complexity trade-offs."}
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["questionNumber"] == 2


def test_candidate_next_question_falls_back_to_latest_in_progress_session(monkeypatch):
    def fake_get_supabase_user(_access_token):
        return {"id": "user-1", "email": "candidate@example.com"}

    def fake_get_or_create_candidate(_user):
        return {"id": "candidate-1", "ai_summary": "Strong Python and API design."}

    def fake_supabase_request(path, method="GET", body=None, bearer_token=None, use_service_role=False):
        if path.startswith("/rest/v1/interview_sessions?id=eq.") and method == "GET":
            return []
        if (
            path.startswith("/rest/v1/interview_sessions?")
            and "candidate_id=eq.candidate-1" in path
            and "status=eq.in_progress" in path
            and method == "GET"
        ):
            return [{"id": "fallback-session", "status": "in_progress", "interview_role": "Backend Developer"}]
        if path.startswith("/rest/v1/job_specifications?") and method == "GET":
            return []
        raise AssertionError(f"Unexpected request: {path}")

    monkeypatch.setattr(routes, "_get_supabase_user", fake_get_supabase_user)
    monkeypatch.setattr(routes, "_get_or_create_candidate", fake_get_or_create_candidate)
    monkeypatch.setattr(routes, "_supabase_request", fake_supabase_request)
    monkeypatch.setattr(routes, "settings", replace(routes.settings, interview_realtime_provider="groq"))

    response = client.post(
        "/candidate/interview-session/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/next-question",
        headers={"Authorization": "Bearer test-token"},
        json={"questionsAsked": 0, "transcriptTurns": []},
    )

    assert response.status_code == 200
    assert response.json()["questionNumber"] == 1
    assert response.json()["question"].startswith("Q1/6:")


def test_get_supabase_user_returns_503_on_supabase_network_error(monkeypatch):
    def fake_supabase_request(path, method="GET", body=None, bearer_token=None, use_service_role=False):
        raise routes.SupabaseError("supabase_network_error: [WinError 10054] connection reset")

    monkeypatch.setattr(routes, "_supabase_request", fake_supabase_request)

    try:
        routes._get_supabase_user("token")
        assert False, "Expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 503
        assert "temporarily unavailable" in str(exc.detail).lower()