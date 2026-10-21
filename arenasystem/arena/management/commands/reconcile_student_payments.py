from django.core.management.base import BaseCommand
from arena.payments import reconcile_student_payments


class Command(BaseCommand):
    help = 'Reconcilia pagamentos de alunos com as contas de cada arena.'

    def handle(self, *args, **options):
        self.stdout.write(str(reconcile_student_payments()))
