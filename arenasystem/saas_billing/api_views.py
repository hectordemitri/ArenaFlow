from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes, throttle_classes
from rest_framework.response import Response

from arena.tenant import get_user_arena
from gestao.audit import registrar_auditoria, sanitize_audit_text
from usuarios.permissions import IsSaasSuperAdmin, papel_usuario

from .models import SaasInvoice, SaasMetricSnapshot, SaasPlan, SaasSubscription, SaasWebhookEvent
from .serializers import (
    ChangePlanSerializer,
    CheckoutSerializer,
    SaasInvoiceSerializer,
    SaasPlanSerializer,
    SaasSubscriptionSerializer,
)
from .services import (
    SaasBillingConfigError,
    SaasBillingProviderError,
    calculate_prorated_upgrade,
    can_fit_plan,
    create_subscription_checkout,
    create_upgrade_checkout,
    ensure_subscription,
    plan_snapshot,
    provider_request,
    sanitize_provider_payload,
    sync_legacy_arena,
    verify_mercado_pago_signature,
)
from .throttles import SaasWebhookThrottle


def _subscription(request, lock=False):
    arena = get_user_arena(request.user)
    queryset = SaasSubscription.objects.select_related('arena', 'plan', 'pending_plan')
    if lock:
        queryset = queryset.select_for_update(of=('self',))
    subscription = queryset.filter(arena=arena).first()
    return subscription or ensure_subscription(arena)


def _owner_required(request):
    if papel_usuario(request.user) not in {'dono', 'superadmin_saas'}:
        return Response({'detail': 'Somente o proprietario pode alterar a assinatura.'}, status=status.HTTP_403_FORBIDDEN)
    return None


def _audit(request, subscription, action, previous=None, new=None, metadata=None):
    registrar_auditoria(
        request,
        subscription.arena,
        action,
        subscription,
        anteriores=previous,
        novos=new,
        metadados=metadata,
    )


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def public_plans(request):
    plans = SaasPlan.objects.filter(
        published=True, monthly_price__gt=0, annual_price__gt=0,
    ).order_by('monthly_price', 'name')
    return Response(SaasPlanSerializer(plans, many=True).data)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def current_subscription(request):
    subscription = _subscription(request)
    return Response(SaasSubscriptionSerializer(subscription, context={'request': request}).data)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def subscription_checkout(request):
    denied = _owner_required(request)
    if denied:
        return denied
    serializer = CheckoutSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    if not request.user.email:
        return Response({'detail': 'Cadastre um e-mail antes de iniciar o checkout.'}, status=status.HTTP_400_BAD_REQUEST)
    with transaction.atomic():
        subscription = _subscription(request, lock=True)
        plan_id = serializer.validated_data.get('plan_id')
        if plan_id:
            subscription.plan = get_object_or_404(SaasPlan, id=plan_id, published=True)
        subscription.billing_cycle = serializer.validated_data['billing_cycle']
        subscription.save(update_fields=['plan', 'billing_cycle', 'updated_at'])
        try:
            provider = create_subscription_checkout(subscription, request.user.email)
        except SaasBillingConfigError as exc:
            transaction.set_rollback(True)
            return Response({'detail': str(exc), 'code': 'billing_not_configured'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except SaasBillingProviderError as exc:
            transaction.set_rollback(True)
            return Response({'detail': str(exc), 'code': 'billing_provider_error'}, status=status.HTTP_502_BAD_GATEWAY)
        _audit(
            request, subscription, 'saas.subscription_checkout_created',
            new={'plan': subscription.plan.code, 'billing_cycle': subscription.billing_cycle},
        )
    return Response({
        'checkout_url': provider.get('init_point') or provider.get('sandbox_init_point'),
        'subscription': SaasSubscriptionSerializer(subscription).data,
    }, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def change_plan(request):
    denied = _owner_required(request)
    if denied:
        return denied
    serializer = ChangePlanSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    target = get_object_or_404(SaasPlan, id=serializer.validated_data['plan_id'], published=True)

    with transaction.atomic():
        subscription = _subscription(request, lock=True)
        target_cycle = serializer.validated_data.get('billing_cycle', subscription.billing_cycle)
        if target.id == subscription.plan_id and target_cycle == subscription.billing_cycle:
            return Response({'detail': 'Este ja e o plano atual.'}, status=status.HTTP_409_CONFLICT)
        incompatible = can_fit_plan(subscription, target)
        if incompatible:
            return Response({
                'code': 'plan_usage_incompatible',
                'detail': 'Reduza o consumo antes de escolher este plano.',
                'resources': incompatible,
            }, status=status.HTTP_409_CONFLICT)

        current_price = subscription.plan.price_for(subscription.billing_cycle)
        target_price = target.price_for(target_cycle)
        if current_price is None or target_price is None:
            return Response({'detail': 'Os precos dos planos precisam estar configurados.'}, status=status.HTTP_409_CONFLICT)
        current_monthly = Decimal(current_price) / (12 if subscription.billing_cycle == 'annual' else 1)
        target_monthly = Decimal(target_price) / (12 if target_cycle == 'annual' else 1)
        previous = {'plan': subscription.plan.code, 'billing_cycle': subscription.billing_cycle}

        if target_cycle != subscription.billing_cycle or target_monthly <= current_monthly:
            subscription.pending_plan = target
            subscription.pending_billing_cycle = target_cycle
            subscription.save(update_fields=['pending_plan', 'pending_billing_cycle', 'updated_at'])
            _audit(
                request, subscription, 'saas.subscription_change_scheduled', previous,
                {'plan': target.code, 'billing_cycle': target_cycle},
            )
            return Response(SaasSubscriptionSerializer(subscription).data)

        amount = calculate_prorated_upgrade(subscription, target)
        if amount <= 0:
            subscription.plan = target
            subscription.save(update_fields=['plan', 'updated_at'])
            sync_legacy_arena(subscription)
            _audit(request, subscription, 'saas.subscription_upgraded', previous, {'plan': target.code, 'amount': '0.00'})
            return Response(SaasSubscriptionSerializer(subscription).data)
        try:
            invoice = create_upgrade_checkout(subscription, target, amount, request.user.email)
        except SaasBillingConfigError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except SaasBillingProviderError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        _audit(
            request, subscription, 'saas.subscription_upgrade_checkout_created', previous,
            {'target_plan': target.code, 'amount': str(amount)},
        )
        return Response({'checkout_url': invoice.checkout_url, 'invoice': SaasInvoiceSerializer(invoice).data}, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def cancel_subscription(request):
    denied = _owner_required(request)
    if denied:
        return denied
    with transaction.atomic():
        subscription = _subscription(request, lock=True)
        if subscription.status in {'canceled', 'suspended'}:
            return Response({'detail': 'A assinatura nao esta elegivel para cancelamento programado.'}, status=status.HTTP_409_CONFLICT)
        previous = subscription.status
        subscription.status = 'cancel_at_period_end'
        subscription.save(update_fields=['status', 'updated_at'])
        sync_legacy_arena(subscription)
        _audit(request, subscription, 'saas.subscription_cancel_scheduled', {'status': previous}, {'status': subscription.status})
    return Response(SaasSubscriptionSerializer(subscription).data)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def reactivate_subscription(request):
    denied = _owner_required(request)
    if denied:
        return denied
    with transaction.atomic():
        subscription = _subscription(request, lock=True)
        if subscription.status == 'cancel_at_period_end':
            subscription.status = 'active'
            subscription.save(update_fields=['status', 'updated_at'])
            sync_legacy_arena(subscription)
            _audit(request, subscription, 'saas.subscription_cancel_reverted', new={'status': 'active'})
            return Response(SaasSubscriptionSerializer(subscription).data)
        try:
            provider = create_subscription_checkout(subscription, request.user.email)
        except SaasBillingConfigError as exc:
            transaction.set_rollback(True)
            return Response({'detail': str(exc), 'code': 'billing_not_configured'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except SaasBillingProviderError as exc:
            transaction.set_rollback(True)
            return Response({'detail': str(exc), 'code': 'billing_provider_error'}, status=status.HTTP_502_BAD_GATEWAY)
        _audit(request, subscription, 'saas.subscription_reactivation_checkout_created')
    return Response({'checkout_url': provider.get('init_point') or provider.get('sandbox_init_point')}, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def invoices(request):
    subscription = _subscription(request)
    queryset = subscription.invoices.all()
    return Response(SaasInvoiceSerializer(queryset, many=True).data)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def invoice_receipt(request, invoice_id):
    subscription = _subscription(request)
    invoice = get_object_or_404(subscription.invoices, id=invoice_id, status='paid')
    if not invoice.receipt_url:
        return Response({'detail': 'Comprovante ainda nao disponibilizado pelo provedor.'}, status=status.HTTP_404_NOT_FOUND)
    return Response({'receipt_url': invoice.receipt_url})


def _period_end(start, billing_cycle):
    return start + timedelta(days=365 if billing_cycle == 'annual' else 30)


def _mark_paid(request, invoice, payment):
    now = timezone.now()
    invoice.status = 'paid'
    invoice.paid_at = now
    invoice.provider_payment_id = str(payment.get('id', invoice.provider_payment_id))
    invoice.receipt_url = payment.get('transaction_details', {}).get('external_resource_url') or ''
    invoice.save(update_fields=['status', 'paid_at', 'provider_payment_id', 'receipt_url', 'updated_at'])
    subscription = invoice.subscription
    previous = {'status': subscription.status, 'plan': subscription.plan.code}
    if invoice.kind == 'upgrade' and invoice.metadata.get('target_plan_id'):
        subscription.plan = get_object_or_404(SaasPlan, id=invoice.metadata['target_plan_id'])
    subscription.status = 'active'
    subscription.grace_ends_at = None
    subscription.current_period_start = subscription.current_period_start or now
    subscription.current_period_end = subscription.current_period_end or _period_end(now, subscription.billing_cycle)
    subscription.save(update_fields=[
        'plan', 'status', 'grace_ends_at', 'current_period_start', 'current_period_end', 'updated_at',
    ])
    sync_legacy_arena(subscription)
    _audit(request, subscription, 'saas.invoice_paid', previous, {
        'status': subscription.status, 'plan': subscription.plan.code, 'invoice_id': invoice.id,
    })


def _process_provider_resource(request, topic, resource_id):
    if topic == 'payment':
        resource = provider_request('GET', f'/v1/payments/{resource_id}')
        external_reference = resource.get('external_reference', '')
        invoice = SaasInvoice.objects.select_related('subscription', 'subscription__plan', 'arena').filter(
            external_reference=external_reference,
        ).first()
        if not invoice:
            return None
        if resource.get('status') == 'approved':
            _mark_paid(request, invoice, resource)
        elif resource.get('status') in {'rejected', 'cancelled', 'charged_back', 'refunded'}:
            invoice.status = 'refunded' if resource.get('status') in {'charged_back', 'refunded'} else 'failed'
            invoice.save(update_fields=['status', 'updated_at'])
        return invoice.arena

    if topic == 'subscription_preapproval':
        resource = provider_request('GET', f'/preapproval/{resource_id}')
        subscription = SaasSubscription.objects.select_related('arena', 'plan').filter(
            provider_preapproval_id=str(resource.get('id', resource_id)),
        ).first()
        if not subscription:
            external = str(resource.get('external_reference', ''))
            if external.startswith('saas-subscription:'):
                subscription = SaasSubscription.objects.select_related('arena', 'plan').filter(id=external.rsplit(':', 1)[-1]).first()
        if not subscription:
            return None
        subscription.provider_preapproval_id = str(resource.get('id', resource_id))
        if resource.get('status') in {'cancelled', 'paused'} and subscription.status == 'active':
            subscription.status = 'past_due'
            subscription.grace_ends_at = timezone.now() + timedelta(days=subscription.plan.grace_days)
        subscription.save(update_fields=['provider_preapproval_id', 'status', 'grace_ends_at', 'updated_at'])
        sync_legacy_arena(subscription)
        return subscription.arena

    if topic == 'subscription_authorized_payment':
        resource = provider_request('GET', f'/authorized_payments/{resource_id}')
        subscription = SaasSubscription.objects.select_related('arena', 'plan').filter(
            provider_preapproval_id=str(resource.get('preapproval_id', '')),
        ).first()
        if not subscription:
            return None
        invoice, _ = SaasInvoice.objects.get_or_create(
            external_reference=f'saas-authorized:{resource_id}',
            defaults={
                'arena': subscription.arena, 'subscription': subscription,
                'amount': resource.get('transaction_amount') or subscription.plan.price_for(subscription.billing_cycle),
                'plan_snapshot': plan_snapshot(subscription.plan),
            },
        )
        if resource.get('status') == 'approved':
            _mark_paid(request, invoice, resource)
        elif resource.get('status') in {'rejected', 'cancelled'}:
            invoice.status = 'failed'
            invoice.save(update_fields=['status', 'updated_at'])
        return subscription.arena
    return None


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
@throttle_classes([SaasWebhookThrottle])
def mercado_pago_saas_webhook(request):
    resource_id = request.query_params.get('data.id') or request.data.get('data', {}).get('id')
    topic = request.query_params.get('type') or request.data.get('type', '')
    event_id = str(request.data.get('id') or request.headers.get('X-Request-ID') or f'{topic}:{resource_id}')
    signature_valid = verify_mercado_pago_signature(
        request.headers.get('X-Signature'), request.headers.get('X-Request-ID'), resource_id,
    )
    event, created = SaasWebhookEvent.objects.get_or_create(
        provider='mercado_pago', event_id=event_id,
        defaults={
            'event_type': topic, 'action': sanitize_audit_text(request.data.get('action'), 100),
            'signature_valid': signature_valid, 'payload': sanitize_provider_payload(request.data),
        },
    )
    if not signature_valid:
        return Response({'detail': 'Assinatura invalida.'}, status=status.HTTP_401_UNAUTHORIZED)
    if not event.signature_valid:
        event.signature_valid = True
        event.save(update_fields=['signature_valid'])
    if not created and event.processed:
        return Response({'detail': 'Evento ja processado.'})
    if not resource_id or topic not in {'payment', 'subscription_preapproval', 'subscription_authorized_payment'}:
        event.processing_error = 'Evento sem recurso ou tipo nao suportado.'
        event.save(update_fields=['processing_error'])
        return Response({'detail': 'Evento ignorado.'})
    try:
        arena = _process_provider_resource(request, topic, resource_id)
    except (SaasBillingConfigError, SaasBillingProviderError) as exc:
        event.processing_error = sanitize_audit_text(exc, 500)
        event.save(update_fields=['processing_error'])
        return Response({'detail': 'Falha temporaria ao consultar o provedor.'}, status=status.HTTP_502_BAD_GATEWAY)
    event.arena = arena
    event.processed = True
    event.processed_at = timezone.now()
    event.processing_error = '' if arena else 'Recurso nao associado a uma assinatura SaaS.'
    event.save(update_fields=['arena', 'processed', 'processed_at', 'processing_error'])
    return Response({'detail': 'Webhook processado.'})


class SaasPlanAdminViewSet(viewsets.ModelViewSet):
    serializer_class = SaasPlanSerializer
    permission_classes = [IsSaasSuperAdmin]
    queryset = SaasPlan.objects.all()

    def perform_create(self, serializer):
        plan = serializer.save()
        registrar_auditoria(self.request, self.request.user.arena, 'saas.plan_created', plan, novos=serializer.data)

    def perform_update(self, serializer):
        before = SaasPlanSerializer(serializer.instance).data
        plan = serializer.save()
        registrar_auditoria(self.request, self.request.user.arena, 'saas.plan_updated', plan, anteriores=before, novos=serializer.data)

    @action(detail=False, methods=['get'])
    def metrics(self, request):
        latest = SaasMetricSnapshot.objects.first()
        statuses = {
            value: SaasSubscription.objects.filter(status=value).count()
            for value, _ in SaasSubscription.STATUSES
        }
        return Response({'latest_snapshot': latest.metrics if latest else None, 'statuses': statuses})
