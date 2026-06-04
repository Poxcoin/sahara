import sys
from pydantic_settings import BaseSettings, SettingsConfigDict

_WEAK_PASSWORDS = {"change_me", "admin", "password", "1234", "sahara"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Telegram User API (my.telegram.org)
    tg_api_id: int = 0
    tg_api_hash: str = ""
    tg_source: str = ""  # @channel або -100xxxxxxxxxx

    replicate_api_token: str = ""
    anthropic_api_key: str = ""
    fal_key: str = ""
    fashn_key: str = ""

    admin_username: str = "admin"
    admin_password_hash: str = ""
    totp_encryption_key: str = ""
    secret_key: str = "change_me_secret_key_32_chars_min"
    site_name: str = "SAHARA"
    base_url: str = "http://localhost:8000"

    # 1C HTTP API key (shared secret for both 1C databases)
    api_1c_key: str = ""

    # Telegram Bot для сповіщень про замовлення
    tg_bot_token: str = ""
    tg_admin_chat_id: str = ""

    # Nova Poshta API (np.api.key з особистого кабінету сайту novaposhta.ua)
    np_api_key: str = ""

    # Resend (resend.com) — for transactional emails
    resend_api_key: str = ""
    smtp_from: str = "noreply@sahara-store.net"

    # SMTP fallback (not used if resend_api_key is set)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""

    db_path: str = "data/sahara.db"
    media_dir: str = "media"


settings = Settings()
