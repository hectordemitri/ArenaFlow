import hashlib
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError

from gestao.audit import registrar_auditoria
from .models import Matricula, Mensalidade, PaymentAccount, PaymentWebhookEvent, StudentPayment


def update_overdue(queryset=None, today=None):
    today = today or timezone.localdate()
    if queryset is None:
        queryset = Mensalidade.objects.all()
    return queryset.filter(status='pendente', vencimento__lte=today - timezone.timedelta(days=5)).update(status='atrasado')


def generate_monthly_dues(today=None):
    import calendar
    today = today or timezone.localdate()
    created = 0
    # Lock an existing parent row; an empty child queryset cannot serialize concurrent creation.
    ids = Matricula.objects.filter(
        ativa=True, arena__ativa=True, data_inicio__lte=today,
    ).filter(Q(data_fim__isnull=True) | Q(data_fim__gte=today)).values_list('pk', flat=True)
    for enrollment_id in ids.iterator():
        with transaction.atomic():
            enrollment = Matricula.objects.select_for_update().select_related('plano').get(pk=enrollment_id)
            if not enrollment.ativa or (enrollment.data_fim and enrollment.data_fim < today):
                continue
            due_day = min(enrollment.dia_vencimento, calendar.monthrange(today.year, today.month)[1])
            _, was_created = Mensalidade.objects.get_or_create(
                matricula=enrollment, mes_referencia=today.replace(day=1),
                defaults={'arena_id': enrollment.arena_id, 'valor': enrollment.plano.valor,
                          'vencimento': today.replace(day=due_day)},
            )
            created += was_created
    return {'created': created, 'overdue': update_overdue(today=today)}


@transaction.atomic
def apply_payment(arena, payment, request=None):
    account = PaymentAccount.objects.get(arena=arena, disconnected_at__isnull=True)
    status = payment.get('status')
    if status not in {'approved', 'pending', 'in_process', 'authorized', 'rejected', 'cancelled', 'refunded', 'charged_back', 'in_mediation'}:
        raise ValidationError('Estado de pagamento desconhecido.')
    raw_updated = payment.get('date_last_updated') or ''
    updated = parse_datetime(raw_updated)
    if not updated or timezone.is_naive(updated):
        raise ValidationError('Data do pagamento invalida.')
    provider_id = str(payment.get('id', ''))
    if not provider_id.isdigit() or str(payment.get('collector_id', '')) != account.collector_id:
        raise ValidationError('Destinatario do pagamento divergente.')
    due = Mensalidade.objects.select_for_update().filter(
        arena=arena, external_reference=payment.get('external_reference') or None,
    ).first()
    if not due:
        raise ValidationError('Referencia de cobranca desconhecida nesta arena.')
    try:
        amount = Decimal(str(payment.get('transaction_amount')))
        refunded = Decimal(str(payment.get('transaction_amount_refunded', 0)))
        valid_amounts = amount.is_finite() and refunded.is_finite() and amount == due.valor and 0 <= refunded <= amount
    except (InvalidOperation, TypeError, ValueError):
        valid_amounts = False
    if payment.get('currency_id') != 'BRL' or not valid_amounts:
        raise ValidationError('Valor ou moeda do pagamento divergente.')
    other = StudentPayment.objects.filter(provider_id=provider_id).exclude(mensalidade=due)
    if other.exists():
        raise ValidationError('Pagamento ja associado a outra cobranca.')
    fingerprint = hashlib.sha256(f'{arena.pk}:{provider_id}:{status}:{raw_updated}:{refunded}'.encode()).hexdigest()
    event, _ = PaymentWebhookEvent.objects.get_or_create(
        provider='mercado_pago', external_id=fingerprint,
        defaults={'arena': arena, 'event_type': status, 'idempotency_key': fingerprint,
                  'payload': {'payment_id': provider_id, 'status': status, 'amount': str(amount), 'refunded': str(refunded)}},
    )
    if event.processed:
        return due
    existing = StudentPayment.objects.filter(provider_id=provider_id).first()
    if not existing or updated > existing.provider_updated_at:
        StudentPayment.objects.update_or_create(provider_id=provider_id, defaults={
            'mensalidade': due, 'status': status, 'amount': amount, 'refunded_amount': refunded,
            'provider_updated_at': updated,
        })
        previous = {'status': due.status, 'data_pagamento': str(due.data_pagamento)}
        rows = list(due.payments.all())
        received = sum((row.amount - row.refunded_amount for row in rows if row.status == 'approved'), Decimal('0'))
        if due.status != 'cancelada':
            if received >= due.valor:
                due.status = 'pago'
                if not due.data_pagamento:
                    due.data_pagamento = timezone.localdate()
            elif any(row.status in {'charged_back', 'in_mediation'} for row in rows):
                due.status, due.data_pagamento = 'contestada', None
            elif any(row.status == 'refunded' or row.refunded_amount > 0 for row in rows):
                due.status, due.data_pagamento = 'estornada', None
            elif due.payment_provider == 'mercado_pago' or due.status != 'pago':
                due.status, due.data_pagamento = 'pendente', None
                due.atualizar_status_atraso(salvar=False)
        due.payment_provider = 'mercado_pago'
        due.external_status = status
        due.mercado_pago_payment_id = provider_id
        due.processed_at = timezone.now()
        due.idempotency_key = fingerprint
        due.save(update_fields=['status', 'data_pagamento', 'payment_provider', 'external_status',
                                'mercado_pago_payment_id', 'processed_at', 'idempotency_key'])
        registrar_auditoria(request, arena, 'mensalidade.pagamento_conciliado', due,
                            anteriores=previous, novos={'status': due.status, 'payment_id': provider_id, 'external_status': status})
    event.processed, event.processed_at = True, timezone.now()
    event.save(update_fields=['processed', 'processed_at'])
    return due


def reconcile_student_payments(limit=100):
    from .services import buscar_pagamentos_por_referencia, MercadoPagoAPIError, MercadoPagoConfigError
    ids = list(Mensalidade.objects.filter(
        arena__payment_account__disconnected_at__isnull=True, arena__payment_account__isnull=False,
    ).exclude(external_reference='').order_by(F('payment_checked_at').asc(nulls_first=True), 'pk').values_list('pk', flat=True)[:limit])
    result = {'checked': 0, 'failed': 0}
    for pk in ids:
        due = Mensalidade.objects.select_related('arena').get(pk=pk)
        try:
            response = buscar_pagamentos_por_referencia(due.external_reference, due.arena)
            for payment in response.get('results', []):
                apply_payment(due.arena, payment)
            result['checked'] += 1
        except (MercadoPagoAPIError, MercadoPagoConfigError, ValidationError):
            result['failed'] += 1
        finally:
            Mensalidade.objects.filter(pk=pk).update(payment_checked_at=timezone.now())
    return result
