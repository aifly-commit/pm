"""全局配置（design.md 8.8：JWT 12 小时；4.2：时区 Asia/Shanghai）。"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict

# 全平台统一时区
TZ = ZoneInfo("Asia/Shanghai")

# JWT access_token 有效期（小时）
ACCESS_TOKEN_EXPIRE_HOURS = 12

# 开发用默认密钥：仅本地调试用，生产启动时必须通过 PM_SECRET_KEY 覆盖
DEFAULT_SECRET_KEY = "dev-only-insecure-secret-change-me"


class Settings(BaseSettings):
    """应用配置，支持环境变量 / .env 覆盖。"""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="PM_")

    # JWT 密钥：生产环境必须通过 PM_SECRET_KEY 注入
    secret_key: str = DEFAULT_SECRET_KEY
    algorithm: str = "HS256"

    # 数据库：默认项目根目录下 pm.db
    database_url: str = "sqlite+aiosqlite:///./pm.db"

    # 提醒配置（design.md 4.1）
    reminder_due_soon_days: int = 1  # 距预计结束 ≤ N 天视为临期
    reminder_start_soon_enabled: bool = False  # 临开始提醒（可选，默认关闭）


settings = Settings()


def ensure_secret_key_safe() -> None:
    """启动校验：secret_key 仍为不安全的默认值时拒绝启动。

    默认密钥硬编码在仓库中，任何人可用它伪造任意角色（含 admin）的 token。
    """
    if settings.secret_key == DEFAULT_SECRET_KEY:
        raise RuntimeError(
            "JWT 密钥为不安全的默认值，拒绝启动。"
            "请通过环境变量 PM_SECRET_KEY 设置随机密钥后重试"
        )
