from __future__ import annotations

import os


class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://marketplace:marketplace@localhost:5432/marketplace",
    )
    jwt_secret: str = os.getenv("JWT_SECRET", "change-me-in-production")
    access_token_minutes: int = int(os.getenv("ACCESS_TOKEN_MINUTES", "20"))
    refresh_token_days: int = int(os.getenv("REFRESH_TOKEN_DAYS", "14"))
    order_rate_limit_minutes: int = int(os.getenv("ORDER_RATE_LIMIT_MINUTES", "1"))


settings = Settings()
