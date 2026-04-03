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
- POST /candidate/profile-upload -> mock profile upload

## Frontend Integration

Your frontend axios base URL is configured via:
- VITE_API_BASE_URL=http://localhost:8000

The frontend currently posts to:
- /candidate/profile-upload

The backend route is exposed at:
- /candidate/profile-upload
