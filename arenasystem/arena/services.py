import json
import secrets
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify


class MercadoPagoConfigError(Exception):
    pass


class MercadoPagoAPIError(Exception):
    pass


def criar_dados_iniciais_arena(arena, dados_admin=None):
    from arena.models import Plano, Quadra
    from loja.models import Categoria
    from usuarios.models import Usuario

    Quadra.objects.get_or_create(
        arena=arena,
        nome='Quadra 1',
        defaults={'tipo_areia': 'Areia', 'ativa': True, 'observacoes': 'Quadra inicial criada automaticamente.'},
    )
    Plano.objects.get_or_create(
        arena=arena,
        nome='Mensal 2x semana',
        defaults={'valor': 290, 'frequencia_semanal': 2, 'descricao': 'Plano inicial sugerido.', 'ativo': True},
    )
    Plano.objects.get_or_create(
        arena=arena,
        nome='Livre modalidades',
        defaults={'valor': 420, 'frequencia_semanal': 4, 'descricao': 'Plano inicial sugerido.', 'ativo': True},
    )
    for categoria in ['Bebidas', 'Comidas', 'Uniforme', 'Bola', 'Vestuario']:
        Categoria.objects.get_or_create(arena=arena, nome=categoria)

    dados_admin = dados_admin or {}
    email = dados_admin.get('admin_email') or arena.email_contato
    if email and not Usuario.objects.filter(arena=arena, email=email).exists():
        username_base = slugify(email.split('@')[0]) or f'admin-{arena.slug}'
        username = username_base
        contador = 1
        while Usuario.objects.filter(username=username).exists():
            contador += 1
            username = f'{username_base}{contador}'
        admin = Usuario.objects.create_user(
            username=username,
            email=email,
            first_name=dados_admin.get('admin_nome', 'Admin'),
            last_name=dados_admin.get('admin_sobrenome', arena.nome),
            tipo='admin_arena',
            papel='dono',
            arena=arena,
            is_staff=True,
        )
        senha = dados_admin.get('admin_senha') or secrets.token_urlsafe(9)
        admin.set_password(senha)
        admin.save(update_fields=['password'])
        admin._senha_temporaria = senha
        return admin
    return None


def _access_token(arena):
    from .payment_accounts import access_token_for
    return access_token_for(arena)


def _request_json(method, url, payload=None, *, arena, idempotency_key=None):
    headers = {
        'Authorization': f'Bearer {_access_token(arena)}',
        'Content-Type': 'application/json',
    }
    if idempotency_key:
        headers['X-Idempotency-Key'] = idempotency_key
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    request = Request(url, data=data, headers=headers, method=method)

    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode('utf-8'))
    except HTTPError as exc:
        raise MercadoPagoAPIError(f'Mercado Pago indisponivel para esta operacao (HTTP {exc.code}).') from exc
    except (URLError, TimeoutError, ValueError) as exc:
        raise MercadoPagoAPIError('Nao foi possivel consultar o Mercado Pago. Tente novamente.') from exc


def criar_preferencia_mensalidade(mensalidade):
    aluno = mensalidade.matricula.aluno
    external_reference = mensalidade.external_reference or f'mensalidade:{mensalidade.arena_id}:{uuid.uuid4()}'
    # Persist the reference before the external call so a retry keeps the same identity.
    mensalidade.external_reference = external_reference
    mensalidade.save(update_fields=['external_reference'])
    expires_at = timezone.now() + timezone.timedelta(hours=24)

    payload = {
        'items': [
            {
                'id': str(mensalidade.id),
                'title': f'Mensalidade {mensalidade.mes_referencia:%m/%Y}',
                'description': mensalidade.plano_nome if hasattr(mensalidade, 'plano_nome') else mensalidade.matricula.plano.nome,
                'quantity': 1,
                'currency_id': 'BRL',
                'unit_price': float(mensalidade.valor),
            }
        ],
        'payer': {
            'name': aluno.first_name,
            'surname': aluno.last_name,
            'email': aluno.email,
        },
        'back_urls': {
            'success': f'{settings.FRONTEND_URL}/mensalidades',
            'pending': f'{settings.FRONTEND_URL}/mensalidades',
            'failure': f'{settings.FRONTEND_URL}/mensalidades',
        },
        'notification_url': f'{settings.PUBLIC_BACKEND_URL}/api/mercado-pago/webhook/{mensalidade.arena_id}/',
        'external_reference': external_reference,
        'metadata': {'arena_id': mensalidade.arena_id, 'mensalidade_id': mensalidade.id},
        'expires': True,
        'expiration_date_from': timezone.now().isoformat(),
        'expiration_date_to': expires_at.isoformat(),
        'auto_return': 'approved',
        'payment_methods': {
            'installments': 1,
        },
    }

    preference = _request_json(
        'POST',
        'https://api.mercadopago.com/checkout/preferences',
        payload,
        arena=mensalidade.arena,
        idempotency_key=f'{external_reference}:{expires_at:%Y-%m-%d}',
    )

    mensalidade.external_reference = external_reference
    mensalidade.mercado_pago_preference_id = preference.get('id', '')
    mensalidade.mercado_pago_checkout_url = (
        preference.get('init_point')
        or preference.get('sandbox_init_point')
        or ''
    )
    mensalidade.checkout_expires_at = expires_at
    mensalidade.save(update_fields=[
        'external_reference',
        'mercado_pago_preference_id',
        'mercado_pago_checkout_url',
        'checkout_expires_at',
    ])
    return mensalidade.mercado_pago_checkout_url


def obter_pagamento(payment_id, arena):
    if not str(payment_id).isdigit():
        raise MercadoPagoAPIError('Identificador de pagamento invalido.')
    return _request_json('GET', f'https://api.mercadopago.com/v1/payments/{payment_id}', arena=arena)


def buscar_pagamentos_por_referencia(external_reference, arena):
    query = urlencode({'external_reference': external_reference})
    return _request_json('GET', f'https://api.mercadopago.com/v1/payments/search?{query}', arena=arena)
