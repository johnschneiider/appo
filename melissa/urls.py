from django.contrib import admin
from django.urls import path, include
from django.shortcuts import render, redirect
from django.conf import settings
from django.conf.urls.static import static
from negocios.models import Negocio
from django.utils import timezone
from django.db.models import Count, Avg
from negocios import views
from django.views.generic import RedirectView

def inicio(request):
    """
    Ruta raíz: redirige según el tipo de usuario autenticado.
    - cliente      → lista de negocios para agendar cita
    - negocio      → panel de mis negocios
    - profesional  → panel del profesional
    - sin sesión   → landing institucional
    """
    if request.user.is_authenticated:
        tipo = getattr(request.user, 'tipo', None)
        if tipo == 'cliente':
            return redirect('clientes:dashboard')
        if tipo == 'negocio':
            return redirect('negocios:mis_negocios')
        if tipo == 'profesional':
            return redirect('profesionales:panel')

    nombres_negocios = list(Negocio.objects.filter(activo=True).values_list('nombre', flat=True)[:30])
    contexto = {
        "precio_mensual": 49000,
        "moneda": "COP",
        "dias_trial": 30,
        "beneficios": [
            "Reservas en segundos, sin llamadas",
            "Agenda para varios barberos",
            "Servicios y precios configurables",
            "Panel con citas y métricas básicas",
            "Soporte digital",
        ],
        "caso_exito": {
            "nombre": "Barbería Centro",
            "resultado": "+30% citas cumplidas en 6 semanas",
            "detalle": "Usaron el link público y organizaron horarios de 3 barberos.",
        },
        "nombres_negocios": nombres_negocios,
    }
    return render(request, 'landing_barberias.html', contexto)

def custom_429(request, exception=None):
    return render(request, "429.html", status=429)

def health_check(request):
    """Endpoint para health check de Docker"""
    from django.http import JsonResponse
    return JsonResponse({"status": "healthy", "timestamp": timezone.now().isoformat()})

handler429 = "melissa.urls.custom_429"

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/login/', RedirectView.as_view(url='/cuentas/login/', permanent=False)),
    path('accounts/', include('allauth.urls')),
    path('cuentas/', include('cuentas.urls')),
    path('', inicio, name='inicio'),
    path('health/', health_check, name='health_check'),
    # Vista pública del negocio (sin login requerido) - CORREGIDA
    path('clientes/peluquero/<int:negocio_id>/', views.negocio_publico, name='negocio_publico_public'),
    path('negocios/', include(('negocios.urls', 'negocios'), namespace='negocios')),
    path('clientes/', include('clientes.urls')),
    path('profesionales/', include(('profesionales.urls', 'profesionales'), namespace='profesionales')),
    path('chat/', include('chat.urls')),
    path('ia-visagismo/', include('ia_visagismo.urls')),
    path('suscripciones/', include('suscripciones.urls')),
    path('negocio/billing/', include('billing.urls')),
    path('leads/', include('leads_admin.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT) + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)