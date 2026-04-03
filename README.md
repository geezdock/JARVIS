# JARVIS - AI Recruitment Platform

This repository contains a full-stack AI recruitment platform with separate frontend and backend applications.

## Project Structure

- `frontend/` - React + Vite + Tailwind UI with Supabase Auth
- `backend/` - FastAPI service with candidate profile upload mock endpoint
- `backend/frontend-supabase/` - copied frontend Supabase helper files for reference

## What Is Implemented

### Frontend

- Role-based routing (`candidate`, `admin`) with protected routes
- Supabase authentication context (login, signup, logout, session listener)
- Candidate flow:
  - Dashboard
  - Profile upload (PDF validation + API call)
  - Interview scheduling (mock slots)
- Admin flow:
  - Dashboard with candidate list and search filter
  - Candidate details (resume preview, AI transcript, score)
  - Recommended candidates section
- UI polish:
  - Tailwind CSS styling
  - Framer Motion micro-animations
  - Toast notifications via `react-hot-toast`

### Backend

- FastAPI app with CORS configured for frontend
- Endpoints:
  - `GET /` (API message)
  - `GET /health` (health check)
  - `POST /candidate/profile-upload` (mock profile upload)
- Environment-based configuration loading via `.env`

## Environment Variables

### Frontend (`frontend/.env`)

Use `frontend/.env.example` as reference:

- `VITE_SUPABASE_URL`
- `VITE_SUPABASE_ANON_KEY`
- `VITE_API_BASE_URL` (default: `http://localhost:8000`)

### Backend (`backend/.env`)

Use `backend/.env.example` as reference:

- `APP_NAME`
- `APP_ENV`
- `APP_PORT`
- `FRONTEND_ORIGIN` (default: `http://localhost:5173`)
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`

## Run the Project

## 1. Frontend

```powershell
cd frontend
npm install
npm run dev
```

Frontend runs at: `http://localhost:5173`

## 2. Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn run:app --reload --port 8000
```

Backend runs at: `http://localhost:8000`

## Build Frontend

```powershell
cd frontend
npm run build
```

## Common Windows Command Note

If you run `npm run ...` from project root and get ENOENT for `package.json`, run from `frontend/` or use:

```powershell
npm --prefix frontend run dev
```

## Next Recommended Steps

- Add real backend auth token verification for protected API routes
- Connect backend endpoints to Supabase database/storage
- Add tests for frontend routes and backend endpoints
- Add Docker compose for one-command local startup
