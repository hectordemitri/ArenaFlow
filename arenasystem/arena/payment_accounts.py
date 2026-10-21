import base64
import hashlib
import json
import secrets
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from arenasystem.secrets import decrypt_secret, encrypt_secret
from .models import Mensalidade, PaymentAccount, PaymentOAuthAttempt
from .services import MercadoPagoAPIError, MercadoPagoConfigError


def oauth_config():
    if not all((settings.MERCADO_PAGO_CLIENT_ID, settings.MERCADO_PAGO_CLIENT_SECRET,
                settings.MERCADO_PAGO_REDIRECT_URI, settings.MERCADO_PAGO_WEBHOOK_SECRET)):
        raise MercadoPagoConfigError('A conexao com o Mercado Pago ainda nao foi configurada.')


def exchange_token(payload):
    oauth_config()
    payload = {**payload, 'client_id': settings.MERCADO_PAGO_CLIENT_ID,
               'client_secret': settings.MERCADO_PAGO_CLIENT_SECRET}
    request = Request('https://api.mercadopago.com/oauth/token',
                      data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urlopen(request, timeout=20) as response:
            result = json.loads(response.read())
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        raise MercadoPagoAPIError('Nao foi possivel autorizar a conta no Mercado Pago.') from exc
    if not all(result.get(key) for key in ('access_token', 'refresh_token', 'user_id', 'expires_in')):
        raise MercadoPagoAPIError('O Mercado Pago retornou uma autorizacao incompleta.')
    return result


def start_authorization(arena, actor):
    oauth_config()
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    PaymentOAuthAttempt.objects.create(
        arena=arena, actor=actor, state_hash=hashlib.sha256(state.encode()).hexdigest(),
        verifier_encrypted=encrypt_secret(verifier), expires_at=timezone.now() + timezone.timedelta(minutes=10),
    )
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    return state, 'https://auth.mercadopago.com/authorization?' + urlencode({
        'client_id': settings.MERCADO_PAGO_CLIENT_ID, 'response_type': 'code', 'platform_id': 'mp',
        'redirect_uri': settings.MERCADO_PAGO_REDIRECT_URI, 'state': state,
        'code_challenge': challenge, 'code_challenge_method': 'S256',
    })


@transaction.atomic
def finish_authorization(state, code):
    attempt = PaymentOAuthAttempt.objects.select_for_update().select_related('actor', 'arena').filter(
        state_hash=hashlib.sha256(state.encode()).hexdigest(), consumed_at__isnull=True,
        expires_at__gt=timezone.now(),
    ).first()
    if not attempt or not attempt.actor.is_active or not attempt.arena.ativa:
        raise MercadoPagoConfigError('Autorizacao invalida ou expirada. Inicie novamente.')
    from usuarios.permissions import papel_usuario
    role = papel_usuario(attempt.actor)
    if role != 'superadmin_saas' and (role != 'dono' or attempt.actor.arena_id != attempt.arena_id):
        raise MercadoPagoConfigError('O responsavel nao possui mais acesso a esta arena.')
    data = exchange_token({
        'grant_type': 'authorization_code', 'code': code, 'redirect_uri': settings.MERCADO_PAGO_REDIRECT_URI,
        'code_verifier': decrypt_secret(attempt.verifier_encrypted),
    })
    if PaymentAccount.objects.filter(collector_id=str(data['user_id'])).exclude(arena=attempt.arena).exists():
        raise MercadoPagoConfigError('Esta conta de recebimento ja pertence a outra arena.')
    previous = PaymentAccount.objects.filter(arena=attempt.arena).first()
    if previous and previous.collector_id != str(data['user_id']) and Mensalidade.objects.filter(
        arena=attempt.arena,
    ).exclude(mercado_pago_preference_id='').exists():
        raise MercadoPagoConfigError('Existem cobrancas vinculadas a outra conta. Solicite a migracao pelo suporte.')
    account, _ = PaymentAccount.objects.update_or_create(arena=attempt.arena, defaults={
        'collector_id': str(data['user_id']), 'access_token_encrypted': encrypt_secret(data['access_token']),
        'refresh_token_encrypted': encrypt_secret(data['refresh_token']),
        'expires_at': timezone.now() + timezone.timedelta(seconds=int(data['expires_in'])),
        'connected_by': attempt.actor, 'disconnected_at': None,
    })
    attempt.consumed_at = timezone.now()
    attempt.verifier_encrypted = ''
    attempt.save(update_fields=['consumed_at', 'verifier_encrypted'])
    return account


@transaction.atomic
def access_token_for(arena):
    account = PaymentAccount.objects.select_for_update().filter(arena=arena, disconnected_at__isnull=True).first()
    if not account:
        raise MercadoPagoConfigError('O responsavel precisa conectar o Mercado Pago desta arena.')
    if account.expires_at <= timezone.now() + timezone.timedelta(minutes=5):
        data = exchange_token({'grant_type': 'refresh_token', 'refresh_token': decrypt_secret(account.refresh_token_encrypted)})
        if str(data['user_id']) != account.collector_id:
            raise MercadoPagoAPIError('Conta de recebimento divergente na renovacao.')
        account.access_token_encrypted = encrypt_secret(data['access_token'])
        account.refresh_token_encrypted = encrypt_secret(data['refresh_token'])
        account.expires_at = timezone.now() + timezone.timedelta(seconds=int(data['expires_in']))
        account.save(update_fields=['access_token_encrypted', 'refresh_token_encrypted', 'expires_at'])
    return decrypt_secret(account.access_token_encrypted)
