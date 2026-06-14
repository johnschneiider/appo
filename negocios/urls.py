from django.urls import path
from . import views
from .views import api_responder_matricula

app_name = 'negocios'

urlpatterns = [
    # Vista pública del negocio (sin login requerido)
    path('clientes/peluquero/<int:negocio_id>/', views.negocio_publico, name='negocio_publico'),
    
    path('mis/', views.mis_negocios, name='mis_negocios'),
    path('crear/', views.crear_negocio, name='crear_negocio'),
    path('<int:negocio_id>/editar/', views.editar_negocio, name='editar_negocio'),
    path('<int:negocio_id>/eliminar/', views.eliminar_negocio, name='eliminar_negocio'),
    path('<int:negocio_id>/configurar/', views.configurar_negocio, name='configurar_negocio'),
    path('<int:negocio_id>/panel/', views.panel_negocio, name='panel_negocio'),
    path('<int:negocio_id>/dashboard/', views.dashboard_negocio, name='dashboard_negocio'),
    path('solicitudes-matricula/', views.solicitudes_matricula, name='solicitudes_matricula'),
    path('perfil-profesional/<int:profesional_id>/', views.ver_perfil_profesional, name='ver_perfil_profesional'),
    path('desvincular-profesional/<int:matricula_id>/', views.desvincular_profesional, name='desvincular_profesional'),
    path('api/matricula/<int:solicitud_id>/<str:accion>/', api_responder_matricula, name='api_responder_matricula'),
    path('api/matricula/<int:solicitud_id>/aceptar/', api_responder_matricula, {'accion': 'aceptar'}, name='api_aceptar_matricula'),
    path('api/matricula/<int:solicitud_id>/rechazar/', api_responder_matricula, {'accion': 'rechazar'}, name='api_rechazar_matricula'),
    path('<int:negocio_id>/galeria/', views.galeria_negocio, name='galeria_negocio'),
    path('<int:negocio_id>/profesional/<int:profesional_id>/editar/', views.editar_profesional_negocio, name='editar_profesional_negocio'),
    path('<int:negocio_id>/calendario/', views.calendario_reservas, name='calendario_reservas'),
    path('<int:negocio_id>/api/reservas/', views.api_reservas_negocio, name='api_reservas_negocio'),
    path('<int:negocio_id>/api/reservas/crear/', views.api_crear_reserva, name='api_crear_reserva'),
    path('<int:negocio_id>/api/estadisticas/', views.api_estadisticas_negocio, name='api_estadisticas_negocio'),
    path('<int:negocio_id>/api/usuarios/', views.api_usuarios_negocio, name='api_usuarios_negocio'),
    path('<int:negocio_id>/api/reservas-dia/', views.api_reservas_dia, name='api_reservas_dia'),
    path('<int:negocio_id>/api/agendas-profesionales/', views.api_agendas_profesionales, name='api_agendas_profesionales'),
    path('<int:negocio_id>/api/profesionales/', views.api_profesionales_negocio, name='api_profesionales_negocio'),
    path('<int:negocio_id>/servicios/', views.gestionar_servicios, name='gestionar_servicios'),
    path('servicios/editar/<int:servicio_negocio_id>/', views.editar_servicio_negocio, name='editar_servicio_negocio'),
    path('servicios/eliminar/<int:servicio_negocio_id>/', views.eliminar_servicio_negocio, name='eliminar_servicio_negocio'),
    path('notificaciones/', views.notificaciones_negocio, name='notificaciones'),
    path('solicitudes-ausencia/', views.solicitudes_ausencia, name='solicitudes_ausencia'),
    path('revisar-solicitud-ausencia/<int:solicitud_id>/', views.revisar_solicitud_ausencia, name='revisar_solicitud_ausencia'),
    
    # URLs para días de descanso
    path('dias-descanso/', views.listar_dias_descanso, name='listar_dias_descanso'),
    path('dias-descanso/crear/', views.crear_dia_descanso, name='crear_dia_descanso'),
    path('dias-descanso/editar/<int:dia_id>/', views.editar_dia_descanso, name='editar_dia_descanso'),
    path('dias-descanso/eliminar/<int:dia_id>/', views.eliminar_dia_descanso, name='eliminar_dia_descanso'),
    
    # URLs para gestión de inasistencias
    path('<int:negocio_id>/inasistencias/', views.gestionar_inasistencias, name='gestionar_inasistencias'),
    path('<int:negocio_id>/inasistencias/marcar/<int:reserva_id>/', views.marcar_inasistencia_manual, name='marcar_inasistencia_manual'),
    path('<int:negocio_id>/inasistencias/configurar/', views.configurar_politica_inasistencias, name='configurar_politica_inasistencias'),
    path('<int:negocio_id>/inasistencias/desbloquear/<int:bloqueo_id>/', views.desbloquear_cliente, name='desbloquear_cliente'),
    
    # API para cambiar estado de reserva desde el calendario
    path('<int:negocio_id>/api/reserva/<int:reserva_id>/estado/', views.api_cambiar_estado_reserva, name='api_cambiar_estado_reserva'),
    # API para actualizar hora de reserva (drag and drop)
    path('<int:negocio_id>/api/reserva/<int:reserva_id>/actualizar-hora/', views.api_actualizar_hora_reserva, name='api_actualizar_hora_reserva'),
    path("<int:negocio_id>/lista-negra/", views.lista_negra, name="lista_negra"),
]
