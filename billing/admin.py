from django.contrib import admin
from .models import SaaSSubscription, PaymentRecord


@admin.register(SaaSSubscription)
class SaaSSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('negocio', 'plan', 'status', 'amount_cop', 'numero_barberos', 'starts_at', 'expires_at', 'days_until_expiry')
    list_filter = ('plan', 'status')
    search_fields = ('negocio__nombre',)
    readonly_fields = ('created_at', 'updated_at')
    actions = ['degradar_a_gratuito', 'extender_30_dias']

    def degradar_a_gratuito(self, request, queryset):
        for sub in queryset:
            sub._degradar_a_gratuito()
        self.message_user(request, f'{queryset.count()} suscripciones degradadas.')
    degradar_a_gratuito.short_description = 'Degradar a Capa Gratuita'

    def extender_30_dias(self, request, queryset):
        from django.utils import timezone
        for sub in queryset:
            if sub.expires_at:
                sub.expires_at += timezone.timedelta(days=30)
            else:
                sub.expires_at = timezone.now().date() + timezone.timedelta(days=30)
            sub.status = 'active'
            sub.save()
        self.message_user(request, f'{queryset.count()} suscripciones extendidas 30 días.')
    extender_30_dias.short_description = 'Extender 30 días'


@admin.register(PaymentRecord)
class PaymentRecordAdmin(admin.ModelAdmin):
    list_display = ('subscription', 'amount_cop', 'paid_at', 'confirmed_by')
    list_filter = ('paid_at',)
    search_fields = ('subscription__negocio__nombre',)
