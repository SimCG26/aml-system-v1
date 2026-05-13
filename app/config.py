from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
     # Application
    app_name: str = "AML System"
    app_version: str = "1.0.0"
    api_v1_prefix: str = "/api/v1"

    # Environment
    environment: str = "development"
    debug: bool = True

    # Database
    postgres_db: str = "aml_db"
    postgres_user: str = "aml"
    postgres_password: str = "aml"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    database_url: str = (
        "postgresql+asyncpg://aml:aml@localhost:5432/aml_db"
    )

    # Connection Pool
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Security
    secret_key: str = "aml_super_secret_key"

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings():
    return Settings()