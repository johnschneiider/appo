from django.contrib import admin
from .models import Lead

@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ('nombre_establecimiento', 'ciudad', 'telefono', 'proyecto', 'estado', 'prioridad')
    list_filter = ('proyecto', 'estado', 'ciudad')
    search_fields = ('nombre_establecimiento', 'telefono', 'ciudad')
    readonly_fields = ('fecha_ingreso',)

    def get_queryset(self, request):
        # Forzar el uso de la base de datos de leads
        return super().get_queryset(request).using('leads_db')

    def save_model(self, request, obj, form, change):
        # Guardar en la base de datos de leads
        obj.save(using='leads_db')

    def delete_model(self, request, obj):
        # Borrar de la base de datos de leads
        obj.delete(using='leads_db')
