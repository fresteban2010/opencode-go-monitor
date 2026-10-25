# OpenCode Go Monitor — Plan de ejecución

> **Para agentes:** ejecutar tarea por tarea. Pasos con checkbox.

**Goal:** App nativa Linux (GTK4) + bandeja que monitoriza cuota oficial de
OpenCode Go, gasto real por petición/modelo y avisa antes de agotar ventanas.

**Architecture:** Python 3.14, núcleo desacoplado (credenciales → cliente HTTP
→ sincronización → SQLite → UI). OAuth de OpenCode para la API de consola;
API key de Go como respaldo. GTK4/libadwaita + AyatanaAppIndicator.

**Tech Stack:** Python 3.14, PyGObject (GTK4, Adw, AyatanaAppIndicator3,
Notify), SQLite, urllib, tomllib, pytest.

**Spec:** `docs/superpowers/specs/2026-10-25-opencode-go-monitor-design.md`

## Global Constraints

- No escribir nunca en `~/.local/share/opencode/opencode.db` (abrir `mode=ro`).
- No renovar el token OAuth de OpenCode; solo leerlo.
- No registrar tokens en logs, errores ni JSON de salida.
- Red solo a `opencode.ai`.
- Endpoint de cuota: `https://opencode.ai/zen/go/v1/usage`.
- Endpoint de logs: `https://opencode.ai/console/api/request-logs`.
- Retención de logs del servidor: 30 días.
- Poll de cuota mínimo: 30 s; por defecto 60 s.
- Umbrales por defecto: 70 / 85 / 95 %; cooldown 30 min.
- UI en español; código e identificadores en inglés.
- Python ≥ 3.11 (probado en 3.14).

## Review Focus

- Token ausente/caducado: mensaje accionable, sin crash, última foto visible.
- 429/5xx/timeout: backoff y marca de datos obsoletos, sin perder caché.
- Cursor JSON con caracteres especiales: paginación sin duplicados ni huecos.
- `resetsAt` en el pasado o zona horaria distinta: cuenta atrás correcta.
- BD de OpenCode ausente/bloqueada: funciona solo con API.

---

### Task 1: Esqueleto, modelos y configuración

**Files:**
- Create: `pyproject.toml`, `src/ocgm/__init__.py`, `src/ocgm/core/models.py`,
  `src/ocgm/core/config.py`, `tests/test_config.py`, `.gitignore`, `README.md`

**Interfaces:**
- `models.WindowUsage(status: str, percent: float, resets_at: datetime)`
- `models.Usage(rolling: WindowUsage, weekly: WindowUsage, monthly: WindowUsage, fetched_at: datetime)`
- `models.RequestItem(id: str, started_at: datetime, model: str, provider: str, app: str, session_id: str, outcome: str, status_code: int, input_tokens: int, output_tokens: int, reasoning_tokens: int, cache_read_tokens: int, cache_write_tokens: int, cost_usd: float, duration_ms: int, ttft_ms: int|None)`
- `config.Config(poll_seconds=60, sync_seconds=300, thresholds=(70,85,95), notify=True, api_key=None, stale_after_seconds=180, request_page_size=100)`
- `config.load(path: Path|None=None) -> Config`
- `config.save(cfg: Config, path: Path|None=None) -> None` (0600)
- `config.paths() -> tuple[Path, Path]` (config, data)

- [ ] Paso 1: test de `load` con TOML parcial aplica defaults y valida mínimo 30 s.
- [ ] Paso 2: ejecutar y ver fallo.
- [ ] Paso 3: implementar dataclasses y config.
- [ ] Paso 4: tests en verde.
- [ ] Paso 5: commit `feat: scaffold core models and config`.

### Task 2: Credenciales de OpenCode

**Files:**
- Create: `src/ocgm/core/credentials.py`, `tests/test_credentials.py`
- Fixtures: `tests/fixtures/opencode_auth.json`, `tests/fixtures/mini_opencode.db`

**Interfaces:**
- `credentials.Credential(token: str, source: str, expires_at: datetime|None, kind: Literal["oauth","api_key"])`
- `credentials.resolve(env: dict|None=None, config_key: str|None=None, opencode_db: Path|None=None, auth_json: Path|None=None, now: datetime|None=None) -> Credential`
- `credentials.CredentialsError(Exception)` con `reason` en `{"missing","expired"}`.

Orden: env `OPENCODE_API_KEY` → config → BD (`integration_id='opencode'`, JSON `access`/`expires`) → `auth.json` (`opencode-go`/`opencode`).
OAuth caducado con API key disponible → devuelve la API key (kind api_key); sin alternativa → `CredentialsError("expired")`.

- [ ] Paso 1: tests: preferencia OAuth, fallback API key, caducado, ausente, JSON malformado no revienta.
- [ ] Paso 2: ver fallo.
- [ ] Paso 3: implementar lectura read-only y resolución.
- [ ] Paso 4: verde.
- [ ] Paso 5: commit `feat: resolve credentials read-only from opencode`.

### Task 3: Cliente de la API

**Files:**
- Create: `src/ocgm/core/client.py`, `tests/test_client.py`
- Fixtures: `tests/fixtures/usage.json`, `tests/fixtures/logs_page.json`

**Interfaces:**
- `client.OpenCodeClient(token: str, base_url: str = "https://opencode.ai", timeout: float = 15.0)`
- `.usage() -> Usage` (lanza `ApiError(status, retryable, message)`).
- `.request_logs(cursor: str|dict|None = None, limit: int = 100) -> LogPage`
- `models.LogPage(items: list[RequestItem], next_cursor: str|None, retention_days: int)`
- `client.encode_cursor(cursor: dict) -> str` (JSON + URL encoding).
- `client.ApiError` con `status`, `retryable`.

- [ ] Paso 1: tests con `http.server` local: parseo de usage, cursor compuesto, 401, 429 retryable, JSON inválido.
- [ ] Paso 2: ver fallo.
- [ ] Paso 3: implementar con urllib y User-Agent `ocgm/1.0`.
- [ ] Paso 4: verde.
- [ ] Paso 5: commit `feat: opencode api client`.

### Task 4: Almacén SQLite

**Files:**
- Create: `src/ocgm/core/store.py`, `tests/test_store.py`

**Interfaces:**
- `store.Store(path: Path)`; `.init()`, `.close()`.
- `.record_usage(u: Usage)`, `.last_usage() -> Usage|None`
- `.upsert_requests(items: list[RequestItem]) -> int` (idempotente, devuelve nuevas)
- `.requests(limit=200, model=None, app=None, outcome=None) -> list[RequestItem]`
- `.cost_since(since: datetime) -> float`
- `.aggregate_models(since: datetime) -> list[ModelAgg]`
- `models.ModelAgg(model, requests, input_tokens, output_tokens, cache_read, cost_usd)`
- `.daily_cost(days=14) -> list[tuple[date,float]]`
- `.meta_get(k)/.meta_set(k,v)`, `.record_alert(window, kind, percent, at) -> bool` (False si cooldown activo)

- [ ] Paso 1: tests de esquema, dedupe por id, agregados y cooldown.
- [ ] Paso 2: ver fallo.
- [ ] Paso 3: implementar WAL y migración v1.
- [ ] Paso 4: verde.
- [ ] Paso 5: commit `feat: sqlite cache store`.

### Task 5: Sincronización

**Files:**
- Create: `src/ocgm/core/sync.py`, `tests/test_sync.py`

**Interfaces:**
- `sync.SyncResult(usage: Usage|None, new_requests: int, pages: int, errors: list[str], stale: bool)`
- `sync.synchronize(store: Store, client: OpenCodeClient, full: bool=False, page_size: int=100, max_pages: int=40, now: datetime|None=None) -> SyncResult`
- Incremental: recorre desde la página más nueva y para al encontrar una petición ya cacheada; `full=True` recorre todo (30 días).

- [ ] Paso 1: tests con cliente falso: primera sync, incremental sin duplicados, para al ver id conocido, tolera error de usage y conserva logs.
- [ ] Paso 2: ver fallo.
- [ ] Paso 3: implementar.
- [ ] Paso 4: verde.
- [ ] Paso 5: commit `feat: incremental sync with graceful degradation`.

### Task 6: Análisis y conciliación local

**Files:**
- Create: `src/ocgm/core/analysis.py`, `src/ocgm/core/localdb.py`, `tests/test_analysis.py`, `tests/test_localdb.py`

**Interfaces:**
- `analysis.burn(window: WindowUsage, kind: Literal["rolling","weekly","monthly"], now: datetime) -> Burn(rate_pct_per_hour, projected_percent, eta: datetime|None, resets_in: timedelta)`
- `analysis.summary(store, now) -> Summary(usage, spend_today, spend_7d, spend_30d, burns, top_models)`
- `localdb.session_totals(path: Path, since: datetime) -> LocalTotals(cost_usd, input_tokens, output_tokens, cache_read, sessions)` (read-only).
- `localdb.compare(store, path, since) -> Reconciliation(server_cost, local_cost, delta_pct)`.

- [ ] Paso 1: tests de ritmo (lineal, ya agotado, resets pasados) y conciliación.
- [ ] Paso 2: ver fallo.
- [ ] Paso 3: implementar; abrir BD con `file:...?mode=ro`.
- [ ] Paso 4: verde.
- [ ] Paso 5: commit `feat: burn-rate analysis and local reconciliation`.

### Task 7: CLI

**Files:**
- Create: `src/ocgm/cli.py`, `src/ocgm/__main__.py`, `tests/test_cli.py`

**Interfaces:**
- `ocgm status [--json]`: medidores, gasto 30 d, última sync, fuente de credencial.
- `ocgm sync [--full]`.
- `ocgm doctor`: comprueba credencial, API, BD local, permisos y versión.
- `ocgm watch`: refresco en terminal.
- Salida JSON estable (`schema_version: 1`).

- [ ] Paso 1: tests de `status --json` con store temporal y cliente falso.
- [ ] Paso 2: ver fallo.
- [ ] Paso 3: implementar argparse y render.
- [ ] Paso 4: verde.
- [ ] Paso 5: prueba en vivo `ocgm doctor` y commit.

### Task 8: Bandeja, notificaciones y servicio

**Files:**
- Create: `src/ocgm/tray.py`, `src/ocgm/notify.py`, `src/ocgm/service.py`, `tests/test_notify.py`

**Interfaces:**
- `notify.Notifier(thresholds, cooldown_minutes=30)`; `.evaluate(summary, now) -> list[Alert]`.
- `tray.run(open_callback)`; icono generado en caché; etiqueta `16% · 6% · 3%`.
- `service.run(interval)` bucle headless con señales y backoff.
- `ocgm autostart enable|disable|status`.

- [ ] Paso 1: tests de umbrales y cooldown (sin depender de libnotify).
- [ ] Paso 2: ver fallo.
- [ ] Paso 3: implementar notifier; bandeja con Ayatana; servicio.
- [ ] Paso 4: verde.
- [ ] Paso 5: prueba real de bandeja en KDE + commit.

### Task 9: Ventana GTK4

**Files:**
- Create: `src/ocgm/ui/app.py`, `src/ocgm/ui/summary.py`, `src/ocgm/ui/models_view.py`, `src/ocgm/ui/requests_view.py`, `src/ocgm/ui/settings_view.py`, `src/ocgm/ui/chart.py`, `src/ocgm/ui/style.css`

**Interfaces:**
- `app.run(argv)` → `Adw.Application` id `io.github.fresteban.OpencodeGoMonitor`.
- Ventana: `Adw.ViewStack` con Resumen/Modelos/Peticiones/Ajustes.
- Actualización desde hilo de sync con `GLib.idle_add`.
- Cerrar ventana oculta a bandeja si está disponible; sin bandeja, cierra.

- [ ] Paso 1: crear ventana mínima y arrancarla en Wayland (sin errores).
- [ ] Paso 2: medidores + resumen con datos reales.
- [ ] Paso 3: tablas y gráfico.
- [ ] Paso 4: ajustes persistentes.
- [ ] Paso 5: captura con `spectacle` y revisión visual.
- [ ] Paso 6: commit `feat: gtk4 dashboard`.

### Task 10: Empaquetado, documentación y verificación final

**Files:**
- Create: `install.sh`, `packaging/io.github.fresteban.OpencodeGoMonitor.desktop`,
  `packaging/ocgm.service`, `packaging/icon.svg`, `docs/USAGE.md`
- Modify: `README.md`, `pyproject.toml`

- [ ] Paso 1: instalador de usuario (binario/entrypoint, .desktop, systemd opcional).
- [ ] Paso 2: README con instalación, credenciales, límites y privacidad.
- [ ] Paso 3: `pytest -q` completo en verde.
- [ ] Paso 4: prueba en vivo: doctor, sync, status, GUI, bandeja, notificación de prueba.
- [ ] Paso 5: commit `feat: packaging and docs` + tag `v0.1.0`.

## Verificación final

- `pytest -q` → 0 fallos.
- `ocgm doctor` → credencial OAuth detectada, API 200, BD local OK.
- `ocgm status --json` → 3 medidores + gasto 30 d.
- GUI: 0 errores/warnings GTK; captura revisada.
- Bandeja visible en KDE; menú funcional.
- Simulación de token caducado y de 429 → mensajes claros, sin crash.
