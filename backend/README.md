# Backend (FastAPI)

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:
   pip install -r requirements.txt
3. Copy environment file:
   copy .env.example .env
4. Run server:
   uvicorn run:app --reload --port 8000

## API Endpoints

- GET /            -> basic API message
- GET /health      -> health check
- POST /candidate/profile-upload -> saves upload metadata in Supabase

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
