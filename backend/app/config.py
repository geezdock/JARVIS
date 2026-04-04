import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv


_CONFIG_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _CONFIG_DIR.parent
_ENV_FILE = _BACKEND_DIR / ".env"

# Ensure backend/.env is loaded no matter where uvicorn is launched from.
load_dotenv(_ENV_FILE)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Jarvis Recruit API")
    app_env: str = os.getenv("APP_ENV", "development")
    app_port: int = int(os.getenv("APP_PORT", "8000"))
    frontend_origin: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_anon_key: str = os.getenv("SUPABASE_ANON_KEY", "")
    supabase_service_role_key: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    supabase_db_url: str = os.getenv("SUPABASE_DB_URL", "")
    llm_provider: str = os.getenv("LLM_PROVIDER", "openrouter").strip().lower()
    llm_provider_fallbacks: str = os.getenv("LLM_PROVIDER_FALLBACKS", "groq")
    llm_model: str = os.getenv("LLM_MODEL", "openai/gpt-4o-mini")
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_site_url: str = os.getenv("OPENROUTER_SITE_URL", "")
    openrouter_app_name: str = os.getenv("OPENROUTER_APP_NAME", "")
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    interview_realtime_provider: str = os.getenv("INTERVIEW_REALTIME_PROVIDER", "openai").strip().lower()
    interview_realtime_model: str = os.getenv("INTERVIEW_REALTIME_MODEL", "gpt-4o-realtime-preview-2024-12-17")
    interview_realtime_voice: str = os.getenv("INTERVIEW_REALTIME_VOICE", "alloy")
    interview_max_questions: int = int(os.getenv("INTERVIEW_MAX_QUESTIONS", "6"))
    interview_max_duration_seconds: int = int(os.getenv("INTERVIEW_MAX_DURATION_SECONDS", "900"))
    interview_ai_output_mode: str = os.getenv("INTERVIEW_AI_OUTPUT_MODE", "browser_tts")


settings = Settings()
