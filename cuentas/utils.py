import logging
from datetime import datetime
from django.contrib.auth.models import AnonymousUser

# Loggers específicos
logger_activity = logging.getLogger('melissa.activity')
logger_security = logging.getLogger('melissa.security')
logger_errors = logging.getLogger('melissa.errors')
logger_business = logging.getLogger('melissa.business')
logger_recordatorios = logging.getLogger('melissa.recordatorios')

def log_user_activity(user, action, details=None, ip_address=None):
    """Registra actividad de usuario"""
    if isinstance(user, AnonymousUser):
        user_info = {'username': 'Anonymous', 'tipo': 'Anonymous'}
    else:
        user_info = {
            'username': user.username,
            'email': getattr(user, 'email', ''),
            'tipo': getattr(user, 'tipo', ''),
            'ip': ip_address,
            'action': action,
            'details': details,
            'timestamp': datetime.now().isoformat(),
        }
    
    logger_activity.info(
        f"Actividad de usuario: {user_info['username']} ({user_info['tipo']}) - {action}",
        extra={'user_info': user_info}
    )

def log_security_event(user, event_type, details=None, ip_address=None):
    """Registra eventos de seguridad"""
    if user is None:
        user_info = {'username': 'Unknown', 'tipo': 'Unknown'}
    elif isinstance(user, AnonymousUser):
        user_info = {'username': 'Anonymous', 'tipo': 'Anonymous'}
    else:
        user_info = {
            'username': user.username,
            'email': getattr(user, 'email', ''),
            'tipo': getattr(user, 'tipo', ''),
            'ip': ip_address,
            'event_type': event_type,
            'details': details,
            'timestamp': datetime.now().isoformat(),
        }
    
    logger_security.warning(
        f"Evento de seguridad: {user_info['username']} - {event_type}",
        extra={'user_info': user_info}
    )

def log_business_activity(user, business, action, details=None):
    """Registra actividad relacionada con negocios"""
    user_info = {
        'username': user.username if not isinstance(user, AnonymousUser) else 'Anonymous',
        'business_id': business.id if business else None,
        'business_name': business.nombre if business else None,
        'action': action,
        'details': details,
        'timestamp': datetime.now().isoformat(),
    }
    
    logger_business.info(
        f"Actividad de negocio: {user_info['username']} - {action} en {user_info['business_name']}",
        extra={'user_info': user_info}
    )

def log_reservation_activity(user, reservation, action, details=None):
    """Registra actividad relacionada con reservas"""
    user_info = {
        'username': user.username if not isinstance(user, AnonymousUser) else 'Anonymous',
        'reservation_id': reservation.id if reservation else None,
        'action': action,
        'details': details,
        'timestamp': datetime.now().isoformat(),
    }
    
    logger_activity.info(
        f"Actividad de reserva: {user_info['username']} - {action}",
        extra={'user_info': user_info}
    )

def log_reminder_activity(reminder_type, user_email, status, details=None):
    """Registra actividad de recordatorios"""
    reminder_info = {
        'reminder_type': reminder_type,
        'user_email': user_email,
        'status': status,
        'details': details,
        'timestamp': datetime.now().isoformat(),
    }
    
    logger_recordatorios.info(
        f"Recordatorio {reminder_type}: {user_email} - {status}",
        extra={'reminder_info': reminder_info}
    )

def log_error(error_type, error_message, user=None, context=None):
    """Registra errores críticos"""
    error_info = {
        'error_type': error_type,
        'error_message': error_message,
        'username': user.username if user and not isinstance(user, AnonymousUser) else 'Anonymous',
        'context': context,
        'timestamp': datetime.now().isoformat(),
    }
    
    logger_errors.error(
        f"Error crítico: {error_type} - {error_message}",
        extra={'error_info': error_info}
    )

def log_api_activity(user, endpoint, method, status_code, response_time=None):
    """Registra actividad de APIs"""
    api_info = {
        'username': user.username if user and not isinstance(user, AnonymousUser) else 'Anonymous',
        'endpoint': endpoint,
        'method': method,
        'status_code': status_code,
        'response_time': response_time,
        'timestamp': datetime.now().isoformat(),
    }
    
    logger_activity.info(
        f"API Activity: {method} {endpoint} - {status_code}",
        extra={'api_info': api_info}
    ) 

def get_rate_limit_config(clave, default=None):
    """
    Obtener configuración de rate limiting desde la base de datos
    """
    try:
        from .models import RateLimitConfig
        return RateLimitConfig.get_config(clave, default)
    except Exception as e:
        logger_errors.error(f"Error obteniendo configuración de rate limiting para {clave}: {e}")
        return default 