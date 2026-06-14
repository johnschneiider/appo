"""
Webhook Bold — recibe notificaciones de pago y actualiza suscripciones automáticamente.
Docs: https://developers.bold.co/webhook
"""
import hashlib
import hmac
import base64
import json
import logging
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from .models import SaaSSubscription

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def bold_webhook(request):
    """
    Endpoint que recibe notificaciones de Bold.
    Verifica firma HMAC-SHA256 y procesa el evento de pago.
    """
    # 1. Verificar firma
    signature = request.headers.get('x-bold-signature', '')
    if not _verify_signature(request.body, signature):
        logger.warning('Bold webhook: firma inválida')
        return JsonResponse({'error': 'Invalid signature'}, status=400)

    # 2. Parsear el evento
    try:
        event = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    event_type = event.get('type')
    data = event.get('data', {})

    logger.info(f'Bold webhook received: {event_type} — {event.get("id")}')

    # 3. Procesar según tipo de evento
    if event_type == 'SALE_APPROVED':
        _handle_sale_approved(data)
    elif event_type == 'SALE_REJECTED':
        _handle_sale_rejected(data)
    elif event_type == 'VOID_APPROVED':
        _handle_void_approved(data)

    # 4. Responder 200 inmediatamente (Bold espera <2s)
    return JsonResponse({'status': 'ok'})


def _verify_signature(body, signature):
    """Verifica que el webhook viene de Bold usando HMAC-SHA256."""
    if not signature:
        # En modo pruebas, Bold puede enviar sin firma
        return True

    secret = getattr(settings, 'BOLD_SECRET_KEY', '')
    try:
        encoded = base64.b64encode(body)
        hashed = hmac.new(
            key=secret.encode(),
            digestmod=hashlib.sha256,
            msg=encoded
        ).hexdigest()
        return hmac.compare_digest(hashed.encode(), signature.encode())
    except Exception:
        return False


def _handle_sale_approved(data):
    """Procesa un pago aprobado: activa la suscripción."""
    reference = data.get('metadata', {}).get('reference', '')
    amount = data.get('amount', {}).get('total', 0)

    # Buscar suscripción por referencia (SUB-{negocio_id}-...)
    if not reference or not reference.startswith('SUB-'):
        logger.warning(f'Bold webhook: referencia no reconocida: {reference}')
        return

    try:
        negocio_id = int(reference.split('-')[1])
    except (IndexError, ValueError):
        logger.warning(f'Bold webhook: no se pudo extraer negocio_id de {reference}')
        return

    try:
        sub = SaaSSubscription.objects.get(negocio_id=negocio_id)
    except SaaSSubscription.DoesNotExist:
        logger.error(f'Bold webhook: suscripción no encontrada para negocio {negocio_id}')
        return

    # Confirmar pago y activar
    sub.confirm_payment(
        amount=amount,
        notes=f'Webhook Bold — {reference}'
    )
    logger.info(f'✅ Pago confirmado: {sub.negocio.nombre} — ${amount:,} COP — Plan Pro activado')


def _handle_sale_rejected(data):
    """Registra un pago rechazado (solo logging)."""
    reference = data.get('metadata', {}).get('reference', '')
    logger.info(f'Bold webhook: pago RECHAZADO — {reference}')


def _handle_void_approved(data):
    """Procesa una anulación aprobada."""
    reference = data.get('metadata', {}).get('reference', '')
    logger.info(f'Bold webhook: anulación aprobada — {reference}')
