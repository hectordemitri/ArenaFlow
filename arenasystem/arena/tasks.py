from celery import shared_task
from django.utils import timezone

from .access_adapters import get_access_adapter
from .models import AccessIntegrationEvent, AccessPoint


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={'max_retries': 5})
def process_access_integration_event(self, event_id):
    event = AccessIntegrationEvent.objects.select_related('visit__arena').filter(id=event_id).first()
    if not event or event.status in {'processed', 'ignored'}:
        return 'already_processed'
    event.attempts += 1
    points = list(AccessPoint.objects.filter(arena=event.visit.arena, ativa=True))
    providers = {point.provider_key for point in points if point.provider_key != 'manual'}
    if not providers:
        event.status = 'ignored'
        event.processed_at = timezone.now()
        event.save(update_fields=['status', 'attempts', 'processed_at'])
        return 'ignored'
    for provider in providers:
        adapter = get_access_adapter(provider)
        if not adapter:
            event.status = 'failed'
            event.last_error = f'Adaptador não configurado: {provider}'
            event.save(update_fields=['status', 'attempts', 'last_error'])
            raise RuntimeError(event.last_error)
        adapter.handle(event, [point for point in points if point.provider_key == provider])
    event.status = 'processed'
    event.processed_at = timezone.now()
    event.last_error = ''
    event.save(update_fields=['status', 'attempts', 'processed_at', 'last_error'])
    return 'processed'


@shared_task(name='arena.tasks.expire_access_visits')
def expire_access_visits_task():
    from .access_services import expire_access_visits
    return expire_access_visits()


@shared_task(name='arena.tasks.generate_student_dues')
def generate_student_dues():
    from .payments import generate_monthly_dues
    return generate_monthly_dues()


@shared_task(name='arena.tasks.reconcile_student_payments')
def reconcile_student_payments_task():
    from .payments import reconcile_student_payments
    return reconcile_student_payments()
