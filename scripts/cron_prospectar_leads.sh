#!/bin/bash
# Cron job para prospección de leads WhatsApp (ejecuta cada hora)
# Horario Colombia: 8 AM–8 PM = UTC 13–01

cd /var/www/appo.com.co
source venv/bin/activate
export DJANGO_SETTINGS_MODULE=melissa.settings

# Ejecutar worker de prospección (sin --ignore-hours, respeta horario laboral)
python manage.py prospectar_leads >> logs/cron_prospectar.log 2>&1

# Rotar log si supera 10MB (opcional)
LOG_SIZE=$(stat -c%s logs/cron_prospectar.log 2>/dev/null || echo 0)
if [ $LOG_SIZE -gt 10485760 ]; then
    mv logs/cron_prospectar.log logs/cron_prospectar.log.$(date +%Y%m%d_%H%M%S)
fi