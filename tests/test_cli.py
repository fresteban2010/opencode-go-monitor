from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ocgm.cli import main
from ocgm.core.config import Config
from ocgm.core.credentials import Credential
from ocgm.core.models import LogPage, RequestItem, Usage, WindowUsage
from ocgm.core.store import Store

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


class FakeClient:
    def __init__(self, usage_result: Usage, pages: list[LogPage] | None = None) -> None:
        self.usage_result = usage_result
        self.pages = pages or []
        self.calls = 0

    def usage(self) -> Usage:
        return self.usage_result

    def request_logs(self, cursor=None, limit: int = 100) -> LogPage:
        index = self.calls
        self.calls += 1
        return self.pages[index] if index < len(self.pages) else LogPage([], None, 30)


def item(rid: str, cost: float, started: datetime) -> RequestItem:
    return RequestItem(
        rid, started, "deepseek-v4.1-flash", "opencode", "cli", "s", "succeeded", 200,
        100, 50, 0, 200, 0, cost, 1000, 100,
    )


def make_usage() -> Usage:
    return Usage(
        WindowUsage("ok", 16.0, NOW + timedelta(hours=4)),
        WindowUsage("ok", 6.0, NOW + timedelta(days=5)),
        WindowUsage("ok", 3.0, NOW + timedelta(days=20)),
        NOW,
    )


def test_status_json_is_stable_and_hides_token(tmp_path: Path, capsys) -> None:
    def factory(_token: str) -> FakeClient:
        return FakeClient(make_usage(), [LogPage([item("a", 0.5, NOW)], None, 30)])

    code = main(
        ["status", "--json"],
        cfg_loader=lambda: Config(api_key=None),
        data_path=tmp_path,
        credential_resolver=lambda **_: Credential("super-secret-token", "opencode-db", None, "oauth"),
        client_factory=factory,
    )
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["schema_version"] == 1
    assert out["credential"] == {"source": "opencode-db", "kind": "oauth"}
    assert out["usage"]["rolling"]["percent"] == 16.0
    assert out["spend"]["last_30d"] == 0.5
    assert "super-secret-token" not in json.dumps(out)


def test_status_without_credentials_exits_2(tmp_path: Path, capsys) -> None:
    from ocgm.core.credentials import CredentialsError

    def fail(**_):
        raise CredentialsError("missing")

    code = main(
        ["status"],
        cfg_loader=lambda: Config(),
        data_path=tmp_path,
        credential_resolver=fail,
        client_factory=lambda _: FakeClient(make_usage()),
    )
    assert code == 2
    assert "credencial" in capsys.readouterr().err.lower()


def test_bare_ocgm_acts_as_status(tmp_path: Path, capsys) -> None:
    code = main(
        [],
        cfg_loader=lambda: Config(),
        data_path=tmp_path,
        credential_resolver=lambda **_: Credential("t", "env", None, "api_key"),
        client_factory=lambda _: FakeClient(make_usage(), [LogPage([], None, 30)]),
    )
    assert code == 0
    assert "OpenCode Go" in capsys.readouterr().out


def test_sync_full_flag_reaches_client(tmp_path: Path, capsys) -> None:
    store = Store(tmp_path / "monitor.db")
    store.init()
    store.close()

    code = main(
        ["sync", "--full"],
        cfg_loader=lambda: Config(),
        data_path=tmp_path,
        credential_resolver=lambda **_: Credential("t", "env", None, "api_key"),
        client_factory=lambda _: FakeClient(make_usage(), [LogPage([item("a", 0.1, NOW)], None, 30)]),
    )
    assert code == 0
    assert "1 nuevas" in capsys.readouterr().out


def test_expired_credentials_exits_2(tmp_path: Path, capsys) -> None:
    from ocgm.core.credentials import CredentialsError

    def fail(**_):
        raise CredentialsError("expired")

    code = main(
        ["status"],
        cfg_loader=lambda: Config(),
        data_path=tmp_path,
        credential_resolver=fail,
        client_factory=lambda _: FakeClient(make_usage()),
    )
    assert code == 2
    assert "caducado" in capsys.readouterr().err.lower()


def test_doctor_passes_with_defaults_and_missing_local_db(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setattr("ocgm.core.localdb.DEFAULT_OPENCODE_DB", tmp_path / "missing.db")

    code = main(
        ["doctor"],
        cfg_loader=lambda: Config(),
        data_path=tmp_path,
        credential_resolver=lambda **_: Credential("t", "env", None, "api_key"),
        client_factory=lambda _: FakeClient(make_usage()),
    )
    output = capsys.readouterr().out
    assert code == 0
    assert "valores por defecto" in output
    assert "solo API" in output
    assert "rolling 16%" in output
