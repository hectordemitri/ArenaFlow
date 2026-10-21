import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from gestao.audit import sanitize_audit_text

from .exceptions import PlanLimitReached
from .models import SaasInvoice, SaasMetricSnapshot, SaasPlan, SaasSubscription


SENSITIVE_PAYLOAD_KEYS = {
    'access_token', 'authorization', 'card', 'card_token_id', 'collector_id',
    'payer_identification', 'security_code', 'secret', 'token',
}


class SaasBillingConfigError(Exception):
    pass


class SaasBillingProviderError(Exception):
    pass


def sanitize_provider_payload(value):
    if isinstance(value, list):
        return [sanitize_provider_payload(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        lowered = str(key).lower()
        if any(sensitive in lowered for sensitive in SENSITIVE_PAYLOAD_KEYS):
            result[key] = '[mascarado]'
        else:
            result[key] = sanitize_provider_payload(item)
    return result


def plan_snapshot(plan):
    return {
        'code': plan.code,
        'name': plan.name,
        'currency': plan.currency,
        'monthly_price': str(plan.monthly_price) if plan.monthly_price is not None else None,
        'annual_price': str(plan.annual_price) if plan.annual_price is not None else None,
        'limits': {
            'admins': plan.max_admins,
            'professors': plan.max_professors,
            'students': plan.max_students,
            'courts': plan.max_courts,
            'storage_mb': plan.storage_mb,
        },
        'features': plan.features,
    }


def subscription_usage(arena):
    from arena.models import Matricula, Quadra
    from usuarios.models import Usuario

    return {
        'admins': Usuario.objects.filter(
            arena=arena, is_active=True, tipo__in=['admin', 'admin_arena', 'funcionario'],
        ).count(),
        'professors': Usuario.objects.filter(arena=arena, is_active=True, tipo='professor').count(),
        'students': Matricula.objects.filter(arena=arena, ativa=True).values('aluno_id').distinct().count(),
        'courts': Quadra.objects.filter(arena=arena, ativa=True).count(),
        'storage_mb': 0,
    }


def effective_limits(subscription):
    plan = subscription.plan
    return {
        'admins': plan.max_admins,
        'professors': plan.max_professors,
        'students': plan.max_students,
        'courts': plan.max_courts,
        'storage_mb': plan.storage_mb,
    }


def assert_plan_capacity(arena, resource, increment=1):
    subscription = SaasSubscription.objects.select_related('plan').filter(arena=arena).first()
    if not subscription:
        return
    usage = subscription_usage(arena).get(resource, 0)
    limit = effective_limits(subscription).get(resource)
    if limit is not None and usage + increment > limit:
        raise PlanLimitReached(resource, usage, limit)


def can_fit_plan(subscription, plan):
    usage = subscription_usage(subscription.arena)
    limits = {
        'admins': plan.max_admins,
        'professors': plan.max_professors,
        'students': plan.max_students,
        'courts': plan.max_courts,
        'storage_mb': plan.storage_mb,
    }
    return {key: {'usage': usage[key], 'limit': limit} for key, limit in limits.items() if usage[key] > limit}


def sync_legacy_arena(subscription):
    arena = subscription.arena
    status_map = {
        'trialing': 'trial', 'active': 'ativa', 'past_due': 'ativa',
        'suspended': 'suspensa', 'cancel_at_period_end': 'ativa', 'canceled': 'cancelada',
    }
    arena.status_assinatura = status_map[subscription.status]
    arena.plano_contratado = subscription.plan.code if subscription.plan.code in {'starter', 'professional', 'enterprise'} else arena.plano_contratado
    arena.limite_alunos = subscription.plan.max_students
    arena.limite_quadras = subscription.plan.max_courts
    arena.limite_admins = subscription.plan.max_admins
    arena.ativa = subscription.status not in {'suspended', 'canceled'}
    arena.save(update_fields=[
        'status_assinatura', 'plano_contratado', 'limite_alunos', 'limite_quadras', 'limite_admins', 'ativa',
    ])


def ensure_subscription(arena, plan_code=None):
    plan_code = plan_code or arena.plano_contratado or 'starter'
    plan, _ = SaasPlan.objects.get_or_create(
        code=plan_code,
        defaults={
            'name': plan_code.replace('-', ' ').title(),
            'max_admins': arena.limite_admins,
            'max_students': arena.limite_alunos,
            'max_courts': arena.limite_quadras,
            'published': False,
        },
    )
    now = timezone.now()
    subscription, _ = SaasSubscription.objects.get_or_create(
        arena=arena,
        defaults={
            'plan': plan,
            'status': 'trialing',
            'trial_started_at': now,
            'trial_ends_at': now + timedelta(days=plan.trial_days),
        },
    )
    return subscription


def calculate_prorated_upgrade(subscription, new_plan, now=None):
    now = now or timezone.now()
    old_price = subscription.plan.price_for(subscription.billing_cycle)
    new_price = new_plan.price_for(subscription.billing_cycle)
    if old_price is None or new_price is None:
        raise SaasBillingConfigError('Os dois planos precisam ter preco publicado para calcular o upgrade.')
    difference = Decimal(new_price) - Decimal(old_price)
    if difference <= 0:
        return Decimal('0.00')
    if not subscription.current_period_start or not subscription.current_period_end:
        return difference.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    total = max((subscription.current_period_end - subscription.current_period_start).total_seconds(), 1)
    remaining = max((subscription.current_period_end - now).total_seconds(), 0)
    return (difference * Decimal(str(remaining / total))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _saas_access_token():
    token = settings.MERCADO_PAGO_SAAS_ACCESS_TOKEN
    if not token:
        raise SaasBillingConfigError('Configure MERCADO_PAGO_SAAS_ACCESS_TOKEN.')
    return token


def provider_request(method, path, payload=None):
    headers = {'Authorization': f'Bearer {_saas_access_token()}', 'Content-Type': 'application/json'}
    body = json.dumps(payload).encode('utf-8') if payload is not None else None
    request = Request(f'https://api.mercadopago.com{path}', data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode('utf-8'))
    except HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='ignore')
        raise SaasBillingProviderError(f'Mercado Pago retornou {exc.code}: {sanitize_audit_text(detail, 300)}') from exc
    except URLError as exc:
        raise SaasBillingProviderError(f'Falha de conexao com o Mercado Pago: {exc.reason}') from exc


def create_subscription_checkout(subscription, payer_email):
    price = subscription.plan.price_for(subscription.billing_cycle)
    if not subscription.plan.published or price is None or price <= 0:
        raise SaasBillingConfigError('O plano ainda nao esta publicado com preco valido.')
    frequency = 12 if subscription.billing_cycle == 'annual' else 1
    payload = {
        'reason': f'ArenaFlow - {subscription.plan.name}',
        'external_reference': f'saas-subscription:{subscription.id}',
        'payer_email': payer_email,
        'back_url': f'{settings.FRONTEND_URL}/admin/assinatura',
        'notification_url': f'{settings.PUBLIC_BACKEND_URL}/api/saas/webhook/mercado-pago/',
        'auto_recurring': {
            'frequency': frequency,
            'frequency_type': 'months',
            'transaction_amount': float(price),
            'currency_id': subscription.plan.currency,
        },
        'status': 'pending',
    }
    if subscription.status == 'trialing' and subscription.trial_ends_at and subscription.trial_ends_at > timezone.now():
        payload['auto_recurring']['start_date'] = subscription.trial_ends_at.isoformat()
    response = provider_request('POST', '/preapproval', payload)
    subscription.provider_preapproval_id = str(response.get('id', ''))
    subscription.save(update_fields=['provider_preapproval_id', 'updated_at'])
    return response


def create_upgrade_checkout(subscription, new_plan, amount, payer_email):
    invoice = SaasInvoice.objects.create(
        arena=subscription.arena,
        subscription=subscription,
        kind='upgrade',
        amount=amount,
        period_start=timezone.now(),
        period_end=subscription.current_period_end,
        plan_snapshot=plan_snapshot(new_plan),
        metadata={'target_plan_id': new_plan.id, 'payer_email': payer_email},
    )
    payload = {
        'items': [{
            'id': str(invoice.id), 'title': f'Upgrade ArenaFlow - {new_plan.name}',
            'quantity': 1, 'currency_id': new_plan.currency, 'unit_price': float(amount),
        }],
        'payer': {'email': payer_email},
        'external_reference': invoice.external_reference,
        'notification_url': f'{settings.PUBLIC_BACKEND_URL}/api/saas/webhook/mercado-pago/',
        'back_urls': {
            'success': f'{settings.FRONTEND_URL}/admin/assinatura',
            'pending': f'{settings.FRONTEND_URL}/admin/assinatura',
            'failure': f'{settings.FRONTEND_URL}/admin/assinatura',
        },
        'auto_return': 'approved',
    }
    try:
        response = provider_request('POST', '/checkout/preferences', payload)
    except Exception:
        invoice.delete()
        raise
    invoice.provider_checkout_id = str(response.get('id', ''))
    invoice.checkout_url = response.get('init_point') or response.get('sandbox_init_point') or ''
    invoice.save(update_fields=['provider_checkout_id', 'checkout_url', 'updated_at'])
    return invoice


def verify_mercado_pago_signature(x_signature, x_request_id, data_id, secret=None):
    secret = secret if secret is not None else settings.MERCADO_PAGO_SAAS_WEBHOOK_SECRET
    if not secret or not x_signature or not x_request_id:
        return False
    parts = {}
    for part in x_signature.split(','):
        key, separator, value = part.strip().partition('=')
        if separator:
            parts[key] = value
    timestamp = parts.get('ts')
    signature = parts.get('v1')
    if not timestamp or not signature:
        return False
    normalized_id = str(data_id or '').lower()
    manifest = ''
    if normalized_id:
        manifest += f'id:{normalized_id};'
    manifest += f'request-id:{x_request_id};ts:{timestamp};'
    expected = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def reconcile_subscription_lifecycle(now=None):
    now = now or timezone.now()
    changed = {'past_due': 0, 'suspended': 0, 'canceled': 0, 'renewed_plan': 0}
    with transaction.atomic():
        for subscription in SaasSubscription.objects.select_for_update(of=('self',)).select_related('plan', 'pending_plan'):
            dirty = []
            if subscription.status == 'trialing' and subscription.trial_ends_at and subscription.trial_ends_at <= now:
                subscription.status = 'past_due'
                subscription.grace_ends_at = now + timedelta(days=subscription.plan.grace_days)
                dirty.extend(['status', 'grace_ends_at'])
                changed['past_due'] += 1
            elif subscription.status == 'past_due' and subscription.grace_ends_at and subscription.grace_ends_at <= now:
                subscription.status = 'suspended'
                dirty.append('status')
                changed['suspended'] += 1
            elif subscription.status == 'cancel_at_period_end' and subscription.current_period_end and subscription.current_period_end <= now:
                subscription.status = 'canceled'
                subscription.canceled_at = now
                dirty.extend(['status', 'canceled_at'])
                changed['canceled'] += 1

            if subscription.pending_plan and subscription.current_period_end and subscription.current_period_end <= now:
                subscription.plan = subscription.pending_plan
                subscription.pending_plan = None
                if subscription.pending_billing_cycle:
                    subscription.billing_cycle = subscription.pending_billing_cycle
                subscription.pending_billing_cycle = ''
                dirty.extend(['plan', 'pending_plan', 'billing_cycle', 'pending_billing_cycle'])
                changed['renewed_plan'] += 1

            if dirty:
                subscription.save(update_fields=list(set(dirty + ['updated_at'])))
                sync_legacy_arena(subscription)
    return changed


def take_daily_snapshot(day=None):
    day = day or timezone.localdate()
    subscriptions = SaasSubscription.objects.select_related('plan')
    active = subscriptions.filter(status__in=['active', 'cancel_at_period_end'])
    mrr = Decimal('0')
    for subscription in active:
        price = subscription.plan.price_for(subscription.billing_cycle) or Decimal('0')
        mrr += price / Decimal('12') if subscription.billing_cycle == 'annual' else price
    paid = SaasInvoice.objects.filter(status='paid', paid_at__date=day).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    metrics = {
        'mrr': str(mrr.quantize(Decimal('0.01'))),
        'revenue_received': str(paid),
        'statuses': {status: subscriptions.filter(status=status).count() for status, _ in SaasSubscription.STATUSES},
        'new_arenas': subscriptions.filter(arena__criada_em__date=day).count(),
    }
    snapshot, _ = SaasMetricSnapshot.objects.update_or_create(date=day, defaults={'metrics': metrics})
    return snapshot
