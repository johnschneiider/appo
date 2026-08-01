"""
Señales de billing — conectan Negocio ↔ SaaSSubscription automáticamente.
"""
import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from negocios.models import Negocio
from .models import SaaSSubscription

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Negocio)
def crear_o_actualizar_suscripcion(sender, instance, created, **kwargs):
    """
    Al crear un Negocio nuevo → crea SaaSSubscription con trial 30 días + link Bold.
    Al actualizar → sincroniza numero_barberos.
    """
    if created:
        sub = SaaSSubscription.objects.create(
            negocio=instance,
            plan='pro',
            status='trial',
            amount_cop=49000,
            numero_barberos=1,
            starts_at=timezone.now().date(),
            expires_at=timezone.now().date() + timezone.timedelta(days=30),
        )
        # Activar features Pro durante el trial
        instance.feature_whatsapp = True
        instance.feature_blacklist = True
        instance.feature_comisiones = True
        instance.feature_estadisticas = True
        instance.feature_marketing = True
        instance.feature_asistente = True
        instance.feature_soporte_vip = True
        instance.feature_backup = True
        instance.save(update_fields=[
            'feature_whatsapp', 'feature_blacklist', 'feature_comisiones',
            'feature_estadisticas', 'feature_marketing', 'feature_asistente',
            'feature_soporte_vip', 'feature_backup',
        ])
        # Generar link de pago Bold
        sub._generate_bold_link()
        logger.info(f'✅ SaaSSubscription creada + features Pro activadas + link Bold: {instance.nombre}')
    else:
        # Al actualizar, sincronizar barberos si ya existe suscripción
        try:
            sub = instance.saas_subscription
            sub.sync_numero_barberos()
        except SaaSSubscription.DoesNotExist:
            pass  # Nunca debería pasar, pero por si acaso
