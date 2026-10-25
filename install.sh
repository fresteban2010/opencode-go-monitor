#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
PREFIX="$DATA_HOME/opencode-go-monitor"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="$DATA_HOME/applications"
ICONS_DIR="$DATA_HOME/icons/hicolor/scalable/apps"
SYSTEMD_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"

AUTOSTART=0
SERVICE=0
AWAKE=0
for arg in "$@"; do
  case "$arg" in
    --autostart) AUTOSTART=1 ;;
    --service) SERVICE=1 ;;
    --awake) AWAKE=1 ;;
    -h|--help)
      echo "Uso: $0 [--autostart] [--service] [--awake]"
      exit 0
      ;;
    *) echo "Opción desconocida: $arg" >&2; exit 2 ;;
  esac
done

python3 - <<'PY'
import sys
try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk  # noqa: F401
except Exception as error:
    print("Faltan dependencias de GTK4/PyGObject:", error, file=sys.stderr)
    print("En Arch/CachyOS: sudo pacman -S python-gobject gtk4 libadwaita libnotify", file=sys.stderr)
    raise SystemExit(1)
PY

mkdir -p "$PREFIX" "$BIN_DIR" "$APPS_DIR" "$ICONS_DIR"
python3 -m venv --system-site-packages "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install --quiet --upgrade pip
"$PREFIX/venv/bin/pip" install --quiet "$ROOT"
ln -sf "$PREFIX/venv/bin/ocgm" "$BIN_DIR/ocgm"

sed "s|^Exec=.*|Exec=$BIN_DIR/ocgm gui|" \
  "$ROOT/packaging/io.github.fresteban.OpencodeGoMonitor.desktop" > "$APPS_DIR/io.github.fresteban.OpencodeGoMonitor.desktop"
chmod 0644 "$APPS_DIR/io.github.fresteban.OpencodeGoMonitor.desktop"
install -m 0644 "$ROOT/packaging/io.github.fresteban.OpencodeGoMonitor.svg" "$ICONS_DIR/"

if [ "$AUTOSTART" -eq 1 ]; then
  mkdir -p "$AUTOSTART_DIR"
  cat > "$AUTOSTART_DIR/opencode-go-monitor.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=OpenCode Go Monitor
Exec=$BIN_DIR/ocgm tray
X-GNOME-Autostart-enabled=true
EOF
  echo "Autostart instalado."
fi

if [ "$SERVICE" -eq 1 ]; then
  mkdir -p "$SYSTEMD_DIR"
  sed "s|@OCGM@|$BIN_DIR/ocgm|" "$ROOT/packaging/ocgm.service" > "$SYSTEMD_DIR/ocgm.service"
  systemctl --user daemon-reload
  systemctl --user enable --now ocgm.service
  echo "Servicio systemd de usuario activado."
fi

if [ "$AWAKE" -eq 1 ]; then
  install -m 0755 "$ROOT/packaging/opencode-awake" "$BIN_DIR/opencode-awake"
  mkdir -p "$SYSTEMD_DIR"
  sed "s|@AWAKE@|$BIN_DIR/opencode-awake|" \
    "$ROOT/packaging/opencode-awake.service" > "$SYSTEMD_DIR/opencode-awake.service"
  systemctl --user daemon-reload
  systemctl --user enable --now opencode-awake.service
  echo "Regla anti-bloqueo activada."
fi

if command -v update-desktop-database >/dev/null; then
  update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null; then
  gtk-update-icon-cache -q -t "$DATA_HOME/icons/hicolor" 2>/dev/null || true
fi

echo "Instalado en $PREFIX"
echo "Comando: $BIN_DIR/ocgm"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "Añade $BIN_DIR al PATH para usar 'ocgm'." ;;
esac
echo "Siguiente paso: ocgm doctor"
