from __future__ import annotations

from pathlib import Path

from ocgm.core.config import Config, load, paths, save


def test_load_applies_defaults_when_file_missing(tmp_path: Path) -> None:
    cfg = load(tmp_path / "missing.toml")
    assert cfg.poll_seconds == 60
    assert cfg.sync_seconds == 300
    assert cfg.thresholds == (70, 85, 95)
    assert cfg.notify is True
    assert cfg.api_key is None
    assert cfg.request_page_size == 100


def test_load_reads_partial_toml(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text(
        'poll_seconds = 120\nnotify = false\nthresholds = [50, 75, 90]\napi_key = "sk-test"\n',
        encoding="utf-8",
    )
    cfg = load(p)
    assert cfg.poll_seconds == 120
    assert cfg.sync_seconds == 300
    assert cfg.notify is False
    assert cfg.thresholds == (50, 75, 90)
    assert cfg.api_key == "sk-test"


def test_poll_seconds_below_minimum_is_clamped(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("poll_seconds = 5\n", encoding="utf-8")
    assert load(p).poll_seconds == 30


def test_thresholds_are_sorted_and_bounded(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("thresholds = [95, 10, 70, 99]\n", encoding="utf-8")
    assert load(p).thresholds == (10, 70, 95, 99)


def test_save_roundtrips_with_private_permissions(tmp_path: Path) -> None:
    p = tmp_path / "sub" / "config.toml"
    cfg = Config(poll_seconds=90, api_key="sk-secret")
    save(cfg, p)
    assert load(p) == cfg
    assert oct(p.stat().st_mode & 0o777) == "0o600"


def test_paths_follow_xdg(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    cfg_path, data_path = paths()
    assert cfg_path == tmp_path / "cfg" / "opencode-go-monitor" / "config.toml"
    assert data_path == tmp_path / "data" / "opencode-go-monitor"
