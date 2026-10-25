# OpenCode Go Monitor — Diseño

Fecha: 2026-10-25
Estado: aprobado para ejecución (hibrido API-first)

## Intención

Una app nativa de Linux que muestre, de forma fiable y sin abrir el navegador,
el consumo de la suscripción OpenCode Go: las tres ventanas oficiales
(5 h, semanal, mensual), el gasto real por petición, el desglose por modelo y
su evolución, con avisos antes de agotar una ventana.

El problema que resuelve: la consola oficial da los datos, pero exige entrar
a la web, no avisa y no conserva histórico más allá de 30 días. Las cifras
locales de OpenCode son estimaciones del cliente y solo cubren este equipo.
La app combina la verdad del servidor con una caché local duradera.

## Objetivos

- Mostrar los tres medidores oficiales con porcentaje, estado y cuenta atrás
  hasta el reset.
- Mostrar gasto y tokens reales por petición, modelo, sesión y cliente,
  desde los logs del servidor (no estimaciones).
- Proyectar agotamiento ("a este ritmo...") y notificar por umbrales.
- Funcionar en bandeja (KDE/StatusNotifierItem) y con ventana GTK4.
- Mantener histórico local más allá de la retención de 30 días del servidor.
- Leer credenciales existentes de OpenCode sin pedir configuración.
- Degradar con elegancia si una fuente falla: última foto + histórico local.

## No objetivos

- No es un proxy ni intercepta tráfico; no modifica OpenCode.
- No muestra prompts, código ni contenido de conversaciones.
- No soporta Windows/macOS ni multiusuario.
- No hace scraping de HTML de la consola ni depende de cookies del navegador.
- No muestra cuota por modelo (la API solo expone el agregado); sí gasto por modelo.
- No renueva el token OAuth de OpenCode (evita invalidar la sesión de OpenCode).

## Anti-objetivos

- Presentar estimaciones locales como si fueran cuota oficial.
- Guardar tokens en logs, historial o capturas.
- Escribir en la base de datos de OpenCode.
- Fallar o cerrarse si una fuente no responde.

## Restricciones y hallazgos verificados

- `GET https://opencode.ai/zen/go/v1/usage` con `Authorization: Bearer <token>`
  devuelve `{"usage":{"rolling|weekly|monthly":{"status","percent","resetsAt"}}}`.
  Verificado en vivo: 16 % / 6 % / 3 %, resets en ISO-8601 UTC.
- El token OAuth de OpenCode Console (`st_...`, integración `opencode`) sirve
  tanto para el endpoint anterior como para
  `GET https://opencode.ai/console/api/request-logs?category=inference&limit=N&cursor=...`,
  que devuelve por petición: `cost`, `inputTokens`, `outputTokens`,
  `reasoningTokens`, `cacheReadTokens`, `cacheWriteTokens`, `model`, `provider`,
  `app`, `sessionID`, `outcome`, `statusCode`, `startedAt`, `durationMs`,
  `timeToFirstTokenMs`, `userAgent`, y `retentionDays` (30).
- La paginación usa `nextCursor`, un objeto JSON que debe ir URL-encoded.
- La cuota es de la cuenta/workspace: cubre otros agentes y máquinas que usen
  la misma cuenta, sin proxy.
- El token OAuth caduca (aprox. 30 días) y OpenCode lo renueva al usarse.
  La app solo lo lee; si caduca, avisa y usa la API key de Go si existe.
- La BD local `~/.local/share/opencode/opencode.db` tiene coste y tokens por
  sesión, pero es estimación del cliente: se usa para offline y reconciliación,
  nunca como fuente principal.
- Entorno: CachyOS, KDE Plasma Wayland, Python 3.14, GTK 4.24,
  libadwaita 1.10, AyatanaAppIndicator3, libnotify. Rust no está instalado.

## Enfoques considerados

1. **Solo endpoint oficial** (tipo `ocum`): tres barras, muy fiable, sin
   histórico ni desglose. Descartado por quedarse corto para "todo".
2. **Scraping de consola**: detalle real, pero depende de cookie `auth` y de
   HTML/endpoints internos; frágil. Descartado como base.
3. **Híbrido API-first (elegido)**: medidores oficiales + logs de servidor por
   petición + caché SQLite + BD local como respaldo/conciliación. Cubre todo
   lo que el servidor expone, con degradación limpia.

## Arquitectura

```
OpenCode Console API ──┐
  /zen/go/v1/usage     ├──► OpenCodeClient ──► Sync ──► Store (SQLite)
  /console/api/logs    │                                  │
OpenCode DB (read-only)┘                                  ├──► CLI (status/doctor)
                                                          ├──► Tray + notificaciones
                                                          └──► Ventana GTK4
```

- Un solo paquete Python `ocgm`, sin framework web.
- Proceso único: `ocgm gui` (ventana + bandeja) o `ocgm service` (headless).
  Ambos comparten el mismo núcleo y la misma BD de caché.
- Hilo de sincronización con `threading` + `GLib.idle_add` para actualizar UI.
- Nunca se escribe en la BD de OpenCode: se abre con URI `mode=ro`.

### Fuentes y resolución de credenciales

Orden:
1. `OPENCODE_API_KEY` (entorno) — API key de Go.
2. `api_key` en config propia (`0600`) — API key de Go.
3. BD de OpenCode, tabla `credential`, `integration_id='opencode'` — OAuth
   `access` + `expires` (fuente preferida: habilita logs por petición).
4. `~/.local/share/opencode/auth.json`, claves `opencode-go` u `opencode` —
   API key.

Con OAuth se usan medidores + logs. Con solo API key se usan medidores y el
histórico local; la UI indica "detalle por petición no disponible".

### Almacenamiento

`~/.local/share/opencode-go-monitor/monitor.db` (WAL), tablas:
- `usage_snapshots`: una fila por consulta (tres ventanas).
- `requests`: una fila por petición del servidor, `id` como PK (idempotente).
- `meta`: cursor, última sincronización, versión de esquema.
- `alert_log`: avisos emitidos para evitar repeticiones.

### Cálculo de ritmo

Cada ventana tiene duración conocida (5 h, 7 d, 30 d) y `resetsAt`.
Inicio = `resetsAt - duración`; transcurrido = ahora - inicio;
ritmo = `percent / transcurrido`; proyección al reset = `ritmo * duración`.
Si la proyección supera 100 %, se calcula ETA de agotamiento. Si `resetsAt`
ya pasó, se muestra "pendiente de actualizar" y se fuerza una consulta.

### Interfaz

- **Resumen:** tres medidores con % y cuenta atrás, gasto hoy/7 d/30 d,
  ritmo y proyección, estado de la última sincronización.
- **Modelos:** tabla por modelo (peticiones, tokens, caché, coste) y gráfico
  de coste diario (14 días) dibujado con `Gtk.DrawingArea`.
- **Peticiones:** últimas 200 con filtros por modelo, cliente y resultado.
- **Ajustes:** intervalo de consulta (mín. 30 s), intervalo de logs,
  umbrales de aviso, notificaciones on/off, API key opcional.
- **Bandeja:** icono coloreado (verde/ámbar/rojo), etiqueta con los tres %,
  menú Abrir / Actualizar / Pausar / Salir. Notificaciones en 70/85/95 %
  y por agotamiento proyectado, con cooldown de 30 min por ventana.

### Errores y degradación

- 401/403: credencial inválida o caducada → mensaje accionable; sigue mostrando
  la última foto y el histórico local.
- 429/5xx/timeout: backoff exponencial (30 s → 15 min) y datos marcados como
  "desactualizados" con hora.
- JSON inesperado: se registra el esquema recibido (sin token) y se conserva
  la última foto válida.
- BD de OpenCode ausente o bloqueada: la app funciona solo con API.

## Tecnología

- Python 3.14, GTK4 + libadwaita (PyGObject), AyatanaAppIndicator3,
  libnotify, SQLite (stdlib), `urllib` (stdlib), `tomllib`.
- Pruebas: pytest en venv con `--system-site-packages`.
- Empaquetado: script `install.sh`, `.desktop`, unidad systemd de usuario,
  autostart opcional. Sin dependencias pip en ejecución.

## Seguridad y privacidad

- Solo se leen credenciales; nunca se imprimen ni se envían a otro sitio.
- Red exclusivamente hacia `opencode.ai`.
- Sin telemetría.
- Config con API key: permisos `0600`.

## Criterios de aceptación

- `ocgm status --json` devuelve los tres medidores reales y el gasto de 30 d.
- `ocgm sync` pagina logs sin duplicados ni huecos y es idempotente.
- La ventana muestra medidores, tablas y gráfico sin errores de consola GTK.
- La bandeja aparece en KDE y abre la ventana.
- Token caducado simulado: mensaje claro, sin crash, datos stale visibles.
- Corte de red simulado: backoff, sin crash, última foto conservada.
- Tests unitarios en verde y `ocgm doctor` sin fallos en vivo.
