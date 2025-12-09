import secrets
from urllib.parse import urlparse, urlunparse

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)

    PROJECT_NAME: str = "Agent Chassis"
    API_V1_STR: str = "/api/v1"

    # OpenAI Configuration
    OPENAI_API_KEY: str | None = None
    OPENAI_BASE_URL: str | None = None
    OPENAI_MODEL: str = "kimi-k2-thinking"

    # MCP Configuration
    MCP_CONFIG_PATH: str = "mcp_config.json"

    # OAuth Configuration (for MCP servers requiring authentication)
    OAUTH_TOKENS_PATH: str = ".mcp_tokens"  # Directory for persistent token storage
    OAUTH_REDIRECT_URI: str = "http://localhost:3000/callback"  # Default OAuth callback URI

    # Database Configuration (all optional - for server-side persistence)
    DATABASE_URL: str | None = None  # e.g., "postgresql+asyncpg://user:pass@localhost/agent_chassis"
    REDIS_URL: str | None = None  # e.g., "redis://localhost:6379/0"

    # Session Configuration
    SESSION_TTL_SECONDS: int = 86400  # 24 hours default TTL for Redis cache
    SESSION_MAX_MESSAGES: int = 100  # Max messages per session before truncation

    # Feature Flags
    ENABLE_PERSISTENCE: bool = False  # Default OFF - enables Redis/DB session storage
    ENABLE_USER_AUTH: bool = False  # Default OFF - enables user account system (OSP-14)

    # Security (API Key - legacy/simple auth)
    CHASSIS_API_KEY: str | None = None

    # JWT Configuration (for user auth - OSP-14)
    JWT_SECRET_KEY: str | None = None  # Required if ENABLE_USER_AUTH is True
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Google OAuth Configuration (OSP-14)
    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: str | None = None

    # Email Service Configuration (OSP-14)
    EMAIL_PROVIDER: str = "smtp"  # smtp, sendgrid, resend
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    EMAIL_FROM: str = "noreply@example.com"

    # SendGrid/Resend API keys (alternative to SMTP)
    SENDGRID_API_KEY: str | None = None
    RESEND_API_KEY: str | None = None

    # Verification Configuration (OSP-14)
    VERIFICATION_CODE_EXPIRE_MINUTES: int = 15
    VERIFICATION_MAX_ATTEMPTS: int = 3
    VERIFICATION_RATE_LIMIT_SECONDS: int = 60  # 1 email per minute

    # CORS Configuration
    CORS_ORIGINS: list[str] = ["*"]  # Configure for production: ["https://yourdomain.com"]
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_ALLOW_METHODS: list[str] = ["*"]
    CORS_ALLOW_HEADERS: list[str] = ["*"]

    # Rate Limiting Configuration
    LOGIN_RATE_LIMIT_ATTEMPTS: int = 5  # Max failed login attempts
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 900  # 15 minute window
    # Global API rate limiting (disabled by default)
    ENABLE_RATE_LIMITING: bool = False
    RATE_LIMIT_GLOBAL_PER_MINUTE: int = 120  # Global ceiling
    RATE_LIMIT_PER_USER_PER_MINUTE: int = 60  # Per-user/IP ceiling
    RATE_LIMIT_WINDOW_SECONDS: int = 60  # Fixed window size

    # Input Size Limits
    MAX_MESSAGE_LENGTH: int = 100000  # ~100KB per message
    MAX_METADATA_SIZE: int = 10000  # ~10KB for metadata
    MAX_MESSAGES_PER_REQUEST: int = 100  # Max messages in client-side mode

    @model_validator(mode="after")
    def validate_security_config(self) -> "Settings":
        """
        Validate security configuration to prevent silent failures.

        Ensures:
        - JWT_SECRET_KEY is set when ENABLE_USER_AUTH is enabled
        - Warns about insecure defaults in production-like settings
        """
        if self.ENABLE_USER_AUTH:
            if not self.JWT_SECRET_KEY:
                # Auto-generate a secure key for development, but warn loudly
                self.JWT_SECRET_KEY = secrets.token_urlsafe(32)
                print(
                    "\n" + "=" * 70 + "\n"
                    "WARNING: JWT_SECRET_KEY not set! Auto-generated for this session.\n"
                    "This key will change on restart, invalidating all tokens.\n"
                    "Set JWT_SECRET_KEY in .env for production!\n"
                    "Generated key (add to .env): JWT_SECRET_KEY=" + self.JWT_SECRET_KEY + "\n" + "=" * 70 + "\n"
                )
            elif len(self.JWT_SECRET_KEY) < 32:
                print("\nWARNING: JWT_SECRET_KEY is too short (< 32 chars). Use a longer key for better security.\n")
        return self

    @staticmethod
    def sanitize_url(url: str | None) -> str:
        """
        Remove credentials from URL for safe logging.

        Args:
            url: URL that may contain credentials.

        Returns:
            URL with password masked as *****.
        """
        if not url:
            return "not configured"

        try:
            parsed = urlparse(url)
            if parsed.password:
                # Mask the password
                netloc = parsed.hostname or ""
                if parsed.username:
                    netloc = f"{parsed.username}:*****@{netloc}"
                if parsed.port:
                    netloc = f"{netloc}:{parsed.port}"
                return urlunparse(parsed._replace(netloc=netloc))
            return url
        except Exception:
            return "invalid URL"


settings = Settings()
