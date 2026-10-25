from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ocgm.core.credentials import Credential, CredentialsError, resolve

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


def make_opencode_db(path: Path, access: str, expires_at: datetime | None) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "create table credential (id text primary key, integration_id text, label text,"
        " value text, connector_id text, method_id text, active integer,"
        " time_created integer, time_updated integer)"
    )
    value = {"type": "oauth", "access": access, "refresh": "r", "expires": int(expires_at.timestamp() * 1000)}
    conn.execute(
        "insert into credential values ('c1','opencode','Personal',?,'','',1,0,0)",
        (json.dumps(value),),
    )
    conn.commit()
    conn.close()


def make_auth_json(path: Path, provider: str, key: str) -> None:
    path.write_text(json.dumps({provider: {"type": "api", "key": key}}), encoding="utf-8")


def test_env_key_wins_over_oauth(tmp_path: Path) -> None:
    db = tmp_path / "opencode.db"
    make_opencode_db(db, "st_oauth", NOW + timedelta(days=10))
    cred = resolve(env={"OPENCODE_API_KEY": "sk-env"}, opencode_db=db, auth_json=tmp_path / "absent.json", now=NOW)
    assert cred == Credential("sk-env", "env", None, "api_key")


def test_reads_oauth_from_opencode_db(tmp_path: Path) -> None:
    db = tmp_path / "opencode.db"
    expires = NOW + timedelta(days=10)
    make_opencode_db(db, "st_oauth", expires)
    cred = resolve(opencode_db=db, auth_json=tmp_path / "absent.json", now=NOW)
    assert cred.kind == "oauth"
    assert cred.token == "st_oauth"
    assert cred.source == "opencode-db"
    assert cred.expires_at == expires


def test_falls_back_to_api_key_when_oauth_expired(tmp_path: Path) -> None:
    db = tmp_path / "opencode.db"
    make_opencode_db(db, "st_old", NOW - timedelta(minutes=1))
    auth = tmp_path / "auth.json"
    make_auth_json(auth, "opencode-go", "sk-fallback")
    cred = resolve(opencode_db=db, auth_json=auth, now=NOW)
    assert cred == Credential("sk-fallback", "auth.json", None, "api_key")


def test_raises_expired_without_fallback(tmp_path: Path) -> None:
    db = tmp_path / "opencode.db"
    make_opencode_db(db, "st_old", NOW - timedelta(minutes=1))
    with pytest.raises(CredentialsError) as err:
        resolve(opencode_db=db, auth_json=tmp_path / "absent.json", now=NOW)
    assert err.value.reason == "expired"


def test_raises_missing_when_no_source(tmp_path: Path) -> None:
    with pytest.raises(CredentialsError) as err:
        resolve(env={}, opencode_db=tmp_path / "absent.db", auth_json=tmp_path / "absent.json", now=NOW)
    assert err.value.reason == "missing"


def test_malformed_credential_row_does_not_crash(tmp_path: Path) -> None:
    db = tmp_path / "opencode.db"
    conn = sqlite3.connect(db)
    conn.execute("create table credential (id text, integration_id text, value text, time_updated integer)")
    conn.execute("insert into credential values ('c1','opencode','not-json',0)")
    conn.commit()
    conn.close()
    with pytest.raises(CredentialsError) as err:
        resolve(opencode_db=db, auth_json=tmp_path / "absent.json", now=NOW)
    assert err.value.reason == "missing"


def test_resolve_does_not_modify_opencode_db(tmp_path: Path) -> None:
    db = tmp_path / "opencode.db"
    make_opencode_db(db, "st_oauth", NOW + timedelta(days=10))
    before = db.read_bytes()
    resolve(opencode_db=db, auth_json=tmp_path / "absent.json", now=NOW)
    assert db.read_bytes() == before
