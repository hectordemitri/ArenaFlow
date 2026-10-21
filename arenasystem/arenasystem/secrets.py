import base64
import hashlib

from cryptography.fernet import Fernet, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def secret_cipher():
    keys = settings.APP_ENCRYPTION_KEYS
    if not keys:
        if not settings.DEBUG:
            raise ImproperlyConfigured('Configure APP_ENCRYPTION_KEYS para proteger as credenciais.')
        keys = [base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest()).decode()]
    return MultiFernet([Fernet(key.encode()) for key in keys])


def encrypt_secret(value):
    return secret_cipher().encrypt(value.encode()).decode() if value else ''


def decrypt_secret(value):
    return secret_cipher().decrypt(value.encode()).decode() if value else ''
