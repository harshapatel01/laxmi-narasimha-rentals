from functools import lru_cache
import ipaddress
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    app_env: str = "development"
    app_name: str = "Laxmi Narasimha Rentals API"
    api_v1_prefix: str = "/api/v1"
    frontend_origin: str = "http://localhost:5173"
    db_host: str = "localhost"
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = "laxmi_narasimha_rentals"
    db_user: str = "lnr_app"
    db_password: str | None = None
    admin_mfa_required: bool = True
    auth_secret_key: str | None = Field(default=None, min_length=32)
    totp_encryption_key: str | None = None
    customer_session_hours: int = Field(default=24, ge=1, le=720)
    admin_session_hours: int = Field(default=8, ge=1, le=24)
    otp_expiration_minutes: int = Field(default=5, ge=1, le=10)
    otp_resend_cooldown_seconds: int = Field(default=60, ge=15, le=300)
    otp_max_attempts: int = Field(default=5, ge=1, le=10)
    otp_rate_limit_count: int = Field(default=5, ge=1, le=20)
    otp_rate_limit_window_minutes: int = Field(default=15, ge=1, le=120)
    password_reset_token_minutes: int = Field(default=30, ge=5, le=120)
    password_reset_ip_limit: int = Field(default=10, ge=1, le=100)
    password_reset_ip_window_minutes: int = Field(default=15, ge=1, le=1440)
    password_reset_email_limit: int = Field(default=3, ge=1, le=20)
    password_reset_email_window_minutes: int = Field(default=60, ge=1, le=1440)
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_use_ssl: bool = False
    brevo_api_key: str | None = None
    brevo_sender_email: str | None = None
    brevo_sender_name: str | None = None
    whatsapp_webhook_verify_token: str | None = None
    whatsapp_app_secret: str | None = None
    whatsapp_access_token: str | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_admin_phone_number: str | None = None
    whatsapp_api_version: str | None = None
    whatsapp_booking_template_name: str | None = None
    whatsapp_booking_template_language: str = "en_US"
    booking_admin_email: str | None = None
    secure_cookies: bool | None = None
    vehicle_image_storage_path: str = "uploads/vehicles"
    vehicle_image_max_bytes: int = Field(default=8 * 1024 * 1024, ge=1024, le=25 * 1024 * 1024)

    @property
    def cookies_are_secure(self) -> bool:
        if self.app_env.lower() not in {"development", "test"}:
            return True
        return self.secure_cookies is True

    def requires_admin_mfa(self, client_host: str | None) -> bool:
        return self.admin_mfa_required
    

    @property
    def auth_key(self) -> bytes:
        if self.auth_secret_key:
            return self.auth_secret_key.encode("utf-8")
        raise RuntimeError("AUTH_SECRET_KEY must be configured in backend/.env.")

    @property
    def totp_key(self) -> str:
        if not self.totp_encryption_key:
            raise RuntimeError("TOTP_ENCRYPTION_KEY must be configured before admin authentication.")
        return self.totp_encryption_key

    @property
    def vehicle_image_storage_directory(self) -> Path:
        path = Path(self.vehicle_image_storage_path)
        return path.resolve() if path.is_absolute() else (Path.cwd() / path).resolve()

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def database_url(self) -> URL | None:
        if not self.db_password:
            return None
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.db_user,
            password=self.db_password,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
