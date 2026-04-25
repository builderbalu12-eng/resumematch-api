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
    # config.py
    google_maps_api_key: str = ""


    # ── JWT / Auth ───────────────────────────────────────────────
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 10080   # 7 days

    # ── Google OAuth ─────────────────────────────────────────────
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str
    gmail_redirect_uri: str = ""    # e.g. http://localhost:8000/auth/gmail/callback

    # ── Frontend / URLs ──────────────────────────────────────────
    frontend_uri: str = ""
    frontend_base_url: str                          # required
    payment_success_url: str = ""                   # can be empty

    # ── Claude / Anthropic (sole AI provider) ────────────────────
    claude_api_key: str = ""                        # set CLAUDE_API_KEY in .env
    claude_model: str = "claude-sonnet-4-6"         # safe default

    # ── Google Generative AI (legacy — only used by openclaw CLI) ─
    # Optional. The main API runtime no longer routes any traffic to Google.
    # Kept here so openclaw's CLI scraper, which calls google.generativeai
    # directly, can still run when the env var is provided.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # ── Resume feature specifics ─────────────────────────────────
    resume_template_admins: str = ""   # comma-separated emails
    admin_emails: str = ""             # comma-separated, for admin dashboard

    # ── SMTP / Email ─────────────────────────────────────────────
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_from_name: str = "ResumeMatch"

    # ── Cashfree / Payments ──────────────────────────────────────
    cashfree_app_id: str = ""
    cashfree_secret_key: str = ""
    cashfree_env: str = "sandbox"   # "sandbox" or "production" — set in Railway

    # ── Razorpay (disabled) ──────────────────────────────────────
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: Optional[str] = None

    # ── OpenClaw (whatever this service/gateway is) ──────────────
    base_openclaw_port: int = 19000
    openclaw_data_dir: str = str(Path.home() / "openclaw_data")
    openclaw_max_users: int = 100
    openclaw_gateway_token: str = "supersecret123"   # ← move to .env only!

    telegram_bot_token:    str = ""
    telegram_bot_username: str = ""

    # ── JSearch / RapidAPI ───────────────────────────────────────
    jsearch_api_key: str = ""  # Set JSEARCH_API_KEY in Railway env vars

    # ── Telegram job discovery / alerts ─────────────────────────
    telegram_job_search_top_n: int = 8
    telegram_alert_default_timezone: str = "Asia/Kolkata"
    telegram_job_alert_poll_seconds: int = 60

    # ── Computed / helper properties ─────────────────────────────
    @property
    def admin_email_set(self) -> Set[str]:
        """Returns set of dashboard admin emails (normalized lowercase)"""
        if not self.admin_emails:
            return set()
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}

    @property
    def resume_admin_emails(self) -> Set[str]:
        """Returns set of admin emails (normalized lowercase)"""
        if not self.resume_template_admins:
            return set()
        return {
            email.strip().lower()
            for email in self.resume_template_admins.split(",")
            if email.strip()
        }

    @property
    def openclaw_base_url(self) -> str:
        """Dynamic OpenClaw gateway URL"""
        host = os.getenv("OPENCLAW_HOST", "localhost")
        port = self.base_openclaw_port
        return f"http://{host}:{port}"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_nested_delimiter="__",           # allows MONGODB__URL=... syntax
        env_prefix="",                       # or "APP_" if you prefer namespacing
    )


settings = Settings()