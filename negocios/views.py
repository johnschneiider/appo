from .forms import NegocioForm, ImagenNegocioForm
from django.contrib.auth.decorators import login_required
from .models import Negocio, MetricaNegocio, ReporteMensual, ImagenNegocio, Servicio, ServicioNegocio
from clientes.models import Calificacion
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_protect
from datetime import datetime, timedelta
from django.http import JsonResponse
import holidays
import json
from datetime import datetime, timedelta, time
import logging
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.utils.html import escape
import re
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from django.db.models import Avg, Sum, Count, Max, Q
import numpy as np
from profesionales.models import Matriculacion, Profesional, SolicitudAusencia
from profesionales.models import Notificacion
from negocios.models import ImagenNegocio as ImagenGaleria
from django.db import models
from django.forms import ModelForm
from django.forms import modelformset_factory
from .models import NotificacionNegocio
from negocios.models import DiaDescanso
from datetime import date
from suscripciones.models import PlanSuscripcion
from cuentas.models import BusinessCheckoutIntent

logger = logging.getLogger(__name__)

def sanitize_input(text):
    """Sanitizar entrada de texto para prevenir XSS"""
    if text:
        # Remover caracteres peligrosos
        text = re.sub(r'<script.*?</script>', '', text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r'<.*?>', '', text)
        return escape(text.strip())
    return text

@login_required
def crear_negocio(request):
    print('[DEBUG SERVER] POST recibido:', request.method, request.POST)
    if request.method == 'POST':
        print('[DEBUG SERVER] Valor recibido de dirección:', request.POST.get('direccion'))
        # Verificar que el usuario sea de tipo negocio
        if not hasattr(request.user, 'tipo') or request.user.tipo != 'negocio':
            messages.error(request, 'Solo usuarios de tipo negocio pueden crear negocios.')
            return redirect('inicio')
        
        form = NegocioForm(request.POST, request.FILES)
        if form.is_valid():
            print('[DEBUG SERVER] Formulario válido. Guardando negocio...')
            try:
                negocio = form.save(commit=False)
                negocio.propietario = request.user
                negocio.activo = True
                negocio.save()
                from .models import Servicio, ServicioNegocio
                for servicio in Servicio.objects.all():
                    ServicioNegocio.objects.get_or_create(negocio=negocio, servicio=servicio)
                logger.info(f"Negocio '{negocio.nombre}' creado por {request.user.username}")
                messages.success(request, f'¡Felicidades! Tu negocio "{negocio.nombre}" ha sido creado exitosamente.')
                # Redirigir a la lista de negocios
                return redirect('negocios:mis_negocios')
            except Exception as e:
                logger.error(f"Error al crear negocio: {e}")
                messages.error(request, 'Hubo un error al crear tu negocio. Por favor, intenta nuevamente.')
        else:
            print('[DEBUG SERVER] Formulario inválido:', form.errors)
            messages.error(request, 'Por favor corrige los errores en el formulario.')
    else:
        form = NegocioForm()
    return render(request, 'negocios/crear_negocio.html', {'form': form})

@login_required
@require_GET
def mis_negocios(request):
    try:
        negocios_activos = request.user.negocios.filter(activo=True)
        negocios_eliminados = request.user.negocios.filter(activo=False)
        tiene_eliminados = negocios_eliminados.exists()

        return render(request, 'negocios/mis_negocios.html', {
            'negocios': negocios_activos,
            'negocios_eliminados': negocios_eliminados,
            'tiene_eliminados': tiene_eliminados,
        })
    except Exception as e:
        logger.error(f"Error en mis_negocios: {str(e)}")
        messages.error(request, "Error al cargar tus negocios.")
        return redirect('inicio')

@require_POST
@login_required
@csrf_protect
def eliminar_negocio(request, negocio_id):
    """Vista para eliminar un negocio"""
    negocio = get_object_or_404(Negocio, id=negocio_id, propietario=request.user)
    
    if request.method == 'POST':
        try:
            negocio.delete()
            messages.success(request, f'El negocio "{negocio.nombre}" ha sido eliminado.')
            return redirect('negocios:mis_negocios')
        except Exception as e:
            logger.error(f"Error al eliminar negocio: {e}")
            messages.error(request, 'Error al eliminar el negocio.')
    
    return render(request, 'negocios/confirmar_eliminacion_negocio.html', {'negocio': negocio})

@require_POST
@login_required
@csrf_protect
def restaurar_negocio(request, negocio_id):
    try:
        negocio = get_object_or_404(Negocio, id=negocio_id, propietario=request.user, activo=False)
        negocio.activo = True
        negocio.save()
        logger.info(f"Negocio '{negocio.nombre}' restaurado por {request.user.username}")
        messages.success(request, f"El negocio '{negocio.nombre}' ha sido restaurado.")
    except Exception as e:
        logger.error(f"Error restaurando negocio: {str(e)}")
        messages.error(request, "Error al restaurar el negocio.")
    
    return redirect('negocios:mis_negocios')

@login_required
@csrf_protect
def configurar_negocio(request, negocio_id):
    try:
        negocio = get_object_or_404(Negocio, id=negocio_id, propietario=request.user)
        
        # Obtener servicios del negocio
        servicios_negocio = negocio.servicios_negocio.all().select_related('servicio')

        if request.method == 'POST':
            form = NegocioForm(request.POST, request.FILES, instance=negocio)
            if form.is_valid():
                form.save()
                
                # Procesar servicios seleccionados
                servicios_seleccionados = request.POST.getlist('servicios')
                
                # Actualizar estado de servicios
                for sn in servicios_negocio:
                    if str(sn.id) in servicios_seleccionados:
                        sn.activo = True
                    else:
                        sn.activo = False
                    sn.save()
                
                logger.info(f"Negocio '{negocio.nombre}' actualizado por {request.user.username}")
                messages.success(request, "Negocio actualizado.")
                return redirect('negocios:configurar_negocio', negocio_id=negocio.id)
            else:
                logger.warning(f"Formulario inválido al configurar negocio: {form.errors}")
        else:
            form = NegocioForm(instance=negocio)

        return render(request, 'negocios/configurar_negocio.html', {
            'form': form, 
            'negocio': negocio,
            'servicios_negocio': servicios_negocio
        })
    except Exception as e:
        logger.error(f"Error en configurar_negocio: {str(e)}")
        messages.error(request, "Error al cargar la configuración del negocio.")
        return redirect('negocios:mis_negocios')

@login_required
@csrf_protect
def panel_negocio(request, negocio_id):
    try:
        negocio = get_object_or_404(Negocio, id=negocio_id, propietario=request.user)
        # Servicios activos del negocio
        servicios_activos = negocio.servicios_negocio.filter(activo=True).select_related('servicio')

        # Guardar logo si es POST con archivo de logo
        if request.method == 'POST' and 'logo' in request.FILES:
            negocio.logo = request.FILES['logo']
            negocio.save()
            messages.success(request, "Logo actualizado correctamente.")
            return redirect('negocios:panel_negocio', negocio_id=negocio.id)

        # Guardar horario de atención si es POST y no es cambio de logo
        if request.method == 'POST' and 'logo' not in request.FILES:
            dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
            editar_dia = request.POST.get('editar_dia', '')
            
            if editar_dia and editar_dia in dias:
                # Edición de un solo día: merge con horario existente
                horario_actual = negocio.horario_atencion or {}
                dias_activos = request.POST.getlist('dias_activos')
                if editar_dia in dias_activos:
                    inicio = request.POST.get(f'inicio_{editar_dia}', '')
                    fin = request.POST.get(f'fin_{editar_dia}', '')
                    if inicio and fin:
                        horario_actual[editar_dia] = {"inicio": inicio, "fin": fin}
                else:
                    # Día desactivado: removerlo del horario
                    horario_actual.pop(editar_dia, None)
                negocio.horario_atencion = horario_actual
            else:
                # Edición general (todos los días a la vez)
                nuevo_horario = {}
                dias_activos = request.POST.getlist('dias_activos')
                for dia in dias:
                    if dia in dias_activos:
                        inicio = request.POST.get(f'inicio_{dia}', '')
                        fin = request.POST.get(f'fin_{dia}', '')
                        if inicio and fin:
                            nuevo_horario[dia] = {"inicio": inicio, "fin": fin}
                negocio.horario_atencion = nuevo_horario
            
            negocio.save()
            messages.success(request, "Horario de atención actualizado correctamente.")
            return redirect('negocios:panel_negocio', negocio_id=negocio.id)

        # Profesionales aceptados (matriculación aprobada)
        logger.info(f"Buscando matriculaciones para negocio {negocio.id}")
        matriculaciones = negocio.matriculaciones.all()
        logger.info(f"Total matriculaciones encontradas: {matriculaciones.count()}")
        matriculaciones_aprobadas = negocio.matriculaciones.filter(estado='aprobada')
        logger.info(f"Matriculaciones aprobadas: {matriculaciones_aprobadas.count()}")
        
        profesionales_aceptados = []
        for m in matriculaciones_aprobadas.select_related('profesional'):
            prof = m.profesional
            logger.info(f"Procesando profesional: {prof.nombre_completo} (ID: {prof.id})")
            
            # Horario (puedes ajustar el formato según tu modelo real)
            try:
                horarios = prof.horarios.all()
                horario_str = ', '.join([f"{h.get_dia_semana_display()}: {h.hora_inicio.strftime('%H:%M')} - {h.hora_fin.strftime('%H:%M')}" for h in horarios]) if horarios else 'No asignado'
            except Exception as e:
                logger.warning(f"Error al obtener horarios para {prof.nombre_completo}: {e}")
                horario_str = 'No asignado'
            
            # Calificaciones
            try:
                calificaciones = prof.calificaciones.filter(negocio=negocio)
                promedio = round(calificaciones.aggregate(models.Avg('puntaje'))['puntaje__avg'] or 0, 1)
                num_calificaciones = calificaciones.count()
            except Exception as e:
                logger.warning(f"Error al obtener calificaciones para {prof.nombre_completo}: {e}")
                promedio = 0
                num_calificaciones = 0
            
            # Servicios
            try:
                servicios = prof.servicios.all()
                servicios_nombres = ', '.join([s.nombre for s in servicios]) if servicios else 'No asignados'
            except Exception as e:
                logger.warning(f"Error al obtener servicios para {prof.nombre_completo}: {e}")
                servicios_nombres = 'No asignados'
            
            # Reservas
            try:
                from clientes.models import Reserva
                reservas_count = Reserva.objects.filter(profesional=prof, peluquero=negocio).count()
            except Exception as e:
                logger.warning(f"Error al obtener reservas para {prof.nombre_completo}: {e}")
                reservas_count = 0
            
            profesional_data = {
                'id': prof.id,
                'nombre_completo': prof.nombre_completo,
                'especialidad': prof.especialidad,
                'foto_perfil': prof.foto_perfil,
                'horario': horario_str,
                'promedio': promedio,
                'num_calificaciones': num_calificaciones,
                'servicios': servicios_nombres,
                'reservas_count': reservas_count,
            }
            
            logger.info(f"Datos del profesional: {profesional_data}")
            profesionales_aceptados.append(profesional_data)
        
        logger.info(f"Total de profesionales aceptados procesados: {len(profesionales_aceptados)}")
        
        dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

        horario_guardado = {}
        for dia in dias:
            base = negocio.horario_atencion.get(dia, {})
            horario_guardado[f"{dia}_inicio"] = base.get("inicio", "")
            horario_guardado[f"{dia}_fin"] = base.get("fin", "")
            horario_guardado[f"{dia}_activo"] = bool(base)

        # Calcular datos de suscripciones si el modelo existe
        total_planes = 0
        planes_activos = 0
        total_suscriptores = 0
        ingresos_mensuales = 0
        
        try:
            from suscripciones.models import PlanSuscripcion, Suscripcion
            planes = PlanSuscripcion.objects.filter(negocio=negocio)
            total_planes = planes.count()
            planes_activos = planes.filter(activo=True).count()
            total_suscriptores = Suscripcion.objects.filter(plan__negocio=negocio, estado='activa').count()
            ingresos_mensuales = sum(
                plan.precio_mensual * plan.suscripciones.filter(estado='activa').count()
                for plan in planes.filter(activo=True)
            )
        except ImportError:
            # El modelo de suscripciones no está disponible
            pass
        except Exception as e:
            logger.warning(f"Error calculando datos de suscripciones: {e}")

        return render(request, 'negocios/panel_negocio.html', {
            'negocio': negocio,
            'profesionales_aceptados': profesionales_aceptados,
            'dias': dias,
            'horario_guardado': horario_guardado,
            'servicios_activos': servicios_activos,
            # Datos de suscripciones
            'total_planes': total_planes,
            'planes_activos': planes_activos,
            'total_suscriptores': total_suscriptores,
            'ingresos_mensuales': ingresos_mensuales,
        })
    except Exception as e:
        logger.error(f"Error en panel_negocio: {str(e)}")
        messages.error(request, "Error al cargar el panel del negocio.")
        return redirect('negocios:mis_negocios')

@login_required
def dashboard_negocio(request, negocio_id):
    from datetime import datetime, timedelta, date
    from django.db.models import Count, Avg, Q
    from django.utils import timezone
    from clientes.models import Reserva
    from clientes.models import Calificacion

    # Obtener el negocio específico del usuario
    negocio = get_object_or_404(Negocio, id=negocio_id, propietario=request.user)
    
    # Intento de checkout / trial más reciente del usuario (para banner de trial)
    trial_intent = BusinessCheckoutIntent.objects.filter(
        usuario=request.user
    ).order_by('-creado_en').first()
    trial_dias_restantes = None
    trial_fin = None
    if trial_intent and trial_intent.trial_fin:
        delta = trial_intent.trial_fin - timezone.now()
        trial_dias_restantes = max(0, delta.days)
        trial_fin = trial_intent.trial_fin
    
    # Fechas para los últimos 30 días
    hoy = timezone.now().date()
    hace_30_dias = hoy - timedelta(days=30)
    
    # Datos de reservas de los últimos 30 días
    reservas_30_dias = Reserva.objects.filter(
        peluquero=negocio,
        fecha__gte=hace_30_dias,
        fecha__lte=hoy
    ).order_by('fecha')
    
    # Generar datos para el gráfico de reservas (últimos 10 días)
    fechas_grafico = []
    reservas_grafico = []
    
    for i in range(10):
        fecha_actual = hoy - timedelta(days=9-i)
        count_reservas = reservas_30_dias.filter(fecha=fecha_actual).count()
        fechas_grafico.append(fecha_actual.strftime('%d/%m'))
        reservas_grafico.append(count_reservas)
    
    # Reporte del mes actual
    inicio_mes = hoy.replace(day=1)
    reservas_mes = Reserva.objects.filter(
        peluquero=negocio,
        fecha__gte=inicio_mes,
        fecha__lte=hoy
    )
    
    # Calcular ingresos totales (asumiendo precio promedio de $30 por servicio)
    total_reservas_mes = reservas_mes.count()
    ingresos_totales = total_reservas_mes * 30  # Precio promedio estimado
    
    # Clientes nuevos del mes (clientes que hicieron su primera reserva este mes)
    clientes_nuevos_mes = reservas_mes.values('cliente').distinct().count()
    
    # Día más ocupado del mes
    dia_mas_ocupado = reservas_mes.values('fecha').annotate(
        count=Count('id')
    ).order_by('-count').first()
    
    dia_mas_ocupado_nombre = 'N/A'
    if dia_mas_ocupado:
        fecha_ocupada = dia_mas_ocupado['fecha']
        dias_semana = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
        dia_mas_ocupado_nombre = dias_semana[fecha_ocupada.weekday()]
    
    # Hora pico (hora con más reservas)
    hora_pico_data = reservas_mes.values('hora_inicio').annotate(
        count=Count('id')
    ).order_by('-count').first()
    
    hora_pico = 'N/A'
    if hora_pico_data:
        hora_pico = hora_pico_data['hora_inicio'].strftime('%H:%M')
    
    # Mejor profesional del mes (por calificaciones)
    from profesionales.models import Matriculacion
    
    # Obtener profesionales aprobados del negocio
    matriculaciones_aprobadas = Matriculacion.objects.filter(
        negocio=negocio,
        estado='aprobada'
    ).select_related('profesional')
    
    profesionales_negocio = [m.profesional for m in matriculaciones_aprobadas]
    mejor_profesional = None
    mejor_puntuacion = 0
    
    for profesional in profesionales_negocio:
        calificaciones = Calificacion.objects.filter(
            negocio=negocio,
            profesional=profesional,
            fecha_calificacion__gte=inicio_mes
        )
        if calificaciones.exists():
            promedio = calificaciones.aggregate(Avg('puntaje'))['puntaje__avg']
            if promedio and promedio > mejor_puntuacion:
                mejor_puntuacion = promedio
                mejor_profesional = profesional
    
    # Ventas por mes (últimos 6 meses)
    meses_grafico = []
    ventas_mes_grafico = []
    
    for i in range(6):
        fecha_mes = hoy - timedelta(days=30*i)
        inicio_mes_grafico = fecha_mes.replace(day=1)
        fin_mes_grafico = (inicio_mes_grafico + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        
        reservas_mes_grafico = Reserva.objects.filter(
            peluquero=negocio,
            fecha__gte=inicio_mes_grafico,
            fecha__lte=fin_mes_grafico
        ).count()
        
        meses_grafico.append(fecha_mes.strftime('%m/%y'))
        ventas_mes_grafico.append(reservas_mes_grafico * 30)  # Precio promedio estimado
    
    # Crear objeto reporte
    class Reporte:
        def __init__(self):
            self.total_reservas = total_reservas_mes
            self.ingresos_totales = ingresos_totales
            self.clientes_nuevos = clientes_nuevos_mes
            self.dia_mas_ocupado = dia_mas_ocupado_nombre
            self.hora_pico = hora_pico
    
    reporte = Reporte()
    
    context = {
        'negocio': negocio,
        'fechas': fechas_grafico,
        'reservas': reservas_grafico,
        'meses': meses_grafico,
        'ventas_mes': ventas_mes_grafico,
        'reporte': reporte,
        'peluquero_top': mejor_profesional,
        'peluquero_top_score': round(mejor_puntuacion, 1) if mejor_puntuacion > 0 else 0,
        'dias_ocupados': dia_mas_ocupado_nombre,
        'hora_pico': hora_pico,
        'trial_intent': trial_intent,
        'trial_dias_restantes': trial_dias_restantes,
        'trial_fin': trial_fin,
    }
    return render(request, 'negocios/dashboard_negocio.html', context)

@require_GET
def detalle_negocio(request, negocio_id):
    """Vista pública para ver detalles del negocio"""
    negocio = get_object_or_404(Negocio, id=negocio_id, activo=True)
    # Calificaciones percentil 75
    calificaciones = Calificacion.objects.filter(negocio=negocio).values_list('puntaje', flat=True)
    calificacion_percentil = 5
    if calificaciones:
        calificacion_percentil = round(float(np.percentile(list(calificaciones), 75)), 1)
    # Estado abierto/cerrado
    ahora = datetime.now()
    dia_semana = ahora.strftime('%A')
    dia_semana_es = {
        'Monday': 'Lunes', 'Tuesday': 'Martes', 'Wednesday': 'Miércoles', 'Thursday': 'Jueves', 'Friday': 'Viernes', 'Saturday': 'Sábado', 'Sunday': 'Domingo'
    }[dia_semana]
    horario = negocio.horario_atencion.get(dia_semana_es, {})
    abierto = False
    proximo_cambio = None
    if horario and 'inicio' in horario and 'fin' in horario:
        try:
            inicio = datetime.strptime(horario['inicio'], '%H:%M').time()
            fin = datetime.strptime(horario['fin'], '%H:%M').time()
            if inicio <= ahora.time() <= fin:
                abierto = True
                proximo_cambio = fin.strftime('%H:%M')
            else:
                abierto = False
                proximo_cambio = inicio.strftime('%H:%M')
        except Exception:
            abierto = False
    # Ciudad (asumimos que está en la dirección)
    ciudad = negocio.direccion.split(',')[-1].strip() if ',' in negocio.direccion else negocio.direccion
    # Imágenes
    logo = negocio.logo
    portada = negocio.portada
    galeria = ImagenGaleria.objects.filter(negocio=negocio)
    imagenes = negocio.imagenes.all().order_by('-created_at')
    # Servicios del negocio
    servicios = negocio.servicios_negocio.select_related('servicio').all()
    # Profesionales matriculados aprobados
    matriculaciones = Matriculacion.objects.filter(negocio=negocio, estado='aprobada').select_related('profesional')
    profesionales = [m.profesional for m in matriculaciones]
    peluqueros_info = []
    for profesional in profesionales:
        avatar = profesional.foto_perfil if hasattr(profesional, 'foto_perfil') else None
        especialidad = profesional.especialidad if hasattr(profesional, 'especialidad') else ''
        descripcion = profesional.descripcion if hasattr(profesional, 'descripcion') else ''
        servicios_prof = profesional.servicios.all() if hasattr(profesional, 'servicios') else []
        # Calcular promedio y número de calificaciones
        calificaciones_prof = Calificacion.objects.filter(negocio=negocio, profesional=profesional)
        num_calificaciones = calificaciones_prof.count()
        promedio = round(calificaciones_prof.aggregate(models.Avg('puntaje'))['puntaje__avg'] or 0, 1) if num_calificaciones > 0 else 0
        peluquero_info = {
            'id': profesional.id,
            'nombre': profesional.nombre_completo,
            'avatar': avatar,
            'especialidad': especialidad,
            'descripcion': descripcion,
            'servicios': servicios_prof,
            'promedio': promedio,
            'num_calificaciones': num_calificaciones,
        }
        peluqueros_info.append(peluquero_info)
    # Comentarios
    comentarios = Calificacion.objects.filter(negocio=negocio).exclude(comentario='').order_by('-fecha_calificacion')
    # Días laborables para el calendario visual
    dias_laborables = set()
    for dia, h in (negocio.horario_atencion or {}).items():
        if h and h.get('inicio') and h.get('fin'):
            dias_laborables.add(dia)
    # Mes y año actual para el calendario
    from datetime import date
    hoy = date.today()
    mes_actual = hoy.month
    anio_actual = hoy.year
    return render(request, 'negocios/detalle_negocio.html', {
        'negocio': negocio,
        'peluqueros_info': peluqueros_info,
        'calificacion_percentil': calificacion_percentil,
        'abierto': abierto,
        'proximo_cambio': proximo_cambio,
        'ciudad': ciudad,
        'logo': logo,
        'portada': portada,
        'galeria': galeria,
        'imagenes': imagenes,
        'servicios': servicios,
        'profesionales': profesionales,
        'comentarios': comentarios,
        'dias_laborables': list(dias_laborables),
        'mes_actual': mes_actual,
        'anio_actual': anio_actual,
    })

@login_required
def editar_negocio(request, negocio_id):
    """Vista para editar un negocio y su galería de imágenes"""
    negocio = get_object_or_404(Negocio, id=negocio_id, propietario=request.user)
    imagenes = negocio.imagenes.all()
    imagen_form = ImagenNegocioForm()
    if request.method == 'POST':
        form = NegocioForm(request.POST, request.FILES, instance=negocio)
        if 'agregar_imagen' in request.POST:
            imagen_form = ImagenNegocioForm(request.POST, request.FILES)
            if imagen_form.is_valid():
                nueva_imagen = imagen_form.save(commit=False)
                nueva_imagen.negocio = negocio
                nueva_imagen.save()
                messages.success(request, 'Imagen agregada a la galería.')
                return redirect('negocios:editar_negocio', negocio_id=negocio.id)
        elif form.is_valid():
            negocio = form.save(commit=False)
            negocio.save()
            form.save_m2m()
            # Si se agregó un nuevo servicio, créalo y asígnalo
            nuevo_servicio = form.cleaned_data.get('nuevo_servicio')
            if nuevo_servicio:
                servicio, creado = Servicio.objects.get_or_create(nombre=nuevo_servicio)
                from .models import ServicioNegocio
                ServicioNegocio.objects.get_or_create(negocio=negocio, servicio=servicio)
            # Guardar servicios seleccionados, duración y precio personalizados
            servicios_ids = request.POST.getlist('servicios')
            servicios_negocio = negocio.servicios_negocio.all()
            for sn in servicios_negocio:
                sn_activo = str(sn.id) in servicios_ids
                # Actualizar duración personalizada
                nueva_duracion = request.POST.get(f'duracion_{sn.id}')
                if nueva_duracion:
                    try:
                        sn.duracion = int(nueva_duracion)
                    except ValueError:
                        pass
                # Actualizar precio personalizado
                nuevo_precio = request.POST.get(f'precio_{sn.id}')
                if nuevo_precio:
                    try:
                        if nuevo_precio.strip():  # Solo si no está vacío
                            sn.precio = float(nuevo_precio)
                        else:
                            sn.precio = None  # Si está vacío, establecer como None
                    except ValueError:
                        pass  # Si no es un número válido, mantener el precio actual
                else:
                    sn.precio = None  # Si no se envía el campo, establecer como None
                
                if sn_activo and not sn.activo:
                    sn.activo = True
                elif not sn_activo and sn.activo:
                    sn.activo = False
                sn.save()
            messages.success(request, 'Negocio actualizado exitosamente.')
            # Log para depuración de redirección
            logger.warning(f"[DEBUG] Usuario: {request.user.username}, tipo: {getattr(request.user, 'tipo', None)}")
            # Redirige según el tipo de usuario
            if hasattr(request.user, 'tipo') and request.user.tipo == 'negocio':
                logger.warning(f"[DEBUG] Redirigiendo a panel_negocio para negocio_id={negocio.id}")
                return redirect('negocios:panel_negocio', negocio_id=negocio.id)
            else:
                logger.warning(f"[DEBUG] Redirigiendo a detalle_negocio para negocio_id={negocio.id}")
                return redirect('negocios:detalle_negocio', negocio_id=negocio.id)
    else:
        form = NegocioForm(instance=negocio)
    # Obtener todos los servicios disponibles para el negocio
    servicios_negocio = negocio.servicios_negocio.all()
    return render(request, 'negocios/editar_negocio.html', {
        'form': form,
        'negocio': negocio,
        'imagenes': imagenes,
        'imagen_form': imagen_form,
        'servicios_negocio': servicios_negocio,
    })

@login_required
def solicitudes_matricula(request):
    user = request.user
    if user.tipo != 'negocio':
        messages.error(request, 'Acceso solo para negocios.')
        return redirect('inicio')
    negocios = user.negocios.all()
    solicitudes = Matriculacion.objects.filter(negocio__in=negocios, estado='pendiente').select_related('profesional', 'negocio')
    return render(request, 'negocios/solicitudes_matricula.html', {'solicitudes': solicitudes})

@login_required
def ver_perfil_profesional(request, profesional_id):
    profesional = get_object_or_404(Profesional, id=profesional_id)
    negocio_id = request.GET.get('negocio_id')
    negocio = None
    if negocio_id:
        from .models import Negocio
        try:
            negocio = Negocio.objects.get(id=negocio_id, propietario=request.user)
        except Negocio.DoesNotExist:
            negocio = None
    
    # Obtener horarios del profesional
    from profesionales.models import HorarioProfesional
    horarios = HorarioProfesional.objects.filter(profesional=profesional, disponible=True).order_by('dia_semana')
    
    return render(request, 'negocios/perfil_profesional.html', {
        'profesional': profesional,
        'negocio': negocio,
        'horarios': horarios,
    })

@require_POST
@login_required
def api_responder_matricula(request, solicitud_id, accion):
    user = request.user
    if user.tipo != 'negocio':
        return JsonResponse({'ok': False, 'error': 'Solo negocios pueden realizar esta acción.'}, status=403)
    try:
        solicitud = Matriculacion.objects.get(id=solicitud_id, negocio__propietario=user)
        if solicitud.estado != 'pendiente':
            return JsonResponse({'ok': False, 'error': 'La solicitud ya fue respondida.'}, status=400)
        if accion == 'aceptar':
            solicitud.aprobar()
            Notificacion.objects.create(
                profesional=solicitud.profesional,
                tipo='matriculacion',
                titulo='¡Solicitud aceptada!',
                mensaje=f'Tu solicitud para unirte a {solicitud.negocio.nombre} ha sido aceptada.',
                url_relacionada=''
            )
        elif accion == 'rechazar':
            solicitud.rechazar()
            Notificacion.objects.create(
                profesional=solicitud.profesional,
                tipo='matriculacion',
                titulo='Solicitud rechazada',
                mensaje=f'Tu solicitud para unirte a {solicitud.negocio.nombre} ha sido rechazada.',
                url_relacionada=''
            )
        else:
            return JsonResponse({'ok': False, 'error': 'Acción no válida.'}, status=400)
        return JsonResponse({'ok': True, 'negocio_id': solicitud.negocio.id})
    except Matriculacion.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Solicitud no encontrada.'}, status=404)
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)

@login_required
def desvincular_profesional(request, matricula_id):
    user = request.user
    if user.tipo != 'negocio':
        messages.error(request, 'Acceso solo para negocios.')
        return redirect('inicio')
    matricula = get_object_or_404(Matriculacion, id=matricula_id, negocio__propietario=user, estado='aprobada')
    if request.method == 'POST':
        matricula.estado = 'cancelada'
        matricula.save()
        messages.success(request, 'Profesional desvinculado correctamente.')
        return redirect('negocios:solicitudes_matricula')
    return render(request, 'negocios/desvincular_profesional.html', {'matricula': matricula})

@login_required
def galeria_negocio(request, negocio_id):
    negocio = get_object_or_404(Negocio, id=negocio_id, propietario=request.user)
    imagenes = negocio.imagenes.all().order_by('-created_at')
    
    if request.method == 'POST':
        form = ImagenNegocioForm(request.POST, request.FILES)
        if form.is_valid():
            imagen = form.save(commit=False)
            imagen.negocio = negocio
            imagen.save()
            messages.success(request, 'Imagen agregada a la galería correctamente.')
            return redirect('negocios:galeria_negocio', negocio_id=negocio.id)
        else:
            messages.error(request, 'Error al agregar la imagen. Por favor, verifica los datos.')
    else:
        form = ImagenNegocioForm()
    
    return render(request, 'negocios/galeria_negocio.html', {
        'negocio': negocio,
        'imagenes': imagenes,
        'form': form,
    })

@login_required
def editar_profesional_negocio(request, negocio_id, profesional_id):
    negocio = get_object_or_404(Negocio, id=negocio_id, propietario=request.user)
    profesional = get_object_or_404(Profesional, id=profesional_id)
    matriculacion = get_object_or_404(Matriculacion, negocio=negocio, profesional=profesional, estado='aprobada')
    servicios_negocio = ServicioNegocio.objects.filter(negocio=negocio)
    
    if request.method == 'POST':
        # Actualizar servicios asignados
        servicios_ids = request.POST.getlist('servicios')
        servicios_a_asignar = [s.servicio for s in servicios_negocio if str(s.id) in servicios_ids]
        profesional.servicios.set(servicios_a_asignar)
        
        # Mensaje específico sobre servicios
        if servicios_a_asignar:
            servicios_nombres = ', '.join([s.nombre for s in servicios_a_asignar])
            messages.success(request, f'Servicios asignados correctamente: {servicios_nombres}')
        else:
            messages.warning(request, 'No se asignaron servicios al profesional.')
        
        # Actualizar horarios usando el modelo HorarioProfesional
        from profesionales.models import HorarioProfesional
        from datetime import time
        
        # Eliminar horarios existentes
        profesional.horarios.all().delete()
        
        # Crear nuevos horarios
        dias = request.POST.getlist('dias')
        for dia in dias:
            inicio = request.POST.get(f'inicio_{dia}')
            fin = request.POST.get(f'fin_{dia}')
            if inicio and fin:
                try:
                    # Convertir strings de tiempo a objetos time
                    hora_inicio = time.fromisoformat(inicio)
                    hora_fin = time.fromisoformat(fin)
                    
                    # Mapear nombres de días a los valores del modelo
                    dia_mapping = {
                        'Lunes': 'lunes',
                        'Martes': 'martes', 
                        'Miércoles': 'miercoles',
                        'Jueves': 'jueves',
                        'Viernes': 'viernes',
                        'Sábado': 'sabado',
                        'Domingo': 'domingo'
                    }
                    
                    dia_semana = dia_mapping.get(dia, dia.lower())
                    
                    HorarioProfesional.objects.create(
                        profesional=profesional,
                        dia_semana=dia_semana,
                        hora_inicio=hora_inicio,
                        hora_fin=hora_fin,
                        disponible=True
                    )
                except (ValueError, TypeError) as e:
                    messages.error(request, f'Error en el formato de hora para {dia}: {e}')
                    continue
        
        messages.success(request, 'Perfil del profesional actualizado correctamente.')
        return redirect('negocios:panel_negocio', negocio_id=negocio.id)
    
    # Días de la semana
    dias_semana = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
    
    # Obtener horarios actuales del modelo HorarioProfesional
    horarios_actuales = {}
    for horario in profesional.horarios.all():
        # Mapear de vuelta a nombres en español
        dia_mapping_reverse = {
            'lunes': 'Lunes',
            'martes': 'Martes',
            'miercoles': 'Miércoles', 
            'jueves': 'Jueves',
            'viernes': 'Viernes',
            'sabado': 'Sábado',
            'domingo': 'Domingo'
        }
        dia_nombre = dia_mapping_reverse.get(horario.dia_semana, horario.dia_semana)
        
        # Convertir horas a minutos desde medianoche
        inicio_minutos = horario.hora_inicio.hour * 60 + horario.hora_inicio.minute
        fin_minutos = horario.hora_fin.hour * 60 + horario.hora_fin.minute
        
        horarios_actuales[dia_nombre] = {
            'inicio': horario.hora_inicio.strftime('%H:%M'),
            'fin': horario.hora_fin.strftime('%H:%M'),
            'inicio_minutos': inicio_minutos,
            'fin_minutos': fin_minutos
        }
    
    servicios_asignados = profesional.servicios.values_list('id', flat=True)
    return render(request, 'negocios/editar_profesional_negocio.html', {
        'negocio': negocio,
        'profesional': profesional,
        'servicios_negocio': servicios_negocio,
        'dias_semana': dias_semana,
        'horario_actual': horarios_actuales,
        'servicios_asignados': servicios_asignados,
    })

@login_required
def calendario_reservas(request, negocio_id):
    from django.utils import timezone
    negocio = get_object_or_404(Negocio, id=negocio_id, propietario=request.user)
    fecha_actual = timezone.now().date()
    return render(request, 'negocios/calendario.html', {
        'negocio': negocio,
        'fecha_actual': fecha_actual
    })

@login_required
def api_reservas_negocio(request, negocio_id):
    """API para obtener reservas del negocio con filtros de fecha"""
    from clientes.models import Reserva
    from django.utils import timezone
    
    try:
        negocio = get_object_or_404(Negocio, id=negocio_id, propietario=request.user)
        
        # Obtener parámetros de filtro
        fecha = request.GET.get('fecha')
        start_date = request.GET.get('start')
        end_date = request.GET.get('end')
        
        # Filtrar reservas del negocio
        # Las reservas están relacionadas directamente con el negocio a través del campo peluquero
        reservas = Reserva.objects.filter(
            peluquero=negocio
        ).select_related('cliente', 'cliente_provisional', 'servicio', 'profesional')
        
        # Aplicar filtros de fecha
        if fecha:
            try:
                fecha_obj = timezone.datetime.strptime(fecha, '%Y-%m-%d').date()
                reservas = reservas.filter(fecha=fecha_obj)
            except ValueError:
                return JsonResponse({'error': 'Formato de fecha inválido'}, status=400)
        elif start_date:
            try:
                start_date_obj = timezone.datetime.strptime(start_date[:10], '%Y-%m-%d').date()
                reservas = reservas.filter(fecha__gte=start_date_obj)
            except ValueError:
                return JsonResponse({'error': 'Formato de fecha de inicio inválido'}, status=400)
        elif end_date:
            try:
                end_date_obj = timezone.datetime.strptime(end_date[:10], '%Y-%m-%d').date()
                reservas = reservas.filter(fecha__lte=end_date_obj)
            except ValueError:
                return JsonResponse({'error': 'Formato de fecha de fin inválido'}, status=400)
        
        # Convertir reservas a formato para el calendario
        reservas_data = []
        for r in reservas:
            try:
                # Calcular hora de fin basada en duración del servicio
                hora_inicio = r.hora_inicio
                # Usar la hora_fin que ya está en el modelo
                hora_fin = r.hora_fin
                
                # Si no hay hora_fin, calcular basado en la duración del servicio
                if not hora_fin and r.servicio and r.servicio.duracion:
                    from datetime import datetime, timedelta
                    try:
                        hora_inicio_dt = datetime.strptime(str(hora_inicio), '%H:%M:%S')
                        hora_fin_dt = hora_inicio_dt + timedelta(minutes=r.servicio.duracion)
                        hora_fin = hora_fin_dt.strftime('%H:%M:%S')
                    except:
                        # Si falla el cálculo, usar 1 hora por defecto
                        hora_inicio_dt = datetime.strptime(str(hora_inicio), '%H:%M:%S')
                        hora_fin_dt = hora_inicio_dt + timedelta(hours=1)
                        hora_fin = hora_fin_dt.strftime('%H:%M:%S')
                
                # Verificar si el cliente tiene suscripción activa (solo para clientes con cuenta)
                from suscripciones.models import Suscripcion
                tiene_suscripcion = False
                if r.cliente:
                    tiene_suscripcion = Suscripcion.objects.filter(
                        cliente=r.cliente,
                        negocio=negocio,
                        estado='activa',
                        fecha_inicio__lte=r.fecha,
                        fecha_fin__gte=r.fecha
                    ).exists()
                
                # Obtener nombre del cliente usando el método del modelo que maneja ambos casos
                nombre_cliente = r.get_cliente_nombre()
                
                reserva_data = {
                    'id': r.id,
                    'cliente': nombre_cliente,
                    'servicio': r.servicio.servicio.nombre if r.servicio and r.servicio.servicio else 'Reserva',
                    'hora_inicio': str(hora_inicio),
                    'hora_fin': str(hora_fin),
                    'fecha': r.fecha.isoformat(),
                    'profesional_id': r.profesional.id if r.profesional else None,
                    'estado': r.estado or 'pendiente',
                    'notas': r.notas or '',
                    'precio': 0,  # El modelo Servicio en negocios no tiene precio
                    'tiene_suscripcion': tiene_suscripcion,
                    'es_cliente_provisional': r.es_cliente_provisional()
                }
                
                reservas_data.append(reserva_data)
                
            except Exception as e:
                print(f"Error procesando reserva {r.id}: {e}")
                continue
        
        return JsonResponse({
            'reservas': reservas_data,
            'total': len(reservas_data),
            'fecha': fecha
        }, safe=False)
        
    except Exception as e:
        print(f"Error en api_reservas_negocio: {e}")
        return JsonResponse({
            'error': 'Error interno del servidor',
            'detalle': str(e)
        }, status=500)

@login_required
def api_crear_reserva(request, negocio_id):
    """API para crear una nueva reserva"""
    from clientes.models import Reserva
    from django.utils import timezone
    from django.views.decorators.csrf import csrf_exempt
    from django.utils.decorators import method_decorator
    from django.views.decorators.http import require_http_methods
    
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    
    try:
        negocio = get_object_or_404(Negocio, id=negocio_id, propietario=request.user)
        
        # Obtener datos del request (puede venir como JSON o form data)
        if request.content_type and 'application/json' in request.content_type:
            # Si viene como JSON, parsear el body
            try:
                data = json.loads(request.body.decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return JsonResponse({'error': 'Error al parsear JSON'}, status=400)
        else:
            # Si viene como form data, usar POST
            data = request.POST.dict() if request.POST else {}
        
        # Validar campos requeridos
        # Si es cliente provisional, solo necesita nombre y teléfono
        es_cliente_provisional = data.get('es_cliente_provisional', False)
        
        if es_cliente_provisional:
            campos_requeridos = ['nombre_cliente', 'telefono_cliente', 'servicio', 'fecha', 'hora_inicio']
            for campo in campos_requeridos:
                if not data.get(campo):
                    return JsonResponse({'error': f'Campo requerido: {campo}'}, status=400)
        else:
            campos_requeridos = ['cliente', 'servicio', 'fecha', 'hora_inicio']
            for campo in campos_requeridos:
                if not data.get(campo):
                    return JsonResponse({'error': f'Campo requerido: {campo}'}, status=400)
        
        # Manejar cliente (con cuenta o provisional)
        cliente = None
        cliente_provisional = None
        
        if es_cliente_provisional:
            # Crear cliente provisional (siempre crear uno nuevo para evitar conflictos de nombres)
            from clientes.models import ClienteProvisional
            nombre = data.get('nombre_cliente', '').strip()
            telefono = data.get('telefono_cliente', '').strip()
            
            if not nombre:
                return JsonResponse({'error': 'El nombre del cliente es requerido'}, status=400)
            if not telefono:
                return JsonResponse({'error': 'El teléfono del cliente es requerido'}, status=400)
            
            # Siempre crear un nuevo cliente provisional para esta reserva
            # Esto evita que al actualizar el nombre de un cliente existente se afecten reservas anteriores
            # El mismo teléfono puede pertenecer a diferentes personas (familia, empresa, etc.)
            cliente_provisional = ClienteProvisional.objects.create(
                nombre=nombre,
                telefono=telefono,
                negocio=negocio,
                creado_por=request.user,
                notas=data.get('notas_cliente', '')
            )
            logger.info(f"✅ Creado nuevo cliente provisional: ID {cliente_provisional.id}, nombre: '{nombre}', teléfono: '{telefono}', negocio: {negocio.id}")
        else:
            # Buscar el cliente con cuenta
            from django.contrib.auth import get_user_model
            User = get_user_model()
            try:
                cliente = User.objects.get(username=data['cliente'])
            except User.DoesNotExist:
                return JsonResponse({'error': 'Cliente no encontrado'}, status=400)
        
        # Buscar el servicio del negocio
        try:
            servicio = ServicioNegocio.objects.get(
                negocio=negocio,
                servicio__nombre=data['servicio']
            )
        except ServicioNegocio.DoesNotExist:
            # Si no existe, crear un servicio temporal
            servicio_base, created = Servicio.objects.get_or_create(
                nombre=data['servicio'],
                defaults={
                    'descripcion': f'Servicio {data["servicio"]}'
                }
            )
            servicio = ServicioNegocio.objects.create(
                negocio=negocio,
                servicio=servicio_base,
                activo=True
            )
        
        # Buscar el profesional
        profesional = None
        if data.get('profesional_id'):
            try:
                profesional = Profesional.objects.get(id=data['profesional_id'])
            except Profesional.DoesNotExist:
                return JsonResponse({'error': 'Profesional no encontrado'}, status=400)
        
        # Calcular hora_fin basada en la duración del servicio
        from datetime import datetime, timedelta
        try:
            # Manejar formato de hora con o sin segundos
            hora_inicio_str = data['hora_inicio']
            if len(hora_inicio_str.split(':')) == 2:
                hora_inicio_str += ':00'
            hora_inicio_dt = datetime.strptime(hora_inicio_str, '%H:%M:%S')
            # Usar la duración del servicio si está disponible
            duracion_minutos = servicio.duracion if servicio.duracion else 60
            hora_fin_dt = hora_inicio_dt + timedelta(minutes=duracion_minutos)
            hora_fin = hora_fin_dt.strftime('%H:%M:%S')
        except Exception as e:
            # Si falla el cálculo, usar 1 hora por defecto
            try:
                hora_inicio_str = data['hora_inicio']
                if len(hora_inicio_str.split(':')) == 2:
                    hora_inicio_str += ':00'
                hora_inicio_dt = datetime.strptime(hora_inicio_str, '%H:%M:%S')
            except:
                hora_inicio_dt = datetime.strptime('09:00:00', '%H:%M:%S')
            hora_fin_dt = hora_inicio_dt + timedelta(hours=1)
            hora_fin = hora_fin_dt.strftime('%H:%M:%S')
        
        # Convertir fecha de string a date si es necesario
        fecha_obj = data['fecha']
        if isinstance(fecha_obj, str):
            try:
                fecha_obj = datetime.strptime(fecha_obj, '%Y-%m-%d').date()
            except ValueError:
                return JsonResponse({'error': 'Formato de fecha inválido. Use YYYY-MM-DD'}, status=400)
        
        # Convertir hora_inicio a time si es necesario
        hora_inicio_obj = data['hora_inicio']
        if isinstance(hora_inicio_obj, str):
            try:
                # Asegurar formato HH:MM:SS
                hora_parts = hora_inicio_obj.split(':')
                if len(hora_parts) == 2:
                    hora_inicio_obj = f"{hora_parts[0]}:{hora_parts[1]}:00"
                hora_inicio_obj = datetime.strptime(hora_inicio_obj, '%H:%M:%S').time()
            except ValueError:
                return JsonResponse({'error': 'Formato de hora inválido. Use HH:MM'}, status=400)
        
        # Convertir hora_fin a time si es necesario
        if isinstance(hora_fin, str):
            try:
                hora_fin = datetime.strptime(hora_fin, '%H:%M:%S').time()
            except ValueError:
                # Si falla, calcular desde hora_inicio
                hora_inicio_dt = datetime.combine(datetime.today(), hora_inicio_obj)
                hora_fin_dt = hora_inicio_dt + timedelta(hours=1)
                hora_fin = hora_fin_dt.time()
        
        # Validar que tenemos un cliente (con cuenta o provisional)
        if not cliente and not cliente_provisional:
            return JsonResponse({'error': 'Debe especificar un cliente con cuenta o un cliente provisional'}, status=400)
        
        if cliente and cliente_provisional:
            return JsonResponse({'error': 'No puede tener cliente con cuenta y cliente provisional al mismo tiempo'}, status=400)
        
        # Crear la reserva
        reserva = Reserva(
            cliente=cliente,
            cliente_provisional=cliente_provisional,
            servicio=servicio,
            fecha=fecha_obj,
            hora_inicio=hora_inicio_obj,
            hora_fin=hora_fin,
            profesional=profesional,
            estado='confirmado' if es_cliente_provisional else 'pendiente',  # Las reservas del negocio se confirman automáticamente
            notas=data.get('notas', ''),
            peluquero=negocio  # Asignar al negocio
        )
        
        # Validar el modelo antes de guardar
        try:
            reserva.full_clean()
        except Exception as e:
            return JsonResponse({'error': f'Error de validación: {str(e)}'}, status=400)
        
        # Guardar la reserva
        reserva.save()
        
        return JsonResponse({
            'success': True,
            'reserva_id': reserva.id,
            'mensaje': 'Reserva creada exitosamente'
        }, status=201)
        
    except Exception as e:
        print(f"Error creando reserva: {e}")
        return JsonResponse({
            'error': 'Error interno del servidor',
            'detalle': str(e)
        }, status=500)

def get_color_by_estado(estado):
    """Función auxiliar para obtener el color según el estado de la reserva"""
    colores = {
        'confirmada': '#28a745',
        'confirmado': '#28a745',
        'pendiente': '#ffc107',
        'cancelada': '#dc3545',
        'cancelado': '#dc3545',
        'completada': '#17a2b8',
        'completado': '#17a2b8',
        'inasistencia': '#6c757d',
        'no_show': '#6c757d'
    }
    return colores.get(estado, '#6c757d')

@login_required
def api_estadisticas_negocio(request, negocio_id):
    """API para obtener estadísticas del día del negocio"""
    from clientes.models import Reserva
    from django.utils import timezone
    from decimal import Decimal
    
    negocio = get_object_or_404(Negocio, id=negocio_id, propietario=request.user)
    fecha = request.GET.get('fecha', timezone.now().date().isoformat())
    
    try:
        fecha_obj = timezone.datetime.strptime(fecha, '%Y-%m-%d').date()
    except ValueError:
        fecha_obj = timezone.now().date()
    
    # Obtener reservas del día
    reservas_dia = Reserva.objects.filter(
        peluquero=negocio,
        fecha=fecha_obj
    )
    
    # Calcular estadísticas
    total_reservas = reservas_dia.count()
    reservas_completadas = reservas_dia.filter(estado='completada').count()
    reservas_canceladas = reservas_dia.filter(estado='cancelada').count()
    reservas_pendientes = reservas_dia.filter(estado='pendiente').count()
    reservas_confirmadas = reservas_dia.filter(estado='confirmada').count()
    
    # Calcular ingresos totales
    ingresos_totales = Decimal('0.00')
    for reserva in reservas_dia.filter(estado__in=['completada', 'confirmada']):
        if reserva.servicio and reserva.servicio.precio:
            ingresos_totales += Decimal(str(reserva.servicio.precio))
    
    # Calcular promedio por reserva
    promedio_ticket = Decimal('0.00')
    if total_reservas > 0:
        promedio_ticket = ingresos_totales / total_reservas
    
    estadisticas = {
        'fecha': fecha_obj.isoformat(),
        'total_reservas': total_reservas,
        'reservas_completadas': reservas_completadas,
        'reservas_canceladas': reservas_canceladas,
        'reservas_pendientes': reservas_pendientes,
        'reservas_confirmadas': reservas_confirmadas,
        'ingresos_totales': float(ingresos_totales),
        'promedio_ticket': float(promedio_ticket),
    }
    
    return JsonResponse(estadisticas)

@login_required
def api_usuarios_negocio(request, negocio_id):
    """API para obtener usuarios/profesionales del negocio para el calendario"""
    from profesionales.models import Profesional, Matriculacion
    
    negocio = get_object_or_404(Negocio, id=negocio_id, propietario=request.user)
    
    # Obtener profesionales matriculados y aprobados en el negocio
    matriculaciones = Matriculacion.objects.filter(
        negocio=negocio,
        estado='aprobada'
    ).select_related('profesional')
    
    usuarios = []
    for mat in matriculaciones:
        if mat.profesional.disponible:  # Solo profesionales disponibles
            # Obtener la URL de la imagen del profesional
            foto_url = None
            if mat.profesional.foto_perfil:
                foto_url = mat.profesional.foto_perfil.url
            else:
                # Si no tiene foto, usar la imagen por defecto
                foto_url = None
            
            usuarios.append({
                'id': f'prof_{mat.profesional.id}',
                'title': mat.profesional.nombre_completo,
                'tipo': 'profesional',
                'color': '#3788d8',
                'foto_url': foto_url
            })
    
    # Si no hay profesionales, crear un recurso genérico
    if not usuarios:
        usuarios.append({
            'id': 'todos',
            'title': 'Todos los Usuarios',
            'tipo': 'general',
            'color': '#6c757d',
            'foto_url': None
        })
    
    return JsonResponse({'usuarios': usuarios})

@login_required
def api_reservas_dia(request, negocio_id):
    """API para obtener las reservas de un día específico para el calendario"""
    from clientes.models import Reserva
    from django.utils import timezone
    import logging
    
    logger = logging.getLogger(__name__)
    
    try:
        logger.info(f"API reservas día: Iniciando para negocio {negocio_id}")
        
        # Verificar que el usuario esté autenticado
        if not request.user.is_authenticated:
            logger.error("API reservas día: Usuario no autenticado")
            return JsonResponse({'error': 'Usuario no autenticado'}, status=401)
        
        # Obtener el negocio
        try:
            negocio = get_object_or_404(Negocio, id=negocio_id, propietario=request.user)
            logger.info(f"API reservas día: Negocio {negocio.id} - {negocio.nombre}")
        except Exception as e:
            logger.error(f"API reservas día: Error obteniendo negocio: {e}")
            return JsonResponse({'error': 'Negocio no encontrado'}, status=404)
        
        # Obtener la fecha del parámetro o usar la fecha actual
        fecha_str = request.GET.get('fecha')
        if fecha_str:
            try:
                fecha = timezone.datetime.strptime(fecha_str, '%Y-%m-%d').date()
                logger.info(f"API reservas día: Fecha parseada: {fecha}")
            except ValueError as e:
                logger.error(f"API reservas día: Error parseando fecha '{fecha_str}': {e}")
                fecha = timezone.now().date()
                logger.info(f"API reservas día: Usando fecha por defecto: {fecha}")
        else:
            fecha = timezone.now().date()
            logger.info(f"API reservas día: No se proporcionó fecha, usando actual: {fecha}")
        
        logger.info(f"API reservas día: Buscando reservas para fecha {fecha}")
        
        # Obtener reservas del día para el negocio
        try:
            reservas = Reserva.objects.filter(
                peluquero=negocio,
                fecha=fecha
            ).select_related('cliente', 'servicio', 'profesional')
            
            logger.info(f"API reservas día: Encontradas {reservas.count()} reservas")
        except Exception as e:
            logger.error(f"API reservas día: Error consultando reservas: {e}")
            return JsonResponse({'error': 'Error consultando reservas', 'detalle': str(e)}, status=500)
        
        eventos = []
        for reserva in reservas:
            try:
                logger.info(f"API reservas día: Procesando reserva {reserva.id} - Cliente: {reserva.cliente.username}, Profesional: {reserva.profesional}")
                
                # Calcular hora de fin basada en duración del servicio
                hora_inicio = reserva.hora_inicio
                if reserva.servicio and reserva.servicio.duracion:
                    from datetime import datetime, timedelta
                    hora_inicio_dt = datetime.strptime(str(hora_inicio), '%H:%M:%S')
                    hora_fin_dt = hora_inicio_dt + timedelta(minutes=reserva.servicio.duracion)
                    hora_fin = hora_fin_dt.strftime('%H:%M:%S')
                else:
                    # Si no hay duración del servicio, asumir 30 minutos por defecto
                    hora_inicio_dt = datetime.strptime(str(hora_inicio), '%H:%M:%S')
                    hora_fin_dt = hora_inicio_dt + timedelta(minutes=30)
                    hora_fin = hora_fin_dt.strftime('%H:%M:%S')
                
                # Normalizar el estado para el frontend
                estado_frontend = reserva.estado
                if reserva.estado == 'confirmado':
                    estado_frontend = 'confirmada'
                elif reserva.estado == 'cancelado':
                    estado_frontend = 'cancelada'
                elif reserva.estado == 'completado':
                    estado_frontend = 'completada'
                
                evento = {
                    'id': reserva.id,
                    'profesional_id': f'prof_{reserva.profesional.id}' if reserva.profesional else 'todos',
                    'hora_inicio': str(hora_inicio),
                    'hora_fin': str(hora_fin),
                    'cliente': reserva.cliente.username,
                    'servicio': reserva.servicio.nombre if reserva.servicio else 'Reserva',
                    'estado': estado_frontend,
                    'color': get_color_by_estado(estado_frontend),
                    'notas': reserva.notas or ''
                }
                
                eventos.append(evento)
                logger.info(f"API reservas día: Evento creado: {evento}")
                
            except Exception as e:
                logger.error(f"API reservas día: Error procesando reserva {reserva.id}: {e}")
                continue
        
        response_data = {'reservas': eventos, 'fecha': fecha.isoformat()}
        logger.info(f"API reservas día: Respuesta final con {len(eventos)} eventos")
        
        return JsonResponse(response_data)
        
    except Exception as e:
        logger.error(f"API reservas día: Error general: {e}")
        return JsonResponse({'error': 'Error interno del servidor', 'detalle': str(e)}, status=500)

class ServicioNegocioForm(ModelForm):
    class Meta:
        model = ServicioNegocio
        fields = ['servicio', 'duracion', 'precio']

@login_required
def gestionar_servicios(request, negocio_id):
    negocio = get_object_or_404(Negocio, id=negocio_id, propietario=request.user)
    ServicioFormSet = modelformset_factory(ServicioNegocio, form=ServicioNegocioForm, extra=1, can_delete=True)
    queryset = ServicioNegocio.objects.filter(negocio=negocio)
    if request.method == 'POST':
        formset = ServicioFormSet(request.POST, queryset=queryset)
        if formset.is_valid():
            instances = formset.save(commit=False)
            for obj in formset.deleted_objects:
                obj.delete()
            for instance in instances:
                instance.negocio = negocio
                instance.save()
            formset.save_m2m()
            messages.success(request, 'Servicios actualizados correctamente.')
            return redirect('negocios:gestionar_servicios', negocio_id=negocio.id)
    else:
        formset = ServicioFormSet(queryset=queryset)
    return render(request, 'negocios/gestionar_servicios.html', {'negocio': negocio, 'formset': formset})

@login_required
def notificaciones_negocio(request):
    if getattr(request.user, 'tipo', None) != 'negocio':
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden('Solo negocios pueden ver esta página.')
    # Obtener todas las notificaciones de los negocios del usuario
    negocios_usuario = request.user.negocios.all()
    notificaciones = NotificacionNegocio.objects.filter(negocio__in=negocios_usuario).order_by('-fecha_creacion')
    return render(request, 'negocios/notificaciones.html', {'notificaciones': notificaciones})

@login_required
def solicitudes_ausencia(request):
    """Vista para que el negocio vea las solicitudes de ausencia pendientes"""
    if getattr(request.user, 'tipo', None) != 'negocio':
        messages.error(request, 'Solo negocios pueden ver esta página.')
        return redirect('inicio')
    
    # Obtener solicitudes de ausencia de todos los negocios del usuario
    negocios_usuario = request.user.negocios.all()
    
    # Debug: verificar todos los estados de solicitudes
    todas_solicitudes = SolicitudAusencia.objects.filter(
        negocio__in=negocios_usuario
    ).select_related('profesional', 'negocio')
    
    print(f"DEBUG: Total de solicitudes encontradas: {todas_solicitudes.count()}")
    for solicitud in todas_solicitudes:
        print(f"DEBUG: Solicitud {solicitud.id} - Estado: {solicitud.estado} - Profesional: {solicitud.profesional.nombre_completo}")
    
    solicitudes_pendientes = todas_solicitudes.filter(estado='pendiente').order_by('-fecha_solicitud')
    solicitudes_aprobadas = todas_solicitudes.filter(estado='aprobada').order_by('-fecha_respuesta')
    solicitudes_rechazadas = todas_solicitudes.filter(estado='rechazada').order_by('-fecha_respuesta')
    
    print(f"DEBUG: Pendientes: {solicitudes_pendientes.count()}, Aprobadas: {solicitudes_aprobadas.count()}, Rechazadas: {solicitudes_rechazadas.count()}")
    
    return render(request, 'negocios/solicitudes_ausencia.html', {
        'solicitudes_pendientes': solicitudes_pendientes,
        'solicitudes_aprobadas': solicitudes_aprobadas,
        'solicitudes_rechazadas': solicitudes_rechazadas,
    })

@login_required
def revisar_solicitud_ausencia(request, solicitud_id):
    """Vista para que el negocio revise una solicitud específica de ausencia"""
    if getattr(request.user, 'tipo', None) != 'negocio':
        messages.error(request, 'Solo negocios pueden ver esta página.')
        return redirect('inicio')
    
    solicitud = get_object_or_404(
        SolicitudAusencia, 
        id=solicitud_id,
        negocio__propietario=request.user,
        estado='pendiente'
    )
    
    if request.method == 'POST':
        print(f"DEBUG: POST recibido para solicitud {solicitud_id}")
        print(f"DEBUG: POST data: {request.POST}")
        
        accion = request.POST.get('accion')
        comentario = request.POST.get('comentario', '')
        
        print(f"DEBUG: Acción extraída: '{accion}'")
        print(f"DEBUG: Comentario extraído: '{comentario}'")

        if not accion:
            print(f"DEBUG: No se recibió acción, mostrando error")
            messages.error(request, 'Debes elegir una acción (Aprobar o Rechazar) usando los botones.')
            return redirect(request.path)
        
        print(f"DEBUG: Procesando acción '{accion}' para solicitud {solicitud_id}")
        print(f"DEBUG: Estado actual de la solicitud: {solicitud.estado}")
        
        if accion == 'aprobar':
            # Aprobar la solicitud
            solicitud.aprobar(comentario)
            
            # Verificar que el estado se actualizó correctamente
            solicitud.refresh_from_db()
            print(f"DEBUG: Estado después de aprobar: {solicitud.estado}")
            
            # Crear notificación para el profesional
            Notificacion.objects.create(
                profesional=solicitud.profesional,
                tipo='solicitud_ausencia',
                titulo='Solicitud de ausencia aprobada',
                mensaje=f'Tu solicitud de ausencia del {solicitud.fecha_inicio} al {solicitud.fecha_fin} ha sido aprobada por {solicitud.negocio.nombre}.',
                url_relacionada='/profesionales/gestionar-ausencias/',
            )
            
            messages.success(request, f'Solicitud de ausencia aprobada correctamente. La solicitud de {solicitud.profesional.nombre_completo} ahora aparece en la lista de aprobadas.')
            
        elif accion == 'rechazar':
            # Rechazar la solicitud
            solicitud.rechazar(comentario)
            
            # Verificar que el estado se actualizó correctamente
            solicitud.refresh_from_db()
            print(f"DEBUG: Estado después de rechazar: {solicitud.estado}")
            
            # Crear notificación para el profesional
            Notificacion.objects.create(
                profesional=solicitud.profesional,
                tipo='solicitud_ausencia',
                titulo='Solicitud de ausencia rechazada',
                mensaje=f'Tu solicitud de ausencia del {solicitud.fecha_inicio} al {solicitud.fecha_fin} ha sido rechazada por {solicitud.negocio.nombre}.',
                url_relacionada='/profesionales/gestionar-ausencias/',
            )
            
            messages.success(request, f'Solicitud de ausencia rechazada correctamente. La solicitud de {solicitud.profesional.nombre_completo} ahora aparece en la lista de rechazadas.')
        
        # Forzar un refresh de la página para mostrar los cambios
        return redirect('negocios:solicitudes_ausencia')
    
    return render(request, 'negocios/revisar_solicitud_ausencia.html', {
        'solicitud': solicitud,
    })

@login_required
def listar_dias_descanso(request):
    """Vista para que el negocio vea sus días de descanso"""
    if getattr(request.user, 'tipo', None) != 'negocio':
        messages.error(request, 'Solo negocios pueden ver esta página.')
        return redirect('inicio')
    
    # Obtener días de descanso de todos los negocios del usuario
    negocios_usuario = request.user.negocios.all()
    dias_descanso = DiaDescanso.objects.filter(
        negocio__in=negocios_usuario
    ).select_related('negocio').order_by('-fecha')
    
    dias_activos = dias_descanso.filter(activo=True).count()
    dias_futuros = dias_descanso.filter(fecha__gte=date.today()).count()
    
    context = {
        'dias_descanso': dias_descanso,
        'negocios': negocios_usuario,
        'dias_activos': dias_activos,
        'dias_futuros': dias_futuros,
    }
    return render(request, 'negocios/listar_dias_descanso.html', context)

@login_required
def crear_dia_descanso(request):
    """Vista para que el negocio cree un nuevo día de descanso"""
    if getattr(request.user, 'tipo', None) != 'negocio':
        messages.error(request, 'Solo negocios pueden ver esta página.')
        return redirect('inicio')
    
    if request.method == 'POST':
        negocio_id = request.POST.get('negocio')
        fecha = request.POST.get('fecha')
        tipo = request.POST.get('tipo')
        motivo = request.POST.get('motivo', '')
        descripcion = request.POST.get('descripcion', '')
        
        try:
            negocio = request.user.negocios.get(id=negocio_id)
            
            # Verificar que no exista ya un día de descanso para esa fecha
            if DiaDescanso.objects.filter(negocio=negocio, fecha=fecha).exists():
                messages.error(request, f'Ya existe un día de descanso programado para el {fecha}.')
                return redirect('negocios:listar_dias_descanso')
            
            # Crear el día de descanso
            dia_descanso = DiaDescanso.objects.create(
                negocio=negocio,
                fecha=fecha,
                tipo=tipo,
                motivo=motivo,
                descripcion=descripcion
            )
            
            messages.success(request, f'Día de descanso programado para el {fecha} correctamente.')
            return redirect('negocios:listar_dias_descanso')
            
        except Negocio.DoesNotExist:
            messages.error(request, 'Negocio no válido.')
        except Exception as e:
            logger.error(f"Error al crear día de descanso: {str(e)}")
            messages.error(request, f'Error al crear el día de descanso: {str(e)}')
            # Log detallado para debugging
            import traceback
            logger.error(f"Traceback completo: {traceback.format_exc()}")
    
    # Obtener negocios del usuario para el formulario
    negocios = request.user.negocios.all()
    
    context = {
        'negocios': negocios,
        'tipos': DiaDescanso.TIPO_CHOICES,
    }
    return render(request, 'negocios/crear_dia_descanso.html', context)

@login_required
def editar_dia_descanso(request, dia_id):
    """Vista para que el negocio edite un día de descanso"""
    if getattr(request.user, 'tipo', None) != 'negocio':
        messages.error(request, 'Solo negocios pueden ver esta página.')
        return redirect('inicio')
    
    dia_descanso = get_object_or_404(
        DiaDescanso, 
        id=dia_id,
        negocio__propietario=request.user
    )
    
    if request.method == 'POST':
        fecha = request.POST.get('fecha')
        tipo = request.POST.get('tipo')
        motivo = request.POST.get('motivo', '')
        descripcion = request.POST.get('descripcion', '')
        activo = request.POST.get('activo') == 'on'
        
        try:
            # Verificar que no exista otro día de descanso para esa fecha (excluyendo el actual)
            if DiaDescanso.objects.filter(negocio=dia_descanso.negocio, fecha=fecha).exclude(id=dia_id).exists():
                messages.error(request, f'Ya existe un día de descanso programado para el {fecha}.')
                return redirect('negocios:listar_dias_descanso')
            
            # Actualizar el día de descanso
            dia_descanso.fecha = fecha
            dia_descanso.tipo = tipo
            dia_descanso.motivo = motivo
            dia_descanso.descripcion = descripcion
            dia_descanso.activo = activo
            dia_descanso.save()
            
            messages.success(request, 'Día de descanso actualizado correctamente.')
            return redirect('negocios:listar_dias_descanso')
            
        except Exception as e:
            messages.error(request, f'Error al actualizar el día de descanso: {str(e)}')
    
    context = {
        'dia_descanso': dia_descanso,
        'tipos': DiaDescanso.TIPO_CHOICES,
    }
    return render(request, 'negocios/editar_dia_descanso.html', context)

@login_required
def eliminar_dia_descanso(request, dia_id):
    """Vista para que el negocio elimine un día de descanso"""
    if getattr(request.user, 'tipo', None) != 'negocio':
        messages.error(request, 'Solo negocios pueden ver esta página.')
        return redirect('inicio')
    
    dia_descanso = get_object_or_404(
        DiaDescanso, 
        id=dia_id,
        negocio__propietario=request.user
    )
    
    if request.method == 'POST':
        dia_descanso.delete()
        messages.success(request, 'Día de descanso eliminado correctamente.')
        return redirect('negocios:listar_dias_descanso')
    
    context = {
        'dia_descanso': dia_descanso,
    }
    return render(request, 'negocios/eliminar_dia_descanso.html', context)

@login_required
def gestionar_inasistencias(request, negocio_id):
    """Vista para gestionar inasistencias desde el panel del negocio"""
    negocio = get_object_or_404(Negocio, id=negocio_id, propietario=request.user)
    
    # Obtener inasistencias del negocio
    from clientes.models import Reserva
    inasistencias = Reserva.objects.filter(
        peluquero=negocio,
        estado='inasistencia'
    ).select_related('cliente', 'profesional', 'servicio').order_by('-fecha', '-hora_inicio')
    
    # Estadísticas de inasistencias
    total_inasistencias = inasistencias.count()
    inasistencias_este_mes = inasistencias.filter(
        fecha__gte=timezone.now().replace(day=1)
    ).count()
    inasistencias_esta_semana = inasistencias.filter(
        fecha__gte=timezone.now().date() - timedelta(days=7)
    ).count()
    
    # Clientes con más inasistencias
    clientes_problematicos = Reserva.objects.filter(
        peluquero=negocio,
        estado='inasistencia'
    ).values('cliente__username', 'cliente__email').annotate(
        total_inasistencias=Count('id')
    ).filter(total_inasistencias__gte=2).order_by('-total_inasistencias')[:10]
    
    context = {
        'negocio': negocio,
        'inasistencias': inasistencias,
        'total_inasistencias': total_inasistencias,
        'inasistencias_este_mes': inasistencias_este_mes,
        'inasistencias_esta_semana': inasistencias_esta_semana,
        'clientes_problematicos': clientes_problematicos,
    }
    
    return render(request, 'negocios/gestionar_inasistencias.html', context)

@login_required
def marcar_inasistencia_manual(request, negocio_id, reserva_id):
    """Vista para marcar manualmente una inasistencia"""
    negocio = get_object_or_404(Negocio, id=negocio_id, propietario=request.user)
    reserva = get_object_or_404(Reserva, id=reserva_id, peluquero=negocio)
    
    if request.method == 'POST':
        motivo = request.POST.get('motivo', 'Inasistencia marcada manualmente por el negocio')
        
        try:
            reserva.marcar_inasistencia(motivo=motivo)
            messages.success(request, f'Se ha marcado la inasistencia de {reserva.cliente.username}')
            
            # Log de la actividad
            from clientes.models import ActividadUsuario
            ActividadUsuario.registrar_actividad(
                usuario=request.user,
                tipo='inasistencia_manual',
                objeto_id=reserva.id,
                objeto_tipo='reserva',
                descripcion=f'Marcó inasistencia manualmente: {reserva.cliente.username}',
                request=request
            )
            
        except Exception as e:
            messages.error(request, f'Error al marcar inasistencia: {str(e)}')
    
    return redirect('negocios:gestionar_inasistencias', negocio_id=negocio_id)

@login_required
def configurar_politica_inasistencias(request, negocio_id):
    """Vista para configurar política de inasistencias del negocio"""
    negocio = get_object_or_404(Negocio, id=negocio_id, propietario=request.user)
    
    if request.method == 'POST':
        # Obtener configuración del formulario
        tolerancia_minutos = request.POST.get('tolerancia_minutos', 15)
        penalizacion_dias = request.POST.get('penalizacion_dias', 0)
        max_inasistencias = request.POST.get('max_inasistencias', 3)
        
        # Guardar configuración en el modelo del negocio
        negocio.configuracion_inasistencias = {
            'tolerancia_minutos': int(tolerancia_minutos),
            'penalizacion_dias': int(penalizacion_dias),
            'max_inasistencias': int(max_inasistencias),
        }
        negocio.save()
        
        messages.success(request, 'Configuración de inasistencias actualizada correctamente')
        return redirect('negocios:gestionar_inasistencias', negocio_id=negocio_id)
    
    # Obtener configuración actual
    config_actual = getattr(negocio, 'configuracion_inasistencias', {})
    
    # Obtener clientes bloqueados
    from clientes.models import BloqueoCliente
    clientes_bloqueados = BloqueoCliente.objects.filter(
        negocio=negocio,
        activo=True
    ).select_related('cliente').order_by('-fecha_creacion')
    
    context = {
        'negocio': negocio,
        'config_actual': config_actual,
        'clientes_bloqueados': clientes_bloqueados,
    }
    
    return render(request, 'negocios/configurar_politica_inasistencias.html', context)

@login_required
def desbloquear_cliente(request, negocio_id, bloqueo_id):
    """Vista para desbloquear manualmente a un cliente"""
    negocio = get_object_or_404(Negocio, id=negocio_id, propietario=request.user)
    from clientes.models import BloqueoCliente
    
    try:
        bloqueo = BloqueoCliente.objects.get(id=bloqueo_id, negocio=negocio, activo=True)
        bloqueo.desbloquear(usuario=request.user)
        messages.success(request, f'Cliente {bloqueo.cliente.username} desbloqueado correctamente')
    except BloqueoCliente.DoesNotExist:
        messages.error(request, 'Bloqueo no encontrado o ya fue desbloqueado')
    
    return redirect('negocios:configurar_politica_inasistencias', negocio_id=negocio_id)

@login_required
def api_agendas_profesionales(request, negocio_id):
    """API para obtener las agendas de todos los profesionales del negocio para un rango de fechas"""
    import logging
    
    logger = logging.getLogger(__name__)
    
    try:
        logger.info(f"API agendas profesionales: Iniciando para negocio {negocio_id}")
        logger.info(f"API agendas profesionales: Usuario: {request.user}")
        logger.info(f"API agendas profesionales: Autenticado: {request.user.is_authenticated}")
        logger.info(f"API agendas profesionales: Método: {request.method}")
        logger.info(f"API agendas profesionales: Headers: {dict(request.headers)}")
        
        # Verificar que el usuario esté autenticado
        if not request.user.is_authenticated:
            logger.error("API agendas profesionales: Usuario no autenticado")
            return JsonResponse({'error': 'Usuario no autenticado'}, status=401)
        
        # Obtener el negocio
        try:
            logger.info(f"API agendas profesionales: Buscando negocio con ID: {negocio_id}")
            logger.info(f"API agendas profesionales: Usuario actual: {request.user.id} - {request.user.username}")
            
            negocio = get_object_or_404(Negocio, id=negocio_id, propietario=request.user)
            logger.info(f"API agendas profesionales: Negocio encontrado: {negocio.id} - {negocio.nombre}")
        except Exception as e:
            logger.error(f"API agendas profesionales: Error obteniendo negocio: {e}")
            logger.error(f"API agendas profesionales: Tipo de error: {type(e).__name__}")
            import traceback
            logger.error(f"API agendas profesionales: Traceback: {traceback.format_exc()}")
            return JsonResponse({'error': f'Error obteniendo negocio: {str(e)}'}, status=404)
        
        # Obtener parámetros de fecha
        fecha_inicio_str = request.GET.get('fecha_inicio')
        fecha_fin_str = request.GET.get('fecha_fin')
        
        if fecha_inicio_str and fecha_fin_str:
            try:
                fecha_inicio = timezone.datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date()
                fecha_fin = timezone.datetime.strptime(fecha_fin_str, '%Y-%m-%d').date()
                logger.info(f"API agendas profesionales: Rango de fechas: {fecha_inicio} a {fecha_fin}")
                logger.info(f"API agendas profesionales: Fechas en formato ISO: {fecha_inicio.isoformat()} a {fecha_fin.isoformat()}")
            except ValueError as e:
                logger.error(f"API agendas profesionales: Error parseando fechas: {e}")
                return JsonResponse({'error': 'Formato de fecha inválido'}, status=400)
        else:
            # Si no se proporcionan fechas, usar la semana actual
            hoy = timezone.now().date()
            fecha_inicio = hoy - timedelta(days=hoy.weekday())
            fecha_fin = fecha_inicio + timedelta(days=6)
            logger.info(f"API agendas profesionales: Usando semana actual: {fecha_inicio} a {fecha_fin}")
        
        # Obtener profesionales del negocio
        try:
            from profesionales.models import Matriculacion
            logger.info(f"API agendas profesionales: Buscando matriculaciones para negocio {negocio.id}")
            
            matriculaciones = Matriculacion.objects.filter(
                negocio=negocio,
                estado='aprobada'
            ).select_related('profesional')
            
            logger.info(f"API agendas profesionales: Matriculaciones encontradas: {matriculaciones.count()}")
            
            profesionales = [mat.profesional for mat in matriculaciones]
            logger.info(f"API agendas profesionales: Encontrados {len(profesionales)} profesionales")
            
            for prof in profesionales:
                logger.info(f"  - Profesional: {prof.id} - {prof.nombre_completo}")
                
        except Exception as e:
            logger.error(f"API agendas profesionales: Error obteniendo profesionales: {e}")
            logger.error(f"API agendas profesionales: Tipo de error: {type(e).__name__}")
            import traceback
            logger.error(f"API agendas profesionales: Traceback: {traceback.format_exc()}")
            return JsonResponse({'error': f'Error obteniendo profesionales: {str(e)}'}, status=500)
        
        # Obtener reservas del negocio en el rango de fechas
        try:
            from clientes.models import Reserva
            from datetime import datetime, timedelta
            
            reservas = Reserva.objects.filter(
                peluquero=negocio,
                profesional__isnull=False,  # Solo reservas con profesional asignado
                fecha__gte=fecha_inicio,
                fecha__lte=fecha_fin
            ).select_related('cliente', 'servicio', 'profesional').order_by('fecha', 'hora_inicio')
            
            logger.info(f"API agendas profesionales: Encontradas {reservas.count()} reservas en el rango")
            
            # Log detallado de las reservas encontradas
            for reserva in reservas:
                logger.info(f"  - Reserva {reserva.id}: {reserva.fecha} {reserva.hora_inicio} - Profesional: {reserva.profesional.nombre_completo if reserva.profesional else 'Sin profesional'} - Estado: {reserva.estado}")
            
        except Exception as e:
            logger.error(f"API agendas profesionales: Error consultando reservas: {e}")
            return JsonResponse({'error': 'Error consultando reservas'}, status=500)
        
        # Organizar datos por profesional y fecha
        agendas = {}
        for profesional in profesionales:
            agendas[f'prof_{profesional.id}'] = {
                'profesional_id': f'prof_{profesional.id}',
                'nombre': profesional.nombre_completo,
                'fechas': {}
            }
        
        # Procesar cada reserva
        for reserva in reservas:
            try:
                if not reserva.profesional:
                    continue
                    
                profesional_key = f'prof_{reserva.profesional.id}'
                fecha_key = reserva.fecha.isoformat()
                hora_inicio = reserva.hora_inicio
                
                # Calcular hora de fin basada en la duración del servicio
                if reserva.servicio and reserva.servicio.duracion:
                    hora_inicio_dt = datetime.strptime(str(hora_inicio), '%H:%M:%S')
                    hora_fin_dt = hora_inicio_dt + timedelta(minutes=reserva.servicio.duracion)
                    hora_fin = hora_fin_dt.strftime('%H:%M:%S')
                else:
                    # Si no hay duración, asumir 30 minutos
                    hora_inicio_dt = datetime.strptime(str(hora_inicio), '%H:%M:%S')
                    hora_fin_dt = hora_inicio_dt + timedelta(minutes=30)
                    hora_fin = hora_fin_dt.strftime('%H:%M:%S')
                
                # Normalizar estado para el frontend
                estado_frontend = reserva.estado
                if reserva.estado == 'confirmado':
                    estado_frontend = 'confirmada'
                elif reserva.estado == 'cancelado':
                    estado_frontend = 'cancelada'
                elif reserva.estado == 'completado':
                    estado_frontend = 'completada'
                
                evento = {
                    'id': reserva.id,
                    'hora_inicio': str(hora_inicio),
                    'hora_fin': str(hora_fin),
                    'cliente': reserva.cliente.username,
                    'servicio': reserva.servicio.nombre if reserva.servicio else 'Reserva',
                    'estado': estado_frontend,
                    'color': get_color_by_estado(estado_frontend),
                    'notas': reserva.notas or ''
                }
                
                if profesional_key in agendas:
                    if fecha_key not in agendas[profesional_key]['fechas']:
                        agendas[profesional_key]['fechas'][fecha_key] = []
                    agendas[profesional_key]['fechas'][fecha_key].append(evento)
                    
            except Exception as e:
                logger.error(f"API agendas profesionales: Error procesando reserva {reserva.id}: {e}")
                continue
        
        response_data = {
            'agendas': agendas,
            'fecha_inicio': fecha_inicio.isoformat(),
            'fecha_fin': fecha_fin.isoformat(),
            'total_profesionales': len(profesionales),
            'total_reservas': reservas.count()
        }
        
        logger.info(f"API agendas profesionales: Respuesta exitosa con {len(agendas)} agendas")
        return JsonResponse(response_data)
        
    except Exception as e:
        logger.error(f"API agendas profesionales: Error general: {e}")
        import traceback
        logger.error(f"API agendas profesionales: Traceback: {traceback.format_exc()}")
        return JsonResponse({'error': f'Error interno del servidor: {str(e)}'}, status=500)

@login_required
def api_profesionales_negocio(request, negocio_id):
    """API para obtener los profesionales del negocio"""
    import logging
    
    logger = logging.getLogger(__name__)
    
    try:
        logger.info(f"API profesionales negocio: Iniciando para negocio {negocio_id}")
        
        # Verificar que el usuario esté autenticado
        if not request.user.is_authenticated:
            logger.error("API profesionales negocio: Usuario no autenticado")
            return JsonResponse({'error': 'Usuario no autenticado'}, status=401)
        
        # Obtener el negocio
        try:
            negocio = get_object_or_404(Negocio, id=negocio_id, propietario=request.user)
            logger.info(f"API profesionales negocio: Negocio {negocio.id} - {negocio.nombre}")
        except Exception as e:
            logger.error(f"API profesionales negocio: Error obteniendo negocio: {e}")
            return JsonResponse({'error': 'Negocio no encontrado'}, status=404)
        
        # Obtener todos los profesionales del negocio
        try:
            from profesionales.models import Matriculacion
            logger.info(f"API profesionales negocio: Buscando matriculaciones para negocio {negocio.id}")
            
            matriculaciones = Matriculacion.objects.filter(
                negocio=negocio,
                estado='aprobada'
            ).select_related('profesional')
            
            logger.info(f"API profesionales negocio: Matriculaciones encontradas: {matriculaciones.count()}")
            
            profesionales = []
            for mat in matriculaciones:
                profesional = mat.profesional
                profesionales.append({
                    'id': profesional.id,
                    'nombre': profesional.nombre_completo,
                    'especialidad': profesional.especialidad or 'Sin especialidad',
                    'experiencia_anos': profesional.experiencia_anos,
                    'disponible': profesional.disponible,
                    'foto_perfil': str(profesional.foto_perfil) if profesional.foto_perfil else None,
                    'color': '#3788d8'  # Color por defecto
                })
            
            logger.info(f"API profesionales negocio: Encontrados {len(profesionales)} profesionales")
            
            response_data = {
                'profesionales': profesionales,
                'total': len(profesionales),
                'negocio_id': negocio_id,
                'negocio_nombre': negocio.nombre
            }
            
            logger.info(f"API profesionales negocio: Respuesta exitosa")
            return JsonResponse(response_data)
            
        except Exception as e:
            logger.error(f"API profesionales negocio: Error obteniendo profesionales: {e}")
            logger.error(f"API profesionales negocio: Tipo de error: {type(e).__name__}")
            import traceback
            logger.error(f"API profesionales negocio: Traceback: {traceback.format_exc()}")
            return JsonResponse({'error': f'Error obteniendo profesionales: {str(e)}'}, status=500)
        
    except Exception as e:
        logger.error(f"API profesionales negocio: Error general: {e}")
        import traceback
        logger.error(f"API profesionales negocio: Traceback: {traceback.format_exc()}")
        return JsonResponse({'error': f'Error interno del servidor: {str(e)}'}, status=500)


@login_required
@require_POST
def api_cambiar_estado_reserva(request, negocio_id, reserva_id):
    """
    API para que el dueño del negocio cambie el estado de una reserva.
    Solo permite cambiar a 'completado' o 'inasistencia'.
    Usa @login_required para autenticación (protección CSRF activa).
    """
    from clientes.models import Reserva
    
    try:
        negocio = get_object_or_404(Negocio, id=negocio_id, propietario=request.user)
        reserva = get_object_or_404(Reserva, id=reserva_id, peluquero=negocio)
        
        data = json.loads(request.body)
        nuevo_estado = data.get('estado')
        notas = data.get('notas', '')
        
        estados_permitidos = ['completado', 'inasistencia']
        if nuevo_estado not in estados_permitidos:
            return JsonResponse({'error': f'Estado no permitido'}, status=400)
        
        if reserva.estado not in ['confirmado', 'pendiente']:
            return JsonResponse({'error': f'No se puede cambiar el estado de esta reserva'}, status=400)
        
        estado_anterior = reserva.estado
        reserva.estado = nuevo_estado
        if notas:
            reserva.notas = f"{reserva.notas or ''}\n[{nuevo_estado}] {notas}".strip()
        reserva.save()
        
        return JsonResponse({
            'success': True,
            'reserva_id': reserva_id,
            'estado_anterior': estado_anterior,
            'estado_nuevo': nuevo_estado,
            'mensaje': f'Reserva marcada como {nuevo_estado}'
        })
        
    except Exception as e:
        logger.error(f"Error cambiando estado de reserva: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_POST
def api_actualizar_hora_reserva(request, negocio_id, reserva_id):
    """
    API para actualizar la hora de inicio y fin de una reserva (drag and drop).
    """
    from clientes.models import Reserva
    from datetime import datetime, timedelta
    
    try:
        negocio = get_object_or_404(Negocio, id=negocio_id, propietario=request.user)
        reserva = get_object_or_404(Reserva, id=reserva_id, peluquero=negocio)
        
        data = json.loads(request.body)
        nueva_hora_inicio = data.get('hora_inicio')
        nuevo_profesional_id = data.get('profesional_id')  # Opcional: cambiar de profesional
        
        if not nueva_hora_inicio:
            return JsonResponse({'error': 'hora_inicio es requerida'}, status=400)
        
        # Parsear nueva hora de inicio
        try:
            # Normalizar formato: asegurar que tenga segundos
            if isinstance(nueva_hora_inicio, str):
                nueva_hora_inicio = nueva_hora_inicio.strip()
                if len(nueva_hora_inicio.split(':')) == 2:
                    nueva_hora_inicio += ':00'
                # Validar formato
                if not nueva_hora_inicio or not re.match(r'^\d{2}:\d{2}:\d{2}$', nueva_hora_inicio):
                    logger.error(f"Formato de hora inválido recibido: '{nueva_hora_inicio}'")
                    return JsonResponse({'error': f'Formato de hora inválido: {nueva_hora_inicio}. Use HH:MM o HH:MM:SS'}, status=400)
            else:
                logger.error(f"Tipo de hora inválido: {type(nueva_hora_inicio)}")
                return JsonResponse({'error': 'hora_inicio debe ser una cadena de texto'}, status=400)
            
            hora_inicio_dt = datetime.strptime(nueva_hora_inicio, '%H:%M:%S')
            logger.info(f"Parseando hora: '{nueva_hora_inicio}' -> {hora_inicio_dt}")
        except ValueError as e:
            logger.error(f"Error parseando hora '{nueva_hora_inicio}': {e}")
            return JsonResponse({'error': f'Formato de hora inválido: {nueva_hora_inicio}. Use HH:MM o HH:MM:SS'}, status=400)
        
        # Calcular nueva hora de fin basada en la duración del servicio
        if reserva.servicio and reserva.servicio.duracion:
            duracion_minutos = reserva.servicio.duracion
        else:
            # Si no hay duración, calcular basado en la diferencia actual
            hora_actual_inicio = datetime.strptime(str(reserva.hora_inicio), '%H:%M:%S')
            hora_actual_fin = datetime.strptime(str(reserva.hora_fin), '%H:%M:%S')
            duracion_minutos = int((hora_actual_fin - hora_actual_inicio).total_seconds() / 60)
            if duracion_minutos <= 0:
                duracion_minutos = 60  # Default a 1 hora
        
        nueva_hora_fin_dt = hora_inicio_dt + timedelta(minutes=duracion_minutos)
        nueva_hora_fin = nueva_hora_fin_dt.strftime('%H:%M:%S')
        
        # Actualizar reserva
        reserva.hora_inicio = hora_inicio_dt.time()
        reserva.hora_fin = nueva_hora_fin_dt.time()
        
        # Si se especificó un nuevo profesional, actualizarlo
        if nuevo_profesional_id:
            from profesionales.models import Profesional
            try:
                nuevo_profesional = Profesional.objects.get(id=nuevo_profesional_id)
                reserva.profesional = nuevo_profesional
            except Profesional.DoesNotExist:
                return JsonResponse({'error': 'Profesional no encontrado'}, status=400)
        
        reserva.save()
        
        logger.info(f"Reserva {reserva_id} actualizada: nueva hora {nueva_hora_inicio} - {nueva_hora_fin}")
        
        return JsonResponse({
            'success': True,
            'reserva_id': reserva_id,
            'hora_inicio': nueva_hora_inicio,
            'hora_fin': nueva_hora_fin,
            'mensaje': 'Reserva actualizada exitosamente'
        })
        
    except Exception as e:
        logger.error(f"Error actualizando hora de reserva: {e}")
        return JsonResponse({'error': str(e)}, status=500)


def negocio_publico(request, negocio_id):
    """
    Vista pública del negocio para que cualquier cliente pueda ver información
    y suscribirse a planes de suscripción
    """
    try:
        # Obtener el negocio
        negocio = get_object_or_404(Negocio, id=negocio_id, activo=True)
        
        # Obtener planes de suscripción activos
        planes_suscripcion = PlanSuscripcion.objects.filter(
            negocio=negocio,
            activo=True
        ).order_by('precio_mensual')
        
        # Obtener servicios del negocio
        servicios = ServicioNegocio.objects.filter(
            negocio=negocio,
            activo=True
        ).select_related('servicio')
        
        # Obtener profesionales del negocio
        from profesionales.models import Matriculacion
        profesionales = Matriculacion.objects.filter(
            negocio=negocio,
            estado='aprobada'
        ).select_related('profesional')
        
        # Obtener calificaciones del negocio
        calificaciones = Calificacion.objects.filter(
            negocio=negocio
        ).order_by('-fecha_calificacion')[:5]
        
        # Calcular calificación promedio
        calificacion_promedio = calificaciones.aggregate(
            promedio=Avg('puntaje')
        )['promedio'] or 0
        
        # Obtener imágenes de la galería
        imagenes_galeria = []
        imagenes_raw = ImagenGaleria.objects.filter(
            negocio=negocio,
            imagen__isnull=False
        ).exclude(imagen='').order_by('-created_at')[:6]
        
        # Filtrar solo las imágenes que realmente tienen archivos
        for img in imagenes_raw:
            try:
                if img.imagen and hasattr(img.imagen, 'url'):
                    imagenes_galeria.append(img)
            except Exception:
                # Si hay error al acceder a la imagen, la saltamos
                continue
        
        context = {
            'negocio': negocio,
            'planes_suscripcion': planes_suscripcion,
            'servicios': servicios,
            'profesionales': profesionales,
            'calificaciones': calificaciones,
            'calificacion_promedio': round(calificacion_promedio, 1),
            'total_calificaciones': calificaciones.count(),
            'imagenes_galeria': imagenes_galeria,
            'usuario_autenticado': request.user.is_authenticated,
            'es_cliente': getattr(request.user, 'tipo', None) == 'cliente' if request.user.is_authenticated else False,
        }
        
        return render(request, 'negocios/negocio_publico.html', context)
        
    except Exception as e:
        logger.error(f"Error en negocio_publico: {str(e)}")
        messages.error(request, "Error al cargar la información del negocio.")
        return redirect('inicio')

@login_required
def editar_servicio_negocio(request, servicio_negocio_id):
    """
    Vista para editar un servicio específico de un negocio
    """
    try:
        # Obtener el servicio del negocio
        servicio_negocio = get_object_or_404(ServicioNegocio, id=servicio_negocio_id)
        
        # Verificar que el usuario sea propietario del negocio
        if servicio_negocio.negocio.propietario != request.user:
            messages.error(request, "No tienes permisos para editar este servicio.")
            return redirect('negocios:mis_negocios')
        
        if request.method == 'POST':
            # Obtener datos del formulario
            nombre = request.POST.get('nombre', '').strip()
            duracion = request.POST.get('duracion')
            precio = request.POST.get('precio')
            
            # Validaciones básicas
            if not nombre:
                messages.error(request, "El nombre del servicio es obligatorio.")
                return redirect('negocios:panel_negocio', negocio_id=servicio_negocio.negocio.id)
            
            try:
                duracion = int(duracion)
                if duracion < 15 or duracion > 480:  # 15 min a 8 horas
                    messages.error(request, "La duración debe estar entre 15 minutos y 8 horas.")
                    return redirect('negocios:panel_negocio', negocio_id=servicio_negocio.negocio.id)
            except (ValueError, TypeError):
                messages.error(request, "La duración debe ser un número válido.")
                return redirect('negocios:panel_negocio', negocio_id=servicio_negocio.negocio.id)
            
            # Procesar precio
            precio_final = None
            if precio and precio.strip():
                try:
                    precio_final = float(precio)
                    if precio_final < 0:
                        messages.error(request, "El precio no puede ser negativo.")
                        return redirect('negocios:panel_negocio', negocio_id=servicio_negocio.negocio.id)
                except ValueError:
                    messages.error(request, "El precio debe ser un número válido.")
                    return redirect('negocios:panel_negocio', negocio_id=servicio_negocio.negocio.id)
            
            # Actualizar el servicio
            servicio_negocio.duracion = duracion
            servicio_negocio.precio = precio_final
            
            # Si el nombre cambió, actualizar el servicio base
            if servicio_negocio.servicio.nombre != nombre:
                servicio_negocio.servicio.nombre = nombre
                servicio_negocio.servicio.save()
            
            servicio_negocio.save()
            
            messages.success(request, f"Servicio '{nombre}' actualizado correctamente.")
            logger.info(f"Servicio {servicio_negocio.id} actualizado por usuario {request.user.id}")
            
        else:
            messages.error(request, "Método no permitido.")
            
        return redirect('negocios:panel_negocio', negocio_id=servicio_negocio.negocio.id)
        
    except Exception as e:
        logger.error(f"Error en editar_servicio_negocio: {str(e)}")
        messages.error(request, "Error al editar el servicio.")
        return redirect('negocios:mis_negocios')

@login_required
def eliminar_servicio_negocio(request, servicio_negocio_id):
    """
    Vista para eliminar un servicio específico de un negocio
    """
    try:
        # Obtener el servicio del negocio
        servicio_negocio = get_object_or_404(ServicioNegocio, id=servicio_negocio_id)
        
        # Verificar que el usuario sea propietario del negocio
        if servicio_negocio.negocio.propietario != request.user:
            messages.error(request, "No tienes permisos para eliminar este servicio.")
            return redirect('negocios:mis_negocios')
        
        # Obtener el nombre del servicio antes de eliminarlo
        nombre_servicio = servicio_negocio.servicio.nombre
        negocio_id = servicio_negocio.negocio.id
        
        # Eliminar el servicio del negocio (esto desactiva la relación)
        servicio_negocio.activo = False
        servicio_negocio.save()
        
        messages.success(request, f"Servicio '{nombre_servicio}' eliminado correctamente.")
        logger.info(f"Servicio {servicio_negocio.id} eliminado por usuario {request.user.id}")
        
        return redirect('negocios:panel_negocio', negocio_id=negocio_id)
        
    except Exception as e:
        logger.error(f"Error en eliminar_servicio_negocio: {str(e)}")
        messages.error(request, "Error al eliminar el servicio.")
        return redirect('negocios:mis_negocios')
# ── Lista Negra (bloqueo de clientes incumplidos) ──
@login_required
def lista_negra(request, negocio_id):
    negocio = get_object_or_404(Negocio, id=negocio_id, propietario=request.user)
    
    from clientes.models import Reserva
    from django.contrib.auth import get_user_model
    User = get_user_model()
    
    # Clientes con 2+ inasistencias en este negocio
    inasistencias = Reserva.objects.filter(
        peluquero=negocio,
        estado='inasistencia',
        cliente__isnull=False
    ).values('cliente').annotate(total=Count('id')).filter(total__gte=2).order_by('-total')
    
    bloqueados = []
    for item in inasistencias:
        user = User.objects.get(id=item['cliente'])
        bloqueados.append({
            'user': user,
            'inasistencias': item['total'],
            'ultima': Reserva.objects.filter(
                peluquero=negocio, cliente=user, estado='inasistencia'
            ).order_by('-fecha').first()
        })
    
    return render(request, 'negocios/lista_negra.html', {
        'negocio': negocio,
        'bloqueados': bloqueados,
        'total_bloqueados': len(bloqueados),
    })
