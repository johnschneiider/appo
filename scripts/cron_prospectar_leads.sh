#!/bin/bash
# Cron job para prospección de leads WhatsApp (ejecuta cada hora)
# Horario Colombia: 8 AM–8 PM = UTC 13–01

set -euo pipefail

LOCKFILE="/tmp/prospectar_leads.lock"

# Si ya hay un proceso corriendo, salir sin error
if [ -f "$LOCKFILE" ]; then
    LOCK_PID=$(cat "$LOCKFILE" 2>/dev/null || echo "")
    if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
        echo "[$(date -Iseconds)] Prospectar ya corriendo (PID $LOCK_PID). Saliendo."
        exit 0
    fi
    # Stale lock, limpiar
    rm -f "$LOCKFILE"
fi

# Crear lock
echo $$ > "$LOCKFILE"
trap 'rm -f "$LOCKFILE"' EXIT

cd /var/www/appo.com.co || exit 1
export DJANGO_SETTINGS_MODULE=melissa.settings

# Usar Python del venv con path absoluto (no confiar en source activate)
VENV_PYTHON="/var/www/appo.com.co/venv/bin/python"

# Ejecutar worker de prospección (sin --ignore-hours, respeta horario laboral)
$VENV_PYTHON manage.py prospectar_leads >> logs/cron_prospectar.log 2>&1

# Rotar log si supera 10MB (opcional)
LOG_SIZE=$(stat -c%s logs/cron_prospectar.log 2>/dev/null || echo 0)
if [ $LOG_SIZE -gt 10485760 ]; then
    mv logs/cron_prospectar.log logs/cron_prospectar.log.$(date +%Y%m%d_%H%M%S)
fi
