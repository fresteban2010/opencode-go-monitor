from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

DEFAULT_OPENCODE_DB = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
DEFAULT_AUTH_JSON = Path.home() / ".local" / "share" / "opencode" / "auth.json"
EXPIRY_SKEW = timedelta(seconds=60)


@dataclass(frozen=True)
class Credential:
    token: str
    source: str
    expires_at: datetime | None
    kind: Literal["oauth", "api_key"]


class CredentialsError(Exception):
    def __init__(self, reason: Literal["missing", "expired"]) -> None:
        self.reason = reason
        message = (
            "No se encontró ninguna credencial de OpenCode. Abre OpenCode y ejecuta /connect, "
            "o define OPENCODE_API_KEY."
            if reason == "missing"
            else "El token de OpenCode Console ha caducado. Abre OpenCode para renovarlo "
            "o configura una API key de Go."
        )
        super().__init__(message)


def _parse_epoch(value: object) -> datetime | None:
    if not isinstance(value, (int, float)):
        return None
    seconds = value / 1000 if value > 1e12 else value
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def _from_opencode_db(path: Path, now: datetime) -> Credential | None:
    if not path.exists():
        return None
    try:
        uri = f"file:{path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=1.0)
        try:
            row = conn.execute(
                "select value from credential where integration_id = 'opencode'"
                " order by time_updated desc limit 1"
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None

    if not row or not isinstance(row[0], str):
        return None
    try:
        data = json.loads(row[0])
    except json.JSONDecodeError:
        return None
    token = data.get("access")
    if not isinstance(token, str) or not token:
        return None
    return Credential(token, "opencode-db", _parse_epoch(data.get("expires")), "oauth")


def _from_auth_json(path: Path) -> Credential | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    for provider in ("opencode-go", "opencode"):
        entry = data.get(provider)
        if isinstance(entry, dict):
            key = entry.get("key")
        elif isinstance(entry, str):
            key = entry
        else:
            key = None
        if isinstance(key, str) and key:
            return Credential(key, "auth.json", None, "api_key")
    return None


def resolve(
    env: dict[str, str] | None = None,
    config_key: str | None = None,
    opencode_db: Path | None = None,
    auth_json: Path | None = None,
    now: datetime | None = None,
) -> Credential:
    now = now or datetime.now(timezone.utc)
    env = os.environ if env is None else env
    db_path = opencode_db or DEFAULT_OPENCODE_DB
    auth_path = auth_json if auth_json is not None else DEFAULT_AUTH_JSON

    env_key = env.get("OPENCODE_API_KEY")
    if env_key:
        return Credential(env_key, "env", None, "api_key")
    if config_key:
        return Credential(config_key, "config", None, "api_key")

    oauth = _from_opencode_db(db_path, now)
    if oauth and (oauth.expires_at is None or oauth.expires_at - EXPIRY_SKEW > now):
        return oauth

    fallback = _from_auth_json(auth_path)
    if fallback:
        return fallback

    raise CredentialsError("expired" if oauth else "missing")
