"""
Watchdog para Evolution API - mantiene la sesión siempre activa.
Detecta desconexiones y notifica (no puede reconectar sin QR humano).
"""
import time
import requests
import logging
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)

EVOLUTION_URL = "http://localhost:8080"
API_KEY = "OWEN_STRATEGIC_KEY_2026_COL"
INSTANCE = "APPO_CRM"
CHECK_INTERVAL = 30  # segundos


class Command(BaseCommand):
    help = 'Watchdog: mantiene Evolution API monitoreada'

    def handle(self, *args, **options):
        self.stdout.write('Watchdog iniciado')
        consecutive_failures = 0

        while True:
            try:
                r = requests.get(
                    f"{EVOLUTION_URL}/instance/fetchInstances",
                    headers={"apikey": API_KEY},
                    timeout=5
                )
                if r.ok:
                    instances = r.json()
                    state = instances[0].get('instance', {}).get('status', 'unknown') if instances else 'unknown'

                    if state == 'open':
                        consecutive_failures = 0
                        logger.debug('Evolution OK: open')
                    else:
                        consecutive_failures += 1
                        logger.warning(f'Evolution estado: {state} (fallo #{consecutive_failures})')

                        if consecutive_failures >= 3:
                            logger.error('Evolution desconectado 3+ veces. Requiere QR manual.')
                            # Intentar restart suave
                            try:
                                requests.delete(
                                    f"{EVOLUTION_URL}/instance/logout/{INSTANCE}",
                                    headers={"apikey": API_KEY},
                                    timeout=5
                                )
                                logger.info('Logout ejecutado - esperando reconexión manual')
                            except Exception as e:
                                logger.error(f'Error en logout: {e}')
                            consecutive_failures = 0
                else:
                    consecutive_failures += 1
                    logger.warning(f'Evolution API no responde: {r.status_code}')

            except Exception as e:
                consecutive_failures += 1
                logger.error(f'Error watchdog: {e}')

            time.sleep(CHECK_INTERVAL)
