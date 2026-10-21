import secrets
import time

from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from rest_framework.exceptions import APIException, AuthenticationFailed

from arenasystem.secrets import decrypt_secret
from .models import UserMFA


class MFAUnavailable(APIException):
    status_code = 503
    default_detail = 'O autenticador esta indisponivel. Contate o suporte.'


def totp(secret):
    try:
        import pyotp
    except ImportError as exc:
        raise MFAUnavailable() from exc
    return pyotp.TOTP(secret)


@transaction.atomic
def verify_mfa(user, code):
    record = UserMFA.objects.select_for_update().filter(user=user, enabled=True).first()
    if not record:
        raise AuthenticationFailed('Autenticacao em duas etapas indisponivel.')
    step = int(time.time()) // 30
    generator = totp(decrypt_secret(record.secret_encrypted))
    for candidate in (step, step - 1, step + 1):
        if candidate > record.last_step and secrets.compare_digest(generator.at(candidate * 30), str(code)):
            record.last_step = candidate
            record.save(update_fields=['last_step'])
            return
    for index, hashed in enumerate(record.recovery_hashes):
        if check_password(str(code), hashed):
            record.recovery_hashes.pop(index)
            record.save(update_fields=['recovery_hashes'])
            return
    raise AuthenticationFailed('Codigo de autenticacao invalido ou ja utilizado.')


def recovery_codes():
    codes = [secrets.token_hex(8) for _ in range(8)]
    return codes, [make_password(code) for code in codes]
