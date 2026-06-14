from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


def get_whatsapp_service():
    """
    Obtiene el servicio de WhatsApp disponible.
    Prioridad: WebJS (sesión real) > Twilio (API).
    Meta WhatsApp deshabilitado temporalmente.
    """
    # 1. WebJS (whatsapp-web.js) — misma sesión que el CRM, sin templates
    try:
        from .webjs_whatsapp_service import webjs_whatsapp_service
        if webjs_whatsapp_service.is_enabled():
            return webjs_whatsapp_service
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"Error inicializando WebJS WhatsApp: {e}")
    
    # 2. Fallback a Twilio (solo si WebJS no disponible)
    try:
        from .twilio_whatsapp_service import twilio_whatsapp_service
        if twilio_whatsapp_service.is_enabled():
            return twilio_whatsapp_service
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"Error inicializando Twilio WhatsApp: {e}")
    
    return None

def get_current_time_in_timezone():
    """
    Obtiene la hora actual en la zona horaria configurada del proyecto
    """
    return timezone.now()

def make_datetime_aware(fecha, hora):
    """
    Combina fecha y hora y las hace timezone-aware
    """
    naive_datetime = datetime.combine(fecha, hora)
    return timezone.make_aware(naive_datetime)

def is_fecha_pasada(fecha, hora):
    """
    Verifica si una fecha/hora es pasada comparando con la hora actual
    """
    fecha_hora_reserva = make_datetime_aware(fecha, hora)
    return fecha_hora_reserva < get_current_time_in_timezone()

def get_fecha_manana():
    """
    Obtiene la fecha de mañana en la zona horaria configurada
    """
    return get_current_time_in_timezone().date() + timedelta(days=1)

def get_hora_en_tres_horas():
    """
    Obtiene la hora actual + 3 horas en la zona horaria configurada
    """
    return get_current_time_in_timezone() + timezone.timedelta(hours=3)

def procesar_reservas_pasadas():
    """
    Procesa automáticamente las reservas que ya pasaron.
    Las marca como 'completadas' si no fueron canceladas.
    """
    from .models import Reserva
    
    ahora = get_current_time_in_timezone()
    reservas_pasadas = Reserva.objects.filter(
        fecha__lt=ahora.date(),
        estado__in=['pendiente', 'confirmado'],
        cliente__isnull=False  # Solo procesar reservas con cliente asignado
    )
    
    # También incluir reservas de hoy que ya pasaron la hora
    reservas_hoy_pasadas = Reserva.objects.filter(
        fecha=ahora.date(),
        hora_fin__lt=ahora.time(),
        estado__in=['pendiente', 'confirmado'],
        cliente__isnull=False
    )
    
    todas_reservas_pasadas = reservas_pasadas | reservas_hoy_pasadas
    
    completadas = 0
    mensaje_sistema = '[Sistema] Completada automáticamente.'
    
    for reserva in todas_reservas_pasadas:
        # Solo marcar como completada si no fue cancelada explícitamente
        if reserva.estado in ['pendiente', 'confirmado']:
            reserva.estado = 'completado'
            # Evitar mensajes duplicados: solo agregar si no existe ya
            if mensaje_sistema not in (reserva.notas or ''):
                reserva.notas = ((reserva.notas or '') + '\n' + mensaje_sistema).strip()
            reserva.save()
            completadas += 1
            
            # Crear notificación para el cliente (verificar si ya existe)
            from .models import NotificacionCliente
            if not NotificacionCliente.objects.filter(
                cliente=reserva.cliente,
                titulo='Cita Completada',
                mensaje__contains=str(reserva.fecha)
            ).exists():
                NotificacionCliente.objects.create(
                    cliente=reserva.cliente,
                    tipo='sistema',
                    titulo='Cita Completada',
                    mensaje=f'Tu cita del {reserva.fecha} a las {reserva.hora_inicio} ha sido marcada como completada automáticamente.',
                    url_relacionada='/clientes/mis_reservas/'
                )
    
    return completadas

def obtener_reservas_activas(cliente):
    """
    Obtiene las reservas activas (pendientes y confirmadas) que aún no han pasado
    """
    from .models import Reserva
    ahora = get_current_time_in_timezone()
    
    # Reservas futuras
    reservas_futuras = Reserva.objects.filter(
        cliente=cliente,
        fecha__gt=ahora.date(),
        estado__in=['pendiente', 'confirmado']
    )
    
    # Reservas de hoy que aún no han pasado
    reservas_hoy_activas = Reserva.objects.filter(
        cliente=cliente,
        fecha=ahora.date(),
        hora_fin__gt=ahora.time(),
        estado__in=['pendiente', 'confirmado']
    )
    
    return (reservas_futuras | reservas_hoy_activas).order_by('fecha', 'hora_inicio')

def obtener_reservas_historial(cliente):
    """
    Obtiene el historial de reservas (completadas, canceladas, inasistencias)
    """
    from .models import Reserva
    return Reserva.objects.filter(
        cliente=cliente,
        estado__in=['completado', 'cancelado', 'inasistencia']
    ).order_by('-fecha', '-hora_inicio')

def enviar_email_reserva_confirmada(reserva):
    """Envía email de confirmación cuando se crea una nueva reserva"""
    try:
        cliente = reserva.cliente
        negocio = reserva.peluquero
        profesional = reserva.profesional
        
        # Preparar contexto
        context = {
            'cliente': cliente,
            'reserva': reserva,
            'negocio': negocio,
            'profesional': profesional,
            'fecha_formateada': reserva.fecha.strftime('%A, %d de %B de %Y'),
            'hora_formateada': reserva.hora_inicio.strftime('%H:%M'),
            'request': None,  # Para compatibilidad con templates
        }
        
        # Renderizar templates
        html_content = render_to_string('emails/reserva_confirmada.html', context)
        text_content = render_to_string('emails/reserva_confirmada.txt', context)
        
        # Enviar email
        try:
            send_mail(
                subject=f'¡Reserva Confirmada! - {negocio.nombre}',
                message=text_content,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[cliente.email],
                html_message=html_content,
                fail_silently=False,
            )
            
            logger.info(f"Email de confirmación enviado a {cliente.email} para reserva #{reserva.id}")
            return True
        except Exception as e:
            logger.warning(f"Error enviando email: {str(e)}")
            return False
        
    except Exception as e:
        logger.error(f"Error enviando email de confirmación a {cliente.email}: {str(e)}")
        return False

def enviar_email_reserva_cancelada(reserva, motivo=""):
    """Envía email de cancelación cuando se cancela una reserva"""
    try:
        cliente = reserva.cliente
        negocio = reserva.peluquero
        
        # Preparar contexto
        context = {
            'cliente': cliente,
            'reserva': reserva,
            'negocio': negocio,
            'motivo': motivo,
            'fecha_formateada': reserva.fecha.strftime('%A, %d de %B de %Y'),
            'hora_formateada': reserva.hora_inicio.strftime('%H:%M'),
            'request': None,
        }
        
        # Renderizar templates
        html_content = render_to_string('emails/reserva_cancelada.html', context)
        text_content = render_to_string('emails/reserva_cancelada.txt', context)
        
        # Enviar email
        send_mail(
            subject=f'Reserva Cancelada - {negocio.nombre}',
            message=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[cliente.email],
            html_message=html_content,
            fail_silently=False,
        )
        
        logger.info(f"Email de cancelación enviado a {cliente.email} para reserva #{reserva.id}")
        return True
        
    except Exception as e:
        logger.error(f"Error enviando email de cancelación a {cliente.email}: {str(e)}")
        return False

def enviar_email_reserva_reagendada(reserva, fecha_anterior, hora_anterior):
    """Envía email de reagendamiento cuando se reagenda una reserva"""
    try:
        cliente = reserva.cliente
        negocio = reserva.peluquero
        
        # Preparar contexto
        context = {
            'cliente': cliente,
            'reserva': reserva,
            'negocio': negocio,
            'fecha_anterior': fecha_anterior,
            'hora_anterior': hora_anterior,
            'fecha_nueva': reserva.fecha.strftime('%A, %d de %B de %Y'),
            'hora_nueva': reserva.hora_inicio.strftime('%H:%M'),
            'request': None,
        }
        
        # Renderizar templates
        html_content = render_to_string('emails/reserva_reagendada.html', context)
        text_content = render_to_string('emails/reserva_reagendada.txt', context)
        
        # Enviar email
        send_mail(
            subject=f'Reserva Reagendada - {negocio.nombre}',
            message=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[cliente.email],
            html_message=html_content,
            fail_silently=False,
        )
        
        logger.info(f"Email de reagendamiento enviado a {cliente.email} para reserva #{reserva.id}")
        return True
        
    except Exception as e:
        logger.error(f"Error enviando email de reagendamiento a {cliente.email}: {str(e)}")
        return False

def enviar_notificacion_whatsapp(reserva, tipo_notificacion, **kwargs):
    """
    Envía notificación por WhatsApp según el tipo
    """
    try:
        whatsapp_service = get_whatsapp_service()
        
        if not whatsapp_service or not whatsapp_service.is_enabled():
            logger.warning("WhatsApp no está habilitado")
            return False
        
        if not reserva.get_cliente_telefono():
            logger.warning(f"La reserva #{reserva.id} no tiene teléfono de cliente configurado")
            return False
        
        if tipo_notificacion == 'reserva_confirmada':
            return whatsapp_service.send_reserva_confirmada(reserva)
        elif tipo_notificacion == 'reserva_cancelada':
            motivo = kwargs.get('motivo', '')
            return whatsapp_service.send_reserva_cancelada(reserva, motivo)
        elif tipo_notificacion == 'reserva_reagendada':
            fecha_anterior = kwargs.get('fecha_anterior')
            hora_anterior = kwargs.get('hora_anterior')
            return whatsapp_service.send_reserva_reagendada(reserva, fecha_anterior, hora_anterior)
        elif tipo_notificacion == 'recordatorio_dia_antes':
            return whatsapp_service.send_recordatorio_dia_antes(reserva)
        elif tipo_notificacion == 'recordatorio_tres_horas':
            return whatsapp_service.send_recordatorio_tres_horas(reserva)
        elif tipo_notificacion == 'inasistencia':
            motivo = kwargs.get('motivo', '')
            return whatsapp_service.send_inasistencia(reserva, motivo)
        else:
            logger.warning(f"Tipo de notificación no reconocido: {tipo_notificacion}")
            return False
            
    except Exception as e:
        logger.error(f"Error enviando notificación de WhatsApp: {str(e)}")
        return False 