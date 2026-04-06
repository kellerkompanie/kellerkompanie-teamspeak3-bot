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


class DatabaseCredentials(BaseModel):
    """Database connection credentials."""

    host: str = "localhost"
    name: str = "database"
    username: str = "username"
    password: str = "password"

    @property
    def url(self) -> str:
        """Build MariaDB connection URL."""
        return f"mariadb+mariadbconnector://{self.username}:{self.password}@{self.host}/{self.name}"


class DatabaseSettings(BaseModel):
    """Database settings for both teamspeak and webpage databases."""

    teamspeak: DatabaseCredentials = DatabaseCredentials(name="keko_teamspeak")
    webpage: DatabaseCredentials = DatabaseCredentials(name="keko_webpage")


class ApiSettings(BaseModel):
    """Backend API settings."""

    base_url: str = "http://localhost:5000"


class MessagesSettings(BaseModel):
    """Message templates."""

    guest_welcome: str = "Welcome!"


class Settings(BaseSettings):
    """Application settings loaded from YAML config file."""

    model_config = SettingsConfigDict(
        env_prefix="KEKO_",
        env_nested_delimiter="__",
    )

    ts3: TS3Settings = TS3Settings()
    database: DatabaseSettings = DatabaseSettings()
    api: ApiSettings = ApiSettings()
    messages: MessagesSettings = MessagesSettings()

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
