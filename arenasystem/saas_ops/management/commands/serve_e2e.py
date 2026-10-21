from decimal import Decimal

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = 'Prepara e serve exclusivamente o banco isolado dos testes de navegador.'

    def handle(self, *args, **options):
        if settings.SETTINGS_MODULE != 'arenasystem.settings_e2e':
            raise CommandError('Use somente --settings=arenasystem.settings_e2e.')
        call_command('migrate', interactive=False, verbosity=0)
        from arena.models import Arena, ArenaOnboarding, Matricula, Mensalidade, Plano, Quadra
        from loja.models import Categoria, Produto
        from usuarios.models import Usuario
        for suffix in ('a', 'b'):
            arena, _ = Arena.objects.get_or_create(slug=f'e2e-{suffix}', defaults={'nome': f'Arena E2E {suffix.upper()}'})
            ArenaOnboarding.objects.update_or_create(arena=arena, defaults={'completed_at': timezone.now()})
            for role in ('dono', 'aluno'):
                user, _ = Usuario.objects.get_or_create(username=f'e2e-{suffix}-{role}')
                user.arena, user.papel = arena, role
                user.tipo = 'admin_arena' if role == 'dono' else 'aluno'
                user.first_name = f'Membro {suffix.upper()}'
                user.set_password('E2eOnly!Password123')
                user.save()
            Quadra.objects.get_or_create(arena=arena, nome=f'Quadra {suffix.upper()}')
            plan, _ = Plano.objects.get_or_create(arena=arena, nome='Plano E2E', defaults={'valor': Decimal('100'), 'frequencia_semanal': 2})
            student = Usuario.objects.get(username=f'e2e-{suffix}-aluno')
            enrollment, _ = Matricula.objects.get_or_create(arena=arena, aluno=student, plano=plan, defaults={'data_inicio': timezone.localdate()})
            Mensalidade.objects.get_or_create(arena=arena, matricula=enrollment, mes_referencia=timezone.localdate().replace(day=1),
                                             defaults={'valor': 100, 'vencimento': timezone.localdate()})
            category, _ = Categoria.objects.get_or_create(arena=arena, nome='Uniforme')
            Produto.objects.update_or_create(arena=arena, nome=f'Camisa {suffix.upper()}',
                                            defaults={'categoria': category, 'preco': 50, 'estoque': 100, 'canal': 'app'})
        call_command('runserver', '127.0.0.1:8001', use_reloader=False)
