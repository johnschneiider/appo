from django.contrib import admin
from django.urls import path, include
from django.shortcuts import render
from django.conf import settings
from django.conf.urls.static import static
from negocios.models import Negocio
from django.utils import timezone
from django.db.models import Count, Avg
from negocios import views

def inicio(request):
    if request.user.is_authenticated and hasattr(request.user, 'tipo') and request.user.tipo == 'cliente':
        # Procesar reservas pasadas automáticamente
        from clientes.utils import procesar_reservas_pasadas, obtener_reservas_activas, obtener_reservas_historial
        
        # Procesar reservas pasadas
        reservas_completadas_auto = procesar_reservas_pasadas()
        if reservas_completadas_auto > 0:
            from django.contrib import messages
            messages.info(request, f'Se han completado automáticamente {reservas_completadas_auto} reservas pasadas.')
        
        # Obtener reservas usando las funciones utilitarias
        proximas_reservas = obtener_reservas_activas(request.user)[:3]
        historial_reservas = obtener_reservas_historial(request.user)[:5]

        # Negocios vistos recientemente (por actividades registradas)
        from clientes.models import ActividadUsuario
        actividades_visitas = ActividadUsuario.objects.filter(
            usuario=request.user,
            tipo='visita_negocio'
        ).order_by('-fecha_creacion')[:10]
        
        negocios_vistos_ids = [act.objeto_id for act in actividades_visitas if act.objeto_id]
        negocios_vistos = Negocio.objects.filter(id__in=negocios_vistos_ids, activo=True).annotate(
            rating=Avg('calificaciones__puntaje'),
            total_resenias=Count('calificaciones')
        )[:5]

        # Negocios recomendados (top rating, excluyendo los ya vistos)
        negocios_recomendados = Negocio.objects.filter(activo=True).exclude(id__in=negocios_vistos_ids).annotate(
            rating=Avg('calificaciones__puntaje'),
            total_resenias=Count('calificaciones')
        ).order_by('-rating', '-total_resenias')[:5]

        # Lista de todos los negocios activos
        todos_negocios = Negocio.objects.filter(activo=True).select_related().annotate(
            rating=Avg('calificaciones__puntaje'),
            total_resenias=Count('calificaciones')
        ).order_by('-rating', '-total_resenias')

        # Top de negocios mejor valorados (con al menos 1 calificación)
        top_negocios = Negocio.objects.filter(activo=True).annotate(
            rating=Avg('calificaciones__puntaje'),
            total_resenias=Count('calificaciones')
        ).filter(total_resenias__gte=1).order_by('-rating', '-total_resenias')[:10]

        # Reservas activas del cliente
        reservas_cliente = obtener_reservas_activas(request.user)

        # Total histórico de reservas en toda la plataforma (independiente del usuario)
        from clientes.models import Reserva
        total_reservas = Reserva.objects.count()

        context = {
            'is_cliente': True,
            'proximas_reservas': proximas_reservas,
            'historial_reservas': historial_reservas,
            'negocios_vistos': negocios_vistos,
            'negocios_recomendados': negocios_recomendados,
            'todos_negocios': todos_negocios,
            'top_negocios': top_negocios,
            'reservas_cliente': reservas_cliente,
            'total_reservas': total_reservas,
            # Flags para mostrar/ocultar secciones
            'tiene_proximas_reservas': proximas_reservas.exists(),
            'tiene_historial': historial_reservas.exists(),
            'tiene_negocios_vistos': negocios_vistos.exists(),
            'tiene_recomendados': negocios_recomendados.exists(),
        }
        return render(request, 'inicio.html', context)
    else:
        # Para usuarios no autenticados o no clientes: total histórico global
        from clientes.models import Reserva
        total_reservas = Reserva.objects.count()
        
        # Lista de todos los negocios activos
        todos_negocios = Negocio.objects.filter(activo=True).select_related().annotate(
            rating=Avg('calificaciones__puntaje'),
            total_resenias=Count('calificaciones')
        ).order_by('-rating', '-total_resenias')

        # Top de negocios mejor valorados (con al menos 1 calificación)
        top_negocios = Negocio.objects.filter(activo=True).annotate(
            rating=Avg('calificaciones__puntaje'),
            total_resenias=Count('calificaciones')
        ).filter(total_resenias__gte=1).order_by('-rating', '-total_resenias')[:10]

        return render(request, 'inicio.html', {
            'total_reservas': total_reservas,
            'todos_negocios': todos_negocios,
            'top_negocios': top_negocios,
        })

def custom_429(request, exception=None):
    return render(request, "429.html", status=429)

def health_check(request):
    """Endpoint para health check de Docker"""
    from django.http import JsonResponse
    return JsonResponse({"status": "healthy", "timestamp": timezone.now().isoformat()})

handler429 = "melissa.urls.custom_429"

urlpatterns = [
    path('admin/', admin.site.urls),
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
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT) + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)