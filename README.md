# JARVIS AI Recruitment Platform

JARVIS is a modern full-stack recruitment platform that helps teams screen, review, and manage candidates faster with AI-assisted workflows.

The current implementation includes:
- A React + Vite frontend with Supabase auth
- A FastAPI backend that validates Supabase tokens and persists profile uploads
- A Supabase schema migration with RLS policies for candidate data
- Resume upload, interview start, and admin review flows
- AI resume summarization support in the admin detail view

## What Is Working Now

- Candidate login and signup through Supabase auth
- Role-aware routing for candidate and admin views
- Resume upload flow from the frontend to the backend
- Backend verification of the Supabase access token
- Supabase-backed insert flow for candidate upload records
- Live server-synced interview start timing
- Admin candidate detail analysis with extracted skills and summary

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
  - Profile upload with PDF validation
  - Interview start screen
- Admin pages:
  - Candidate dashboard with search
  - Candidate detail view with resume and AI summary cards
- UI polish with Tailwind CSS, Framer Motion, and toast notifications

### Backend

- FastAPI API with CORS configured for the frontend origin
- `GET /health` for service checks
- `GET /time` for server UTC sync
- `POST /candidate/profile-upload` persists upload metadata in Supabase
- `POST /candidate/storage/signed-upload` creates storage signed upload URLs
- `POST /admin/analyze-resume/{candidate_id}` generates and stores resume analysis
- Backend config supports Supabase URL, anon key, service role key, and database URL

### Supabase

- `backend/supabase/schema.sql` contains the migration for:
  - `candidates`
  - `profile_uploads`
  - `interview_slots`
- Row-level security is enabled for all three tables
- Candidate policies restrict access to the authenticated user
- Storage policies scope resume files to the authenticated user folder

## Quick Start

### 1. Frontend

```powershell
cd frontend
npm install
npm run dev
```

Frontend URL: `http://localhost:5173`

### 2. Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn run:app --reload --port 8000
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

## Troubleshooting

### ENOENT: package.json not found

If you run `npm` from the repo root, use the frontend folder explicitly:

```powershell
npm --prefix frontend run dev
```

### Supabase REST root returns 401

That is expected if you test `/rest/v1/` directly. Test a real table route after the schema is applied, for example:

```http
GET /rest/v1/candidates?select=*
```

## Next Steps

- Add storage upload verification for PDFs in Supabase Storage
- Add real AI provider integration for resume summarization
- Add real data fetching in the dashboard pages
- Add automated tests for the backend route and frontend flows
