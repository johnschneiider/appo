"""
Cliente Bold API — genera links de pago reales vía API Link de Pagos.
Docs: https://developers.bold.co/pagos-en-linea/api-link-de-pagos
"""
import logging
import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

BOLD_API_BASE = 'https://integrations.api.bold.co'
BOLD_LINK_ENDPOINT = '/online/link/v1'
BOLD_LINK_STATUS = '/online/link/v1/{payment_link}'


class BoldClient:
    """Cliente para la API Link de Pagos de Bold."""

    def __init__(self):
        self.api_key = getattr(settings, 'BOLD_API_KEY', None)
        self.secret_key = getattr(settings, 'BOLD_SECRET_KEY', None)
        self.base_url = BOLD_API_BASE

    @property
    def is_configured(self):
        return bool(self.api_key and self.api_key != 'tu-bold-api-key')

    def _headers(self):
        return {
            'Authorization': f'x-api-key {self.api_key}',
            'Content-Type': 'application/json',
        }

    def create_payment_link(self, subscription, amount_cop, description, reference):
        """
        Crea un link de pago Bold para una suscripción.
        Retorna (url, payment_link_id) o (None, error).
        """
        if not self.is_configured:
            return None, 'BOLD_API_KEY no configurada'

        payload = {
            'amount_type': 'CLOSE',
            'amount': {
                'currency': 'COP',
                'total_amount': int(amount_cop),
            },
            'description': description[:100],
            'reference': reference[:60],
            'callback_url': f'https://appo.com.co/negocio/billing/',
            'payment_methods': ['CREDIT_CARD', 'PSE', 'NEQUI', 'BOTON_BANCOLOMBIA'],
        }

        try:
            resp = requests.post(
                f'{self.base_url}{BOLD_LINK_ENDPOINT}',
                json=payload,
                headers=self._headers(),
                timeout=15
            )
            data = resp.json()

            if resp.status_code == 200 and data.get('payload'):
                payment_link = data['payload'].get('payment_link')
                url = data['payload'].get('url')
                logger.info(f'Bold link created: {payment_link} → {url}')
                return url, payment_link

            errors = data.get('errors', [])
            logger.error(f'Bold API error: {errors}')
            return None, str(errors)

        except requests.RequestException as e:
            logger.error(f'Bold API request failed: {e}')
            return None, str(e)

    def get_link_status(self, payment_link_id):
        """Consulta el estado de un link de pago."""
        if not self.is_configured:
            return None

        try:
            resp = requests.get(
                f'{self.base_url}{BOLD_LINK_STATUS.format(payment_link=payment_link_id)}',
                headers=self._headers(),
                timeout=10
            )
            if resp.status_code == 200:
                return resp.json()
            return None
        except Exception:
            return None


# Singleton
bold_client = BoldClient()
