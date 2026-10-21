from .settings import *  # noqa: F403,F401

# Only for the isolated automated suite; preserve DATABASE_URL for PostgreSQL CI.
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
CELERY_TASK_ALWAYS_EAGER = True
SUPERADMIN_REQUIRE_MFA = False
APP_ENCRYPTION_KEYS = ['AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=']
LOGGING = {'version': 1, 'disable_existing_loggers': True}
