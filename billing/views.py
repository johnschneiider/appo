import logging
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View
from .models import SaaSSubscription

logger = logging.getLogger(__name__)


class BillingDetailView(LoginRequiredMixin, View):
    template_name = 'billing/detail.html'

    def get(self, request):
        negocio = request.user.negocios.first()
        if not negocio:
            return redirect(reverse('negocios:mis_negocios'))

        sub = getattr(negocio, 'saas_subscription', None)

        # Si no tiene suscripción, crearla con trial
        if sub is None:
            sub = SaaSSubscription.objects.create(
                negocio=negocio,
                plan='pro',
                status='trial',
                amount_cop=49000,
                numero_barberos=1,
                starts_at=timezone.now().date(),
                expires_at=timezone.now().date() + timezone.timedelta(days=30),
            )
            # Activar features Pro
            negocio.feature_whatsapp = True
            negocio.feature_blacklist = True
            negocio.feature_comisiones = True
            negocio.feature_estadisticas = True
            negocio.feature_marketing = True
            negocio.feature_asistente = True
            negocio.feature_soporte_vip = True
            negocio.feature_backup = True
            negocio.save(update_fields=[
                'feature_whatsapp', 'feature_blacklist', 'feature_comisiones',
                'feature_estadisticas', 'feature_marketing', 'feature_asistente',
                'feature_soporte_vip', 'feature_backup',
            ])
            logger.info(f'📋 SaaSSubscription tardía creada para: {negocio.nombre}')

        # Generar link Bold si no tiene o si expiró
        if sub.plan == 'pro' and not sub.bold_payment_link:
            sub._generate_bold_link()

        # Sincronizar barberos reales
        sub.sync_numero_barberos()
        sub.update_status()

        payments = sub.payments.all()
        return render(request, self.template_name, {
            'negocio': negocio,
            'sub': sub,
            'payments': payments,
        })
