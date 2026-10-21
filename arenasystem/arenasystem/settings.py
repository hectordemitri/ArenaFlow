from pathlib import Path
from decouple import config
from django.core.exceptions import ImproperlyConfigured
from corsheaders.defaults import default_headers

BASE_DIR = Path(__file__).resolve().parent.parent


def csv_config(name, default=''):
    return [item.strip() for item in config(name, default=default).split(',') if item.strip()]


SECRET_KEY = config('SECRET_KEY', default='django-insecure-troque-isso')
APP_ENCRYPTION_KEYS = csv_config('APP_ENCRYPTION_KEYS')
DEBUG = config('DEBUG', default=True, cast=bool)
SUPERADMIN_REQUIRE_MFA = config('SUPERADMIN_REQUIRE_MFA', default=not DEBUG, cast=bool)
DEMO_MODE = config('DEMO_MODE', default=DEBUG, cast=bool)
DEMO_ADMIN_PASSWORD = config('DEMO_ADMIN_PASSWORD', default='')
DEFAULT_ARENA_SLUG = config('DEFAULT_ARENA_SLUG', default='arenasystem-demo')
ALLOWED_HOSTS = csv_config('ALLOWED_HOSTS', default='*' if DEBUG else '')

if not DEBUG:
    if SECRET_KEY == 'django-insecure-troque-isso':
        raise ImproperlyConfigured('SECRET_KEY deve ser configurada em producao.')
    if not ALLOWED_HOSTS or '*' in ALLOWED_HOSTS:
        raise ImproperlyConfigured('ALLOWED_HOSTS deve ser restrito em producao.')

INSTALLED_APPS = [
    'arenasystem.apps.ArenaFlowAdminConfig',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Bibliotecas da API
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'drf_spectacular',
    'drf_spectacular_sidecar',

    # Apps do projeto
    'usuarios',
    'arena',
    'aulas',
    'manutencao',
    'loja',
    'notificacoes.apps.NotificacoesConfig',
    'dashboard',
    'gestao',
    'saas_billing.apps.SaasBillingConfig',
    'saas_ops.apps.SaasOpsConfig',
]
MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',  # ← adicionar AQUI no topo
    'arenasystem.observability.RequestIDMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'arena.middleware.CurrentRequestMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'arenasystem.urls'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'],
    'APP_DIRS': True,
    'OPTIONS': {
        'context_processors': [
            'django.template.context_processors.debug',
            'django.template.context_processors.request',
            'django.contrib.auth.context_processors.auth',
            'django.contrib.messages.context_processors.messages',
        ],
    },
}]

WSGI_APPLICATION = 'arenasystem.wsgi.application'

DATABASE_URL = config('DATABASE_URL', default='')
if DATABASE_URL:
    import dj_database_url
    DATABASES = {'default': dj_database_url.parse(
        DATABASE_URL,
        conn_max_age=600,
        conn_health_checks=True,
        ssl_require=not DEBUG,
    )}
    if not DEBUG and DATABASES['default']['ENGINE'] != 'django.db.backends.postgresql':
        raise ImproperlyConfigured('DATABASE_URL deve apontar para PostgreSQL fora do desenvolvimento.')
else:
    if not DEBUG:
        raise ImproperlyConfigured('DATABASE_URL PostgreSQL deve ser configurada fora do desenvolvimento.')
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

AUTH_USER_MODEL = 'usuarios.Usuario'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 10}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Sao_Paulo'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}
MEDIA_STORAGE_BUCKET = config('MEDIA_STORAGE_BUCKET', default='')
BACKUP_STORAGE_BUCKET = config('BACKUP_STORAGE_BUCKET', default='')
if MEDIA_STORAGE_BUCKET:
    STORAGES['default'] = {
        'BACKEND': 'storages.backends.s3.S3Storage',
        'OPTIONS': {
            'bucket_name': MEDIA_STORAGE_BUCKET,
            'access_key': config('MEDIA_STORAGE_ACCESS_KEY', default=None),
            'secret_key': config('MEDIA_STORAGE_SECRET_KEY', default=None),
            'region_name': config('MEDIA_STORAGE_REGION', default='us-east-1'),
            'endpoint_url': config('MEDIA_STORAGE_ENDPOINT', default=None),
            'default_acl': None, 'querystring_auth': True, 'querystring_expire': 900,
            'file_overwrite': False, 'custom_domain': None,
        },
    }
MEDIA_URL = 'media/'
if BACKUP_STORAGE_BUCKET:
    STORAGES['backups'] = {
        'BACKEND': 'storages.backends.s3.S3Storage',
        'OPTIONS': {
            'bucket_name': BACKUP_STORAGE_BUCKET,
            'access_key': config('BACKUP_STORAGE_ACCESS_KEY', default=None),
            'secret_key': config('BACKUP_STORAGE_SECRET_KEY', default=None),
            'region_name': config('BACKUP_STORAGE_REGION', default='us-east-1'),
            'endpoint_url': config('BACKUP_STORAGE_ENDPOINT', default=None),
            'default_acl': None, 'querystring_auth': True, 'file_overwrite': False,
            'custom_domain': None,
        },
    }
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# E-mail (modo console — imprime no terminal)
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
DEFAULT_FROM_EMAIL = 'ArenaSystem <noreply@arenasystem.com>'

LOGIN_URL = '/admin/login/'
LOGIN_REDIRECT_URL = '/admin/'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'saas_billing.authentication.SaasAwareJWTAuthentication',
        'saas_billing.authentication.SaasAwareSessionAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_THROTTLE_RATES': {
        'auth_login': config('THROTTLE_AUTH_LOGIN', default='60/min'),
        'auth_register': config('THROTTLE_AUTH_REGISTER', default='5/hour'),
        'account_security': config('THROTTLE_ACCOUNT_SECURITY', default='10/hour'),
        'saas_webhook': config('THROTTLE_SAAS_WEBHOOK', default='120/min'),
        'student_webhook': config('THROTTLE_STUDENT_WEBHOOK', default='120/min'),
    },
}

# Configuração JWT (token de autenticação)
from datetime import timedelta
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=2),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'AUTH_HEADER_TYPES': ('Bearer',),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
}

# CORS — libera React (em desenvolvimento)
CORS_ALLOWED_ORIGINS = csv_config(
    'CORS_ALLOWED_ORIGINS',
    default='http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000',
)
CSRF_TRUSTED_ORIGINS = csv_config('CSRF_TRUSTED_ORIGINS')
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = (*default_headers, 'x-arena-id', 'x-arena-access-reason', 'x-frontend-route', 'x-idempotency-key')

if not DEBUG and any(origin == '*' for origin in CORS_ALLOWED_ORIGINS):
    raise ImproperlyConfigured('CORS_ALLOWED_ORIGINS nao pode usar wildcard em producao.')

SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=False, cast=bool)
SESSION_COOKIE_SECURE = config('SESSION_COOKIE_SECURE', default=not DEBUG, cast=bool)
CSRF_COOKIE_SECURE = config('CSRF_COOKIE_SECURE', default=not DEBUG, cast=bool)
SECURE_HSTS_SECONDS = config('SECURE_HSTS_SECONDS', default=0, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = config('SECURE_HSTS_INCLUDE_SUBDOMAINS', default=False, cast=bool)
SECURE_HSTS_PRELOAD = config('SECURE_HSTS_PRELOAD', default=False, cast=bool)
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https') if config('USE_X_FORWARDED_PROTO', default=False, cast=bool) else None

FRONTEND_URL = config('FRONTEND_URL', default='http://localhost:5173')
PUBLIC_BACKEND_URL = config('PUBLIC_BACKEND_URL', default='http://127.0.0.1:8000')
MERCADO_PAGO_CLIENT_ID = config('MERCADO_PAGO_CLIENT_ID', default='')
MERCADO_PAGO_CLIENT_SECRET = config('MERCADO_PAGO_CLIENT_SECRET', default='')
MERCADO_PAGO_REDIRECT_URI = config('MERCADO_PAGO_REDIRECT_URI', default='')
MERCADO_PAGO_WEBHOOK_SECRET = config('MERCADO_PAGO_WEBHOOK_SECRET', default='')
MERCADO_PAGO_SAAS_ACCESS_TOKEN = config('MERCADO_PAGO_SAAS_ACCESS_TOKEN', default='')
MERCADO_PAGO_SAAS_WEBHOOK_SECRET = config('MERCADO_PAGO_SAAS_WEBHOOK_SECRET', default='')
MERCADO_PAGO_SAAS_COLLECTOR_ID = config('MERCADO_PAGO_SAAS_COLLECTOR_ID', default='')

CELERY_BROKER_URL = config('REDIS_URL', default='redis://127.0.0.1:6379/0')
CACHE_REDIS_URL = config('CACHE_REDIS_URL', default=config('REDIS_URL', default=''))
if CACHE_REDIS_URL:
    CACHES = {'default': {'BACKEND': 'django.core.cache.backends.redis.RedisCache',
                          'LOCATION': CACHE_REDIS_URL, 'KEY_PREFIX': 'arenaflow',
                          'OPTIONS': {'socket_connect_timeout': 2, 'socket_timeout': 2}}}
CELERY_RESULT_BACKEND = config('CELERY_RESULT_BACKEND', default=CELERY_BROKER_URL)
CELERY_TASK_ALWAYS_EAGER = config('CELERY_TASK_ALWAYS_EAGER', default=DEBUG, cast=bool)
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {
    'generate-student-dues-hourly': {
        'task': 'arena.tasks.generate_student_dues', 'schedule': 3600.0,
    },
    'reconcile-student-payments-every-ten-minutes': {
        'task': 'arena.tasks.reconcile_student_payments', 'schedule': 600.0,
    },
    'generate-class-occurrences-hourly': {
        'task': 'aulas.tasks.generate_daily_occurrences',
        'schedule': 3600.0,
    },
    'expire-pending-checkins-every-ten-minutes': {
        'task': 'aulas.tasks.expire_pending_checkins',
        'schedule': 600.0,
    },
    'expire-access-visits-every-five-minutes': {
        'task': 'arena.tasks.expire_access_visits',
        'schedule': 300.0,
    },
    'worker-heartbeat-every-minute': {
        'task': 'saas_billing.tasks.worker_heartbeat',
        'schedule': 60.0,
    },
    'reconcile-saas-subscriptions-hourly': {
        'task': 'saas_billing.tasks.reconcile_saas_subscriptions',
        'schedule': 3600.0,
    },
    'saas-lifecycle-notifications-daily': {
        'task': 'saas_billing.tasks.send_saas_lifecycle_notifications',
        'schedule': 86400.0,
    },
    'saas-metrics-daily': {
        'task': 'saas_billing.tasks.snapshot_saas_metrics',
        'schedule': 86400.0,
    },
}

if BACKUP_STORAGE_BUCKET:
    CELERY_IMPORTS = ('saas_ops.tasks_backup',)
    CELERY_BEAT_SCHEDULE['backup-database-daily'] = {
        'task': 'saas_ops.tasks_backup.backup_database', 'schedule': 86400.0,
    }

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {'json': {'()': 'arenasystem.observability.JSONFormatter'}},
    'handlers': {'console': {'class': 'logging.StreamHandler', 'formatter': 'json'}},
    'loggers': {
        'arenaflow': {'handlers': ['console'], 'level': config('LOG_LEVEL', default='INFO'), 'propagate': False},
        'django.request': {'handlers': ['console'], 'level': 'WARNING', 'propagate': False},
    },
}

SENTRY_DSN = config('SENTRY_DSN', default='')
if SENTRY_DSN:
    import sentry_sdk
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=config('SENTRY_ENVIRONMENT', default='production' if not DEBUG else 'development'),
        traces_sample_rate=config('SENTRY_TRACES_SAMPLE_RATE', default=0.1, cast=float),
        send_default_pii=False,
    )

IMAGE_UPLOAD_MAX_SIZE = config('IMAGE_UPLOAD_MAX_SIZE', default=5 * 1024 * 1024, cast=int)
ALLOWED_IMAGE_EXTENSIONS = csv_config('ALLOWED_IMAGE_EXTENSIONS', default='jpg,jpeg,png,webp')
ALLOWED_IMAGE_MIME_TYPES = csv_config('ALLOWED_IMAGE_MIME_TYPES', default='image/jpeg,image/png,image/webp')

# Documentação Swagger
SPECTACULAR_SETTINGS = {
    'TITLE': 'ArenaSystem API',
    'DESCRIPTION': 'API do sistema de gestão da arena de vôlei de praia 🏐',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'SCHEMA_PATH_PREFIX': r'/api/',
    'COMPONENT_SPLIT_REQUEST': True,

    # Usa o sidecar para servir Swagger UI e Redoc localmente
    'SWAGGER_UI_DIST': 'SIDECAR',
    'SWAGGER_UI_FAVICON_HREF': 'SIDECAR',
    'REDOC_DIST': 'SIDECAR',

    'SWAGGER_UI_SETTINGS': {
        'deepLinking': True,
        'persistAuthorization': True,
        'displayOperationId': False,
    },
}
# ─────────────────────────────────────────────
#   CONFIGURAÇÃO DE E-MAIL
# ─────────────────────────────────────────────

# Em desenvolvimento, e-mails aparecem no terminal. Em producao configure SMTP por ambiente.
EMAIL_BACKEND = config(
    'EMAIL_BACKEND',
    default='django.core.mail.backends.console.EmailBackend' if DEBUG else 'django.core.mail.backends.smtp.EmailBackend',
)
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='ArenaFlow <noreply@arenaflow.com.br>')
EMAIL_HOST = config('EMAIL_HOST', default='')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')

# Para usar Gmail em produção, descomente as linhas abaixo
# e configure no .env:
# EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
# EMAIL_HOST = 'smtp.gmail.com'
# EMAIL_PORT = 587
# EMAIL_USE_TLS = True
# EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
# EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
