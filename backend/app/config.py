import os
from dataclasses import dataclass
from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Jarvis Recruit API")
    app_env: str = os.getenv("APP_ENV", "development")
    app_port: int = int(os.getenv("APP_PORT", "8000"))
    frontend_origin: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")


settings = Settings()
