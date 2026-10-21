from django.conf import settings
from importlib.util import find_spec
from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response

from arenasystem.secrets import encrypt_secret
from gestao.audit import registrar_auditoria
from .mfa import recovery_codes, totp, verify_mfa
from .models import UserMFA
from .throttles import AccountSecurityRateThrottle


@api_view(['GET', 'POST', 'PUT', 'DELETE'])
@throttle_classes([AccountSecurityRateThrottle])
def mfa_settings(request):
    user = request.user
    record = UserMFA.objects.filter(user=user).first()
    if request.method == 'GET':
        return Response({'enabled': bool(record and record.enabled),
                         'available': find_spec('pyotp') is not None,
                         'required': settings.SUPERADMIN_REQUIRE_MFA and user.papel_efetivo == 'superadmin_saas'})
    if not user.check_password(request.data.get('current_password', '')):
        return Response({'detail': 'Senha atual incorreta.'}, status=400)
    if find_spec('pyotp') is None:
        return Response({'detail': 'Autenticador aguardando atualizacao do servidor. Contate o suporte.'}, status=503)
    if request.method == 'POST':
        import pyotp
        if record and record.enabled:
            return Response({'detail': 'Autenticacao em duas etapas ja esta ativa.'}, status=409)
        secret = pyotp.random_base32()
        UserMFA.objects.update_or_create(user=user, defaults={
            'secret_encrypted': encrypt_secret(secret), 'enabled': False, 'recovery_hashes': [],
            'last_step': -1, 'setup_expires_at': timezone.now() + timezone.timedelta(minutes=10),
        })
        response = Response({'secret': secret, 'provisioning_uri': totp(secret).provisioning_uri(user.username, issuer_name='ArenaFlow')})
        response['Cache-Control'] = 'no-store'
        return response
    with transaction.atomic():
        record = UserMFA.objects.select_for_update().filter(user=user).first()
        if request.method == 'PUT':
            if not record or record.enabled or not record.setup_expires_at or record.setup_expires_at <= timezone.now():
                return Response({'detail': 'Configuracao expirada. Inicie novamente.'}, status=409)
            record.enabled = True
            record.save(update_fields=['enabled'])
            verify_mfa(user, request.data.get('code', ''))
            codes, hashes = recovery_codes()
            record.refresh_from_db()
            record.recovery_hashes = hashes
            record.save(update_fields=['recovery_hashes'])
            user.token_version += 1
            user.save(update_fields=['token_version'])
            registrar_auditoria(request, user.arena, 'account.mfa_enabled', user)
            response = Response({'recovery_codes': codes, 'detail': 'Autenticacao ativada. Entre novamente.'})
            response['Cache-Control'] = 'no-store'
            return response
        if record and record.enabled:
            if settings.SUPERADMIN_REQUIRE_MFA and user.papel_efetivo == 'superadmin_saas':
                return Response({'detail': 'Duas etapas sao obrigatorias para superadmin.'}, status=409)
            verify_mfa(user, request.data.get('code', ''))
            record.delete()
            user.token_version += 1
            user.save(update_fields=['token_version'])
            registrar_auditoria(request, user.arena, 'account.mfa_disabled', user)
    return Response({'detail': 'Autenticacao em duas etapas desativada.'})
