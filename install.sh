#!/bin/sh
# Instala o actualiza Disk Monitor en este servidor.
#   ./install.sh            → puerto 8093
#   HOST_PORT=9000 ./install.sh
set -e
cd "$(dirname "$0")"
command -v docker >/dev/null || { echo "Falta Docker"; exit 1; }
if docker compose version >/dev/null 2>&1; then DC="docker compose"
elif command -v docker-compose >/dev/null; then DC="docker-compose"
else echo "Falta docker compose"; exit 1; fi
mkdir -p data
if [ ! -f .env ]; then
  PASS=$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 18)
  umask 077
  printf 'APP_USER=admin\nAPP_PASSWORD=%s\nHOST_PORT=%s\nTZ=%s\n' "$PASS" "${HOST_PORT:-8093}" \
    "$(cat /etc/timezone 2>/dev/null || timedatectl show -p Timezone --value 2>/dev/null || echo UTC)" > .env
  echo "Se creó .env con una contraseña nueva."
fi
$DC up -d --build
PORT=$(grep '^HOST_PORT=' .env | cut -d= -f2); PORT=${PORT:-8093}
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo
echo "Disk Monitor: http://${IP:-localhost}:${PORT}"
echo "Usuario: $(grep '^APP_USER=' .env | cut -d= -f2)   Contraseña: $(grep '^APP_PASSWORD=' .env | cut -d= -f2)"
echo "La detección de discos corre al iniciar; revisa los logs con: $DC logs -f"
