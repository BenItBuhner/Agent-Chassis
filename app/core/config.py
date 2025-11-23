from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)

    PROJECT_NAME: str = "Agent Chassis"
    API_V1_STR: str = "/api/v1"
    
    # OpenAI Configuration
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_BASE_URL: Optional[str] = None
    OPENAI_MODEL: str = "kimi-k2-thinking"
    
    # MCP Configuration
    MCP_CONFIG_PATH: str = "mcp_config.json"

    # Security
    CHASSIS_API_KEY: Optional[str] = None

settings = Settings()
