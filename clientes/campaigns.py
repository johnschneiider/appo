"""
Servicio de Campañas SMS/Email para Plan Pro.
Usa Twilio para SMS masivos a clientes del negocio.
"""
import logging
from django.conf import settings
from clientes.twilio_whatsapp_service import TwilioWhatsAppService

logger = logging.getLogger(__name__)


class CampañaMarketing:
    """Envía campañas SMS/Email a los clientes de un negocio."""

    def __init__(self, negocio):
        self.negocio = negocio
        self.twilio = TwilioWhatsAppService()

    def enviar_sms_clientes(self, mensaje, limit=50):
        """
        Envía SMS a los clientes del negocio.
        Retorna (enviados, fallidos).
        """
        from clientes.models import Reserva
        from django.contrib.auth import get_user_model
        User = get_user_model()

        # Obtener clientes únicos que han reservado en este negocio
        clientes_ids = Reserva.objects.filter(
            peluquero=self.negocio,
            cliente__isnull=False
        ).values_list('cliente', flat=True).distinct()[:limit]

        enviados = 0
        fallidos = 0

        for user_id in clientes_ids:
            try:
                user = User.objects.get(id=user_id)
                if user.telefono:
                    self.twilio.send_template_message(
                        to_number=user.telefono,
                        template_name=getattr(settings, 'TWILIO_TEMPLATE_TEXTO_LIBRE', ''),
                        variables={'1': mensaje[:100]}
                    )
                    enviados += 1
                    logger.info(f'SMS enviado a {user.username} ({user.telefono})')
            except Exception as e:
                logger.error(f'Error SMS a user {user_id}: {e}')
                fallidos += 1

        return enviados, fallidos

    def enviar_email_clientes(self, asunto, mensaje_html, limit=50):
        """
        Envía email a los clientes del negocio.
        Retorna (enviados, fallidos).
        """
        from django.core.mail import send_mail
        from clientes.models import Reserva
        from django.contrib.auth import get_user_model
        User = get_user_model()

        clientes_ids = Reserva.objects.filter(
            peluquero=self.negocio,
            cliente__isnull=False
        ).values_list('cliente', flat=True).distinct()[:limit]

        enviados = 0
        fallidos = 0

        for user_id in clientes_ids:
            try:
                user = User.objects.get(id=user_id)
                if user.email:
                    send_mail(
                        subject=asunto,
                        message='',
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[user.email],
                        html_message=mensaje_html,
                    )
                    enviados += 1
            except Exception as e:
                logger.error(f'Error email a user {user_id}: {e}')
                fallidos += 1

        return enviados, fallidos
