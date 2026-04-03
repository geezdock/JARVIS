# JARVIS AI Recruitment Platform

JARVIS is a modern full-stack recruitment platform that helps teams screen, review, and manage candidates faster with AI-assisted workflows.

The current implementation includes:
- A React + Vite frontend with Supabase auth
- A FastAPI backend that validates Supabase tokens and persists profile uploads
- A Supabase schema migration with RLS policies for candidate data
- Resume upload, interview start, and admin review flows
- AI resume summarization support in the admin detail view
- Interview role routing with candidate input, admin override, and fallback inference
- Browser-based interview recording with private artifact storage and admin playback
- Strict LLM-based interview scoring with retry handling
- Admin search/filter/sort, stage updates, and bulk stage operations
- Backend pytest coverage for health/admin/audit/background-job paths

## What Is Working Now

- Candidate login and signup through Supabase auth
- Role-aware routing for candidate and admin views
- Resume upload flow from the frontend to Supabase Storage with backend metadata persistence
- Backend verification of the Supabase access token
- Supabase-backed insert flow for candidate upload records and interview role data
- Live server-synced interview start timing
- Admin candidate detail analysis with extracted skills and summary
- Resolved interview role fallback: admin override -> candidate target role -> resume inference
- Role-specific interview flow and starter question set for candidates
- Interview session recording, transcript autosave, and admin playback timeline
- Strict three-part scoring model (resume/interview/behavior) with reliability retry layer
- Admin candidate search, stage filtering, score sorting, pagination, and bulk stage updates
- Background-job execution mode for selected admin actions
- Audit log capture and paginated retrieval endpoint

## Project Layout

```text
JARVIS/
  frontend/                    React + Vite app
  backend/                     FastAPI app
  backend/supabase/schema.sql   Supabase tables + RLS migration
  backend/frontend-supabase/    Reference copies of frontend Supabase helpers
  NEXT_TODO.md                 Implementation checklist
```

## Key Features

### Frontend

- Supabase auth context with login, signup, logout, and session bootstrap
- Role-based protected routes for `candidate` and `admin`
- Candidate pages:
  - Dashboard
  - Profile upload with PDF validation and target interview role text input
  - Interview start screen with role-specific plan/questions
- Admin pages:
  - Candidate dashboard with search
  - Candidate detail view with resume and AI summary cards
  - Interview role controls (target role and admin override)
  - Stage update controls and bulk stage actions
  - Pagination and score sort controls
- UI polish with Tailwind CSS, Framer Motion, and toast notifications

### Backend

- FastAPI API with CORS configured for the frontend origin
- `GET /health` for service checks
- `GET /time` for server UTC sync
- `POST /candidate/profile-upload` persists upload metadata in Supabase
- `POST /candidate/storage/signed-upload` creates storage signed upload URLs
- `POST /candidate/interview-slots` starts interview and returns role-based interview plan
- `POST /candidate/interview-session/start` starts an interview session
- `POST /candidate/interview-session/{session_id}/complete` completes session and scoring flow
- `POST /candidate/interview-session/{session_id}/score/retry` retries scoring for candidate-owned session
- `POST /admin/analyze-resume/{candidate_id}` generates and stores resume analysis
- `POST/PATCH /admin/candidates/{candidate_id}/interview-role` saves target/override interview role
- `POST/PATCH /admin/candidates/{candidate_id}/stage` updates candidate pipeline stage
- `POST/PATCH /admin/candidates/bulk-stage` bulk updates stages for selected candidates
- `GET /admin/background-jobs/{job_id}` checks async background-job status
- `GET /admin/audit-logs` fetches paginated admin audit logs
- Backend config supports Supabase URL, anon key, service role key, and database URL

### Supabase

- `backend/supabase/schema.sql` contains the migration for:
  - `candidates`
  - `profile_uploads`
  - `interview_slots`
- `candidates` includes dedicated interview role fields:
  - `target_role`
  - `admin_override_role`
- Row-level security is enabled for all three tables
- Candidate policies restrict access to the authenticated user
- Storage policies scope resume files to the authenticated user folder

## Quick Start

### 1. Frontend

```powershell
cd frontend
npm install
npm run dev -- --port 5173
```

Frontend URL: `http://localhost:5173` (or next available port shown by Vite)

### 2. Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
.\.venv\Scripts\python.exe -m uvicorn run:app --reload --port 8000
```

Backend URL: `http://localhost:8000`

### 3. Apply Supabase Schema

Open `backend/supabase/schema.sql` in the Supabase SQL editor and run it.

## Environment Variables

### Frontend

Use `frontend/.env.example` and keep only browser-safe values:

- `VITE_SUPABASE_URL`
- `VITE_SUPABASE_ANON_KEY`
- `VITE_API_BASE_URL` (default: `http://localhost:8000`)

### Backend

Use `backend/.env.example` for backend-only values:

- `APP_NAME`
- `APP_ENV`
- `APP_PORT`
- `FRONTEND_ORIGIN`
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_DB_URL`

## Build Frontend

```powershell
cd frontend
npm run build
```

## Run Backend Tests

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
```

## Troubleshooting

### ENOENT: package.json not found

If you run `npm` from the repo root, use the frontend folder explicitly:

```powershell
npm --prefix frontend run dev
```

### Address already in use (backend/frontend)

If a port is already occupied, either stop the process using it or start on another port.

Backend example:

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn run:app --reload --port 8001
```

Frontend example:

```powershell
cd frontend
npm run dev -- --port 5176
```

### Supabase REST root returns 401

That is expected if you test `/rest/v1/` directly. Test a real table route after the schema is applied, for example:

```http
GET /rest/v1/candidates?select=*
```

## Next Steps

- Phase 10: email and notification workflows (provider + stage-based triggers)
- Expand tests to frontend integration/component coverage
- Add deployment docs, containerization, and CI/CD pipeline
- Improve production hardening: rate limiting, monitoring, and caching strategy
