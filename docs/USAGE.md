# Uso

## Comandos

| Comando | Qué hace |
|---|---|
| `ocgm` / `ocgm status` | Resumen en terminal; añade `--json` para integraciones |
| `ocgm sync [--full]` | Sincroniza cuota y peticiones; `--full` recorre los 30 días |
| `ocgm watch` | Vista de terminal que se refresca sola |
| `ocgm doctor` | Diagnóstico de credencial, API, configuración y BD local |
| `ocgm gui` | Ventana GTK4 + bandeja (`--no-tray` para no lanzarla) |
| `ocgm tray` | Solo icono de bandeja |
| `ocgm service` | Bucle headless para systemd |
| `ocgm autostart enable\|disable\|status` | Inicio automático de la bandeja |

## Salida JSON

`ocgm status --json` emite `schema_version: 1` con:

- `credential`: `source` (`opencode-db`, `auth.json`, `config`, `env`) y `kind`.
- `usage`: `rolling`, `weekly`, `monthly` con `percent`, `status`, `resets_at`,
  `resets_in_seconds` y `stale`.
- `spend`: `today`, `last_7d`, `last_30d`.
- `burn`: ritmo y proyección por ventana.
- `models`: peticiones, tokens y coste por modelo (30 días).

## Configuración

`~/.config/opencode-go-monitor/config.toml`:

```toml
poll_seconds = 60
sync_seconds = 300
thresholds = [70, 85, 95]
notify = true
api_key = "sk-..."   # opcional
```

Los cambios también se pueden hacer desde Ajustes en la ventana.

## Renovación de credenciales

El token de OpenCode Console caduca aproximadamente cada 30 días. OpenCode lo
renueva al usarlo. Si `ocgm doctor` lo marca como caducado:

1. Abre OpenCode y ejecuta cualquier sesión o `/connect`.
2. O configura una API key de Go en Ajustes o con `OPENCODE_API_KEY`.

La app no renueva el token por su cuenta para no invalidar la sesión de OpenCode.

## Systemd

```bash
./install.sh --service
systemctl --user status ocgm.service
journalctl --user -u ocgm.service -f
```

## Mantener la pantalla activa

```bash
./install.sh --awake
systemctl --user status opencode-awake.service
systemd-inhibit --list | grep OpenCode
```

El servicio detecta sesiones interactivas de `opencode` con TTY (no el servicio
`serve`) e inhibe `idle:sleep` y el bloqueo de pantalla. Se libera al cerrar
OpenCode.

## Problemas frecuentes

- **No aparece la bandeja en GNOME**: instala la extensión AppIndicator.
- **“Detalle por petición no disponible”**: la credencial es una API key, no el
  OAuth de Console; los medidores siguen funcionando.
- **Datos desactualizados**: revisa la conexión; la app reintenta y conserva la
  última foto.
- **Diferencia con la consola**: la cuota oficial es agregada; el gasto local es
  una estimación. El número de cuota siempre viene del servidor.
