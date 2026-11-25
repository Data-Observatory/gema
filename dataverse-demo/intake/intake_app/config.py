"""Settings, read once from the environment (see dataverse-demo/.env.example)."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from intake_app.errors import ConfigError

_ALIAS_RE = re.compile(r"^[A-Za-z0-9_-]{1,60}$")


def _int(env: Mapping[str, str], key: str, default: int, minimum: int = 0) -> int:
    raw = env.get(key, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{key} must be an integer, got {raw!r}") from None
    if value < minimum:
        raise ConfigError(f"{key} must be >= {minimum}, got {value}")
    return value


def _bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = env.get(key, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    admin_token: str
    data_dir: Path
    log_file: Path
    # Dataverse
    dataverse_url: str  # container-internal address, used for API calls
    dataverse_public_url: str  # what attendees' browsers can reach, used for result links
    dataverse_token: str
    collection_alias: str
    default_contact_email: str
    default_contact_name: str
    # GEMA!
    gema_config: Path
    export_config: Path
    opencode_api_key: str
    # Limits
    workers: int = 4
    record_timeout: int = 300
    max_records: int = 40
    rate_limit: int = 5  # submissions per IP per window
    rate_window: int = 60  # seconds
    preflight_url: bool = True
    allow_private_urls: bool = False
    retry_delay: float = 3.0
    shutdown_grace: int = 20  # seconds in-flight records get on SIGTERM; < stop_grace_period

    @property
    def db_path(self) -> Path:
        return self.data_dir / "intake.db"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        e: Mapping[str, str] = os.environ if env is None else env
        admin_token = e.get("INTAKE_ADMIN_TOKEN", "").strip()
        if not admin_token:
            raise ConfigError("INTAKE_ADMIN_TOKEN is not set (see dataverse-demo/.env.example)")
        opencode_key = e.get("OPENCODE_API_KEY", "").strip()
        if not opencode_key:
            raise ConfigError("OPENCODE_API_KEY is not set: GEMA! runs on the opencode provider")
        alias = e.get("DATAVERSE_COLLECTION_ALIAS", "").strip() or "root"
        if not _ALIAS_RE.match(alias):
            raise ConfigError(f"DATAVERSE_COLLECTION_ALIAS looks invalid: {alias!r}")
        data_dir = Path(e.get("INTAKE_DATA_DIR", "/data"))
        return cls(
            admin_token=admin_token,
            data_dir=data_dir,
            log_file=Path(e.get("INTAKE_LOG_FILE", "") or data_dir / "intake.log"),
            dataverse_url=e.get("DATAVERSE_URL", "http://dataverse:8080").rstrip("/"),
            dataverse_public_url=e.get("DATAVERSE_PUBLIC_URL", "http://localhost:8080").rstrip("/"),
            dataverse_token=e.get("DATAVERSE_API_TOKEN", "").strip(),
            collection_alias=alias,
            default_contact_email=e.get("INTAKE_DEFAULT_CONTACT_EMAIL", "").strip()
            or "workshop@example.org",
            default_contact_name=e.get("INTAKE_DEFAULT_CONTACT_NAME", "").strip()
            or "GEMA! workshop",
            gema_config=Path(e.get("INTAKE_GEMA_CONFIG", "/app/config/agents.yaml")),
            export_config=Path(e.get("INTAKE_EXPORT_CONFIG", "/app/config/dataverse_export.yaml")),
            opencode_api_key=opencode_key,
            workers=_int(e, "INTAKE_WORKERS", 4, 1),
            record_timeout=_int(e, "INTAKE_RECORD_TIMEOUT", 300, 5),
            max_records=_int(e, "INTAKE_MAX_RECORDS", 40, 1),
            rate_limit=_int(e, "INTAKE_RATE_LIMIT", 5, 1),
            rate_window=_int(e, "INTAKE_RATE_WINDOW", 60, 1),
            preflight_url=_bool(e, "INTAKE_PREFLIGHT_URL", True),
            allow_private_urls=_bool(e, "INTAKE_ALLOW_PRIVATE_URLS", False),
            shutdown_grace=_int(e, "INTAKE_SHUTDOWN_GRACE", 20, 0),
        )
