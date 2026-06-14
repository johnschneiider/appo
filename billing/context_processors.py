"""
Banner de suscripción — inyecta un toast/alert en el template cuando:
- La suscripción está por vencer (≤7 días)
- La suscripción ya expiró (bajó a Capa Gratuita)
- El trial está activo (recordatorio amigable)
"""
from django.utils import timezone


def subscription_banner(request):
    """
    Context processor que agrega datos del banner de suscripción al contexto.
    Se renderiza en el template vía un bloque condicional.
    """
    user = request.user
    if not user.is_authenticated:
        return {}

    if getattr(user, 'tipo', None) != 'negocio':
        return {}

    try:
        negocio = user.negocios.first()
        if not negocio:
            return {}

        sub = getattr(negocio, 'saas_subscription', None)
        if not sub:
            return {}

        banner = None

        if sub.status == 'expiring_soon':
            days = sub.days_until_expiry()
            banner = {
                'type': 'warning',
                'title': f'⚠️ Tu Plan Pro vence en {days} días',
                'message': f'Te quedan {days} días de Plan Pro. Renueva ahora para mantener tus funciones premium activas.',
                'action_url': '/negocio/billing/',
                'action_text': 'Renovar ahora',
                'dismissible': True,
            }
        elif sub.status == 'expired':
            banner = {
                'type': 'info',
                'title': '📋 Estás en Capa Gratuita',
                'message': 'Tu Plan Pro ha vencido. Tus datos están seguros y puedes seguir recibiendo reservas. Activa el Plan Pro para recuperar funciones premium.',
                'action_url': '/negocio/billing/',
                'action_text': 'Ver planes',
                'dismissible': True,
            }
        elif sub.status == 'trial':
            days = sub.days_until_expiry()
            if days is not None and days <= 14:
                banner = {
                    'type': 'info',
                    'title': f'🎉 Trial · {days} días restantes',
                    'message': f'Estás en periodo de prueba. Disfruta todas las funciones Pro gratis por {days} días más.',
                    'action_url': '/negocio/billing/',
                    'action_text': 'Ver mi plan',
                    'dismissible': True,
                }

        if banner:
            return {'subscription_banner': banner}

    except Exception:
        pass

    return {'subscription_banner': {}}

def soporte_vip_context(request):
    """Agrega datos de soporte VIP al contexto para negocios Plan Pro."""
    if not request.user.is_authenticated:
        return {}
    if getattr(request.user, 'tipo', None) != 'negocio':
        return {}
    
    try:
        negocio = request.user.negocios.first()
        if negocio and getattr(negocio, 'feature_soporte_vip', False):
            return {
                'soporte_vip': {
                    'activo': True,
                    'whatsapp': '+57 311 745 1274',
                    'mensaje': 'Soporte VIP Appo — Respuesta prioritaria en minutos',
                }
            }
    except Exception:
        pass
    
    return {'soporte_vip': {'activo': False}}
