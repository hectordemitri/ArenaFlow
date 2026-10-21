from rest_framework import permissions


PERMISSOES_POR_PAPEL = {
    'superadmin_saas': {'*'},
    'dono': {'*'},
    'administrador': {
        'dashboard.view', 'alunos.view', 'alunos.manage',
        'reservas.view', 'reservas.manage', 'pedidos.view', 'pedidos.manage',
        'checkin.view', 'checkin.manage', 'turmas.view', 'turmas.manage',
        'access.view', 'access.manage', 'access.override',
        'mensalidades.view', 'financeiro.view', 'estoque.view', 'estoque.manage',
        'auditoria.view', 'usuarios.view', 'usuarios.manage', 'subscription.view',
        'support.view', 'support.manage', 'privacy.manage',
    },
    'recepcao': {
        'alunos.view', 'alunos.manage',
        'reservas.view', 'reservas.manage',
        'pedidos.view', 'pedidos.manage',
        'checkin.view', 'checkin.manage',
        'access.view', 'access.manage',
        'turmas.view', 'turmas.manage',
        'dashboard.view',
        'support.view', 'support.manage',
    },
    'financeiro': {
        'mensalidades.view', 'mensalidades.manage',
        'financeiro.view', 'financeiro.manage',
        'reservas.view',
        'dashboard.view',
        'subscription.view',
        'support.view',
    },
    'professor': {
        'turmas.own.view',
        'checkin.own.view', 'checkin.own.manage',
        'alunos.own.view',
    },
    'estoque': {
        'estoque.view', 'estoque.manage',
        'pedidos.view',
    },
    'aluno': {
        'reservas.self.view', 'reservas.self.manage',
        'mensalidades.self.view',
        'pedidos.self.view', 'pedidos.self.manage',
        'turmas.self.view',
        'checkin.self.manage',
        'access.self.view', 'access.self.manage',
    },
}


def papel_usuario(user):
    if not getattr(user, 'is_authenticated', False):
        return None
    return getattr(user, 'papel_efetivo', None) or 'aluno'


def tem_permissao(user, permissao):
    papel = papel_usuario(user)
    if permissao.startswith('saas.'):
        return papel == 'superadmin_saas'
    permissoes = PERMISSOES_POR_PAPEL.get(papel, set())
    base_allowed = '*' in permissoes or permissao in permissoes
    if papel == 'dono' and permissao in {'subscription.manage', 'ownership.transfer', 'usuarios.manage'}:
        return True
    overrides = getattr(user, 'permission_overrides', None)
    if overrides is None or not getattr(user, 'pk', None):
        return base_allowed
    override = overrides.filter(permission=permissao).values_list('effect', flat=True).first()
    if override == 'deny':
        return False
    if override == 'allow':
        return True
    return base_allowed


class HasArenaPermission(permissions.BasePermission):
    required_permission = None

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        required = getattr(view, 'required_permission', self.required_permission)
        return bool(required and tem_permissao(request.user, required))


class IsSaasSuperAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and papel_usuario(request.user) == 'superadmin_saas'
        )


def require_permission(permissao):
    class RequiredPermission(HasArenaPermission):
        required_permission = permissao
    return RequiredPermission
