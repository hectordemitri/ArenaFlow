from contextvars import ContextVar

from django.conf import settings
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from .models import Arena


_current_request = ContextVar('arena_current_request', default=None)


def set_current_request(request):
    return _current_request.set(request)


def reset_current_request(token):
    _current_request.reset(token)


def _is_retired_warm_tone(hex_value):
    value = str(hex_value or '').strip().lower()
    if len(value) != 7 or not value.startswith('#'):
        return False
    try:
        red = int(value[1:3], 16)
        green = int(value[3:5], 16)
        blue = int(value[5:7], 16)
    except ValueError:
        return False
    return red > 220 and 80 <= green <= 180 and blue < 80


def get_default_arena():
    defaults = {
        'nome': 'ArenaFlow Demo',
        'cor_primaria': '#0F766E',
        'cor_secundaria': '#A3E635',
        'cor_fundo': '#ECFEFF',
        'cor_texto': '#071B26',
    }
    if getattr(settings, 'DEMO_MODE', False):
        arena, _ = Arena.objects.get_or_create(slug='arenasystem-demo', defaults=defaults)
    else:
        arena = Arena.objects.filter(slug=getattr(settings, 'DEFAULT_ARENA_SLUG', 'arenasystem-demo')).first()
        if not arena:
            raise ValidationError({'detail': 'Nenhuma arena padrao foi configurada para este ambiente.'})
    if getattr(settings, 'DEMO_MODE', False) and (arena.nome.startswith('ArenaSystem') or arena.cor_primaria.lower() == '#123b5d' or _is_retired_warm_tone(arena.cor_primaria)):
        arena.nome = 'ArenaFlow Demo'
        arena.cor_primaria = '#0F766E'
        arena.cor_secundaria = '#A3E635'
        arena.cor_fundo = '#ECFEFF'
        arena.cor_texto = '#071B26'
        arena.save(update_fields=['nome', 'cor_primaria', 'cor_secundaria', 'cor_fundo', 'cor_texto'])
    return arena


def _is_saas_superadmin(user):
    return bool(
        getattr(user, 'is_authenticated', False)
        and (
            getattr(user, 'is_superuser', False)
            or getattr(user, 'papel_efetivo', None) == 'superadmin_saas'
            or getattr(user, 'papel', None) == 'superadmin_saas'
            or getattr(user, 'tipo', None) == 'superadmin_saas'
        )
    )


def _arena_selecionada_superadmin(user, request):
    if not request:
        return None

    query_params = getattr(request, 'query_params', getattr(request, 'GET', {}))
    arena_id = request.headers.get('X-Arena-ID') or query_params.get('arena_id')
    if not arena_id:
        return None

    if not _is_saas_superadmin(user):
        raise PermissionDenied('Contexto de arena exclusivo para superadmin.')

    arena = Arena.objects.filter(id=arena_id, ativa=True).first()
    if not arena:
        raise NotFound('Contexto de arena invalido ou inativo.')
    return arena


def get_user_arena(user):
    request = _current_request.get()
    arena_selecionada = _arena_selecionada_superadmin(user, request)
    if arena_selecionada:
        return arena_selecionada

    if _is_saas_superadmin(user):
        raise ValidationError({'detail': 'Selecione uma arena no painel SaaS para acessar dados operacionais.'})

    if getattr(user, 'is_authenticated', False) and getattr(user, 'arena_id', None):
        return user.arena
    if getattr(user, 'is_authenticated', False):
        raise PermissionDenied('Esta conta nao esta vinculada a uma arena.')
    return get_default_arena()


def get_request_arena(request):
    user = getattr(request, 'user', None)

    arena_selecionada = _arena_selecionada_superadmin(user, request)
    if arena_selecionada:
        return arena_selecionada

    if _is_saas_superadmin(user):
        raise ValidationError({'detail': 'Selecione uma arena no painel SaaS para acessar dados operacionais.'})

    if getattr(user, 'is_authenticated', False) and getattr(user, 'arena_id', None):
        return user.arena
    if getattr(user, 'is_authenticated', False):
        raise PermissionDenied('Esta conta nao esta vinculada a uma arena.')

    host = request.get_host().split(':', 1)[0].lower() if request else ''
    if host:
        arena = Arena.objects.filter(dominio__iexact=host, ativa=True).first()
        if arena:
            return arena

    return get_default_arena()


class TenantQuerySetMixin:
    arena_field = 'arena'

    def get_arena(self):
        return get_request_arena(self.request)

    def filter_by_arena(self, qs):
        return qs.filter(**{self.arena_field: self.get_arena()})

    def perform_create(self, serializer):
        serializer.save(arena=self.get_arena())
