from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Telegram User API (my.telegram.org)
    tg_api_id: int = 0
    tg_api_hash: str = ""
    tg_source: str = ""  # @channel або -100xxxxxxxxxx

    replicate_api_token: str = ""
    anthropic_api_key: str = ""

    admin_password: str = "change_me"
    site_name: str = "SAHARA"
    base_url: str = "http://localhost:8000"

    db_path: str = "data/sahara.db"
    media_dir: str = "media"


settings = Settings()
