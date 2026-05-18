"""Configuration management using pydantic-settings with YAML support."""

from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class TS3Settings(BaseModel):
    """TeamSpeak 3 connection settings."""

    host: str = "127.0.0.1"
    port: int = 10011
    user: str = "serveradmin"
    password: str = "password"
    nickname: str = "Kellerkompanie Bot"
    default_channel: str = "Botchannel"
    server_id: int = 1


class ApiSettings(BaseModel):
    """Backend API settings.

    The bot is a thin TS3 client. All persistent state (account links,
    authkeys, welcome messages) lives in the webpage's keko_teamspeak DB
    and is reached exclusively through the HTTP API documented in
    kellerkompanie-webpage/API.md (formerly REQ.md).
    """

    base_url: str = "http://localhost:8000"
    token: str = "change-me"
    timeout: float = 10.0
    # How long to cache the guest-welcome message between API fetches.
    guest_welcome_cache_seconds: float = 300.0


class Settings(BaseSettings):
    """Application settings loaded from YAML config file."""

    model_config = SettingsConfigDict(
        env_prefix="KEKO_",
        env_nested_delimiter="__",
    )

    ts3: TS3Settings = TS3Settings()
    api: ApiSettings = ApiSettings()

    @classmethod
    def from_yaml(cls, path: Path) -> Self:
        """Load settings from a YAML file."""
        if path.exists():
            with open(path) as f:
                data = yaml.safe_load(f) or {}
            return cls.model_validate(data)
        return cls()

    def to_yaml(self, path: Path) -> None:
        """Save settings to a YAML file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(self.model_dump(), f, default_flow_style=False, sort_keys=False)


# Default config path
CONFIG_PATH = Path(__file__).parent.parent.parent / "configs" / "keko-ts3bot.yaml"


def get_settings(config_path: Path = CONFIG_PATH) -> Settings:
    """Load settings from config file, creating default if not exists."""
    settings = Settings.from_yaml(config_path)
    if not config_path.exists():
        settings.to_yaml(config_path)
    return settings
