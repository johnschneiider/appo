#!/bin/bash
# Script para ejecutar prospección de leads con entorno correcto
# Uso: prospectar.sh [--dry-run] [--ignore-hours] [--limit N]
# Ejecuta python manage.py prospectar_leads con las opciones proporcionadas.

# Cambiar al directorio del proyecto
cd /var/www/appo.com.co || exit 1

# Cargar variables de entorno desde .env usando source (si no hay problemas)
if [ -f .env ]; then
    echo "[prospectar.sh] Cargando variables de entorno desde .env"
    # Usar export con grep (más robusto)
    export $(grep -v '^#' .env | grep -v '^$' | xargs) >/dev/null 2>&1 || true
fi

# Establecer DJANGO_SETTINGS_MODULE si no está establecido
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-melissa.settings}"

# Argumentos para el comando
ARGS="$*"
# Si no se especifican argumentos, usar --ignore-hours (para que se ejecute fuera de horario cuando lo llame el cron)
if [ -z "$ARGS" ]; then
    ARGS="--ignore-hours"
fi

echo "[prospectar.sh] Ejecutando: python manage.py prospectar_leads $ARGS"
echo "[prospectar.sh] Variables cargadas:"
echo "  DJANGO_SETTINGS_MODULE=$DJANGO_SETTINGS_MODULE"
echo "  DB=${POSTGRES_DB:-'no definido'}"
echo "  PATH=$PATH"

# Verificar que el comando existe
if ! ./venv/bin/python manage.py help prospectar_leads >/dev/null 2>&1; then
    echo "[prospectar.sh] ERROR: Comando prospectar_leads no encontrado"
    echo "[prospectar.sh] Comandos disponibles:"
    ./venv/bin/python manage.py help | grep -i lead
    exit 1
fi

# Ejecutar prospección
echo "[prospectar.sh] Iniciando ejecución..."
./venv/bin/python manage.py prospectar_leads $ARGS
EXIT_CODE=$?

# Fin
echo "[prospectar.sh] Script completado con código de salida: $EXIT_CODE"
exit $EXIT_CODE