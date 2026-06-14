import logging
from django.utils.deprecation import MiddlewareMixin
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.contrib.auth.models import AnonymousUser
import json
from datetime import datetime
from django.core.cache import cache
from django.http import HttpResponseForbidden
from django.conf import settings
from django.shortcuts import render

logger = logging.getLogger(__name__)
logger_activity = logging.getLogger('melissa.activity')
logger_security = logging.getLogger('melissa.security')
logger_errors = logging.getLogger('melissa.errors')

class AuthenticationMiddleware(MiddlewareMixin):
    """
    Middleware personalizado para mejorar la experiencia de autenticación
    """
    
    def process_request(self, request):
        """Procesa cada request para mejorar la experiencia de autenticación"""
        
        # Log de requests para usuarios autenticados
        if request.user.is_authenticated:
            logger.debug(f"Request de usuario autenticado: {request.user.username} - {request.path}")
        
        # Verificar si el usuario necesita verificar su email
        if (request.user.is_authenticated and 
            not request.user.is_staff and 
            not request.user.is_superuser and
            hasattr(request.user, 'email') and 
            request.user.email and
            not request.path.startswith('/admin/') and
            not request.path.startswith('/accounts/') and
            not request.path.startswith('/cuentas/')):
            
            # Aquí puedes agregar lógica adicional para verificación de email
            pass
        
        return None
    
    def process_response(self, request, response):
        """Procesa la respuesta para agregar headers de seguridad adicionales"""
        
        # Agregar headers de seguridad
        response['X-Content-Type-Options'] = 'nosniff'
        response['X-Frame-Options'] = 'DENY'
        response['X-XSS-Protection'] = '1; mode=block'
        
        # Log de respuestas de error
        if response.status_code >= 400:
            logger.warning(f"Error {response.status_code} en {request.path} - Usuario: {request.user.username if request.user.is_authenticated else 'Anónimo'}")
        
        return response

class UserTypeMiddleware(MiddlewareMixin):
    """
    Middleware para manejar el tipo de usuario y redirecciones
    """
    
    def process_request(self, request):
        """Procesa el request para manejar tipos de usuario"""
        
        if request.user.is_authenticated:
            # Agregar información del tipo de usuario al request
            request.es_cliente = getattr(request.user, 'tipo', None) == 'cliente'
            request.es_negocio = getattr(request.user, 'tipo', None) == 'negocio'
            
            # Redirecciones basadas en el tipo de usuario
            if request.path == '/':
                if request.es_negocio and not request.user.negocios.exists():
                    # Si es negocio y no tiene negocios, sugerir crear uno
                    messages.info(request, 'Como dueño de negocio, te recomendamos crear tu primer negocio.')
                elif request.es_cliente:
                    # Si es cliente, mostrar opciones de búsqueda
                    pass
        
        return None 

class RateLimitMiddleware(MiddlewareMixin):
    """Middleware personalizado para rate limiting avanzado"""
    
    def process_request(self, request):
        # Obtener IP del cliente
        ip = self.get_client_ip(request)
        
        # Rutas que NO requieren rate limiting (APIs de polling legítimas)
        excluded_routes = [
            '/chat/api/mensajes-no-leidos/',
            '/cuentas/api/notificaciones/',
        ]
        
        # Verificar si la ruta está excluida
        current_path = request.path
        if any(current_path.startswith(excluded) for excluded in excluded_routes):
            return None  # No aplicar rate limiting a estas rutas
        
        # Rutas sensibles que requieren rate limiting
        sensitive_routes = {
            '/cuentas/login/': {'rate': '5/m', 'key': f'login_{ip}'},
            '/cuentas/registro/': {'rate': '3/h', 'key': f'register_{ip}'},
            '/clientes/reserva/': {'rate': '10/h', 'key': f'reservation_{ip}'},
            '/api/': {'rate': '200/h', 'key': f'api_{ip}'},  # Aumentado de 100 a 200
        }
        
        # Verificar si la ruta actual requiere rate limiting
        for route, config in sensitive_routes.items():
            if current_path.startswith(route):
                # Solo aplicar rate limit a POST
                if request.method != 'POST':
                    # No aplicar rate limiting a métodos diferentes de POST
                    # (GET carga página, OPTIONS preflight, etc.)
                    continue
                
                if self.is_rate_limited(config['key'], config['rate']):
                    logger_security.warning(
                        f"Rate limit excedido: {ip} -> {current_path}",
                        extra={'ip': ip, 'path': current_path}
                    )
                    return render(request, "429.html", status=429)
                break
        
        return None
    
    def is_rate_limited(self, key, rate):
        """Verificar si una clave ha excedido el rate limit"""
        try:
            # Parsear rate (ej: '5/m' -> 5 requests por minuto)
            if '/' in rate:
                limit, period = rate.split('/')
                limit = int(limit)
                
                if period == 'm':
                    window = 60  # segundos
                elif period == 'h':
                    window = 3600  # segundos
                elif period == 'd':
                    window = 86400  # segundos
                else:
                    return False
                
                # Obtener contador actual del cache
                current_count = cache.get(key, 0)
                
                if current_count >= limit:
                    return True
                
                # Incrementar contador
                cache.set(key, current_count + 1, window)
                return False
                
        except Exception as e:
            logger_errors.error(f"Error en rate limiting: {e}")
            return False
    
    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip

class ActivityLoggingMiddleware(MiddlewareMixin):
    """Middleware para registrar actividad de usuarios"""
    
    def process_request(self, request):
        # Registrar información básica de la solicitud
        if hasattr(request, 'user') and not isinstance(request.user, AnonymousUser):
            user_info = {
                'username': request.user.username,
                'email': getattr(request.user, 'email', ''),
                'tipo': getattr(request.user, 'tipo', ''),
                'ip': self.get_client_ip(request),
                'method': request.method,
                'path': request.path,
                'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                'timestamp': datetime.now().isoformat(),
            }
            
            # Log de actividad general
            logger_activity.info(
                f"Usuario {user_info['username']} ({user_info['tipo']}) accedió a {user_info['path']}",
                extra={'user_info': user_info}
            )
            
            # Log de seguridad para acciones sensibles
            sensitive_paths = [
                '/admin/', '/cuentas/login/', '/cuentas/logout/',
                '/cuentas/registro/', '/negocios/crear/', '/clientes/reserva/'
            ]
            
            if any(path in request.path for path in sensitive_paths):
                logger_security.warning(
                    f"Acceso a ruta sensible: {user_info['username']} -> {request.path}",
                    extra={'user_info': user_info}
                )
    
    def process_response(self, request, response):
        # Registrar respuestas de error
        if response.status_code >= 400:
            user_info = {
                'username': getattr(request.user, 'username', 'Anonymous') if hasattr(request, 'user') else 'Anonymous',
                'ip': self.get_client_ip(request),
                'method': request.method,
                'path': request.path,
                'status_code': response.status_code,
                'timestamp': datetime.now().isoformat(),
            }
            
            logger_errors.error(
                f"Error {response.status_code}: {request.method} {request.path}",
                extra={'user_info': user_info}
            )
        
        return response
    
    def process_exception(self, request, exception):
        # Registrar excepciones no manejadas
        user_info = {
            'username': getattr(request.user, 'username', 'Anonymous') if hasattr(request, 'user') else 'Anonymous',
            'ip': self.get_client_ip(request),
            'method': request.method,
            'path': request.path,
            'exception_type': type(exception).__name__,
            'exception_message': str(exception),
            'timestamp': datetime.now().isoformat(),
        }
        
        logger_errors.error(
            f"Excepción no manejada: {type(exception).__name__}: {str(exception)}",
            extra={'user_info': user_info}
        )
    
    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip 


class SecurityHeadersMiddleware(MiddlewareMixin):
    """Middleware para agregar encabezados de seguridad avanzados (CSP, Permissions-Policy, etc.)"""

    def process_response(self, request, response):
        # Content-Security-Policy
        csp = getattr(settings, 'CSP_POLICY', None)
        if csp:
            directives = []
            for directive, sources in csp.items():
                directives.append(f"{directive} {' '.join(sources)}")
            response['Content-Security-Policy'] = '; '.join(directives)

        # Permissions-Policy — restringir APIs del navegador
        response['Permissions-Policy'] = (
            'accelerometer=(), camera=(self), geolocation=(self), '
            'gyroscope=(), magnetometer=(), microphone=(), '
            'payment=(), usb=()'
        )

        # Cache-Control para respuestas con datos privados
        if hasattr(request, 'user') and request.user.is_authenticated:
            response['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
            response['Pragma'] = 'no-cache'

        # Evitar MIME-sniffing (refuerzo)
        response['X-Content-Type-Options'] = 'nosniff'

        # Referrer Policy
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'

        # Cross-Origin policies
        response['Cross-Origin-Opener-Policy'] = 'same-origin'

        return response