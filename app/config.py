# app/config.py - full file
from pydantic_settings import BaseSettings, SettingsConfigDict


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


settings = Settings()



