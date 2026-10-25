from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

APP_DIR = "opencode-go-monitor"
MIN_POLL_SECONDS = 30


@dataclass(frozen=True)
class Config:
    poll_seconds: int = 60
    sync_seconds: int = 300
    thresholds: tuple[int, ...] = (70, 85, 95)
    notify: bool = True
    api_key: str | None = None
    stale_after_seconds: int = 180
    request_page_size: int = 100


def paths() -> tuple[Path, Path]:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return config_home / APP_DIR / "config.toml", data_home / APP_DIR


def load(path: Path | None = None) -> Config:
    cfg_path = path or paths()[0]
    cfg = Config()
    if not cfg_path.exists():
        return cfg
    try:
        raw = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return cfg

    poll = int(raw.get("poll_seconds", cfg.poll_seconds))
    sync = int(raw.get("sync_seconds", cfg.sync_seconds))
    thresholds = raw.get("thresholds", list(cfg.thresholds))
    cleaned = tuple(sorted({max(1, min(100, int(t))) for t in thresholds if isinstance(t, int)}))
    if not cleaned:
        cleaned = cfg.thresholds

    cfg = replace(
        cfg,
        poll_seconds=max(MIN_POLL_SECONDS, poll),
        sync_seconds=max(MIN_POLL_SECONDS, sync),
        thresholds=cleaned,
        notify=bool(raw.get("notify", cfg.notify)),
        api_key=raw.get("api_key") or None,
        stale_after_seconds=max(30, int(raw.get("stale_after_seconds", cfg.stale_after_seconds))),
        request_page_size=max(1, min(200, int(raw.get("request_page_size", cfg.request_page_size)))),
    )
    return cfg


def save(cfg: Config, path: Path | None = None) -> None:
    cfg_path = path or paths()[0]
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"poll_seconds = {cfg.poll_seconds}",
        f"sync_seconds = {cfg.sync_seconds}",
        f"thresholds = [{', '.join(str(t) for t in cfg.thresholds)}]",
        f"notify = {'true' if cfg.notify else 'false'}",
        f"stale_after_seconds = {cfg.stale_after_seconds}",
        f"request_page_size = {cfg.request_page_size}",
    ]
    if cfg.api_key:
        lines.append(f"api_key = {json.dumps(cfg.api_key)}")
    cfg_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    cfg_path.chmod(0o600)
