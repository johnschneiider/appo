from django.db import models
from django.utils import timezone


class SaaSSubscription(models.Model):
    """
    Suscripción del negocio a la plataforma Appo.
    Inspirado en mesenú — sin gateway de pago integrado,
    pagos se confirman manualmente vía link de pago externo.
    """
    PLAN_CHOICES = [
        ('gratuito', 'Capa Gratuita'),
        ('pro', 'Plan Pro'),
        ('empresarial', 'Plan Empresarial'),
    ]
    STATUS_CHOICES = [
        ('active', 'Activa'),
        ('trial', 'Trial 30 días'),
        ('trial_7d', 'Trial 7 días (Bot)'),
        ('expiring_soon', 'Por vencer'),
        ('expired', 'Vencida — Capa Gratuita'),
        ('suspended', 'Suspendida'),
    ]
    PLAN_AMOUNTS = {
        'gratuito': 0,
        'pro': 49000,  # por barbero
        'empresarial': 79000,  # por barbero
    }
    PLAN_LEVELS = {'gratuito': 0, 'pro': 1, 'empresarial': 2}

    negocio = models.OneToOneField(
        'negocios.Negocio',
        on_delete=models.CASCADE,
        related_name='saas_subscription'
    )
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES, default='gratuito')
    amount_cop = models.IntegerField(default=0)
    numero_barberos = models.PositiveIntegerField(default=1, help_text='Calculado automáticamente según profesionales activos')
    starts_at = models.DateField(default=timezone.now)
    expires_at = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='trial')
    bold_payment_link = models.URLField(blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Suscripción SaaS'
        verbose_name_plural = 'Suscripciones SaaS'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.negocio.nombre} — {self.get_plan_display()} ({self.get_status_display()})'

    def sync_numero_barberos(self):
        """Sincroniza numero_barberos con los profesionales aprobados reales."""
        real = self.negocio.matriculaciones_aprobadas.count()
        if real != self.numero_barberos:
            self.numero_barberos = max(real, 1)  # mínimo 1 (el dueño)
            self.amount_cop = self.PLAN_AMOUNTS.get(self.plan, 0) * self.numero_barberos
            self.save(update_fields=['numero_barberos', 'amount_cop'])
            return True
        return False

    def days_until_expiry(self):
        if not self.expires_at:
            return None
        return (self.expires_at - timezone.now().date()).days

    @property
    def plan_level(self):
        return self.PLAN_LEVELS.get(self.plan, 0)

    @property
    def is_active(self):
        return self.status in ('active', 'trial', 'trial_7d')

    def update_status(self):
        """Actualiza el estado según fechas. Si expiró, degrada a Capa Gratuita."""
        if self.expires_at is None:
            return  # Sin fecha de expiración (Capa Gratuita)

        days = self.days_until_expiry()

        if days is not None and days < 0:
            if self.plan != 'gratuito':
                self._degradar_a_gratuito()
            elif self.status != 'expired':
                self.status = 'expired'
                self.save(update_fields=['status'])
        elif days is not None and days <= 7:
            if self.status != 'expiring_soon':
                self.status = 'expiring_soon'
                self.save(update_fields=['status'])
        elif self.status not in ('active', 'trial', 'trial_7d'):
            self.status = 'active'
            self.save(update_fields=['status'])

    def _degradar_a_gratuito(self):
        """Degrada a Capa Gratuita: pierde funciones Pro, mantiene reservas."""
        if self.plan == 'gratuito':
            return

        self.status = 'expired'
        self.plan = 'gratuito'
        self.amount_cop = 0
        self.save(update_fields=['status', 'plan', 'amount_cop'])

        # Desactivar features Pro en el negocio
        negocio = self.negocio
        negocio.feature_whatsapp = False
        negocio.feature_blacklist = False
        negocio.feature_comisiones = False
        negocio.feature_estadisticas = False
        negocio.feature_marketing = False
        negocio.feature_asistente = False
        negocio.feature_soporte_vip = False
        negocio.feature_backup = False
        negocio.save(update_fields=[
            'feature_whatsapp', 'feature_blacklist', 'feature_comisiones',
            'feature_estadisticas', 'feature_marketing', 'feature_asistente',
            'feature_soporte_vip', 'feature_backup',
        ])

    def activate_trial(self, days=30):
        """Activa trial para Plan Pro. Por defecto 30 días, acepta 7 días."""
        self.plan = 'pro'
        self.status = 'trial_7d' if days <= 7 else 'trial'
        self.amount_cop = self.PLAN_AMOUNTS['pro'] * self.numero_barberos
        self.starts_at = timezone.now().date()
        self.expires_at = self.starts_at + timezone.timedelta(days=days)
        self.save()
        self._generate_bold_link()

    def activate_bot_trial(self):
        """Activa trial de 7 días del Bot WhatsApp (Plan Pro)."""
        self.activate_trial(days=7)

    def confirm_payment(self, amount, confirmed_by=None, notes=''):
        """Registra un pago manual y extiende la suscripción 30 días."""
        self.sync_numero_barberos()  # Asegurar cantidad real de barberos
        PaymentRecord.objects.create(
            subscription=self,
            amount_cop=amount,
            paid_at=timezone.now().date(),
            confirmed_by=confirmed_by,
            notes=notes
        )

        # Reactivar si estaba vencida
        today = timezone.now().date()
        if self.expires_at and self.expires_at < today:
            self.expires_at = today + timezone.timedelta(days=30)
        else:
            self.expires_at = (self.expires_at or today) + timezone.timedelta(days=30)

        self.status = 'active'
        self.plan = 'pro'
        self.amount_cop = amount
        self.save()

        # Reactivar features Pro
        negocio = self.negocio
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

    def _generate_bold_link(self):
        """Genera un link de pago Bold para esta suscripción."""
        from .services import bold_client

        if not bold_client.is_configured:
            return

        self.sync_numero_barberos()  # Asegurar conteo real antes de generar link
        
        # Calcular monto basado en número real de barberos
        monto = self.PLAN_AMOUNTS.get('pro', 49000) * self.numero_barberos
        if monto == 0:
            monto = 49000  # Fallback mínimo
        
        reference = f'SUB-{self.negocio_id}-{timezone.now().strftime("%Y%m%d%H%M")}'
        description = f'Plan Pro Appo - {self.negocio.nombre}'[:100]

        url, link_id = bold_client.create_payment_link(
            subscription=self,
            amount_cop=monto,
            description=description,
            reference=reference,
        )

        if url:
            self.bold_payment_link = url
            self.save(update_fields=['bold_payment_link'])


class PaymentRecord(models.Model):
    """Registro manual de pagos (sin gateway automático)."""
    subscription = models.ForeignKey(
        SaaSSubscription,
        on_delete=models.CASCADE,
        related_name='payments'
    )
    amount_cop = models.IntegerField()
    paid_at = models.DateField()
    confirmed_by = models.ForeignKey(
        'cuentas.UsuarioPersonalizado',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Pago registrado'
        verbose_name_plural = 'Pagos registrados'
        ordering = ['-paid_at']

    def __str__(self):
        return f'{self.subscription.negocio.nombre} — ${self.amount_cop:,} ({self.paid_at})'
