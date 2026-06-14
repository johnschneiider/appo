import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv
import socket

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# --- Carga robusta de .env en producción ---
# En VPS/systemd no siempre se garantiza el cwd, y python-dotenv puede ignorar líneas inválidas.
# Por eso: 1) intentamos cargar explícitamente BASE_DIR/.env 2) si aún faltan vars críticas,
# aplicamos un parser mínimo de respaldo (KEY=VALUE).
def _load_dotenv_explicit():
    env_path = BASE_DIR / '.env'
    if not env_path.exists():
        return
    try:
        # No sobreescribir variables ya definidas por el entorno/systemd
        try:
            load_dotenv(dotenv_path=env_path, encoding='utf-8', override=False)
        except TypeError:
            load_dotenv(dotenv_path=env_path, override=False)
    except Exception as e:
        print(f"Warning: Error cargando .env explícito ({env_path}): {e}")


def _load_env_fallback_parser():
    """
    Parser de respaldo (muy simple) para .env cuando python-dotenv no logra parsear algunas líneas.
    - Ignora líneas vacías y comentarios (# al inicio)
    - Toma KEY=VALUE (primer '=')
    - Remueve comillas simples/dobles envolventes
    - No sobreescribe variables ya definidas
    """
    env_path = BASE_DIR / '.env'
    if not env_path.exists():
        return
    try:
        for raw_line in env_path.read_text(encoding='utf-8', errors='replace').splitlines():
            line = raw_line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' not in line:
                continue
            key, value = line.split('=', 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            # Remover comillas envolventes
            if (len(value) >= 2) and ((value[0] == value[-1]) and value[0] in ("'", '"')):
                value = value[1:-1]
            # No sobreescribir si ya existe y no está vacío
            if os.environ.get(key):
                continue
            os.environ[key] = value
    except Exception as e:
        print(f"Warning: Error en parser fallback de .env: {e}")


_load_dotenv_explicit()
# Parser fallback SIEMPRE (no sobreescribe vars existentes).
# Esto evita que una sola línea malformada en .env haga que no se cargue nada.
_load_env_fallback_parser()

# Forzar CSRF_USE_SESSIONS a False antes de cualquier otra cosa
CSRF_USE_SESSIONS = False

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    raise ImproperlyConfigured('La variable de entorno SECRET_KEY es obligatoria. Configúrala en .env')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'

ALLOWED_HOSTS = [
    'appo.com.co',
    'www.appo.com.co',
]
if DEBUG:
    ALLOWED_HOSTS += ['localhost', '127.0.0.1']

AUTH_USER_MODEL = 'cuentas.UsuarioPersonalizado'

# Configuración de seguridad
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'

# Forzar HTTPS en producción
SECURE_SSL_REDIRECT = not DEBUG
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Content Security Policy (implementado vía SecurityHeadersMiddleware)
CSP_POLICY = {
    "default-src": ["'self'"],
    "script-src": [
        "'self'",
        "'unsafe-inline'",
        "https://cdn.jsdelivr.net",
        "https://maps.googleapis.com",
        "https://maps.gstatic.com",
        "https://cdnjs.cloudflare.com",
        "https://code.jquery.com",
    ],
    "style-src": [
        "'self'",
        "'unsafe-inline'",
        "https://cdn.jsdelivr.net",
        "https://fonts.googleapis.com",
        "https://cdnjs.cloudflare.com",
    ],
    "img-src": [
        "'self'",
        "data:",
        "blob:",
        "https://maps.googleapis.com",
        "https://maps.gstatic.com",
        "https://*.googleusercontent.com",
    ],
    "font-src": [
        "'self'",
        "https://fonts.gstatic.com",
        "https://cdn.jsdelivr.net",
        "https://cdnjs.cloudflare.com",
    ],
    "connect-src": [
        "'self'",
        "https://maps.googleapis.com",
        "wss://appo.com.co",
    ],
    "frame-src": ["'none'"],
    "object-src": ["'none'"],
    "base-uri": ["'self'"],
    "form-action": ["'self'"],
}

# Configuración de sesiones
SESSION_COOKIE_SECURE = not DEBUG  # True en producción, False en desarrollo
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax' if DEBUG else 'Strict'
CSRF_COOKIE_SECURE = not DEBUG  # True en producción, False en desarrollo
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Lax' if DEBUG else 'Strict'
SESSION_COOKIE_AGE = 86400  # 24 horas
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_SAVE_EVERY_REQUEST = False  # Cambiado a False para evitar problemas de concurrencia
SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_CACHE_ALIAS = 'default'



CSRF_TRUSTED_ORIGINS = [
    "https://appo.com.co",
    "https://www.appo.com.co",
    "https://vitalmix.com.co",
    "https://www.vitalmix.com.co",
]
if DEBUG:
    CSRF_TRUSTED_ORIGINS += [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
# Configuración de mensajes
MESSAGE_STORAGE = 'django.contrib.messages.storage.session.SessionStorage'

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',
    
    # Third party apps
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
    'corsheaders',
    'channels',
    'widget_tweaks',
    'django_extensions',
    
    # Local apps
    'cuentas',
    'negocios',
    'billing',
    'clientes',
    'profesionales',
    'chat',
    'ia_visagismo',
    'suscripciones',
    'recordatorios.apps.RecordatoriosConfig',
    'fidelizacion',
    'django.contrib.humanize',
    'leads_admin',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'allauth.account.middleware.AccountMiddleware',
    'cuentas.middleware.AuthenticationMiddleware',
    'cuentas.middleware.UserTypeMiddleware',
    'cuentas.middleware.RateLimitMiddleware',
    'cuentas.middleware.ActivityLoggingMiddleware',
    'cuentas.middleware.SecurityHeadersMiddleware',
    'billing.middleware.SubscriptionCheckMiddleware',
    'clientes.middleware.ActividadUsuarioMiddleware',
]

ROOT_URLCONF = 'melissa.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'cuentas.context_processors.tipo_usuario',
                'cuentas.context_processors.app_metrics',
                'cuentas.context_processors.google_maps_key',
                'billing.context_processors.subscription_banner',
                'billing.context_processors.soporte_vip_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'melissa.wsgi.application'


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

# Configuración de base de datos
# Prioridad: DATABASE_URL > PostgreSQL individual > SQLite (solo desarrollo)

# Si hay DATABASE_URL, usarlo (evita problemas de codificación) pero sin bloquear producción
# si viene en un formato inesperado.
db_configured = False
database_url = os.environ.get('DATABASE_URL', '')
if database_url:
    # Limpiar y normalizar DATABASE_URL
    try:
        if isinstance(database_url, bytes):
            database_url = database_url.decode('utf-8', errors='replace')
        database_url = str(database_url).strip()
        database_url.encode('utf-8')

        # Aceptar ambos esquemas comunes: postgres:// y postgresql://
        # (algunos proveedores/plantillas usan postgres://)
        if database_url.startswith('postgres://'):
            database_url = 'postgresql://' + database_url[len('postgres://'):]

        from urllib.parse import urlparse
        parsed = urlparse(database_url)
        if parsed.scheme in ('postgresql', 'postgres'):
            DATABASES = {
                'default': {
                    'ENGINE': 'django.db.backends.postgresql',
                }
            }
            DATABASES['default'].update({
                'NAME': parsed.path[1:] if parsed.path else 'appo_db',
                'USER': parsed.username or 'appo_user',
                'PASSWORD': parsed.password or '',
                'HOST': parsed.hostname or 'localhost',
                'PORT': str(parsed.port) if parsed.port else '5432',
                'OPTIONS': {
                    'client_encoding': 'UTF8',
                    'connect_timeout': 10,
                },
                'CONN_MAX_AGE': 600,
            })
            DATABASES['leads_db'] = {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': '/var/www/appo.com.co/data/leads_colombia.db',
            }
            db_configured = True
        else:
            # Si el esquema no corresponde a Postgres, ignorar DATABASE_URL y permitir fallback a POSTGRES_*
            database_url = ''
    except Exception as e:
        print(f"Warning: Error parseando DATABASE_URL: {e}")
        # Continuar con configuración individual
        database_url = ''

if not db_configured and os.environ.get('POSTGRES_DB'):
    # Configuración para PostgreSQL del sistema (producción/VPS)
    # Leer variables de entorno con manejo seguro de codificación
    def safe_getenv(key, default=''):
        """Obtiene variable de entorno manejando correctamente la codificación UTF-8"""
        try:
            value = os.environ.get(key, default)
            if value is None:
                return default
            
            # Si es bytes, decodificar con diferentes codificaciones
            if isinstance(value, bytes):
                # Intentar UTF-8 primero
                try:
                    value = value.decode('utf-8')
                except UnicodeDecodeError:
                    # Si falla, intentar latin-1 (que puede decodificar cualquier byte)
                    try:
                        value = value.decode('latin-1')
                        # Luego intentar convertir a UTF-8
                        value = value.encode('latin-1').decode('utf-8', errors='replace')
                    except:
                        # Último recurso: usar errors='replace'
                        value = value.decode('utf-8', errors='replace')
            
            # Si es string, asegurar que es UTF-8 válido y limpiar
            if isinstance(value, str):
                # Intentar codificar a UTF-8 para validar
                try:
                    # Normalizar y limpiar el string
                    value = value.strip()
                    # Validar que puede codificarse a UTF-8
                    value.encode('utf-8')
                except UnicodeEncodeError:
                    # Si hay caracteres no-UTF-8, limpiarlos
                    try:
                        # Asumir que viene de latin-1 y convertir
                        value = value.encode('latin-1').decode('utf-8', errors='replace')
                    except:
                        # Si todo falla, reemplazar caracteres problemáticos
                        value = value.encode('utf-8', errors='replace').decode('utf-8')
                        # Limpiar caracteres de control y no imprimibles
                        value = ''.join(char for char in value if char.isprintable() or char.isspace())
            
            return value
        except Exception as e:
            # Si hay cualquier error, usar el valor por defecto
            print(f"Warning: Error de codificación al leer {key}: {e}")
            return default
    
    # Leer variables con manejo seguro
    db_name = safe_getenv('POSTGRES_DB', 'appo_db')
    db_user = safe_getenv('POSTGRES_USER', 'appo_user')
    db_password = safe_getenv('POSTGRES_PASSWORD', '')
    db_host = safe_getenv('POSTGRES_HOST', 'localhost')
    db_port = safe_getenv('POSTGRES_PORT', '5432')
    
    # Asegurar que todos los valores son strings válidos y limpios
    db_name = str(db_name).strip() if db_name else 'appo_db'
    db_user = str(db_user).strip() if db_user else 'appo_user'
    db_password = str(db_password).strip() if db_password else ''
    db_host = str(db_host).strip() if db_host else 'localhost'
    db_port = str(db_port).strip() if db_port else '5432'
    
    # Asegurar que todos los valores están correctamente codificados como UTF-8
    # y limpiar cualquier carácter problemático
    def ensure_utf8_string(value):
        """Asegura que un valor es un string UTF-8 válido"""
        if value is None:
            return ''
        if isinstance(value, bytes):
            try:
                return value.decode('utf-8')
            except UnicodeDecodeError:
                # Intentar latin-1 como fallback
                return value.decode('latin-1').encode('latin-1').decode('utf-8', errors='replace')
        value = str(value).strip()
        # Validar y limpiar
        try:
            value.encode('utf-8')
        except UnicodeEncodeError:
            # Limpiar caracteres problemáticos
            value = value.encode('utf-8', errors='replace').decode('utf-8')
        return value
    
    # Aplicar limpieza a todos los valores
    db_name = ensure_utf8_string(db_name)
    db_user = ensure_utf8_string(db_user)
    db_password = ensure_utf8_string(db_password)
    db_host = ensure_utf8_string(db_host)
    db_port = ensure_utf8_string(db_port)
    
    # Validar que no hay caracteres de control o no imprimibles
    def clean_string(s):
        """Limpia string de caracteres problemáticos"""
        if not s:
            return s
        # Remover caracteres de control excepto espacios
        cleaned = ''.join(char for char in s if char.isprintable() or char.isspace())
        # Asegurar que es UTF-8 válido
        try:
            cleaned.encode('utf-8')
            return cleaned
        except:
            return cleaned.encode('utf-8', errors='replace').decode('utf-8')
    
    db_name = clean_string(db_name) or 'appo_db'
    db_user = clean_string(db_user) or 'appo_user'
    db_password = clean_string(db_password) or ''
    db_host = clean_string(db_host) or 'localhost'
    db_port = clean_string(db_port) or '5432'
    
    # Construir DSN manualmente con codificación correcta para evitar problemas
    # Esto evita que psycopg2 construya el DSN internamente con codificación incorrecta
    from urllib.parse import quote_plus
    
    # Codificar cada componente del DSN correctamente
    dsn_parts = []
    if db_user:
        dsn_parts.append(f"user={quote_plus(db_user)}")
    if db_password:
        dsn_parts.append(f"password={quote_plus(db_password)}")
    if db_host:
        dsn_parts.append(f"host={quote_plus(db_host)}")
    if db_port:
        dsn_parts.append(f"port={quote_plus(db_port)}")
    if db_name:
        dsn_parts.append(f"dbname={quote_plus(db_name)}")
    
    # Agregar opciones de codificación
    dsn_parts.append("client_encoding=UTF8")
    
    dsn_string = ' '.join(dsn_parts)
    
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': db_name,
            'USER': db_user,
            'PASSWORD': db_password,
            'HOST': db_host,
            'PORT': db_port,
            'OPTIONS': {
                'client_encoding': 'UTF8',
                'connect_timeout': 10,
            },
            'CONN_MAX_AGE': 600,
        },
        'leads_db': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': '/var/www/appo.com.co/data/leads_colombia.db',
        }
    }
    db_configured = True
    
    # Log del DSN (sin contraseña) para debugging
    dsn_debug = dsn_string.replace(f"password={quote_plus(db_password)}", "password=***")
    print(f"Database DSN (debug): {dsn_debug}")
elif not db_configured:
    # Configuración para SQLite SOLO en desarrollo local (si no hay PostgreSQL).
    # En producción, fallar rápido para evitar pérdida de datos por usar un SQLite local accidentalmente.
    if not DEBUG:
        raise ImproperlyConfigured(
            "Base de datos no configurada para producción. Define DATABASE_URL o POSTGRES_DB/USER/PASSWORD/HOST/PORT. "
            "Se evitó fallback a SQLite para proteger datos."
        )
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        },
        'leads_db': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': '/var/www/appo.com.co/data/leads_colombia.db',
        }
    }

# Configuración de caché
# Intentar usar Redis si está disponible (del sistema)
redis_url = os.environ.get('REDIS_URL', '')
if redis_url or not DEBUG:
    # Usar Redis en producción (del sistema)
    try:
        import redis
        CACHES = {
            'default': {
                'BACKEND': 'django.core.cache.backends.redis.RedisCache',
                'LOCATION': redis_url or 'redis://localhost:6379/1',
            }
        }
    except (ImportError, Exception):
        # Fallback a memoria local si Redis no está disponible
        CACHES = {
            'default': {
                'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            }
        }
else:
    # Configuración de caché para desarrollo local
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        }
    }

# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'es-co'

TIME_ZONE = 'America/Bogota'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [
    BASE_DIR / 'static',
]

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Marketing
# Offset para el contador público de "citas reservadas"
RESERVAS_MARKETING_OFFSET = int(os.environ.get('RESERVAS_MARKETING_OFFSET', '879') or '879')

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Configuración de archivos
FILE_UPLOAD_MAX_MEMORY_SIZE = 5242880  # 5MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 5242880  # 5MB

# Extensiones permitidas para subida de archivos
ALLOWED_IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'gif', 'webp']
ALLOWED_DOCUMENT_EXTENSIONS = ['pdf', 'doc', 'docx']
ALLOWED_UPLOAD_EXTENSIONS = ALLOWED_IMAGE_EXTENSIONS + ALLOWED_DOCUMENT_EXTENSIONS

# Configuración de django-allauth
ACCOUNT_LOGIN_METHODS = {'email', 'username'}
ACCOUNT_SIGNUP_FIELDS = ['email*', 'username*', 'password1*', 'password2*']
ACCOUNT_EMAIL_VERIFICATION = 'none'
ACCOUNT_USERNAME_MIN_LENGTH = 3
ACCOUNT_PASSWORD_MIN_LENGTH = 8
ACCOUNT_SESSION_REMEMBER = True
ACCOUNT_LOGOUT_ON_GET = False
ACCOUNT_LOGOUT_REDIRECT_URL = '/'
ACCOUNT_LOGIN_REDIRECT_URL = '/cuentas/dashboard/'
ACCOUNT_SIGNUP_REDIRECT_URL = '/'

# Custom User Model
AUTHENTICATION_BACKENDS = [
    'cuentas.backends.CaseInsensitiveAuthBackend',  # Username case-insensitive
    'allauth.account.auth_backends.AuthenticationBackend',
]

SITE_ID = 1

# Configuración de django-allauth
ACCOUNT_LOGIN_METHODS = {'email', 'username'}
ACCOUNT_SIGNUP_FIELDS = ['email*', 'username*', 'password1*', 'password2*']
ACCOUNT_SIGNUP_REDIRECT_URL = '/'

# CORS Settings
CORS_ALLOWED_ORIGINS = [
    "https://appo.com.co",
    "https://www.appo.com.co",
]
if DEBUG:
    CORS_ALLOWED_ORIGINS += [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]

CORS_ALLOW_CREDENTIALS = True

# Configuraciones adicionales de CORS
CORS_ALLOW_ALL_ORIGINS = False  # Solo permitir orígenes específicos
CORS_ALLOW_METHODS = [
    'DELETE',
    'GET',
    'OPTIONS',
    'PATCH',
    'POST',
    'PUT',
]
CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
]

# Google OAuth Settings
SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'SCOPE': [
            'profile',
            'email',
        ],
        'AUTH_PARAMS': {
            'access_type': 'online',
        },
        'OAUTH_PKCE_ENABLED': True,
    }
}

# Configuraciones adicionales para autenticación social
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_EMAIL_REQUIRED = True
SOCIALACCOUNT_EMAIL_VERIFICATION = 'none'
SOCIALACCOUNT_LOGIN_ON_GET = True

# Email Configuration (for development) - Comentado para usar SMTP real
# EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
# EMAIL_HOST = 'localhost'
# EMAIL_PORT = 1025
# EMAIL_USE_TLS = False
# EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
# EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')

# Configuración avanzada de Email con servicios profesionales
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'

# Configuración principal de email
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'True').lower() == 'true'
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'APPO <noreply@appo.com.co>')

# Configuración de SendGrid (servicio principal)
SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY', '')
SENDGRID_FROM_EMAIL = os.environ.get('SENDGRID_FROM_EMAIL', 'noreply@appo.com.co')
SENDGRID_FROM_NAME = os.environ.get('SENDGRID_FROM_NAME', 'APPO')

# Configuración de AWS SES (servicio de respaldo)
AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID', '')
AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY', '')
AWS_SES_REGION_NAME = os.environ.get('AWS_SES_REGION_NAME', 'us-east-1')
AWS_SES_REGION_ENDPOINT = os.environ.get('AWS_SES_REGION_ENDPOINT', 'email.us-east-1.amazonaws.com')

# Configuración de email avanzada
EMAIL_USE_SSL = os.environ.get('EMAIL_USE_SSL', 'False').lower() == 'true'
EMAIL_TIMEOUT = int(os.environ.get('EMAIL_TIMEOUT', '30'))
EMAIL_SSL_KEYFILE = os.environ.get('EMAIL_SSL_KEYFILE', '')
EMAIL_SSL_CERTFILE = os.environ.get('EMAIL_SSL_CERTFILE', '')

# Configuración de templates de email
EMAIL_TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates', 'emails')
EMAIL_DEFAULT_CHARSET = 'utf-8'

# Configuración de cola de emails
EMAIL_QUEUE_ENABLED = os.environ.get('EMAIL_QUEUE_ENABLED', 'False').lower() == 'true'
EMAIL_QUEUE_BATCH_SIZE = int(os.environ.get('EMAIL_QUEUE_BATCH_SIZE', '100'))
EMAIL_QUEUE_DELAY = int(os.environ.get('EMAIL_QUEUE_DELAY', '5'))

# Configuración de tracking de emails
EMAIL_TRACKING_ENABLED = os.environ.get('EMAIL_TRACKING_ENABLED', 'True').lower() == 'true'
EMAIL_OPEN_TRACKING = os.environ.get('EMAIL_OPEN_TRACKING', 'True').lower() == 'true'
EMAIL_CLICK_TRACKING = os.environ.get('EMAIL_CLICK_TRACKING', 'True').lower() == 'true'

# Configuración de rate limiting para emails
EMAIL_RATE_LIMIT = os.environ.get('EMAIL_RATE_LIMIT', '100/hour')  # 100 emails por hora
EMAIL_RATE_LIMIT_PER_USER = os.environ.get('EMAIL_RATE_LIMIT_PER_USER', '10/hour')  # 10 emails por usuario por hora

# Configuración de mensajes
MESSAGE_STORAGE = 'django.contrib.messages.storage.session.SessionStorage'

# Configuración de CSRF para desarrollo
CSRF_COOKIE_DOMAIN = None  # Permitir cookies en cualquier dominio
SESSION_COOKIE_DOMAIN = None  # Permitir cookies de sesión en cualquier dominio
CSRF_TRUSTED_ORIGINS = [
    "https://appo.com.co",
    "https://www.appo.com.co",
    "https://vitalmix.com.co",
    "https://www.vitalmix.com.co",
    "http://localhost",
    "http://localhost:80",
    "http://127.0.0.1:8000",
]

# Configuración de adaptadores personalizados
ACCOUNT_ADAPTER = 'cuentas.adapters.CustomAccountAdapter'
SOCIALACCOUNT_ADAPTER = 'cuentas.adapters.CustomSocialAccountAdapter'

# Database routers
DATABASE_ROUTERS = ['leads_admin.db_router.LeadsRouter']

# Django Channels Configuration
ASGI_APPLICATION = 'melissa.asgi.application'

# Channel Layers Configuration (Redis backend)
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            "hosts": [('127.0.0.1', 6379)],
        },
    },
}

# Configuración para desarrollo (sin Redis)
if DEBUG:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer"
        }
    }

# Configuración de Replicate (IA Generativa)
REPLICATE_API_TOKEN = os.environ.get('REPLICATE_API_TOKEN')

# Celery settings
CELERY_BROKER_URL = 'redis://localhost:6379/0'
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'

# Configuración de Twilio WhatsApp
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID', '')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN', '')
TWILIO_WHATSAPP_NUMBER = os.getenv('TWILIO_WHATSAPP_NUMBER', '+14155238886')  # Número de WhatsApp de Twilio
TWILIO_WHATSAPP_ENABLED = os.getenv('TWILIO_WHATSAPP_ENABLED', 'true').lower() == 'true'
TWILIO_TEMPLATE_TEXTO_LIBRE = os.getenv('TWILIO_TEMPLATE_TEXTO_LIBRE', '')  # Content SID (HX...) para primer contacto
TWILIO_TEMPLATE_TEXTO_LIBRE_VAR_KEY = os.getenv('TWILIO_TEMPLATE_TEXTO_LIBRE_VAR_KEY', '1')  # ej: 1 o body

# Templates específicos por evento (recomendado para producción)
# Cada variable se manda via Content API (content_sid + content_variables)
TWILIO_TEMPLATE_RESERVA_CONFIRMADA = os.getenv('TWILIO_TEMPLATE_RESERVA_CONFIRMADA', '')
TWILIO_TEMPLATE_RESERVA_CANCELADA = os.getenv('TWILIO_TEMPLATE_RESERVA_CANCELADA', '')
TWILIO_TEMPLATE_RESERVA_REAGENDADA = os.getenv('TWILIO_TEMPLATE_RESERVA_REAGENDADA', '')
TWILIO_TEMPLATE_RECORDATORIO_DIA_ANTES = os.getenv('TWILIO_TEMPLATE_RECORDATORIO_DIA_ANTES', '')
TWILIO_TEMPLATE_RECORDATORIO_TRES_HORAS = os.getenv('TWILIO_TEMPLATE_RECORDATORIO_TRES_HORAS', '')
TWILIO_TEMPLATE_INASISTENCIA = os.getenv('TWILIO_TEMPLATE_INASISTENCIA', '')

# URL base de la aplicación
if not DEBUG:
    BASE_URL = 'https://appo.com.co'  # Producción
else:
    BASE_URL = 'http://127.0.0.1:8000'  # Desarrollo

# Configuración de WhatsApp Business API (Usando Twilio)
WHATSAPP_CONFIG = {
    'ENABLED': TWILIO_WHATSAPP_ENABLED,
    'PROVIDER': 'twilio',
    'ACCOUNT_SID': TWILIO_ACCOUNT_SID,
    'AUTH_TOKEN': TWILIO_AUTH_TOKEN,
    'WHATSAPP_NUMBER': TWILIO_WHATSAPP_NUMBER,
    'TEXTO_LIBRE_VAR_KEY': TWILIO_TEMPLATE_TEXTO_LIBRE_VAR_KEY,
    'TEMPLATES': {
        'reserva_confirmada': TWILIO_TEMPLATE_RESERVA_CONFIRMADA,
        'recordatorio_dia_antes': TWILIO_TEMPLATE_RECORDATORIO_DIA_ANTES,
        'recordatorio_tres_horas': TWILIO_TEMPLATE_RECORDATORIO_TRES_HORAS,
        'reserva_cancelada': TWILIO_TEMPLATE_RESERVA_CANCELADA,
        'reserva_reagendada': TWILIO_TEMPLATE_RESERVA_REAGENDADA,
        'inasistencia': TWILIO_TEMPLATE_INASISTENCIA,
        # Template genérica para “primer mensaje” / fuera de ventana (por ejemplo: body = "{{1}}")
        'texto_libre': TWILIO_TEMPLATE_TEXTO_LIBRE,
    }
}

# Configuración de Meta WhatsApp Business API
META_WHATSAPP_ENABLED = os.getenv('META_WHATSAPP_ENABLED', 'False').lower() == 'true'
META_WHATSAPP_PHONE_NUMBER_ID = os.getenv('META_WHATSAPP_PHONE_NUMBER_ID', '')
# El token puede venir como META_WHATSAPP_ACCESS_TOKEN o TOKEN_WHATSAPP (para compatibilidad)
META_WHATSAPP_ACCESS_TOKEN = os.getenv('META_WHATSAPP_ACCESS_TOKEN') or os.getenv('TOKEN_WHATSAPP', '')
META_WHATSAPP_VERIFY_TOKEN = os.getenv('META_WHATSAPP_VERIFY_TOKEN', '')
META_WHATSAPP_WEBHOOK_SECRET = os.getenv('META_WHATSAPP_WEBHOOK_SECRET', '')
META_WHATSAPP_API_VERSION = os.getenv('META_WHATSAPP_API_VERSION', 'v22.0')

# Nombres de templates de Meta (los nombres exactos que creaste en Meta WhatsApp Manager)
META_TEMPLATE_RESERVA_CONFIRMADA = os.getenv('META_TEMPLATE_RESERVA_CONFIRMADA', 'reserva_confirmada_appo')
META_TEMPLATE_RECORDATORIO_DIA_ANTES = os.getenv('META_TEMPLATE_RECORDATORIO_DIA_ANTES', 'recordatorio_dia_antes_appo')
META_TEMPLATE_RECORDATORIO_TRES_HORAS = os.getenv('META_TEMPLATE_RECORDATORIO_TRES_HORAS', 'recordatorio_tres_horas_appo')
META_TEMPLATE_RESERVA_CANCELADA = os.getenv('META_TEMPLATE_RESERVA_CANCELADA', 'reserva_cancelada_appo')
META_TEMPLATE_RESERVA_REAGENDADA = os.getenv('META_TEMPLATE_RESERVA_REAGENDADA', 'reserva_reagendada_appo')
META_TEMPLATE_INASISTENCIA = os.getenv('META_TEMPLATE_INASISTENCIA', 'inasistencia_appo')

# Google Maps API Key (Places, Maps JavaScript, Geocoding)
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY', '')

# Configuración de Logging
import os
from pathlib import Path

# Crear directorio de logs si no existe
LOGS_DIR = BASE_DIR / 'logs'
LOGS_DIR.mkdir(exist_ok=True)

# Configuración de caché para rate limiting
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'unique-snowflake',
        'TIMEOUT': 300,  # 5 minutos
        'OPTIONS': {
            'MAX_ENTRIES': 1000,
        }
    }
}

# Configuración de Rate Limiting
RATELIMIT_ENABLE = True
RATELIMIT_USE_CACHE = 'default'
RATELIMIT_KEY_PREFIX = 'rl'

# Configuraciones específicas de rate limiting (ajustadas 8-Jun-2026)
RATELIMIT_SETTINGS = {
    'LOGIN_RATE': '20/m',  # 20 intentos POST por minuto
    'REGISTER_RATE': '30/h',  # 30 registros por hora
    'RESERVATION_RATE': '30/m',  # 30 reservas por minuto
    'API_RATE': '500/h',  # 500 requests por hora para APIs
    'GENERAL_RATE': '2000/h',  # 2000 requests por hora general
}

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
        'detailed': {
            'format': '[{asctime}] {levelname} {name} {funcName}:{lineno} - {message}',
            'style': '{',
        },
    },
    'filters': {
        'require_debug_true': {
            '()': 'django.utils.log.RequireDebugTrue',
        },
        'require_debug_false': {
            '()': 'django.utils.log.RequireDebugFalse',
        },
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'detailed',
        },
        'file_general': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGS_DIR / 'melissa_general.log',
            'maxBytes': 1024 * 1024 * 10,  # 10MB
            'backupCount': 5,
            'formatter': 'detailed',
        },
        'file_errors': {
            'level': 'ERROR',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGS_DIR / 'melissa_errors.log',
            'maxBytes': 1024 * 1024 * 10,  # 10MB
            'backupCount': 5,
            'formatter': 'detailed',
        },
        'file_security': {
            'level': 'WARNING',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGS_DIR / 'melissa_security.log',
            'maxBytes': 1024 * 1024 * 10,  # 10MB
            'backupCount': 5,
            'formatter': 'detailed',
        },
        'file_activity': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGS_DIR / 'melissa_activity.log',
            'maxBytes': 1024 * 1024 * 10,  # 10MB
            'backupCount': 5,
            'formatter': 'detailed',
        },
        'mail_admins': {
            'level': 'ERROR',
            'class': 'django.utils.log.AdminEmailHandler',
            'include_html': True,
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file_general'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['file_errors', 'mail_admins', 'console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django.security': {
            'handlers': ['file_security', 'mail_admins'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django.db.backends': {
            'handlers': ['console', 'file_errors'],
            'level': 'WARNING',
            'propagate': False,
        },
        # Loggers personalizados para Melissa
        'melissa.security': {
            'handlers': ['file_security', 'mail_admins'],
            'level': 'WARNING',
            'propagate': False,
        },
        'melissa.activity': {
            'handlers': ['file_activity', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
        'melissa.errors': {
            'handlers': ['file_errors', 'mail_admins', 'console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'melissa.business': {
            'handlers': ['file_activity', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
        'melissa.recordatorios': {
            'handlers': ['file_activity', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.server': {
            'handlers': ['console', 'file_errors'],
            'level': 'WARNING',
            'propagate': False,
        },
    },
    'root': {
        'handlers': ['console', 'file_general'],
        'level': 'WARNING',
    },
}

# Configuración de Twilio para WhatsApp y SMS
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID', '')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN', '')
TWILIO_WHATSAPP_NUMBER = os.getenv('TWILIO_WHATSAPP_NUMBER', '+14155238886')  # WhatsApp Sandbox
TWILIO_SMS_NUMBER = os.getenv('TWILIO_SMS_NUMBER', '+18578871809')  # SMS sigue usando tu número

# Configuración de recordatorios
RECORDATORIOS_EMAIL_ENABLED = True
RECORDATORIOS_WHATSAPP_ENABLED = True
RECORDATORIOS_SMS_ENABLED = False

# Fidelización (sistema alterno de mensajes programados). Para evitar duplicados
# con el sistema de recordatorios, la confirmación inmediata se puede activar explícitamente.
FIDELIZACION_CONFIRMACION_INMEDIATA = os.getenv('FIDELIZACION_CONFIRMACION_INMEDIATA', 'False').lower() == 'true'

# Configuración PayU (placeholders, modo sandbox por defecto)
PAYU_API_KEY = os.getenv('PAYU_API_KEY', '')
PAYU_API_LOGIN = os.getenv('PAYU_API_LOGIN', '')
PAYU_MERCHANT_ID = os.getenv('PAYU_MERCHANT_ID', '')
PAYU_ACCOUNT_ID = os.getenv('PAYU_ACCOUNT_ID', '')
PAYU_TEST_MODE = os.getenv('PAYU_TEST_MODE', 'true').lower() == 'true'
PAYU_BASE_URL = os.getenv('PAYU_BASE_URL', 'https://sandbox.api.payulatam.com/payments-api/4.0/')
# ── Bold Payment Gateway ──
# Docs: https://developers.bold.co/pagos-en-linea/api-link-de-pagos
# Obtener llaves en: https://panel.bold.co → Integraciones → Llaves de integración → Botón de pagos
BOLD_API_KEY = os.environ.get('BOLD_API_KEY', '')
BOLD_SECRET_KEY = os.environ.get('BOLD_SECRET_KEY', '')
