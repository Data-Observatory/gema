"""Settings and configuration schema."""

from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel


class ContextStrategy(str, Enum):
    """Context passing strategy for agents."""

    ACCUMULATIVE = "accumulative"
    LAYERED = "layered"


class LLMSettings(BaseModel):
    """LLM provider configuration."""

    provider: str = "openai"
    model: str = "gpt-4o-mini"
    api_key_env: str = "LLM_API_KEY"


class AppSettings(BaseModel):
    """Application settings."""

    llm: LLMSettings = LLMSettings()
    context_strategy: ContextStrategy = ContextStrategy.ACCUMULATIVE
    output_path: str = "output.json"


def load_settings(config_path: Optional[Path] = None) -> AppSettings:
    """Load settings from config file or return defaults.

    Args:
        config_path: Path to settings.json (optional)

    Returns:
        AppSettings instance
    """
    if config_path and config_path.exists():
        import json

        with open(config_path) as f:
            data = json.load(f)
        return AppSettings(**data)
    return AppSettings()
