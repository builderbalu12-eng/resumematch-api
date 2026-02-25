# app/config.py - full file
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Any, Dict, Optional, List  # ← ADD THIS LINE
from pathlib import Path

class Settings(BaseSettings):
    environment: str = "development"
    port: int = 8000

    mongodb_url: str
    mongodb_db_name: str

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 10080

    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str

    frontend_uri: str = "http://localhost:5173"

    resume_template_admins: str = ""  # comma-separated list

    razorpay_key_id: str
    razorpay_key_secret: str
    razorpay_webhook_secret: Optional[str] = None

    gemini_api_key: str   # ← ADD THIS LINE

    base_openclaw_port: int = 19000                  # users get 19000, 19001, ...
    openclaw_data_dir: str = str(Path.home() / "openclaw_data")
    # openclaw_data_dir: str = "/var/lib/openclaw"     # persistent folder
    openclaw_max_users: int = 100                    # safety limit

    openclaw_gateway_token: str ="supersecret123" # ← Add this line

    @property
    def resume_admin_emails(self) -> set[str]:
        """Returns set of admin emails (normalized)"""
        if not self.resume_template_admins:
            return set()
        return {email.strip().lower() for email in self.resume_template_admins.split(",") if email.strip()}

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def openclaw_base_url(self) -> str:
        return f"http://localhost"  # or domain if you expose gateways

settings = Settings()



