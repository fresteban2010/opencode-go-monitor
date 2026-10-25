# OpenCode Go Monitor

App nativa para Linux (GTK4 / libadwaita) que vigila tu suscripción **OpenCode Go**:
las tres ventanas oficiales de cuota, gasto real por petición, desglose por modelo,
histórico local y avisos antes de agotar una ventana.

No es un proxy ni modifica OpenCode: lee su token existente y consulta las APIs
oficiales de `opencode.ai` en modo lectura.

## Funciones

- **3 medidores oficiales**: 5 h, semanal y mensual, con porcentaje, estado y
  cuenta atrás hasta el reset.
- **Gasto real por petición**: coste, tokens, caché, modelo, cliente, sesión y
  resultado, desde los logs del servidor (no estimaciones).
- **Proyección de agotamiento**: “a este ritmo se agota a las 23:40”.
- **Histórico local**: SQLite propia; conserva datos más allá de los 30 días que
  guarda el servidor.
- **Bandeja KDE** (StatusNotifierItem): icono por severidad, tooltip con los tres
  porcentajes, menú Abrir/Actualizar/Salir.
- **Notificaciones** al 70 / 85 / 95 % y por agotamiento proyectado, con cooldown.
- **Reconciliación** con el coste que OpenCode calcula en local.
- **Degradación limpia**: si la API falla, muestra la última foto y avisa; si el
  token caduca, indica cómo renovarlo.

## Requisitos

- Linux con GTK 4.10+, libadwaita 1.6+, PyGObject y libnotify.
- En Arch/CachyOS:

```bash
sudo pacman -S python-gobject gtk4 libadwaita libnotify
```

- OpenCode con sesión iniciada (`/connect` con OpenCode Console o Go), o una API
  key de Go en `OPENCODE_API_KEY`.

## Instalación

```bash
git clone <repo> opencode-go-monitor
cd opencode-go-monitor
./install.sh
```

El instalador crea un venv en `~/.local/share/opencode-go-monitor/venv`, instala
el comando `ocgm` en `~/.local/bin`, el lanzador `.desktop` y el icono. Opciones:

```bash
./install.sh --autostart   # arranca la bandeja al iniciar sesión
./install.sh --service     # instala y activa el servicio systemd de usuario
```

Después:

```bash
ocgm doctor     # comprueba credencial, API, caché y BD local
ocgm status     # resumen en terminal
ocgm gui        # ventana + bandeja
ocgm tray       # solo bandeja
```

## Cómo obtiene los datos

| Fuente | Qué aporta | Fiabilidad |
|---|---|---|
| `GET /zen/go/v1/usage` | 3 ventanas, % y reset | Verdad del servidor |
| `GET /console/api/request-logs` | coste/tokens/modelo por petición (30 días) | Verdad del servidor |
| `~/.local/share/opencode/opencode.db` | sesiones y coste local | Estimación del cliente; solo respaldo |

Credenciales, por orden: `OPENCODE_API_KEY` → API key en Ajustes →
token OAuth de OpenCode Console (`~/.local/share/opencode/opencode.db`) →
`~/.local/share/opencode/auth.json`.

El token OAuth lo renueva OpenCode. Esta app **nunca** lo renueva ni escribe en
la base de datos de OpenCode; si caduca, abre OpenCode o configura una API key.

## Limitaciones

- La API oficial expone la cuota **agregada** de la cuenta, no por modelo. El
  gasto por modelo sí se calcula con los logs.
- Los logs del servidor se conservan 30 días; para más histórico se usa la caché
  local, que empieza a llenarse desde la primera sincronización.
- El coste de la BD local puede diferir del servidor; manda el servidor.
- La bandeja usa StatusNotifierItem; en GNOME requiere la extensión AppIndicator.

## Datos y privacidad

- Config: `~/.config/opencode-go-monitor/config.toml` (permisos `0600` si hay API key).
- Caché: `~/.local/share/opencode-go-monitor/monitor.db`.
- Red: solo `opencode.ai`. Sin telemetría. No se guardan prompts ni respuestas.

## Desarrollo

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e . pytest
.venv/bin/pytest
```

Diseño y plan: `docs/superpowers/specs/` y `docs/superpowers/plans/`.
