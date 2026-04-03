# JARVIS AI Recruitment Platform

JARVIS is a modern full-stack recruitment platform that helps teams screen, review, and manage candidates faster with AI-assisted workflows.

It includes:
- A polished React frontend for candidates and admins
- A FastAPI backend for API endpoints and integration
- Supabase-ready auth and token-based request flow

## Why This Project Feels Useful

- Clear candidate journey: signup, profile upload, interview scheduling
- Admin-focused dashboard: search candidates, review details, see AI score
- Clean UX: responsive layout, micro-animations, and toast feedback
- Simple local setup with separate frontend and backend folders

## Project Layout

```text
JARVIS/
  frontend/                  React + Vite + Tailwind + Supabase Auth
  backend/                   FastAPI service
  backend/frontend-supabase/ Copied frontend Supabase helper files (reference)
```

## Features

### Frontend

- Role-based protected routes (`candidate`, `admin`)
- Supabase auth context: login, signup, logout, session listener
- Candidate flow:
  - Dashboard
  - PDF resume upload with validation
  - Interview slot scheduling (mock)
- Admin flow:
  - Candidate list with search
  - Candidate detail page with transcript summary and score
  - Recommended candidates panel
- UI stack:
  - Tailwind CSS
  - Framer Motion
  - react-hot-toast notifications

### Backend

- FastAPI app with CORS configured for local frontend
- Available endpoints:
  - `GET /` - API message
  - `GET /health` - health status
  - `POST /candidate/profile-upload` - mock profile upload
- Environment-driven settings via `.env`

## Quick Start (Windows)

### 1. Start Frontend

```powershell
cd frontend
npm install
npm run dev
```

Frontend URL: `http://localhost:5173`

### 2. Start Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn run:app --reload --port 8000
```

Backend URL: `http://localhost:8000`

## Environment Variables

### Frontend (`frontend/.env`)

Use `frontend/.env.example` and configure:

- `VITE_SUPABASE_URL`
- `VITE_SUPABASE_ANON_KEY`
- `VITE_API_BASE_URL` (default: `http://localhost:8000`)

### Backend (`backend/.env`)

Use `backend/.env.example` and configure:

- `APP_NAME`
- `APP_ENV`
- `APP_PORT`
- `FRONTEND_ORIGIN` (default: `http://localhost:5173`)
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`

## Build Frontend

```powershell
cd frontend
npm run build
```

## Troubleshooting

### ENOENT: package.json not found

If you run npm from repo root, you may see ENOENT. Run commands inside `frontend/` or use:

```powershell
npm --prefix frontend run dev
```

## Roadmap

- Add backend JWT verification for protected APIs
- Integrate real Supabase DB and storage operations
- Add frontend and backend test coverage
- Add Docker Compose for one-command local startup
