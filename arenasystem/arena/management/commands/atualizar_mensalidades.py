from django.core.management.base import BaseCommand
from arena.payments import generate_monthly_dues


class Command(BaseCommand):
    help = 'Gera mensalidades do mes para matriculas ativas e marca atrasos automaticamente.'

    def handle(self, *args, **options):
        result = generate_monthly_dues()
        self.stdout.write(self.style.SUCCESS(
            f"Mensalidades criadas: {result['created']}. Marcadas como atrasadas: {result['overdue']}."
        ))
