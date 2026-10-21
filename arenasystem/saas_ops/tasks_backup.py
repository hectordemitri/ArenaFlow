from celery import shared_task
from django.core.management import call_command


@shared_task(name='saas_ops.tasks_backup.backup_database')
def backup_database():
    call_command('backup_database', upload=True)
