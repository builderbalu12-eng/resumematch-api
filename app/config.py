# app/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Set, Optional
from pathlib import Path
import os


class Settings(BaseSettings):
    # ── Core / Environment ───────────────────────────────────────
    environment: str = "development"
    port: int = 8000

    # ── MongoDB ──────────────────────────────────────────────────
    mongodb_url: str
    mongodb_db_name: str

    # ── JWT / Auth ───────────────────────────────────────────────
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 10080   # 7 days

    # ── Google OAuth ─────────────────────────────────────────────
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str

    # ── Frontend / URLs ──────────────────────────────────────────
    frontend_uri: str = "http://localhost:5173"
    frontend_base_url: str                          # required
    payment_success_url: str = ""                   # can be empty

    # ── Gemini (AI features) ─────────────────────────────────────
    gemini_api_key: str
    gemini_model: str = "gemini-1.5-flash"          # fallback
    # Optional: you can add more granularity later
    # gemini_temperature_default: float = 0.2
    # gemini_max_tokens_default: int = 1800

    # ── Resume feature specifics ─────────────────────────────────
    resume_template_admins: str = ""   # comma-separated emails

    # ── Razorpay / Payments ──────────────────────────────────────
    razorpay_key_id: str
    razorpay_key_secret: str
    razorpay_webhook_secret: Optional[str] = None

    # ── OpenClaw (whatever this service/gateway is) ──────────────
    base_openclaw_port: int = 19000
    openclaw_data_dir: str = str(Path.home() / "openclaw_data")
    openclaw_max_users: int = 100
    openclaw_gateway_token: str = "supersecret123"   # ← consider renaming or moving to secret

    # ── Computed / helper properties ─────────────────────────────
    @property
    def resume_admin_emails(self) -> Set[str]:
        if not self.resume_template_admins:
            return set()
        return {
            email.strip().lower()
            for email in self.resume_template_admins.split(",")
            if email.strip()
        }

    @property
    def openclaw_base_url(self) -> str:
        # Better: read from env or make it more flexible
        host = os.getenv("OPENCLAW_HOST", "localhost")
        port = self.base_openclaw_port
        return f"http://{host}:{port}"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        # Very useful in containers / CI:
        env_nested_delimiter="__",           # allows MONGODB__URL=... syntax
        env_prefix="",                       # or "APP_" if you prefer namespacing
    )


settings = Settings()