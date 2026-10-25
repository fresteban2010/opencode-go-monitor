from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .core import localdb
from .core.analysis import summary
from .core.client import OpenCodeClient
from .core.config import Config, load, paths, save
from .core.credentials import Credential, CredentialsError, resolve
from .core.store import Store
from .core.sync import synchronize

SCHEMA_VERSION = 1


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


def _usage_payload(usage, stale: bool, now: datetime) -> dict | None:
    if usage is None:
        return None
    payload: dict = {"fetched_at": _iso(usage.fetched_at), "stale": stale}
    for kind, window in usage.by_window().items():
        payload[kind] = {
            "percent": window.percent,
            "status": window.status,
            "resets_at": _iso(window.resets_at),
            "resets_in_seconds": int((window.resets_at - now).total_seconds()),
        }
    return payload


def build_status(report, cred: Credential, store: Store, now: datetime) -> dict:
    result = summary(store, now=now)
    payload: dict = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso(now),
        "credential": {"source": cred.source, "kind": cred.kind},
        "usage": _usage_payload(result.usage, report.stale, now),
        "spend": {
            "today": result.spend_today,
            "last_7d": result.spend_7d,
            "last_30d": result.spend_30d,
        },
        "burn": {
            kind: {
                "rate_pct_per_hour": value.rate_pct_per_hour,
                "projected_percent": value.projected_percent,
                "eta": _iso(value.eta),
                "resets_in_seconds": int(value.resets_in.total_seconds()),
            }
            for kind, value in result.burns.items()
        },
        "models": [asdict(model) for model in result.top_models],
    }
    return payload


def _fmt_reset(delta_seconds: int) -> str:
    if delta_seconds <= 0:
        return "pendiente"
    hours, rest = divmod(delta_seconds, 3600)
    minutes = rest // 60
    if hours >= 48:
        return f"{hours // 24}d {hours % 24}h"
    return f"{hours}h {minutes:02d}m"


def render_text(payload: dict) -> str:
    lines: list[str] = [
        f"OpenCode Go · credencial: {payload['credential']['source']}",
    ]
    usage = payload["usage"]
    if usage:
        stale = " (desactualizado)" if usage["stale"] else ""
        for label, kind in (("5 h", "rolling"), ("semanal", "weekly"), ("mensual", "monthly")):
            window = usage[kind]
            bar = "#" * int(window["percent"] / 5) + "-" * (20 - int(window["percent"] / 5))
            reset = _fmt_reset(window["resets_in_seconds"])
            lines.append(
                f"{label:<8} [{bar[:20]}] {window['percent']:5.1f}%  "
                f"{window['status']:<12} reset en {reset}{stale}"
            )
    else:
        lines.append("Sin datos de cuota todavía. Ejecuta: ocgm sync")

    spend = payload["spend"]
    lines.append(
        f"Gasto    hoy ${spend['today']:.2f} · 7d ${spend['last_7d']:.2f} · 30d ${spend['last_30d']:.2f}"
    )
    for kind, value in payload["burn"].items():
        if value["eta"]:
            lines.append(
                f"Ritmo {kind:<8} {value['rate_pct_per_hour']:.1f}%/h → "
                f"proyección {value['projected_percent']:.0f}% · agota {value['eta']}"
            )
    models = payload["models"]
    if models:
        lines.append("Modelos (30 d):")
        for model in models[:8]:
            lines.append(
                f"  {model['model']:<26} {model['requests']:>5} pet · ${model['cost_usd']:.2f}"
            )
    return "\n".join(lines)


def _open_store(data_path: Path) -> Store:
    store = Store(data_path / "monitor.db")
    store.init()
    return store


def _sync(store: Store, client: OpenCodeClient, full: bool, cfg: Config):
    return synchronize(store, client, full=full, page_size=cfg.request_page_size)


def cmd_status(args, cfg: Config, store: Store, client: OpenCodeClient, cred: Credential) -> int:
    report = _sync(store, client, False, cfg)
    for error in report.errors:
        print(f"aviso: {error}", file=sys.stderr)
    now = datetime.now(timezone.utc)
    payload = build_status(report, cred, store, now)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_text(payload))
    return 0


def cmd_sync(args, cfg: Config, store: Store, client: OpenCodeClient, cred: Credential) -> int:
    report = _sync(store, client, args.full, cfg)
    for error in report.errors:
        print(f"aviso: {error}", file=sys.stderr)
    print(f"Sincronizado: {report.new_requests} nuevas peticiones en {report.pages} páginas.")
    if report.stale:
        print("Cuota no actualizada; se muestra la última foto disponible.", file=sys.stderr)
    return 0 if not report.errors else 1


def cmd_doctor(args, cfg: Config, store: Store, client: OpenCodeClient, cred: Credential) -> int:
    ok = True

    def check(label: str, condition: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and condition
        print(f"{'✓' if condition else '✗'} {label}{(': ' + detail) if detail else ''}")

    check("Credencial", True, f"{cred.source} ({cred.kind})")
    if cred.expires_at:
        remaining = cred.expires_at - datetime.now(timezone.utc)
        check("Caducidad del token", remaining.total_seconds() > 60, f"{remaining.days} días")
    cfg_path = paths()[0]
    check("Configuración", True, str(cfg_path) if cfg_path.exists() else "valores por defecto")
    check("Caché local", store.path.exists(), str(store.path))
    try:
        usage = client.usage()
        check("API de cuota", True, f"rolling {usage.rolling.percent:.0f}%")
    except Exception as error:  # noqa: BLE001 - doctor must report, never crash
        check("API de cuota", False, str(error))
    now = datetime.now(timezone.utc)
    local = localdb.session_totals(localdb.DEFAULT_OPENCODE_DB, now - timedelta(days=30))
    check(
        "Base de datos de OpenCode",
        True,
        f"{local.sessions} sesiones (30 d)" if localdb.DEFAULT_OPENCODE_DB.exists() else "no encontrada; solo API",
    )
    return 0 if ok else 1


def cmd_watch(args, cfg: Config, store: Store, client: OpenCodeClient, cred: Credential) -> int:
    try:
        while True:
            report = _sync(store, client, False, cfg)
            for error in report.errors:
                print(f"aviso: {error}", file=sys.stderr)
            payload = build_status(report, cred, store, datetime.now(timezone.utc))
            print("\033[2J\033[H" + render_text(payload), flush=True)
            time.sleep(cfg.poll_seconds)
    except KeyboardInterrupt:
        return 0


def cmd_autostart(args) -> int:
    autostart = Path.home() / ".config" / "autostart" / "opencode-go-monitor.desktop"
    if args.action == "status":
        print("activado" if autostart.exists() else "desactivado")
        return 0
    if args.action == "enable":
        autostart.parent.mkdir(parents=True, exist_ok=True)
        autostart.write_text(
            "[Desktop Entry]\nType=Application\nName=OpenCode Go Monitor\n"
            "Exec=ocgm tray\nX-GNOME-Autostart-enabled=true\n",
            encoding="utf-8",
        )
        print(f"Autostart activado: {autostart}")
        return 0
    if autostart.exists():
        autostart.unlink()
    print("Autostart desactivado")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ocgm", description="OpenCode Go Monitor")
    sub = parser.add_subparsers(dest="command")
    status = sub.add_parser("status", help="muestra el estado actual")
    status.add_argument("--json", action="store_true", help="salida JSON")
    sync = sub.add_parser("sync", help="sincroniza con opencode.ai")
    sync.add_argument("--full", action="store_true", help="recorre los 30 días completos")
    sub.add_parser("doctor", help="diagnóstico de credenciales y APIs")
    sub.add_parser("watch", help="vista en terminal con refresco")
    gui = sub.add_parser("gui", help="abre la ventana GTK4")
    gui.add_argument("--no-tray", action="store_true", help="no iniciar la bandeja")
    sub.add_parser("tray", help="icono de bandeja")
    sub.add_parser("service", help="bucle headless para systemd")
    auto = sub.add_parser("autostart", help="gestiona el inicio automático")
    auto.add_argument("action", choices=["enable", "disable", "status"])
    return parser


def main(
    argv: list[str] | None = None,
    *,
    cfg_loader=load,
    data_path: Path | None = None,
    credential_resolver=resolve,
    client_factory=OpenCodeClient,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "status"

    if command == "autostart":
        return cmd_autostart(args)
    if command == "gui":
        from .ui.app import run

        return run(sys.argv[1:] if argv is None else argv)
    if command == "tray":
        from .tray import run_tray

        return run_tray()
    if command == "service":
        from .service import run_service

        return run_service()

    cfg = cfg_loader()
    try:
        cred = credential_resolver(config_key=cfg.api_key)
    except CredentialsError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2

    data = data_path or paths()[1]
    store = _open_store(data)
    client = client_factory(cred.token)
    try:
        handlers = {
            "status": cmd_status,
            "sync": cmd_sync,
            "doctor": cmd_doctor,
            "watch": cmd_watch,
        }
        return handlers[command](args, cfg, store, client, cred)
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
