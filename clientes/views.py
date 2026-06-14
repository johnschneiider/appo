from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import ListView, DetailView
from django.utils import timezone
from datetime import timedelta, datetime, time
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST, require_GET
from negocios.models import Negocio, ServicioNegocio, Servicio
from .models import Reserva, NotificacionCliente, Calificacion
from .forms import ReservaForm, ReservaNegocioForm, CalificacionForm
from .utils import enviar_email_reserva_confirmada, enviar_email_reserva_cancelada, enviar_email_reserva_reagendada, get_current_time_in_timezone
import json
import holidays
import logging
from django.core.exceptions import ValidationError
from django.utils.html import escape
import re
from django.db.models import Q
from profesionales.models import Notificacion, Profesional, Matriculacion, HorarioProfesional
from django.db import models
from math import radians, cos, sin, asin, sqrt
from cuentas.utils import log_user_activity, log_reservation_activity, log_error
from django_ratelimit.decorators import ratelimit
from django.db.models import Avg, Count
from .models import ActividadUsuario
import requests
from django.views.decorators.http import require_GET
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
import json

logger = logging.getLogger(__name__)

def sanitize_input(text):
    """Sanitizar entrada de texto para prevenir XSS"""
    if text:
        text = re.sub(r'<script.*?</script>', '', text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r'<.*?>', '', text)
        return escape(text.strip())
    return text

class ListaNegociosView(ListView):
    model = Negocio
    template_name = 'clientes/lista_negocios.html'
    context_object_name = 'negocios'
    
    def get_queryset(self):
        try:
            return Negocio.objects.filter(activo=True)
        except Exception as e:
            logger.error(f"Error obteniendo lista de negocios: {str(e)}")
            return Negocio.objects.none()
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        try:
            negocios = context['negocios']
            negocios_mapa = []
            for negocio in negocios:
                profesionales_aceptados = [m.profesional for m in Matriculacion.objects.filter(negocio=negocio, estado='aprobada')]
                negocios_mapa.append({
                    'id': negocio.id,
                    'nombre': negocio.nombre,
                    'direccion': negocio.direccion,
                    'latitud': negocio.latitud,
                    'longitud': negocio.longitud,
                    'url': f"/clientes/peluquero/{negocio.id}/",  # Ajusta si tienes un nombre de url
                    'logo_url': negocio.logo.url if negocio.logo else '',
                    'profesionales': profesionales_aceptados,
                })
            context['negocios_mapa'] = negocios_mapa
        except Exception as e:
            logger.error(f"Error procesando contexto de negocios: {str(e)}")
            context['negocios_mapa'] = []
        return context

class DetallePeluqueroView(DetailView):
    model = Negocio
    template_name = 'clientes/detalle_peluquero.html'
    context_object_name = 'negocio'
    
    def get_queryset(self):
        return Negocio.objects.filter(activo=True)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        negocio = self.object
        
        try:
            # Obtener los próximos 60 días de disponibilidad
            hoy = get_current_time_in_timezone().date()
            proximos_dias = [hoy + timedelta(days=i) for i in range(60)]
            
            # Verificar días festivos
            co_holidays = holidays.CountryHoliday('CO')
            
            dias_disponibilidad = []
            for dia in proximos_dias:
                nombre_dia = dia.strftime('%A')
                nombre_dia_es = {
                    'Monday': 'Lunes',
                    'Tuesday': 'Martes',
                    'Wednesday': 'Miércoles',
                    'Thursday': 'Jueves',
                    'Friday': 'Viernes',
                    'Saturday': 'Sábado',
                    'Sunday': 'Domingo'
                }.get(nombre_dia, nombre_dia)
                
                es_festivo = dia in co_holidays or nombre_dia_es == 'Domingo'
                
                # Obtener horario del negocio para este día
                horario = negocio.horario_atencion.get(nombre_dia_es, {}) if negocio.horario_atencion else {}
                turnos = horario.get('turnos', []) if horario else []
                
                # Verificar reservas existentes para este día
                reservas_dia = Reserva.objects.filter(
                    peluquero=negocio,
                    fecha=dia,
                    estado__in=['pendiente', 'confirmado']
                ).values_list('hora_inicio', 'hora_fin')
                
                # Calcular intervalos disponibles
                intervalos_disponibles = []
                for turno in turnos:
                    if turno.get('disponible', True) and not es_festivo:
                        try:
                            inicio = datetime.strptime(turno['inicio'], '%H:%M').time()
                            fin = datetime.strptime(turno['fin'], '%H:%M').time()
                            duracion = int(turno.get('duracion', 30))
                            
                            # Generar intervalos
                            inicio_minutos = inicio.hour * 60 + inicio.minute
                            fin_minutos = fin.hour * 60 + fin.minute
                            tiempo_actual = inicio_minutos
                            
                            while tiempo_actual + duracion <= fin_minutos:
                                hora_inicio = time(tiempo_actual // 60, tiempo_actual % 60)
                                hora_fin = time((tiempo_actual + duracion) // 60, (tiempo_actual + duracion) % 60)
                                
                                # Verificar si este intervalo está disponible
                                ocupado = False
                                for reserva_inicio, reserva_fin in reservas_dia:
                                    if not (hora_fin <= reserva_inicio or hora_inicio >= reserva_fin):
                                        ocupado = True
                                        break
                                        
                                if not ocupado:
                                    intervalos_disponibles.append({
                                        'inicio': hora_inicio.strftime('%H:%M'),
                                        'fin': hora_fin.strftime('%H:%M'),
                                        'duracion': duracion
                                    })
                                    
                                tiempo_actual += duracion
                        except (ValueError, KeyError) as e:
                            logger.warning(f"Error procesando turno: {str(e)}")
                            continue
                
                dias_disponibilidad.append({
                    'fecha': dia,
                    'nombre_dia': nombre_dia_es,
                    'festivo': es_festivo,
                    'intervalos': intervalos_disponibles
                })
            
            context['dias_disponibilidad'] = dias_disponibilidad
            context['hoy'] = hoy
        except Exception as e:
            logger.error(f"Error procesando disponibilidad: {str(e)}")
            context['dias_disponibilidad'] = []
            context['hoy'] = get_current_time_in_timezone().date()
        # Calcular promedio y total de calificaciones
        calificaciones = negocio.calificaciones.all()
        total_opiniones = calificaciones.count()
        if total_opiniones > 0:
            promedio = sum([c.puntaje for c in calificaciones]) / total_opiniones
        else:
            promedio = None
        context['promedio_calificacion'] = promedio
        context['total_opiniones'] = total_opiniones
        
        # Calcular estado abierto/cerrado y hora de cierre
        from datetime import datetime
        ahora = datetime.now()
        dia_semana = ahora.strftime('%A')
        dia_semana_es = {
            'Monday': 'Lunes', 'Tuesday': 'Martes', 'Wednesday': 'Miércoles', 
            'Thursday': 'Jueves', 'Friday': 'Viernes', 'Saturday': 'Sábado', 
            'Sunday': 'Domingo'
        }.get(dia_semana, dia_semana)
        
        horario = negocio.horario_atencion.get(dia_semana_es, {}) if negocio.horario_atencion else {}
        abierto = False
        hora_cierre = None
        
        if horario and 'inicio' in horario and 'fin' in horario:
            try:
                inicio = datetime.strptime(horario['inicio'], '%H:%M').time()
                fin = datetime.strptime(horario['fin'], '%H:%M').time()
                
                if inicio <= ahora.time() <= fin:
                    abierto = True
                    hora_cierre = fin.strftime('%H:%M')
                else:
                    abierto = False
                    hora_cierre = fin.strftime('%H:%M')
            except Exception as e:
                abierto = False
                hora_cierre = None
        
        # Agregar al contexto
        context['abierto'] = abierto
        context['hora_cierre'] = hora_cierre
        
        # Agregar planes de suscripción del negocio
        try:
            from suscripciones.models import PlanSuscripcion
            # Usar self.object (que es el negocio) en lugar de negocio
            planes_suscripcion = PlanSuscripcion.objects.filter(
                negocio=self.object,
                activo=True
            ).order_by('precio_mensual')
            
            # Debug: imprimir información para verificar
            logger.debug(f"DEBUG: Negocio ID: {self.object.id}, Nombre: {self.object.nombre}")
            logger.debug(f"DEBUG: Planes encontrados: {planes_suscripcion.count()}")
            for plan in planes_suscripcion:
                logger.debug(f"DEBUG: Plan: {plan.nombre} (ID: {plan.id}) - Activo: {plan.activo}")
            
            context['planes_suscripcion'] = planes_suscripcion
            context['tiene_planes_suscripcion'] = planes_suscripcion.exists()
        except Exception as e:
            logger.warning(f"No se pudieron cargar los planes de suscripción: {str(e)}")
            logger.debug(f"DEBUG ERROR: {str(e)}")
            context['planes_suscripcion'] = []
            context['tiene_planes_suscripcion'] = False
        
        return context

@ratelimit(key='ip', rate='10/m', method=['POST'])
def reservar_turno(request, peluquero_id):
    """
    Vista pública de reserva: cualquier persona puede VER servicios y precios.
    Solo se requiere autenticación al CONFIRMAR la reserva (POST).
    """
    logger.info(f"=== INICIO reservar_turno ===")
    logger.info(f"Usuario: {request.user} ({getattr(request.user, 'tipo', 'anon')})")
    logger.info(f"Usuario autenticado: {request.user.is_authenticated}")
    logger.info(f"Método HTTP: {request.method}")
    logger.info(f"Peluquero ID: {peluquero_id}")
    logger.info(f"GET params: {request.GET}")
    
    # ── Gate de autenticación suave: GET público, POST requiere auth ──
    if not request.user.is_authenticated and request.method == 'POST':
        logger.info("Anónimo intentó POST en reservar_turno, redirigiendo a login")
        from django.contrib.auth import redirect_to_login
        return redirect_to_login(request.get_full_path())
    
    if not request.user.is_authenticated:
        # Anónimo en GET: redirigir a reservar_negocio que ya tiene vitrina + CTA
        logger.info(f"Anónimo en GET reservar_turno, redirigiendo a reservar_negocio")
        from django.shortcuts import redirect
        from django.urls import reverse
        qs = request.GET.urlencode()
        url = reverse('clientes:reservar_negocio', kwargs={'negocio_id': peluquero_id})
        if qs:
            url += '?' + qs
        return redirect(url)
    
    try:
        negocio = get_object_or_404(Negocio, id=peluquero_id, activo=True)
        logger.info(f"Negocio encontrado: {negocio.nombre}")
        
        if request.method == 'POST':
            form = ReservaForm(request.POST, request.FILES, negocio=negocio, user=request.user)
            if form.is_valid():
                try:
                    # Obtener los datos del formulario
                    servicio = form.cleaned_data.get('servicio')
                    profesional = form.cleaned_data.get('profesional')
                    fecha = form.cleaned_data.get('fecha')
                    hora_inicio = form.cleaned_data.get('hora_inicio')
                    notas = form.cleaned_data.get('notas', '')
                    
                    logger.info(f"Datos del formulario - servicio: {servicio}, profesional: {profesional}, fecha: {fecha}, hora_inicio: {hora_inicio}")
                    
                    # Crear la reserva manualmente
                    reserva = Reserva(
                        cliente=request.user,
                        peluquero=negocio,
                        profesional=profesional,
                        fecha=fecha,
                        hora_inicio=hora_inicio,
                        servicio=servicio,
                        notas=notas,
                        estado='pendiente'
                    )
                    
                    # Calcular hora_fin usando la duración del servicio (siempre requerida)
                    if hora_inicio:
                        duracion = servicio.duracion if servicio and servicio.duracion is not None else 30
                        from datetime import datetime, timedelta
                        hora_inicio_dt = datetime.combine(fecha, hora_inicio)
                        hora_fin_dt = hora_inicio_dt + timedelta(minutes=duracion)
                        reserva.hora_fin = hora_fin_dt.time()
                        logger.info(f"Hora fin calculada: {reserva.hora_fin}")
                    
                    logger.info(f"Intentando guardar reserva con datos: cliente={reserva.cliente.id}, peluquero={reserva.peluquero.id}, profesional={reserva.profesional.id if reserva.profesional else None}, servicio={reserva.servicio.id if reserva.servicio else None}")
                    
                    reserva.save()
                    
                    # Log de actividad de reserva exitosa
                    log_reservation_activity(
                        user=request.user,
                        reservation=reserva,
                        action="reserva_creada",
                        details=f"Negocio: {negocio.nombre}, Servicio: {servicio.servicio.nombre if servicio else 'Sin servicio'}, Fecha: {fecha}, Hora: {hora_inicio}"
                    )
                    
                    # Crear notificación para el profesional si existe
                    if reserva.profesional:
                        from profesionales.models import Notificacion
                        Notificacion.objects.create(
                            profesional=reserva.profesional,
                            tipo='reserva',
                            titulo='Nueva Reserva',
                            mensaje=f'Nueva reserva pendiente para el {reserva.fecha} a las {reserva.hora_inicio} con {reserva.cliente.username}.',
                            url_relacionada='/profesionales/panel/'
                        )
                    
                    # Enviar email de confirmación
                    try:
                        resultado = enviar_email_reserva_confirmada(reserva)
                        if resultado:
                            logger.info(f"Email de confirmación enviado para reserva #{reserva.id}")
                        else:
                            logger.warning(f"No se pudo enviar email de confirmación para reserva #{reserva.id}")
                    except Exception as e_email:
                        logger.warning(f"Email fallido para reserva #{reserva.id}: {e_email}")
                        try:
                            log_error(error_type="email_confirmacion_fallido", error_message=str(e_email), user=request.user, context={"reserva_id": reserva.id})
                        except Exception:
                            pass

                    messages.success(request, '¡Reserva realizada con éxito!')

                    # WhatsApp de confirmación: lo maneja automáticamente recordatorios/signals.py
                    # al dispararse post_save de Reserva. No llamar aquí para evitar duplicados.
                    
                    return redirect('clientes:reserva_exitosa', reserva_id=reserva.id)
                except Exception as e:
                    log_error(
                        error_type="reserva_fallida",
                        error_message=str(e),
                        user=request.user,
                        context={
                            "negocio_id": negocio.id,
                            "servicio": servicio.servicio.nombre if servicio else None,
                            "fecha": str(fecha),
                            "hora_inicio": str(hora_inicio)
                        }
                    )
                    messages.error(request, 'Error al guardar la reserva. Por favor, intenta nuevamente.')
                    return render(request, 'clientes/reservar_turno.html', {
                        'negocio': negocio,
                        'form': form,
                        'today': timezone.now().date()
                    })
            else:
                log_user_activity(
                    user=request.user,
                    action="formulario_reserva_invalido",
                    details=f"Errores: {form.errors}",
                    ip_address=request.META.get('REMOTE_ADDR')
                )
                logger.warning(f"Formulario inválido - errores: {form.errors}")
                messages.error(request, 'Por favor corrige los errores en el formulario.')
                return render(request, 'clientes/reservar_turno.html', {
                    'negocio': negocio,
                    'form': form,
                    'today': timezone.now().date()
                })
        else:
            form = ReservaForm(negocio=negocio, user=request.user)
        
        logger.info(f"Renderizando template reservar_turno.html para negocio: {negocio.nombre}")
        logger.info("=== FIN reservar_turno ===")
        return render(request, 'clientes/reservar_turno.html', {
            'negocio': negocio,
            'form': form,
            'today': timezone.now().date()
        })
    except Exception as e:
        log_error(
            error_type="error_cargar_reserva",
            error_message=str(e),
            user=request.user if request.user.is_authenticated else None,
            context={"peluquero_id": peluquero_id}
        )
        messages.error(request, 'Error al cargar la página de reserva.')
        return redirect('clientes:lista_negocios')

@login_required
@require_GET
def confirmacion_reserva(request, reserva_id):
    try:
        reserva = get_object_or_404(Reserva, id=reserva_id, cliente=request.user)
        return render(request, 'clientes/confirmacion_reserva.html', {'reserva': reserva})
    except Exception as e:
        logger.error(f"Error mostrando confirmación de reserva: {str(e)}")
        messages.error(request, 'Error al mostrar la confirmación de la reserva.')
        return redirect('clientes:lista_negocios')

@require_GET
def horarios_disponibles(request, negocio_id):
    import logging
    logger = logging.getLogger('clientes')
    try:
        negocio = get_object_or_404(Negocio, id=negocio_id, activo=True)
        fecha = request.GET.get('fecha')
        servicio_negocio_id = request.GET.get('servicio_negocio_id')
        profesional_id = request.GET.get('profesional_id')
        duracion = None
        logger.info(f"[HORARIOS DISPONIBLES] Params: negocio_id={negocio_id}, fecha={fecha}, profesional_id={profesional_id}, servicio_negocio_id={servicio_negocio_id}")
        
        # Verificar si el cliente está bloqueado (solo si está autenticado)
        if request.user.is_authenticated:
            from clientes.models import BloqueoCliente
            if BloqueoCliente.esta_bloqueado(request.user, negocio):
                logger.info(f"[HORARIOS DISPONIBLES] Cliente {request.user.username} está bloqueado para {negocio.nombre}")
                # Retornar lista vacía sin mensaje (bloqueo silencioso)
                return JsonResponse({'disponibles': [], 'festivo': False})
        if servicio_negocio_id:
            try:
                servicio_negocio = ServicioNegocio.objects.get(id=servicio_negocio_id, negocio=negocio)
                duracion = servicio_negocio.duracion
                logger.info(f"[HORARIOS DISPONIBLES] Servicio encontrado: {servicio_negocio.servicio.nombre}, duración: {duracion}")
            except ServicioNegocio.DoesNotExist:
                logger.warning(f"[HORARIOS DISPONIBLES] ServicioNegocio no encontrado: {servicio_negocio_id}")
                pass
        if not fecha or not profesional_id:
            logger.warning(f"[HORARIOS DISPONIBLES] Faltan parámetros: fecha={fecha}, profesional_id={profesional_id}")
            return JsonResponse({'error': 'Fecha y profesional requeridos'}, status=400)
        try:
            fecha_obj = datetime.strptime(fecha, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            logger.warning(f"[HORARIOS DISPONIBLES] Formato de fecha inválido: {fecha}")
            return JsonResponse({'error': 'Formato de fecha inválido'}, status=400)
        co_holidays = holidays.CountryHoliday('CO')
        nombre_dia = fecha_obj.strftime('%A')
        nombre_dia_es = {
            'Monday': 'lunes',
            'Tuesday': 'martes',
            'Wednesday': 'miercoles',
            'Thursday': 'jueves',
            'Friday': 'viernes',
            'Saturday': 'sabado',
            'Sunday': 'domingo'
        }.get(nombre_dia, nombre_dia)
        es_festivo = fecha_obj in co_holidays or nombre_dia_es == 'domingo'
        logger.info(f"[HORARIOS DISPONIBLES] Día de la semana: {nombre_dia} -> {nombre_dia_es}, es_festivo: {es_festivo}")
        if es_festivo:
            logger.info("[HORARIOS DISPONIBLES] Es festivo, no hay horarios disponibles")
            return JsonResponse({'disponibles': [], 'festivo': True})
        profesional = get_object_or_404(Profesional, id=profesional_id)
        logger.info(f"[HORARIOS DISPONIBLES] Profesional encontrado: {profesional.nombre_completo} (ID: {profesional.id})")
        logger.info(f"[HORARIOS DISPONIBLES] Buscando horario_prof para dia_semana={nombre_dia_es}, profesional_id={profesional_id}")
        horarios_qs = HorarioProfesional.objects.filter(profesional=profesional, dia_semana=nombre_dia_es)
        logger.info(f"[HORARIOS DISPONIBLES] Horarios encontrados para ese día: {[str(h) for h in horarios_qs]}")
        horario_prof = horarios_qs.filter(disponible=True).first()
        logger.info(f"[HORARIOS DISPONIBLES] horario_prof (después de filtrar disponible=True): {horario_prof}")
        if not horario_prof:
            todos_horarios = HorarioProfesional.objects.filter(profesional=profesional)
            logger.info(f"[HORARIOS DISPONIBLES] Todos los horarios del profesional: {list(todos_horarios)}")
            return JsonResponse({'disponibles': [], 'festivo': False})
        inicio = horario_prof.hora_inicio
        fin = horario_prof.hora_fin
        duracion_turno = duracion or 30
        logger.info(f"[HORARIOS DISPONIBLES] Horario: {inicio} - {fin}, duración turno: {duracion_turno}")
        reservas = Reserva.objects.filter(
            peluquero=negocio,
            profesional=profesional,
            fecha=fecha_obj,
            estado__in=['pendiente', 'confirmado']
        ).values_list('hora_inicio', 'hora_fin')
        logger.info(f"[HORARIOS DISPONIBLES] Reservas existentes: {list(reservas)}")
        horarios_disponibles = []
        inicio_minutos = inicio.hour * 60 + inicio.minute
        fin_minutos = fin.hour * 60 + fin.minute
        tiempo_actual = inicio_minutos
        logger.info(f"[HORARIOS DISPONIBLES] Generando slots desde {inicio_minutos} hasta {fin_minutos} minutos")
        while tiempo_actual + duracion_turno <= fin_minutos:
            hora_inicio = time(tiempo_actual // 60, tiempo_actual % 60)
            hora_fin = time((tiempo_actual + duracion_turno) // 60, (tiempo_actual + duracion_turno) % 60)
            ocupado = False
            for reserva_inicio, reserva_fin in reservas:
                if not (hora_fin <= reserva_inicio or hora_inicio >= reserva_fin):
                    ocupado = True
                    break
            if not ocupado:
                horarios_disponibles.append({
                    'inicio': hora_inicio.strftime('%H:%M'),
                    'fin': hora_fin.strftime('%H:%M'),
                    'duracion': duracion_turno
                })
            tiempo_actual += duracion_turno
        logger.info(f"[HORARIOS DISPONIBLES] Slots generados: {len(horarios_disponibles)}")
        return JsonResponse({
            'disponibles': horarios_disponibles,
            'festivo': False
        })
    except Exception as e:
        logger.error(f"[HORARIOS DISPONIBLES] Error: {str(e)}")
        return JsonResponse({'error': 'Error interno del servidor'}, status=500)

@require_GET
def horarios_disponibles_reagendar(request, reserva_id):
    """Vista para obtener horarios disponibles al reagendar una reserva"""
    try:
        reserva = get_object_or_404(Reserva, id=reserva_id, cliente=request.user)
        fecha = request.GET.get('fecha')
        
        if not fecha:
            return JsonResponse({'error': 'Fecha requerida'}, status=400)
        
        try:
            fecha_obj = datetime.strptime(fecha, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            return JsonResponse({'error': 'Formato de fecha inválido'}, status=400)
        
        # Verificar si es festivo
        co_holidays = holidays.CountryHoliday('CO')
        nombre_dia = fecha_obj.strftime('%A')
        nombre_dia_es = {
            'Monday': 'lunes',
            'Tuesday': 'martes',
            'Wednesday': 'miercoles',
            'Thursday': 'jueves',
            'Friday': 'viernes',
            'Saturday': 'sabado',
            'Sunday': 'domingo'
        }.get(nombre_dia, nombre_dia)
        es_festivo = fecha_obj in co_holidays or nombre_dia_es == 'domingo'
        
        if es_festivo:
            return JsonResponse({'disponibles': [], 'festivo': True})
        
        # Obtener información de la reserva
        negocio = reserva.peluquero
        profesional = reserva.profesional
        duracion = reserva.servicio.duracion if reserva.servicio else 30
        
        # Buscar horario del profesional para ese día
        horario_prof = HorarioProfesional.objects.filter(
            profesional=profesional, 
            dia_semana=nombre_dia_es, 
            disponible=True
        ).first()
        
        if not horario_prof:
            return JsonResponse({'disponibles': [], 'festivo': False})
        
        inicio = horario_prof.hora_inicio
        fin = horario_prof.hora_fin
        
        # Obtener reservas existentes para este profesional, negocio y día (excluyendo la reserva actual)
        reservas = Reserva.objects.filter(
            peluquero=negocio,
            profesional=profesional,
            fecha=fecha_obj,
            estado__in=['pendiente', 'confirmado']
        ).exclude(id=reserva.id).values_list('hora_inicio', 'hora_fin')
        
        # Generar slots
        horarios_disponibles = []
        inicio_minutos = inicio.hour * 60 + inicio.minute
        fin_minutos = fin.hour * 60 + fin.minute
        tiempo_actual = inicio_minutos
        
        while tiempo_actual + duracion <= fin_minutos:
            hora_inicio = time(tiempo_actual // 60, tiempo_actual % 60)
            hora_fin = time((tiempo_actual + duracion) // 60, (tiempo_actual + duracion) % 60)
            
            # Verificar si este slot está ocupado
            ocupado = False
            for reserva_inicio, reserva_fin in reservas:
                if not (hora_fin <= reserva_inicio or hora_inicio >= reserva_fin):
                    ocupado = True
                    break
            
            if not ocupado:
                horarios_disponibles.append({
                    'inicio': hora_inicio.strftime('%H:%M'),
                    'fin': hora_fin.strftime('%H:%M'),
                    'duracion': duracion
                })
            
            tiempo_actual += duracion
        
        return JsonResponse({
            'disponibles': horarios_disponibles,
            'festivo': False
        })
        
    except Exception as e:
        logger.error(f"Error en horarios_disponibles_reagendar: {str(e)}")
        return JsonResponse({'error': 'Error interno del servidor'}, status=500)

@login_required
def mis_reservas(request):
    """Vista para que los clientes vean sus reservas"""
    try:
        # Procesar reservas pasadas automáticamente
        from .utils import procesar_reservas_pasadas, obtener_reservas_activas, obtener_reservas_historial
        
        # Procesar reservas pasadas
        reservas_completadas_auto = procesar_reservas_pasadas()
        if reservas_completadas_auto > 0:
            messages.info(request, f'Se han completado automáticamente {reservas_completadas_auto} reservas pasadas.')
        
        # Obtener reservas usando las funciones utilitarias
        reservas_activas = obtener_reservas_activas(request.user)
        reservas_historial = obtener_reservas_historial(request.user)
        
        # Separar por tipo para compatibilidad con el template
        reservas_pendientes = reservas_activas.filter(estado='pendiente')
        reservas_confirmadas = reservas_activas.filter(estado='confirmado')
        reservas_completadas = reservas_historial.filter(estado='completado')
        reservas_canceladas = reservas_historial.filter(estado='cancelado')
        reservas_inasistencias = reservas_historial.filter(estado='inasistencia')
        
        context = {
            'reservas_pendientes': reservas_pendientes,
            'reservas_confirmadas': reservas_confirmadas,
            'reservas_completadas': reservas_completadas,
            'reservas_canceladas': reservas_canceladas,
            'reservas_inasistencias': reservas_inasistencias,
            'total_reservas': reservas_activas.count() + reservas_historial.count(),
        }
        
        return render(request, 'clientes/mis_reservas.html', context)
        
    except Exception as e:
        logger.error(f"Error obteniendo reservas del usuario {request.user.username}: {str(e)}")
        messages.error(request, 'Error al cargar tus reservas.')
        return render(request, 'clientes/mis_reservas.html', {
            'reservas_pendientes': [],
            'reservas_confirmadas': [],
            'reservas_completadas': [],
            'reservas_canceladas': [],
            'reservas_inasistencias': [],
            'total_reservas': 0,
        })

@login_required
def dashboard_cliente(request):
    """Dashboard principal del cliente — optimizado para escala (O(1) queries)"""
    from django.core.paginator import Paginator

    query = request.GET.get('q', '').strip()
    page_number = request.GET.get('page', 1)
    PER_PAGE = 16

    # Una sola query con anotaciones: evita el bucle N+1
    negocios_qs = (
        Negocio.objects
        .filter(activo=True)
        .annotate(
            cal_promedio=models.Avg('calificaciones__puntaje'),
            cal_cantidad=Count('calificaciones', distinct=True),
        )
        .only('id', 'nombre', 'direccion', 'ciudad', 'barrio', 'logo', 'portada')
        .order_by('-cal_cantidad', 'nombre')
    )

    if query:
        negocios_qs = negocios_qs.filter(
            Q(nombre__icontains=query) |
            Q(direccion__icontains=query) |
            Q(
                id__in=Matriculacion.objects
                .filter(estado='aprobada', profesional__nombre_completo__icontains=query)
                .values('negocio_id')
            )
        ).distinct()

    paginator = Paginator(negocios_qs, PER_PAGE)
    page_obj = paginator.get_page(page_number)

    negocios_info = [
        {
            'negocio': n,
            'calificacion_promedio': round(n.cal_promedio or 0, 1),
            'calificacion_cantidad': n.cal_cantidad or 0,
        }
        for n in page_obj
    ]

    # Sidebar — usuario específico, queries acotadas
    reservas_usuario = (
        Reserva.objects
        .filter(cliente=request.user)
        .select_related('peluquero')
        .order_by('-creado_en')[:5]
    )
    calificaciones_usuario = (
        Calificacion.objects
        .filter(cliente=request.user)
        .select_related('profesional', 'negocio')
        .order_by('-fecha_calificacion')[:5]
    )

    # Stats del usuario en una sola query agregada
    stats = Reserva.objects.filter(cliente=request.user).aggregate(
        total=Count('id'),
        pendientes=Count('id', filter=Q(estado='pendiente')),
        completadas=Count('id', filter=Q(estado='completado')),
    )

    context = {
        'negocios_info': negocios_info,
        'page_obj': page_obj,
        'paginator': paginator,
        'reservas_usuario': reservas_usuario,
        'calificaciones_usuario': calificaciones_usuario,
        'query': query,
        'total_reservas': stats['total'],
        'reservas_pendientes': stats['pendientes'],
        'reservas_completadas': stats['completadas'],
    }

    return render(request, 'clientes/dashboard.html', context)

def reservar_negocio(request, negocio_id):
    """
    Vista pública de reserva: cualquier persona puede VER servicios y precios.
    Solo se requiere autenticación al CONFIRMAR la reserva (POST).
    """
    logger.info(f"=== INICIO reservar_negocio ===")
    logger.info(f"Usuario: {request.user} ({getattr(request.user, 'tipo', 'anon')})")
    logger.info(f"Usuario autenticado: {request.user.is_authenticated}")
    logger.info(f"Método HTTP: {request.method}")
    logger.info(f"Negocio ID: {negocio_id}")
    
    negocio = get_object_or_404(Negocio, id=negocio_id, activo=True)
    logger.info(f"Negocio encontrado: {negocio.nombre}")
    
    servicios = negocio.servicios_negocio.select_related('servicio').all()
    logger.info(f"Servicios encontrados: {servicios.count()}")
    
    profesional_id = request.GET.get('profesional')
    servicio_id = request.GET.get('servicio')
    fecha_preseleccionada = request.GET.get('fecha')
    profesional_preseleccionado = None
    if profesional_id:
        try:
            profesional_preseleccionado = Profesional.objects.get(id=profesional_id)
            logger.info(f"Profesional preseleccionado: {profesional_preseleccionado.nombre_completo}")
        except Profesional.DoesNotExist:
            profesional_preseleccionado = None
            logger.warning(f"Profesional con ID {profesional_id} no encontrado")
    initial = {}
    if servicio_id:
        initial['servicio'] = servicio_id
        logger.info(f"Servicio preseleccionado: {servicio_id}")
    
    # Manejar GET request - mostrar formulario
    if request.method == 'GET':
        logger.info("Procesando GET request - mostrando formulario")
        
        # Debug del negocio
        logger.info(f"Negocio ID: {negocio.id}, Nombre: {negocio.nombre}")
        logger.info(f"Servicios del negocio: {[s.servicio.nombre for s in servicios]}")
        
        try:
            form = ReservaNegocioForm(negocio=negocio, profesional_preseleccionado=profesional_preseleccionado, initial=initial)
            logger.info("Formulario creado exitosamente")
            logger.info(f"Campos del formulario: {list(form.fields.keys())}")
        except Exception as e:
            logger.error(f"Error creando formulario: {e}")
            logger.error(f"Tipo de error: {type(e).__name__}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            form = None
        
        # Simplificar disponibilidad temporalmente
        disponibilidad = {}
        for i in range(7):  # Solo próximos 7 días para debug
            from datetime import date, timedelta
            dia = date.today() + timedelta(days=i)
            disponibilidad[dia.strftime('%Y-%m-%d')] = True
        
        logger.info(f"Renderizando template con {len(disponibilidad)} días de disponibilidad")
        logger.info("=== FIN reservar_negocio (GET) ===")
        return render(request, 'clientes/reservar_negocio.html', {
            'negocio': negocio,
            'servicios': servicios,
            'form': form,
            'profesional_preseleccionado': profesional_preseleccionado,
            'fecha_preseleccionada': fecha_preseleccionada,
            'disponibilidad': disponibilidad,
            'user_authenticated': request.user.is_authenticated,
        })
    
    # Manejar POST request - procesar formulario
    if request.method == 'POST':
        logger.info(f"POST recibido en reservar_negocio - negocio_id: {negocio_id}")
        form = ReservaNegocioForm(request.POST, negocio=negocio, profesional_preseleccionado=profesional_preseleccionado)
        logger.info(f"Formulario creado - válido: {form.is_valid()}")
        
        if form.is_valid():
            try:
                servicio = form.cleaned_data.get('servicio')
                profesional = form.cleaned_data.get('profesional')
                fecha = form.cleaned_data.get('fecha')
                hora_inicio = form.cleaned_data.get('hora_inicio')
                notas = form.cleaned_data.get('notas', '')
                logger.info(f"Datos del formulario - servicio: {servicio}, profesional: {profesional}, fecha: {fecha}, hora_inicio: {hora_inicio}")
                
                # Validar que todos los campos requeridos estén presentes
                if not fecha or not hora_inicio:
                    logger.error("Fecha o hora_inicio faltantes")
                    form.add_error(None, "Debes seleccionar una fecha y un horario para tu reserva.")
                    return render(request, 'clientes/reservar_negocio.html', {
                        'negocio': negocio,
                        'servicios': servicios,
                        'form': form,
                        'profesional_preseleccionado': profesional_preseleccionado,
                        'fecha_preseleccionada': fecha_preseleccionada,
                        'disponibilidad': {},
                    })
                
                # Validar que el profesional esté disponible en ese horario
                from profesionales.models import HorarioProfesional
                import holidays
                co_holidays = holidays.CountryHoliday('CO')
                nombre_dia = fecha.strftime('%A')
                nombre_dia_es = {
                    'Monday': 'lunes',
                    'Tuesday': 'martes',
                    'Wednesday': 'miercoles',
                    'Thursday': 'jueves',
                    'Friday': 'viernes',
                    'Saturday': 'sabado',
                    'Sunday': 'domingo'
                }.get(nombre_dia, nombre_dia)
                # Solo considerar festivos de Colombia, NO todos los domingos automáticamente
                es_festivo = fecha in co_holidays
                if es_festivo:
                    form.add_error(None, "El profesional no trabaja en días festivos. Por favor, elige otra fecha.")
                    return render(request, 'clientes/reservar_negocio.html', {
                        'negocio': negocio,
                        'servicios': servicios,
                        'form': form,
                        'profesional_preseleccionado': profesional_preseleccionado,
                        'fecha_preseleccionada': fecha_preseleccionada,
                        'disponibilidad': {},
                    })
                
                # Verificar si el profesional tiene horario para ese día
                horario_prof = HorarioProfesional.objects.filter(profesional=profesional, dia_semana=nombre_dia_es, disponible=True).first()
                if not horario_prof:
                    form.add_error(None, "El profesional no trabaja ese día. Por favor, elige otra fecha.")
                    return render(request, 'clientes/reservar_negocio.html', {
                        'negocio': negocio,
                        'servicios': servicios,
                        'form': form,
                        'profesional_preseleccionado': profesional_preseleccionado,
                        'fecha_preseleccionada': fecha_preseleccionada,
                        'disponibilidad': {},
                    })
                
                # Validar que el horario no esté ocupado
                reservas = Reserva.objects.filter(
                    peluquero=negocio,
                    profesional=profesional,
                    fecha=fecha,
                    estado__in=['pendiente', 'confirmado']
                ).exclude(estado='cancelado').values_list('hora_inicio', 'hora_fin')
                
                duracion = servicio.duracion if servicio and servicio.duracion is not None else 30
                from datetime import datetime, timedelta
                hora_inicio_dt = datetime.combine(fecha, hora_inicio)
                hora_fin_dt = hora_inicio_dt + timedelta(minutes=duracion)
                hora_fin = hora_fin_dt.time()
                
                for reserva_inicio, reserva_fin in reservas:
                    if not (hora_fin <= reserva_inicio or hora_inicio >= reserva_fin):
                        form.add_error(None, "¡Ups! Alguien más ya reservó ese horario. Por favor, elige otro disponible.")
                        return render(request, 'clientes/reservar_negocio.html', {
                            'negocio': negocio,
                            'servicios': servicios,
                            'form': form,
                            'profesional_preseleccionado': profesional_preseleccionado,
                            'fecha_preseleccionada': fecha_preseleccionada,
                            'disponibilidad': {},
                        })
                
                # Crear la reserva
                # ── Gate de autenticación: solo para CONFIRMAR la reserva ──
                if not request.user.is_authenticated:
                    logger.info("Usuario anónimo intentó reservar, redirigiendo a login")
                    from django.contrib.auth import redirect_to_login
                    return redirect_to_login(request.get_full_path())
                
                reserva = Reserva(
                    cliente=request.user,
                    peluquero=negocio,
                    fecha=fecha,
                    hora_inicio=hora_inicio,
                    hora_fin=hora_fin,
                    estado='pendiente'
                )
                
                # Agregar campos opcionales solo si existen
                if profesional:
                    reserva.profesional = profesional
                if servicio:
                    reserva.servicio = servicio
                if notas:
                    reserva.notas = notas
                
                logger.info(f"Intentando guardar reserva con datos: cliente={reserva.cliente.id}, peluquero={reserva.peluquero.id}, profesional={reserva.profesional.id if reserva.profesional else None}, servicio={reserva.servicio.id if reserva.servicio else None}")
                
                reserva.save()
                
                # Crear notificación para el profesional si existe
                if reserva.profesional:
                    from profesionales.models import Notificacion
                    Notificacion.objects.create(
                        profesional=reserva.profesional,
                        tipo='reserva',
                        titulo='Nueva Reserva',
                        mensaje=f'Nueva reserva pendiente para el {reserva.fecha} a las {reserva.hora_inicio} con {reserva.cliente.username}.',
                        url_relacionada='/profesionales/panel/'
                    )
                
                logger.info(f"Reserva creada exitosamente: {reserva.id}")
                messages.success(request, '¡Reserva realizada con éxito!')
                return redirect('clientes:reserva_exitosa', reserva_id=reserva.id)
                
            except Exception as e:
                logger.error(f"Error guardando reserva: {str(e)}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                messages.error(request, 'Error al guardar la reserva. Por favor, intenta nuevamente.')
                # Renderizar formulario con error
                return render(request, 'clientes/reservar_negocio.html', {
                    'negocio': negocio,
                    'servicios': servicios,
                    'form': form,
                    'profesional_preseleccionado': profesional_preseleccionado,
                    'fecha_preseleccionada': fecha_preseleccionada,
                    'disponibilidad': {},
                })
        else:
            logger.warning(f"Formulario inválido - errores: {form.errors}")
            logger.warning(f"Datos POST: {request.POST}")
            messages.error(request, 'Por favor corrige los errores en el formulario.')
            # Renderizar formulario con errores
            return render(request, 'clientes/reservar_negocio.html', {
                'negocio': negocio,
                'servicios': servicios,
                'form': form,
                'profesional_preseleccionado': profesional_preseleccionado,
                'fecha_preseleccionada': fecha_preseleccionada,
                'disponibilidad': {},
            })
    
    # Si no es POST, mostrar formulario normal
    form = ReservaNegocioForm(negocio=negocio, profesional_preseleccionado=profesional_preseleccionado, initial=initial)

    # --- NUEVO: calcular disponibilidad diaria para el mes visible si hay profesional seleccionado ---
    from datetime import date, timedelta
    import calendar
    disponibilidad = {}
    hoy = date.today()
    mes = hoy.month
    anio = hoy.year
    # Si hay fecha preseleccionada, usar ese mes
    if fecha_preseleccionada:
        try:
            partes = fecha_preseleccionada.split('-')
            anio = int(partes[0])
            mes = int(partes[1])
        except Exception:
            pass
    # Calcular primer y último día del mes
    primer_dia = date(anio, mes, 1)
    ultimo_dia = date(anio, mes, calendar.monthrange(anio, mes)[1])
    dias_mes = (ultimo_dia - primer_dia).days + 1
    profesional = profesional_preseleccionado
    servicio = None
    if servicio_id:
        try:
            servicio = negocio.servicios_negocio.get(id=servicio_id)
        except Exception:
            servicio = None
    for i in range(dias_mes):
        dia = primer_dia + timedelta(days=i)
        disponible = False
        if profesional and servicio:
            # Verificar si es festivo/domingo
            import holidays
            co_holidays = holidays.CountryHoliday('CO')
            nombre_dia = dia.strftime('%A')
            nombre_dia_es = {
                'Monday': 'lunes',
                'Tuesday': 'martes',
                'Wednesday': 'miercoles',
                'Thursday': 'jueves',
                'Friday': 'viernes',
                'Saturday': 'sabado',
                'Sunday': 'domingo'
            }.get(nombre_dia, nombre_dia)
            es_festivo = dia in co_holidays or nombre_dia_es == 'domingo'
            if not es_festivo:
                from profesionales.models import HorarioProfesional
                horario_prof = HorarioProfesional.objects.filter(profesional=profesional, dia_semana=nombre_dia_es, disponible=True).first()
                if horario_prof:
                    # Verificar si hay al menos un slot disponible
                    inicio = horario_prof.hora_inicio
                    fin = horario_prof.hora_fin
                    duracion = servicio.duracion or 30
                    inicio_minutos = inicio.hour * 60 + inicio.minute
                    fin_minutos = fin.hour * 60 + fin.minute
                    tiempo_actual = inicio_minutos
                    reservas = Reserva.objects.filter(
                        peluquero=negocio,
                        profesional=profesional,
                        fecha=dia,
                        estado__in=['pendiente', 'confirmado']
                    ).values_list('hora_inicio', 'hora_fin')
                    while tiempo_actual + duracion <= fin_minutos:
                        hora_inicio = time(tiempo_actual // 60, tiempo_actual % 60)
                        hora_fin = time((tiempo_actual + duracion) // 60, (tiempo_actual + duracion) % 60)
                        ocupado = False
                        for reserva_inicio, reserva_fin in reservas:
                            if not (hora_fin <= reserva_inicio or hora_inicio >= reserva_fin):
                                ocupado = True
                                break
                        if not ocupado:
                            disponible = True
                            break
                        tiempo_actual += duracion
        disponibilidad[dia.strftime('%Y-%m-%d')] = disponible
    # --- FIN NUEVO ---

    return render(request, 'clientes/reservar_negocio.html', {
        'negocio': negocio,
        'servicios': servicios,
        'form': form,
        'profesional_preseleccionado': profesional_preseleccionado,
        'fecha_preseleccionada': fecha_preseleccionada,
        'disponibilidad': disponibilidad,  # <-- pasar al contexto
    })

@login_required
def notificaciones_cliente(request):
    notificaciones = NotificacionCliente.objects.filter(cliente=request.user).order_by('-fecha_creacion')
    return render(request, 'clientes/notificaciones.html', {'notificaciones': notificaciones})

@require_POST
@login_required
@ratelimit(key='ip', rate='5/m', method=['POST'])
def eliminar_notificacion_cliente(request, notificacion_id):
    try:
        noti = NotificacionCliente.objects.get(id=notificacion_id, cliente=request.user)
        noti.delete()
        return JsonResponse({'ok': True})
    except NotificacionCliente.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'No encontrada'}, status=404)

@login_required
def confirmar_reserva(request, reserva_id):
    """
    Vista para confirmar una reserva pendiente
    """
    reserva = get_object_or_404(Reserva, id=reserva_id)
    
    # Verificar permisos
    if request.user.tipo == 'negocio':
        # El negocio puede confirmar reservas de sus negocios
        if not reserva.peluquero.propietario == request.user:
            messages.error(request, 'No tienes permisos para confirmar esta reserva.')
            return redirect('clientes:mis_reservas')
    elif request.user.tipo == 'cliente':
        # El cliente solo puede confirmar sus propias reservas
        if not reserva.cliente == request.user:
            messages.error(request, 'No tienes permisos para confirmar esta reserva.')
            return redirect('clientes:mis_reservas')
    else:
        messages.error(request, 'No tienes permisos para confirmar reservas.')
        return redirect('clientes:mis_reservas')
    
    if request.method == 'POST':
        notas_adicionales = request.POST.get('notas_adicionales', '')
        
        try:
            reserva.confirmar(notas_adicionales)
            messages.success(request, 'Reserva confirmada exitosamente.')
        except ValidationError as e:
            messages.error(request, str(e))
        
        return redirect('clientes:mis_reservas')
    
    context = {
        'reserva': reserva,
        'accion': 'confirmar'
    }
    return render(request, 'clientes/confirmar_reserva.html', context)

@login_required
def cancelar_reserva(request, reserva_id):
    """
    Vista para cancelar una reserva
    """
    logger.info(f"=== INICIO cancelar_reserva ===")
    logger.info(f"Reserva ID: {reserva_id}")
    logger.info(f"Usuario: {request.user.username} ({request.user.tipo})")
    logger.info(f"Método HTTP: {request.method}")
    logger.info(f"POST data: {request.POST}")
    logger.info(f"GET data: {request.GET}")
    
    try:
        reserva = get_object_or_404(Reserva, id=reserva_id)
        logger.info(f"Reserva encontrada: {reserva.id}, estado: {reserva.estado}, cliente: {reserva.cliente.username}")
        
        # Verificar permisos
        if request.user.tipo == 'negocio':
            # El negocio puede cancelar reservas de sus negocios
            if not reserva.peluquero.propietario == request.user:
                logger.warning(f"Usuario {request.user.username} intentó cancelar reserva {reserva_id} sin permisos (negocio)")
                messages.error(request, 'No tienes permisos para cancelar esta reserva.')
                return redirect('clientes:mis_reservas')
        elif request.user.tipo == 'cliente':
            # El cliente solo puede cancelar sus propias reservas
            if not reserva.cliente == request.user:
                logger.warning(f"Usuario {request.user.username} intentó cancelar reserva {reserva_id} sin permisos (cliente)")
                messages.error(request, 'No tienes permisos para cancelar esta reserva.')
                return redirect('clientes:mis_reservas')
        else:
            logger.warning(f"Usuario {request.user.username} de tipo {request.user.tipo} intentó cancelar reserva {reserva_id}")
            messages.error(request, 'No tienes permisos para cancelar reservas.')
            return redirect('clientes:mis_reservas')
        
        if request.method == 'POST':
            motivo = request.POST.get('motivo', '')
            cancelado_por = request.user.tipo
            
            logger.info(f"Cancelando reserva {reserva_id} con motivo: '{motivo}', cancelado por: {cancelado_por}")
            
            try:
                reserva.cancelar(motivo, cancelado_por)
                logger.info(f"Reserva {reserva_id} cancelada exitosamente")
                
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': True,
                        'message': 'Reserva cancelada exitosamente.'
                    })
                else:
                    messages.success(request, 'Reserva cancelada exitosamente.')
                    return redirect('clientes:mis_reservas')
                    
            except ValidationError as e:
                error_msg = str(e)
                logger.error(f"Error de validación al cancelar reserva {reserva_id}: {error_msg}")
                
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': False,
                        'message': error_msg
                    })
                else:
                    messages.error(request, error_msg)
                    context = {
                        'reserva': reserva,
                        'accion': 'cancelar'
                    }
                    return render(request, 'clientes/cancelar_reserva.html', context)
            except Exception as e:
                logger.error(f"Error inesperado al cancelar reserva {reserva_id}: {str(e)}")
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': False,
                        'message': f'Error al cancelar la reserva: {str(e)}'
                    })
                else:
                    messages.error(request, f'Error al cancelar la reserva: {str(e)}')
        
        context = {
            'reserva': reserva,
            'accion': 'cancelar'
        }
        logger.info(f"Renderizando template para reserva {reserva_id}")
        return render(request, 'clientes/cancelar_reserva.html', context)
        
    except Exception as e:
        logger.error(f"Error general en cancelar_reserva para reserva {reserva_id}: {str(e)}")
        messages.error(request, 'Error al procesar la solicitud de cancelación.')
        return redirect('clientes:mis_reservas')

@login_required
def completar_reserva(request, reserva_id):
    """
    Vista para marcar una reserva como completada
    """
    reserva = get_object_or_404(Reserva, id=reserva_id)
    
    # Verificar permisos - solo negocios pueden completar reservas
    if request.user.tipo != 'negocio':
        messages.error(request, 'Solo los negocios pueden marcar reservas como completadas.')
        return redirect('clientes:mis_reservas')
    
    if not reserva.peluquero.propietario == request.user:
        messages.error(request, 'No tienes permisos para completar esta reserva.')
        return redirect('clientes:mis_reservas')
    
    if request.method == 'POST':
        notas_adicionales = request.POST.get('notas_adicionales', '')
        
        try:
            reserva.completar(notas_adicionales)
            messages.success(request, 'Reserva marcada como completada exitosamente.')
        except ValidationError as e:
            messages.error(request, str(e))
        
        return redirect('clientes:mis_reservas')
    
    context = {
        'reserva': reserva,
        'accion': 'completar'
    }
    return render(request, 'clientes/completar_reserva.html', context)

@login_required
def reagendar_reserva(request, reserva_id):
    """
    Vista para reagendar una reserva
    """
    reserva = get_object_or_404(Reserva, id=reserva_id)
    
    # Verificar permisos
    if request.user.tipo == 'negocio':
        # El negocio puede reagendar reservas de sus negocios
        if not reserva.peluquero.propietario == request.user:
            messages.error(request, 'No tienes permisos para reagendar esta reserva.')
            return redirect('clientes:mis_reservas')
    elif request.user.tipo == 'cliente':
        # El cliente solo puede reagendar sus propias reservas
        if not reserva.cliente == request.user:
            messages.error(request, 'No tienes permisos para reagendar esta reserva.')
            return redirect('clientes:mis_reservas')
    else:
        messages.error(request, 'No tienes permisos para reagendar reservas.')
        return redirect('clientes:mis_reservas')
    
    if request.method == 'POST':
        nueva_fecha = request.POST.get('nueva_fecha')
        nueva_hora_inicio = request.POST.get('nueva_hora_inicio')
        nueva_hora_fin = request.POST.get('nueva_hora_fin')
        motivo = request.POST.get('motivo', '')
        
        try:
            from datetime import datetime
            nueva_fecha = datetime.strptime(nueva_fecha, '%Y-%m-%d').date()
            nueva_hora_inicio = datetime.strptime(nueva_hora_inicio, '%H:%M').time()
            nueva_hora_fin = datetime.strptime(nueva_hora_fin, '%H:%M').time()
            
            reserva.reagendar(nueva_fecha, nueva_hora_inicio, nueva_hora_fin, motivo)
            messages.success(request, 'Reserva reagendada exitosamente.')
        except (ValidationError, ValueError) as e:
            messages.error(request, f'Error al reagendar: {str(e)}')
        
        return redirect('clientes:mis_reservas')
    
    context = {
        'reserva': reserva,
        'accion': 'reagendar'
    }
    return render(request, 'clientes/reagendar_reserva.html', context)

@login_required
def crear_calificacion(request, negocio_id, profesional_id):
    """Vista para crear una calificación"""
    negocio = get_object_or_404(Negocio, id=negocio_id)
    profesional = None
    if int(profesional_id) != 0:
        profesional = get_object_or_404(Profesional, id=profesional_id)
    # Si es comentario solo al negocio, no exigir reserva previa con profesional
    if profesional:
        reservas_completadas = Reserva.objects.filter(
            cliente=request.user,
            peluquero=negocio,
            profesional=profesional,
            estado='completado'
        )
        if not reservas_completadas.exists():
            messages.error(request, 'Solo puedes calificar a profesionales con los que hayas completado una reserva.')
            return redirect('negocios:detalle_negocio', negocio_id=negocio_id)
        # Verificar que no haya calificado ya a ese profesional en ese negocio
        calificacion_existente = Calificacion.objects.filter(
            cliente=request.user,
            negocio=negocio,
            profesional=profesional
        ).first()
        if calificacion_existente:
            messages.info(request, 'Ya has calificado a este profesional en este negocio.')
            return redirect('negocios:detalle_negocio', negocio_id=negocio_id)
    else:
        # Solo negocio: verificar que no haya calificado ya solo al negocio
        calificacion_existente = Calificacion.objects.filter(
            cliente=request.user,
            negocio=negocio,
            profesional__isnull=True
        ).first()
        if calificacion_existente:
            messages.info(request, 'Ya has dejado un comentario para este negocio.')
            return redirect('clientes:detalle_peluquero', pk=negocio_id)
    if request.method == 'POST':
        form = CalificacionForm(request.POST)
        if form.is_valid():
            calificacion = form.save(commit=False)
            calificacion.cliente = request.user
            calificacion.negocio = negocio
            calificacion.profesional = profesional
            calificacion.save()
            # Notificaciones solo si hay profesional
            if profesional:
                Notificacion.objects.create(
                    destinatario=profesional.usuario,
                    tipo='calificacion',
                    titulo=f'Nueva calificación de {request.user.username}',
                    mensaje=f'Has recibido una calificación de {calificacion.puntaje}/5 estrellas en {negocio.nombre}',
                    url_relacionada=f'/negocios/detalle-negocio/{negocio.id}/',
                )
                if negocio.usuario != profesional.usuario:
                    Notificacion.objects.create(
                        destinatario=negocio.usuario,
                        tipo='calificacion',
                        titulo=f'Nueva calificación en {negocio.nombre}',
                        mensaje=f'{request.user.username} calificó a {profesional.nombre_completo} con {calificacion.puntaje}/5 estrellas',
                        url_relacionada=f'/negocios/detalle-negocio/{negocio.id}/',
                    )
            messages.success(request, '¡Gracias por tu comentario!')
            return redirect('clientes:detalle_peluquero', pk=negocio_id)
    else:
        form = CalificacionForm()
    context = {
        'form': form,
        'negocio': negocio,
        'profesional': profesional,
    }
    return render(request, 'clientes/crear_calificacion.html', context)

@login_required
def editar_calificacion(request, calificacion_id):
    """Vista para editar una calificación existente"""
    calificacion = get_object_or_404(Calificacion, id=calificacion_id, cliente=request.user)
    
    if request.method == 'POST':
        form = CalificacionForm(request.POST, instance=calificacion)
        if form.is_valid():
            form.save()
            messages.success(request, 'Calificación actualizada correctamente.')
            return redirect('negocios:detalle_negocio', negocio_id=calificacion.negocio.id)
    else:
        form = CalificacionForm(instance=calificacion)
    
    context = {
        'form': form,
        'calificacion': calificacion,
        'negocio': calificacion.negocio,
        'profesional': calificacion.profesional,
    }
    return render(request, 'clientes/editar_calificacion.html', context)

@login_required
def eliminar_calificacion(request, calificacion_id):
    """Vista para eliminar una calificación"""
    calificacion = get_object_or_404(Calificacion, id=calificacion_id, cliente=request.user)
    
    if request.method == 'POST':
        negocio_id = calificacion.negocio.id
        calificacion.delete()
        messages.success(request, 'Calificación eliminada correctamente.')
        return redirect('negocios:detalle_negocio', negocio_id=negocio_id)
    
    context = {
        'calificacion': calificacion,
    }
    return render(request, 'clientes/eliminar_calificacion.html', context)

def proximamente_app(request):
    return render(request, 'clientes/proximamente_app.html')

def autocompletar_servicios(request):
    """Endpoint para autocompletar servicios según los negocios activos y el texto ingresado, filtrando por ubicación si se provee lat/lon."""
    q = request.GET.get('q', '').strip()
    lat = request.GET.get('lat')
    lon = request.GET.get('lon')
    radio_metros = 500
    negocios_qs = Negocio.objects.filter(activo=True, latitud__isnull=False, longitud__isnull=False)
    if lat and lon:
        try:
            lat = float(lat)
            lon = float(lon)
            def haversine(lat1, lon1, lat2, lon2):
                # Radio de la tierra en km
                R = 6371.0
                dlat = radians(lat2 - lat1)
                dlon = radians(lon2 - lon1)
                a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
                c = 2 * asin(sqrt(a))
                return R * c * 1000  # metros
            negocios_qs = [n for n in negocios_qs if haversine(lat, lon, n.latitud, n.longitud) <= radio_metros]
        except Exception:
            negocios_qs = []
    servicios_qs = Servicio.objects.filter(servicionegocio__negocio__in=negocios_qs).distinct()
    if q:
        servicios_qs = servicios_qs.filter(nombre__icontains=q)
    servicios = list(servicios_qs.values_list('nombre', flat=True))
    return JsonResponse({'servicios': servicios})

@require_GET
def obtener_todos_servicios(request):
    """API para obtener todos los servicios disponibles en la base de datos"""
    try:
        servicios = Servicio.objects.all().order_by('nombre')
        
        servicios_list = []
        for servicio in servicios:
            servicios_list.append({
                'id': servicio.id,
                'nombre': servicio.nombre,
                'descripcion': servicio.descripcion
            })
        
        return JsonResponse({
            'servicios': servicios_list,
            'total': len(servicios_list)
        })
    except Exception as e:
        logger.error(f"Error obteniendo todos los servicios: {str(e)}")
        return JsonResponse({'servicios': [], 'total': 0})

@require_GET
def autocompletar_servicios_mejorado(request):
    """API para autocompletar servicios con máximo 4 resultados"""
    try:
        query = request.GET.get('q', '').strip()
        
        if not query or len(query) < 1:
            return JsonResponse({'sugerencias': []})
        
        # Buscar servicios que coincidan con la consulta (máximo 4)
        servicios = Servicio.objects.filter(
            nombre__icontains=query
        ).order_by('nombre')[:4]
        
        sugerencias = []
        for servicio in servicios:
            sugerencias.append({
                'id': servicio.id,
                'nombre': servicio.nombre,
                'descripcion': servicio.descripcion
            })
        
        return JsonResponse({'sugerencias': sugerencias})
    except Exception as e:
        logger.error(f"Error en autocompletar servicios mejorado: {str(e)}")
        return JsonResponse({'sugerencias': []})

@require_GET
def negocios_cercanos(request):
    from math import radians, cos, sin, asin, sqrt
    lat = request.GET.get('lat')
    lon = request.GET.get('lon')
    if not lat or not lon:
        return JsonResponse({'negocios': []})
    try:
        lat = float(lat)
        lon = float(lon)
    except Exception:
        return JsonResponse({'negocios': []})
    def haversine(lat1, lon1, lat2, lon2):
        R = 6371.0
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
        c = 2 * asin(sqrt(a))
        return R * c * 1000  # metros
    negocios = []
    for n in Negocio.objects.filter(activo=True, latitud__isnull=False, longitud__isnull=False):
        distancia = haversine(lat, lon, n.latitud, n.longitud)
        negocios.append({
            'id': n.id,
            'nombre': n.nombre,
            'direccion': n.direccion,
            'latitud': n.latitud,
            'longitud': n.longitud,
            'distancia': distancia,
            'servicios': list(n.servicios_negocio.values_list('servicio__nombre', flat=True)),
        })
    negocios = sorted(negocios, key=lambda x: x['distancia'])[:5]
    return JsonResponse({'negocios': negocios})

@require_GET
def autocompletar_negocios(request):
    try:
        query = request.GET.get('q', '').strip()
        if len(query) < 2:
            return JsonResponse({'sugerencias': []})
        
        # Buscar negocios por nombre, dirección o servicio (máximo 6 resultados)
        negocios = Negocio.objects.filter(
            Q(nombre__icontains=query) | 
            Q(direccion__icontains=query) |
            Q(servicios_negocio__servicio__nombre__icontains=query),
            activo=True
        ).distinct()[:6]
        
        sugerencias = []
        for negocio in negocios:
            calificaciones = Calificacion.objects.filter(negocio=negocio)
            promedio = calificaciones.aggregate(avg=models.Avg('puntaje'))['avg'] or 0
            cantidad = calificaciones.count()
            logo_url = negocio.logo.url if negocio.logo else ''
            sugerencias.append({
                'id': negocio.id,
                'nombre': negocio.nombre,
                'direccion': negocio.direccion,
                'ciudad': negocio.ciudad,
                'barrio': negocio.barrio,
                'logo_url': logo_url,
                'calificacion': round(promedio, 1),
                'calificacion_cantidad': cantidad,
            })
        
        return JsonResponse({'sugerencias': sugerencias})
    except Exception as e:
        logger.error(f"Error en autocompletar negocios: {str(e)}")
        return JsonResponse({'sugerencias': []})

def buscar_negocios(request):
    """
    Búsqueda inteligente y combinada de negocios:
    - Por nombre de negocio específico
    - Por servicio (todos los negocios que ofrezcan ese servicio)
    - Por ubicación (con coordenadas para distancia, sin coordenadas para texto)
    - Combinaciones flexibles de todos los criterios
    """
    try:
        # Parámetros de búsqueda
        lat = request.GET.get('lat')
        lon = request.GET.get('lon')
        radio = request.GET.get('radio', '5000')  # Radio por defecto 5km para búsquedas combinadas
        servicio = request.GET.get('servicio', '').strip()
        negocio_nombre = request.GET.get('negocio', '').strip()
        ubicacion = request.GET.get('ubicacion', '').strip()
        
        # Query base
        queryset = Negocio.objects.filter(activo=True)
        
        # Función para calcular distancia
        def haversine(lat1, lon1, lat2, lon2):
            R = 6371  # Radio de la tierra en km
            lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
            c = 2 * asin(sqrt(a))
            return R * c
        
        # 1. BÚSQUEDA POR NOMBRE DE NEGOCIO (prioridad alta)
        if negocio_nombre:
            queryset = queryset.filter(
                Q(nombre__icontains=negocio_nombre) |
                Q(direccion__icontains=negocio_nombre)
            )
        
        # 2. BÚSQUEDA POR SERVICIO
        if servicio:
            queryset = queryset.filter(
                servicios__servicio__nombre__icontains=servicio
            ).distinct()
        
        # 3. BÚSQUEDA POR UBICACIÓN
        if ubicacion and not lat and not lon:
            # Búsqueda por texto (ciudad, barrio, dirección)
            queryset = queryset.filter(
                Q(ciudad__icontains=ubicacion) |
                Q(barrio__icontains=ubicacion) |
                Q(direccion__icontains=ubicacion)
            )
        
        # 4. BÚSQUEDA POR COORDENADAS (con distancia)
        if lat and lon:
            try:
                lat = float(lat)
                lon = float(lon)
                radio_km = float(radio) / 1000  # Convertir metros a km
                
                # Filtrar por distancia
                negocios_cercanos = []
                for neg in queryset:
                    if neg.latitud and neg.longitud:
                        distancia = haversine(lat, lon, neg.latitud, neg.longitud)
                        if distancia <= radio_km:
                            neg.distancia = distancia
                            negocios_cercanos.append(neg)
                
                # Ordenar por distancia si hay coordenadas
                negocios_cercanos.sort(key=lambda x: x.distancia)
                queryset = negocios_cercanos
                
            except (ValueError, TypeError) as e:
                logger.error(f"Error procesando coordenadas: {str(e)}")
                # Si hay error en coordenadas, continuar con búsqueda sin distancia
                pass
        
        # 5. ORDENAMIENTO INTELIGENTE
        if lat and lon:
            # Si hay coordenadas, ya está ordenado por distancia
            pass
        elif negocio_nombre:
            # Si buscó por nombre, ordenar por relevancia del nombre
            from django.db.models import Case, When, Value, IntegerField
            queryset = queryset.annotate(
                relevancia=Case(
                    When(nombre__icontains=negocio_nombre, then=Value(1)),
                    When(direccion__icontains=negocio_nombre, then=Value(2)),
                    default=Value(3),
                    output_field=IntegerField(),
                )
            ).order_by('relevancia', 'nombre')
        elif servicio:
            # Si buscó por servicio, ordenar alfabéticamente por nombre
            queryset = queryset.order_by('nombre')
        else:
            # Ordenamiento por defecto
            queryset = queryset.order_by('nombre')
        
        # Limitar resultados
        queryset = queryset[:50]
        
        # Preparar contexto con información detallada
        context = {
            'negocios': queryset,
            'total_resultados': len(queryset),
            'parametros_busqueda': {
                'lat': lat,
                'lon': lon,
                'radio': radio,
                'servicio': servicio,
                'negocio': negocio_nombre,
                'ubicacion': ubicacion
            },
            'tipo_busqueda': {
                'por_nombre': bool(negocio_nombre),
                'por_servicio': bool(servicio),
                'por_ubicacion': bool(ubicacion or (lat and lon)),
                'combinada': sum([bool(negocio_nombre), bool(servicio), bool(ubicacion or (lat and lon))]) > 1
            }
        }
        
        # Preparar datos para el mapa si hay resultados
        if queryset:
            negocios_mapa = []
            for negocio in queryset:
                profesionales_aceptados = [m.profesional for m in Matriculacion.objects.filter(negocio=negocio, estado='aprobada')]
                negocio_mapa = {
                    'id': negocio.id,
                    'nombre': negocio.nombre,
                    'direccion': negocio.direccion,
                    'latitud': negocio.latitud,
                    'longitud': negocio.longitud,
                    'url': f"/clientes/peluquero/{negocio.id}/",
                    'logo_url': negocio.logo.url if negocio.logo else '',
                    'profesionales': profesionales_aceptados,
                }
                if hasattr(negocio, 'distancia'):
                    negocio_mapa['distancia'] = round(negocio.distancia * 1000)  # Convertir a metros
                    negocio_mapa['distancia_texto'] = f"{round(negocio.distancia * 1000)}m"
                else:
                    negocio_mapa['distancia'] = None
                    negocio_mapa['distancia_texto'] = None
                negocios_mapa.append(negocio_mapa)
            context['negocios_mapa'] = negocios_mapa
        
        return render(request, 'clientes/lista_negocios.html', context)
        
    except Exception as e:
        logger.error(f"Error en búsqueda de negocios: {str(e)}")
        return render(request, 'clientes/lista_negocios.html', {
            'negocios': [],
            'total_resultados': 0,
            'error': 'Error en la búsqueda'
        })

@require_GET
def disponibilidad_dias(request):
    from datetime import date, timedelta
    from clientes.models import BloqueoCliente
    import calendar
    import holidays
    from profesionales.models import HorarioProfesional
    profesional_id = request.GET.get('profesional_id')
    servicio_id = request.GET.get('servicio_id')
    fecha_inicio_str = request.GET.get('fecha_inicio')
    fecha_fin_str = request.GET.get('fecha_fin')
    negocio_id = request.GET.get('negocio_id')
    disponibilidad = {}
    
    if not (profesional_id and servicio_id and negocio_id and fecha_inicio_str and fecha_fin_str):
        return JsonResponse({'disponibilidad': disponibilidad})
    
    try:
        negocio = Negocio.objects.get(id=negocio_id)
        profesional = Profesional.objects.get(id=profesional_id)
        servicio = negocio.servicios_negocio.get(id=servicio_id)
        fecha_inicio = date.fromisoformat(fecha_inicio_str)
        fecha_fin = date.fromisoformat(fecha_fin_str)
        
        # Verificar si el cliente está bloqueado (solo si está autenticado)
        if request.user.is_authenticated:
            if BloqueoCliente.esta_bloqueado(request.user, negocio):
                # Si está bloqueado, retornar todos los días como no disponibles
                for i in range((fecha_fin - fecha_inicio).days + 1):
                    dia = fecha_inicio + timedelta(days=i)
                    disponibilidad[dia.strftime('%Y-%m-%d')] = False
                return JsonResponse({'disponibilidad': disponibilidad})
    except Exception:
        return JsonResponse({'disponibilidad': disponibilidad})
    
    # Generar disponibilidad para el rango de fechas (60 días)
    dias_rango = (fecha_fin - fecha_inicio).days + 1
    for i in range(dias_rango):
        dia = fecha_inicio + timedelta(days=i)
        disponible = False
        # Verificar si es festivo/domingo
        co_holidays = holidays.CountryHoliday('CO')
        nombre_dia = dia.strftime('%A')
        nombre_dia_es = {
            'Monday': 'lunes',
            'Tuesday': 'martes',
            'Wednesday': 'miercoles',
            'Thursday': 'jueves',
            'Friday': 'viernes',
            'Saturday': 'sabado',
            'Sunday': 'domingo'
        }.get(nombre_dia, nombre_dia)
        es_festivo = dia in co_holidays or nombre_dia_es == 'domingo'
        if not es_festivo:
            horario_prof = HorarioProfesional.objects.filter(profesional=profesional, dia_semana=nombre_dia_es, disponible=True).first()
            if horario_prof:
                # Verificar si hay al menos un slot disponible
                inicio = horario_prof.hora_inicio
                fin = horario_prof.hora_fin
                duracion = servicio.duracion or 30
                inicio_minutos = inicio.hour * 60 + inicio.minute
                fin_minutos = fin.hour * 60 + fin.minute
                tiempo_actual = inicio_minutos
                reservas = Reserva.objects.filter(
                    peluquero=negocio,
                    profesional=profesional,
                    fecha=dia,
                    estado__in=['pendiente', 'confirmado']
                ).values_list('hora_inicio', 'hora_fin')
                while tiempo_actual + duracion <= fin_minutos:
                    hora_inicio = time(tiempo_actual // 60, tiempo_actual % 60)
                    hora_fin = time((tiempo_actual + duracion) // 60, (tiempo_actual + duracion) % 60)
                    ocupado = False
                    for reserva_inicio, reserva_fin in reservas:
                        if not (hora_fin <= reserva_inicio or hora_inicio >= reserva_fin):
                            ocupado = True
                            break
                    if not ocupado:
                        disponible = True
                        break
                    tiempo_actual += duracion
        disponibilidad[dia.strftime('%Y-%m-%d')] = disponible
    return JsonResponse({'disponibilidad': disponibilidad})

@require_GET
def api_negocios_vistos_recientes(request):
    """API para obtener negocios vistos recientemente desde localStorage"""
    if request.user.is_authenticated:
        # Para usuarios autenticados, usar la base de datos
        actividades = ActividadUsuario.objects.filter(
            usuario=request.user,
            tipo='visita_negocio'
        ).order_by('-fecha_creacion')[:10]
        
        negocios_ids = [act.objeto_id for act in actividades if act.objeto_id]
        negocios = Negocio.objects.filter(id__in=negocios_ids, activo=True).annotate(
            rating=Avg('calificaciones__puntaje'),
            total_resenias=Count('calificaciones')
        )[:5]
        
        data = []
        for negocio in negocios:
            data.append({
                'id': negocio.id,
                'nombre': negocio.nombre,
                'direccion': negocio.direccion,
                'rating': float(negocio.rating) if negocio.rating else 0,
                'total_resenias': negocio.total_resenias,
                'categoria': negocio.categoria or 'Salón de belleza',
                'portada_url': negocio.portada.url if negocio.portada else None,
                'url': f'/clientes/peluquero/{negocio.id}/'
            })
        
        return JsonResponse({'negocios': data})
    else:
        # Para usuarios no autenticados, devolver lista vacía
        # El frontend se encargará de obtener desde localStorage
        return JsonResponse({'negocios': []})

@require_GET
def api_buscar_negocios(request):
    """API para búsqueda AJAX de negocios con radios expandibles"""
    try:
        logger.debug("=== API BUSCAR NEGOCIOS INICIADA ===")
        
        # Parámetros de búsqueda
        ubicacion = request.GET.get('ubicacion', '').strip()
        lat = request.GET.get('lat')
        lon = request.GET.get('lon')
        servicio = request.GET.get('servicio', '').strip()
        negocio = request.GET.get('negocio', '').strip()
        
        logger.debug(f"=== PARÁMETROS RECIBIDOS ===")
        logger.debug(f"ubicacion: '{ubicacion}'")
        logger.debug(f"lat: '{lat}'")
        logger.debug(f"lon: '{lon}'")
        logger.debug(f"servicio: '{servicio}'")
        logger.debug(f"negocio: '{negocio}'")
        logger.debug(f"Todos los parámetros GET: {dict(request.GET)}")
        
        # Query base - TODOS los negocios activos
        queryset = Negocio.objects.filter(activo=True)
        logger.debug(f"Negocios activos totales: {queryset.count()}")
        
        # Filtrar por servicio si se especifica
        if servicio:
            queryset = queryset.filter(
                servicios_negocio__servicio__nombre__icontains=servicio
            ).distinct()
            logger.debug(f"Negocios después del filtro de servicio: {queryset.count()}")
        
        # Filtrar por ubicación textual si se especifica (sin coordenadas)
        if ubicacion and not lat and not lon:
            queryset = queryset.filter(
                Q(ciudad__icontains=ubicacion) |
                Q(barrio__icontains=ubicacion) |
                Q(direccion__icontains=ubicacion) |
                Q(nombre__icontains=ubicacion)
            )
            logger.debug(f"Negocios después del filtro de ubicación: {queryset.count()}")
        
        negocios_data = []
        
        if lat and lon:
            logger.debug(f"=== BÚSQUEDA CON COORDENADAS ===")
            # BÚSQUEDA CON COORDENADAS - RADIOS EXPANDIBLES
            from math import radians, cos, sin, asin, sqrt
            
            try:
                lat = float(lat)
                lon = float(lon)
                logger.debug(f"Coordenadas convertidas: lat={lat}, lon={lon}")
                
                def haversine(lat1, lon1, lat2, lon2):
                    R = 6371.0
                    dlat = radians(lat2 - lat1)
                    dlon = radians(lon2 - lon1)
                    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
                    c = 2 * asin(sqrt(a))
                    return R * c * 1000  # metros
                
                # Radios expandibles en metros
                radios = [500, 2000, 5000, 10000, 50000]  # 500m, 2km, 5km, 10km, 50km
                negocios_encontrados = set()
                negocios_con_distancia = []
                
                for radio in radios:
                    logger.debug(f"Buscando en radio de {radio}m...")
                    
                    for negocio_obj in queryset:
                        if negocio_obj.id in negocios_encontrados:
                            continue
                            
                        if negocio_obj.latitud is not None and negocio_obj.longitud is not None:
                            distancia = haversine(lat, lon, negocio_obj.latitud, negocio_obj.longitud)
                            
                            if distancia <= radio:
                                negocios_encontrados.add(negocio_obj.id)
                                negocios_con_distancia.append((negocio_obj, distancia))
                                logger.debug(f"  - {negocio_obj.nombre}: {round(distancia)}m")
                    
                    # Si encontramos suficientes negocios, parar
                    if len(negocios_con_distancia) >= 20:
                        break
                
                # Ordenar por distancia
                negocios_con_distancia.sort(key=lambda x: x[1])
                
                # Convertir a JSON
                for negocio_obj, distancia in negocios_con_distancia:
                    negocio_data = {
                        'id': negocio_obj.id,
                        'nombre': negocio_obj.nombre,
                        'direccion': negocio_obj.direccion,
                        'ciudad': negocio_obj.ciudad,
                        'barrio': negocio_obj.barrio,
                        'rating': 4.5,
                        'total_resenias': 10,
                        'categoria': 'Barbería',
                        'portada_url': negocio_obj.portada.url if negocio_obj.portada else None,
                        'url': f'/clientes/peluquero/{negocio_obj.id}/',
                        'distancia_m': round(distancia)
                    }
                    negocios_data.append(negocio_data)
                
                logger.debug(f"Total negocios encontrados con coordenadas: {len(negocios_data)}")
                
            except Exception as e:
                logger.debug(f"Error calculando distancias: {e}")
                import traceback
                traceback.print_exc()
                # Fallback: mostrar todos los negocios sin distancia
                for negocio_obj in queryset[:20]:
                    negocio_data = {
                        'id': negocio_obj.id,
                        'nombre': negocio_obj.nombre,
                        'direccion': negocio_obj.direccion,
                        'ciudad': negocio_obj.ciudad,
                        'barrio': negocio_obj.barrio,
                        'rating': 4.5,
                        'total_resenias': 10,
                        'categoria': 'Barbería',
                        'portada_url': negocio_obj.portada.url if negocio_obj.portada else None,
                        'url': f'/clientes/peluquero/{negocio_obj.id}/',
                        'distancia_m': None
                    }
                    negocios_data.append(negocio_data)
        else:
            logger.debug(f"=== BÚSQUEDA SIN COORDENADAS ===")
            logger.debug("Sin coordenadas - mostrando todos los negocios")
            for negocio_obj in queryset[:50]:  # Limitar a 50 para no sobrecargar
                negocio_data = {
                    'id': negocio_obj.id,
                    'nombre': negocio_obj.nombre,
                    'direccion': negocio_obj.direccion,
                    'ciudad': negocio_obj.ciudad,
                    'barrio': negocio_obj.barrio,
                    'rating': 4.5,
                    'total_resenias': 10,
                    'categoria': 'Barbería',
                                            'portada_url': negocio_obj.portada.url if negocio_obj.portada else None,
                        'url': f'/clientes/peluquero/{negocio_obj.id}/',
                        'distancia_m': None
                }
                negocios_data.append(negocio_data)
        
        logger.debug(f"Total negocios procesados: {len(negocios_data)}")
        
        return JsonResponse({
            'negocios': negocios_data,
            'total_resultados': len(negocios_data),
            'parametros_busqueda': {
                'ubicacion': ubicacion,
                'lat': request.GET.get('lat'),
                'lon': request.GET.get('lon'),
                'servicio': servicio
            }
        })
        
    except Exception as e:
        logger.debug(f"ERROR EN API: {str(e)}")
        import traceback
        traceback.print_exc()
        logger.error(f"Error en búsqueda AJAX de negocios: {str(e)}")
        return JsonResponse({
            'negocios': [],
            'total_resultados': 0,
            'error': 'Error en la búsqueda'
        }, status=500)

@login_required
@require_GET
def google_places_autocomplete(request):
    """Proxy para autocompletado de Google Places (evita CORS)"""
    try:
        query = request.GET.get('input', '').strip()
        if not query or len(query) < 3:
            return JsonResponse({'predictions': []})
        
        # Parámetros para la API de Google Places
        params = {
            'input': query,
            'key': settings.GOOGLE_MAPS_API_KEY,
            'language': 'es',
            'components': 'country:co',
            'types': 'geocode'
        }
        
        # Llamar a la API de Google Places
        url = 'https://maps.googleapis.com/maps/api/place/autocomplete/json'
        response = requests.get(url, params=params)
        
        if response.status_code == 200:
            data = response.json()
            return JsonResponse(data)
        else:
            return JsonResponse({'error': 'Error en API de Google Places'}, status=500)
            
    except Exception as e:
        logger.error(f"Error en autocompletado de Google Places: {str(e)}")
        return JsonResponse({'error': 'Error interno del servidor'}, status=500)

@login_required
@require_GET
def google_places_details(request):
    """Proxy para obtener detalles de Google Places (evita CORS)"""
    try:
        place_id = request.GET.get('place_id')
        if not place_id:
            return JsonResponse({'error': 'place_id requerido'}, status=400)
        
        # Parámetros para la API de Google Places
        params = {
            'place_id': place_id,
            'key': settings.GOOGLE_MAPS_API_KEY,
            'language': 'es'
        }
        
        # Llamar a la API de Google Places
        url = 'https://maps.googleapis.com/maps/api/place/details/json'
        response = requests.get(url, params=params)
        
        if response.status_code == 200:
            data = response.json()
            return JsonResponse(data)
        else:
            return JsonResponse({'error': 'Error en API de Google Places'}, status=500)
            
    except Exception as e:
        logger.error(f"Error obteniendo detalles de Google Places: {str(e)}")
        return JsonResponse({'error': 'Error interno del servidor'}, status=500)

@require_GET
def profesionales_por_servicio(request, negocio_id):
    """Vista AJAX para obtener profesionales que ofrecen un servicio específico"""
    logger.debug(f"DEBUG: profesionales_por_servicio llamado con negocio_id={negocio_id}")
    servicio_id = request.GET.get('servicio_id')
    logger.debug(f"DEBUG: servicio_id={servicio_id}")
    
    if not servicio_id:
        logger.debug("DEBUG: No hay servicio_id, retornando lista vacía")
        return JsonResponse({'profesionales': []})
    
    try:
        negocio = Negocio.objects.get(id=negocio_id, activo=True)
        logger.debug(f"DEBUG: Negocio encontrado: {negocio.nombre}")
        
        servicio_negocio = negocio.servicios_negocio.get(id=servicio_id)
        logger.debug(f"DEBUG: Servicio encontrado: {servicio_negocio.servicio.nombre}")
        
        # Obtener profesionales que ofrecen este servicio
        from profesionales.models import Profesional
        
        # Primero, verificar si hay profesionales matriculados en este negocio
        profesionales_matriculados = Profesional.objects.filter(
            matriculaciones__negocio=negocio,
            matriculaciones__estado='aprobada'
        )
        logger.debug(f"DEBUG: Profesionales matriculados en este negocio: {profesionales_matriculados.count()}")
        
        # Luego, verificar si hay profesionales que ofrecen este servicio
        profesionales_con_servicio = Profesional.objects.filter(
            servicios=servicio_negocio.servicio
        )
        logger.debug(f"DEBUG: Profesionales con este servicio: {profesionales_con_servicio.count()}")
        
        # Finalmente, la intersección
        profesionales = Profesional.objects.filter(
            matriculaciones__negocio=negocio,
            matriculaciones__estado='aprobada',
            servicios=servicio_negocio.servicio,
            disponible=True
        ).distinct().values('id', 'nombre_completo')
        
        logger.debug(f"DEBUG: Profesionales encontrados: {list(profesionales)}")
        
        return JsonResponse({
            'profesionales': list(profesionales)
        })
    except Negocio.DoesNotExist:
        logger.debug(f"DEBUG: Negocio {negocio_id} no encontrado")
        return JsonResponse({'profesionales': []})
    except negocio.servicios_negocio.model.DoesNotExist:
        logger.debug(f"DEBUG: Servicio {servicio_id} no encontrado")
        return JsonResponse({'profesionales': []})
    except Exception as e:
        logger.debug(f"DEBUG: Error inesperado: {str(e)}")
        return JsonResponse({'profesionales': []})

@login_required
def marcar_inasistencia(request, reserva_id):
    """
    Vista para que el negocio marque inasistencias en reservas pasadas
    """
    try:
        reserva = get_object_or_404(Reserva, id=reserva_id)
        
        # Verificar que el usuario es propietario del negocio o profesional
        if not (request.user == reserva.peluquero.propietario or 
                (reserva.profesional and request.user == reserva.profesional.usuario)):
            messages.error(request, 'No tienes permisos para marcar inasistencias en esta reserva.')
            return redirect('clientes:mis_reservas')
        
        # Verificar que la reserva ya pasó
        from .utils import is_fecha_pasada
        if not is_fecha_pasada(reserva.fecha, reserva.hora_fin):
            messages.error(request, 'Solo se puede marcar inasistencia en reservas que ya pasaron.')
            return redirect('clientes:mis_reservas')
        
        if request.method == 'POST':
            motivo = request.POST.get('motivo', '')
            
            try:
                reserva.marcar_inasistencia(motivo)
                messages.success(request, 'Inasistencia marcada correctamente.')
                
                # Log de actividad
                from cuentas.utils import log_user_activity
                log_user_activity(
                    user=request.user,
                    tipo='inasistencia_marcada',
                    objeto_id=reserva.id,
                    objeto_tipo='reserva',
                    descripcion=f'Inasistencia marcada en reserva {reserva.id}',
                    datos_adicionales={'motivo': motivo}
                )
                
            except ValidationError as e:
                messages.error(request, str(e))
            except Exception as e:
                logger.error(f"Error marcando inasistencia: {str(e)}")
                messages.error(request, 'Error al marcar inasistencia.')
            
            return redirect('clientes:mis_reservas')
        
        # GET: mostrar formulario de confirmación
        context = {
            'reserva': reserva,
        }
        return render(request, 'clientes/marcar_inasistencia.html', context)
        
    except Exception as e:
        logger.error(f"Error en marcar_inasistencia: {str(e)}")
        messages.error(request, 'Error al procesar la solicitud.')
        return redirect('clientes:mis_reservas')


@login_required
def reserva_exitosa(request, reserva_id):
    """
    Vista para mostrar los detalles de una reserva exitosa
    """
    try:
        # Obtener la reserva y verificar que pertenece al usuario
        reserva = get_object_or_404(Reserva, id=reserva_id, cliente=request.user)
        
        # Obtener el negocio de la reserva
        negocio = reserva.peluquero
        
        context = {
            'reserva': reserva,
            'negocio': negocio,
        }
        
        return render(request, 'clientes/reserva_exitosa.html', context)
        
    except Exception as e:
        logger.error(f"Error en reserva_exitosa: {str(e)}")
        messages.error(request, 'Error al mostrar los detalles de la reserva.')
        return redirect('clientes:mis_reservas')
# ── Google Maps Geocoding Proxy (seguridad: API key nunca sale al frontend) ──
@require_GET
def geocode_proxy(request):
    """Proxy seguro para Google Geocoding API — la API key se mantiene server-side"""
    lat = request.GET.get('lat')
    lng = request.GET.get('lng')
    if not lat or not lng:
        return JsonResponse({'error': 'lat y lng requeridos'}, status=400)
    
    from urllib.request import urlopen
    from urllib.parse import urlencode
    import json as _json
    try:
        params = urlencode({
            'latlng': f'{lat},{lng}',
            'key': settings.GOOGLE_MAPS_API_KEY,
            'language': 'es',
        })
        url = f'https://maps.googleapis.com/maps/api/geocode/json?{params}'
        with urlopen(url, timeout=5) as resp:
            data = _json.loads(resp.read().decode())
        return JsonResponse(data, safe=False)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
