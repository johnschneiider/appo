"""
Middleware de verificación de suscripción SaaS para Appo.
Inspirado en mesenú — verifica estado de suscripción en cada request,
degrada automáticamente a Capa Gratuita si expiró, cachea por 5 min.
"""
from django.utils.deprecation import MiddlewareMixin
from django.core.cache import cache


class SubscriptionCheckMiddleware:
    EXEMPT_PREFIXES = (
        '/admin/', '/static/', '/media/', '/accounts/',
        '/cuentas/', '/leads/', '/superadmin/',
    )
    CACHE_TTL = 300  # 5 minutos

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user

        if not user.is_authenticated:
            return self.get_response(request)

        # Solo aplica a dueños de negocio
        if getattr(user, 'tipo', None) != 'negocio':
            return self.get_response(request)

        # Rutas exentas (auth, admin, static)
        if request.path.startswith(self.EXEMPT_PREFIXES):
            return self.get_response(request)

        # Verificar suscripción con caché
        cache_key = f'saas_sub_status_{user.pk}'
        cached = cache.get(cache_key)

        if cached is None or cached.get('needs_check'):
            try:
                negocio = user.negocios.first()
                if negocio:
                    sub = getattr(negocio, 'saas_subscription', None)
                    if sub:
                        sub.sync_numero_barberos()  # Sincronizar profesionales reales
                        sub.update_status()
                        cache.set(cache_key, {
                            'plan': sub.plan,
                            'level': sub.plan_level,
                            'status': sub.status,
                            'expired': sub.status == 'expired',
                            'needs_check': False,
                        }, self.CACHE_TTL)
            except Exception:
                pass  # No bloquear el request si falla la verificación

        return self.get_response(request)
