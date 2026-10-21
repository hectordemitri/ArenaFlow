import secrets

from django.conf import settings
from django.core import signing
from django.http import HttpResponseRedirect
from django.utils import timezone
from urllib.parse import urlencode
from rest_framework import permissions, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from gestao.audit import registrar_auditoria
from saas_billing.services import verify_mercado_pago_signature
from usuarios.permissions import papel_usuario
from .models import Arena, PaymentAccount
from .payment_accounts import finish_authorization, start_authorization
from .payments import apply_payment
from .services import MercadoPagoAPIError, MercadoPagoConfigError, obter_pagamento
from .tenant import get_request_arena


@api_view(['GET', 'POST', 'DELETE'])
@permission_classes([permissions.IsAuthenticated])
def payment_account(request):
    if papel_usuario(request.user) not in {'dono', 'superadmin_saas'}:
        return Response({'detail': 'Somente o responsavel pode configurar recebimentos.'}, status=403)
    arena = get_request_arena(request)
    account = PaymentAccount.objects.filter(arena=arena, disconnected_at__isnull=True).first()
    if request.method == 'GET':
        return Response({'connected': bool(account), 'collector_id': account.collector_id if account else '',
                         'connected_at': account.connected_at if account else None,
                         'configured': bool(settings.MERCADO_PAGO_CLIENT_ID and settings.MERCADO_PAGO_CLIENT_SECRET
                                            and settings.MERCADO_PAGO_WEBHOOK_SECRET and settings.MERCADO_PAGO_REDIRECT_URI)})
    if request.method == 'DELETE':
        if account:
            account.disconnected_at = timezone.now()
            account.access_token_encrypted = account.refresh_token_encrypted = ''
            account.save(update_fields=['disconnected_at', 'access_token_encrypted', 'refresh_token_encrypted'])
            registrar_auditoria(request, arena, 'payment_account.disconnected', account)
        return Response(status=204)
    try:
        state, url = start_authorization(arena, request.user)
    except MercadoPagoConfigError as exc:
        return Response({'detail': str(exc)}, status=503)
    ticket = signing.dumps({'state': state, 'authorization_url': url}, salt='student-payment-handoff')
    response = Response({'authorization_url': f'{settings.PUBLIC_BACKEND_URL}/api/mercado-pago/authorize/?' + urlencode({'ticket': ticket})})
    response['Cache-Control'] = 'no-store'
    return response


@api_view(['GET'])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
def payment_oauth_authorize(request):
    try:
        data = signing.loads(request.query_params.get('ticket', ''), salt='student-payment-handoff', max_age=60)
    except signing.BadSignature:
        return Response({'detail': 'Conexao expirada. Inicie novamente pelo painel.'}, status=400)
    # Set the binding cookie during top-level navigation, including on different frontend/API domains.
    response = HttpResponseRedirect(data['authorization_url'])
    response.set_cookie('mp_oauth_state', data['state'], max_age=600, httponly=True,
                        secure=not settings.DEBUG, samesite='Lax', path='/api/mercado-pago/')
    response['Cache-Control'] = 'no-store'
    response['Referrer-Policy'] = 'no-referrer'
    return response


@api_view(['GET'])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
def payment_oauth_callback(request):
    state = request.query_params.get('state', '')
    cookie = request.COOKIES.get('mp_oauth_state', '')
    if not state or not cookie or not secrets.compare_digest(state, cookie):
        return Response({'detail': 'Autorizacao invalida. Inicie a conexao pelo painel da arena.'}, status=400)
    result = 'error'
    try:
        if request.query_params.get('code'):
            account = finish_authorization(state, request.query_params['code'])
            registrar_auditoria(None, account.arena, 'payment_account.connected', account, usuario=account.connected_by,
                                novos={'collector_id': account.collector_id})
            result = 'connected'
    except (MercadoPagoAPIError, MercadoPagoConfigError):
        pass
    response = HttpResponseRedirect(f'{settings.FRONTEND_URL}/admin/mensalidades?mercado_pago={result}')
    response.delete_cookie('mp_oauth_state', path='/api/mercado-pago/')
    response['Cache-Control'] = 'no-store'
    response['Referrer-Policy'] = 'no-referrer'
    return response


class PaymentWebhookThrottle(ScopedRateThrottle):
    scope = 'student_webhook'

    def allow_request(self, request, view):
        view.throttle_scope = self.scope
        return super().allow_request(request, view)


@api_view(['POST'])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
@throttle_classes([PaymentWebhookThrottle])
def mercado_pago_webhook(request, arena_id=None):
    if not isinstance(request.data, dict):
        return Response({'detail': 'Notificacao invalida.'}, status=400)
    # Only the query resource ID is covered by the provider signature.
    payment_id = request.query_params.get('data.id', '')
    if not payment_id.isdigit() or not verify_mercado_pago_signature(
        request.headers.get('x-signature'), request.headers.get('x-request-id'), payment_id,
        secret=settings.MERCADO_PAGO_WEBHOOK_SECRET,
    ):
        return Response({'detail': 'Notificacao nao autenticada.'}, status=401)
    if request.data.get('type') not in {None, 'payment'}:
        return Response({'detail': 'Evento ignorado.'})
    if arena_id is None:
        account = PaymentAccount.objects.filter(collector_id=str(request.data.get('user_id', '')),
                                                disconnected_at__isnull=True).first()
        arena_id = account.arena_id if account else None
    arena = Arena.objects.filter(pk=arena_id, payment_account__disconnected_at__isnull=True,
                                 payment_account__isnull=False).first()
    if not arena:
        return Response({'detail': 'Conta de recebimento indisponivel.'}, status=404)
    try:
        payment = obter_pagamento(payment_id, arena)
        if str(payment.get('id')) != payment_id:
            raise ValidationError('Identificador divergente.')
        apply_payment(arena, payment, request)
    except MercadoPagoConfigError:
        return Response({'detail': 'Conta precisa ser reconectada.'}, status=503)
    except MercadoPagoAPIError:
        return Response({'detail': 'Consulta indisponivel. A notificacao pode ser repetida.'}, status=502)
    except ValidationError:
        return Response({'detail': 'Pagamento nao corresponde a cobranca desta arena.'}, status=400)
    return Response({'detail': 'Notificacao processada.'}, status=status.HTTP_200_OK)
