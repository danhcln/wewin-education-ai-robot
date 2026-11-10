import os
from pathlib import Path
import re
from dotenv import dotenv_values

# Base directory
BASE_DIR = Path(__file__).resolve().parent.parent

def load_admin_token(values: dict) -> str:
    """Read one explicit secret source; absent/invalid configuration disables admin access."""
    token_file = (values.get("ADMIN_SYNC_TOKEN_FILE") or "").strip()
    inline_token = (values.get("ADMIN_SYNC_TOKEN") or "").strip()
    if token_file and inline_token:
        return ""  # Ambiguous configuration must never silently choose a credential.
    if token_file:
        try:
            path = (BASE_DIR / token_file).resolve()
            if any(path.is_relative_to(BASE_DIR / "frontend" / part) for part in ("dist", "public")):
                return ""
            if path.stat().st_size > 4096:
                return ""
            inline_token = path.read_text(encoding="utf-8").strip()
        except (OSError, ValueError, UnicodeError, RuntimeError):
            return ""
    # Legacy short development credentials are not accepted, even if left in .env.
    return inline_token if re.fullmatch(r"[A-Za-z0-9_-]{32,512}", inline_token) else ""

class Settings:
    def __init__(self):
        self.reload()

    def reload(self):
        """Reload file configuration without overwriting service environment variables."""
        values = {**dotenv_values(BASE_DIR / ".env", interpolate=False), **os.environ}
        def env(name: str, default: str = "") -> str:
            return values.get(name) or default

        # Server settings
        self.SERVER_HOST: str = env("SERVER_HOST", "127.0.0.1").strip()
        self.SERVER_PORT: int = int(env("SERVER_PORT", "8000"))
        self.DEBUG: bool = env("DEBUG", "false").lower() in ("true", "1", "yes")

        # Security
        self.ADMIN_SYNC_TOKEN: str = load_admin_token(values)
        self.CORS_ALLOWED_ORIGINS = [origin.strip() for origin in env("CORS_ALLOWED_ORIGINS").split(",") if origin.strip() and origin.strip() != "*"]

        # Storage paths
        self.DATABASE_PATH: Path = BASE_DIR / env("DATABASE_PATH", "data/wewin_fts.db").strip()
        self.KNOWLEDGE_JSON_PATH: Path = BASE_DIR / env("KNOWLEDGE_JSON_PATH", "data/wewin_knowledge.json").strip()

        # Crawler Settings
        self.WEBSITE_BASE_URL: str = "https://wewin.edu.vn"
        self.CRAWLER_USER_AGENT: str = env("CRAWLER_USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) WeWIN-AI-Connector/1.0").strip()
        self.CRAWLER_TIMEOUT_SECONDS: int = int(env("CRAWLER_TIMEOUT_SECONDS", "15"))
        self.CRAWLER_DELAY_SECONDS: float = max(0.2, float(env("CRAWLER_DELAY_SECONDS", "0.8")))
        self.MAX_PAGES_TO_CRAWL: int = int(env("MAX_PAGES_TO_CRAWL", "50"))
        self.CRAWLER_RETRY_ATTEMPTS = max(1, min(5, int(env("CRAWLER_RETRY_ATTEMPTS", "3"))))
        self.CRAWLER_RETRY_BACKOFF_SECONDS = max(0.1, float(env("CRAWLER_RETRY_BACKOFF_SECONDS", "1")))
        self.CRAWLER_MAX_RETRY_WAIT_SECONDS = max(1, float(env("CRAWLER_MAX_RETRY_WAIT_SECONDS", "60")))
        self.CRAWLER_MAX_RESPONSE_BYTES = max(1024, int(env("CRAWLER_MAX_RESPONSE_BYTES", "5242880")))

        # Auto-Sync Settings
        self.AUTO_SYNC_ENABLED: bool = env("AUTO_SYNC_ENABLED", "false").lower() in ("true", "1", "yes")
        self.SYNC_INTERVAL_HOURS: int = int(env("SYNC_INTERVAL_HOURS", "12"))
        self.SYNC_LOCK_TIMEOUT_MINUTES: int = int(env("SYNC_LOCK_TIMEOUT_MINUTES", "25"))
        self.SYNC_SCHEDULER_OWNER = env("SYNC_SCHEDULER_OWNER", "external").lower()
        if self.SYNC_SCHEDULER_OWNER not in ("windows", "internal", "external"):
            raise ValueError("SYNC_SCHEDULER_OWNER must be windows, internal or external")
        self.SYNC_SCHEDULE_ARMED = env("SYNC_SCHEDULE_ARMED", "false").lower() in ("true", "1", "yes")

        # XiaoZhi MCP Bridge
        def bridge_secret(name):
            location = env(name + "_FILE").strip()
            if location:
                path = (BASE_DIR / location).resolve(strict=True)
                if path.is_relative_to(BASE_DIR / "frontend") or path.stat().st_size > 8192:
                    raise ValueError("Invalid bridge secret file location or size")
                return path.read_text(encoding="utf-8").strip()
            return env(name).strip()
        self.XIAOZHI_MCP_ENDPOINT: str = bridge_secret("XIAOZHI_MCP_ENDPOINT")
        self.XIAOZHI_MCP_TOKEN: str = bridge_secret("XIAOZHI_MCP_TOKEN")

settings = Settings()

