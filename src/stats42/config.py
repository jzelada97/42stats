from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración desde variables de entorno (prefijo FT_) o fichero .env."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="FT_", extra="ignore")

    uid: str
    secret: str
    campus_id: int = 22  # 42 Madrid
    cursus_id: int = 21  # 42cursus
    database_url: str = "sqlite:///data/stats42.db"
    api_base: str = "https://api.intra.42.fr"
    # Sin User-Agent propio, el filtro anti-bots de la API responde 403.
    user_agent: str = "stats42/0.1"
