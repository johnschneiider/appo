from django.contrib import admin
from .models import RecuperacionCliente


@admin.register(RecuperacionCliente)
class RecuperacionClienteAdmin(admin.ModelAdmin):
    list_display = ('fecha_envio', 'tipo', 'get_cliente', 'negocio',
                    'telefono', 'enviado_ok', 'respondio', 'reagendo', 'opt_out')
    list_filter = ('tipo', 'enviado_ok', 'respondio', 'reagendo', 'opt_out', 'negocio')
    search_fields = ('telefono', 'detalle')
    date_hierarchy = 'fecha_envio'
    readonly_fields = ('fecha_envio',)

    def get_cliente(self, obj):
        if obj.cliente:
            return obj.cliente.get_full_name() or obj.cliente.username
        if obj.cliente_provisional:
            return obj.cliente_provisional.nombre
        return obj.telefono or '—'
    get_cliente.short_description = 'Cliente'
