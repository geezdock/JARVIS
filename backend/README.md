# Backend (FastAPI)

## Setup

1. Create and activate a virtual environment:
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
2. Install dependencies:
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
3. Copy environment file:
   copy .env.example .env
4. Run server:
   .\.venv\Scripts\python.exe -m uvicorn run:app --reload --port 8000

## API Endpoints

- GET /            -> basic API message
- GET /health      -> health check
- POST /candidate/profile-upload -> saves upload metadata in Supabase
- POST /candidate/interview-session/start -> starts candidate interview session
- POST /candidate/interview-session/{session_id}/complete -> completes session and stores scoring state
- POST /candidate/interview-session/{session_id}/score/retry -> candidate retry scoring
- POST/PATCH /admin/candidates/{candidate_id}/stage -> update candidate stage
- POST/PATCH /admin/candidates/bulk-stage -> bulk update candidate stages
- GET /admin/background-jobs/{job_id} -> background job status
- GET /admin/audit-logs -> admin audit log listing

## Frontend Integration

Your frontend axios base URL is configured via:
- VITE_API_BASE_URL=http://localhost:8000

The frontend currently posts to:
- /candidate/profile-upload

The backend route validates the Supabase bearer token, resolves the user, and inserts into Supabase tables.

## Supabase Schema

Apply the migration in:
- supabase/schema.sql

## Backend Environment

Use `backend/.env.example` as the source of truth for backend-only values, including:

- SUPABASE_URL
- SUPABASE_ANON_KEY
- SUPABASE_SERVICE_ROLE_KEY
- SUPABASE_DB_URL

## AI Resume Summarization

The resume analysis endpoint uses OpenAI when `OPENAI_API_KEY` is set.

- Default model: `gpt-4o-mini`
- Keep requests short by extracting only the relevant resume text before sending it to the model
- Review OpenAI pricing and rate limits before enabling production traffic
- Scoring is strict LLM-based, with retry/backoff and pending status handling instead of heuristic fallback
