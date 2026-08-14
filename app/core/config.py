"""全局配置（design.md 8.8：JWT 12 小时；4.2：时区 Asia/Shanghai）。"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict

# 全平台统一时区
TZ = ZoneInfo("Asia/Shanghai")

# JWT access_token 有效期（小时）
ACCESS_TOKEN_EXPIRE_HOURS = 12


class Settings(BaseSettings):
    """应用配置，支持环境变量 / .env 覆盖。"""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="PM_")

    # JWT 密钥：生产环境必须通过 PM_SECRET_KEY 注入
    secret_key: str = "dev-only-insecure-secret-change-me"
    algorithm: str = "HS256"

    # 数据库：默认项目根目录下 pm.db
    database_url: str = "sqlite+aiosqlite:///./pm.db"


settings = Settings()
