from .settings_test import *  # noqa: F403,F401
from .settings import BASE_DIR

DEBUG = True
DEMO_MODE = False
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'e2e.sqlite3'}}
ALLOWED_HOSTS = ['127.0.0.1', 'localhost', 'testserver']
CORS_ALLOWED_ORIGINS = ['http://127.0.0.1:4173']
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
