export const ROLE_LABELS = {
  superadmin_saas: 'Superadmin SaaS',
  dono: 'Dono',
  recepcao: 'Recepcao',
  financeiro: 'Financeiro',
  professor: 'Professor',
  estoque: 'Estoque',
  aluno: 'Aluno',
};

export const ROLE_PERMISSIONS = {
  superadmin_saas: ['*'],
  dono: ['*'],
  administrador: ['dashboard.view', 'alunos.manage', 'reservas.manage', 'pedidos.view', 'turmas.manage', 'checkin.manage', 'access.view', 'access.manage', 'access.override', 'estoque.manage', 'auditoria.view', 'usuarios.view', 'usuarios.manage', 'subscription.view', 'support.view', 'privacy.manage'],
  recepcao: ['dashboard.view', 'alunos.manage', 'reservas.manage', 'pedidos.view', 'turmas.manage', 'checkin.manage', 'access.view', 'access.manage', 'support.view'],
  financeiro: ['dashboard.view', 'mensalidades.manage', 'financeiro.manage', 'subscription.view', 'support.view'],
  professor: ['turmas.own.view', 'checkin.own.manage'],
  estoque: ['estoque.manage', 'pedidos.view'],
  aluno: [],
};

export const ADMIN_MENU_ITEMS = [
  { key: 'saas', permission: 'saas.manage', path: '/admin/saas/arenas', label: 'SaaS', icon: 'settings' },
  { key: 'dashboard', permission: 'dashboard.view', path: '/admin', label: 'Visao Geral', icon: 'overview', exact: true },
  { key: 'solicitacoes', permission: 'alunos.manage', path: '/admin/solicitacoes', label: 'Solicitacoes', icon: 'inbox' },
  { key: 'fila', permission: 'alunos.manage', path: '/admin/fila-espera', label: 'Fila de Espera', icon: 'queue' },
  { key: 'alunos', permission: 'alunos.manage', path: '/admin/alunos', label: 'Alunos', icon: 'users' },
  { key: 'memberplans', permission: 'alunos.manage', path: '/admin/planos-membros', label: 'Planos dos alunos', icon: 'money' },
  { key: 'checkins', permission: 'checkin.manage', path: '/admin/checkins', label: 'Check-ins', icon: 'check' },
  { key: 'mensalidades', permission: 'mensalidades.manage', path: '/admin/mensalidades', label: 'Mensalidades', icon: 'money' },
  { key: 'gestao', permission: 'financeiro.manage', path: '/admin/gestao', label: 'Gestao', icon: 'trend' },
  { key: 'estoque', permission: 'estoque.manage', path: '/admin/estoque', label: 'Estoque', icon: 'stock' },
  { key: 'quadras', permission: 'turmas.manage', path: '/admin/turmas', label: 'Quadras', icon: 'court' },
  { key: 'auditoria', permission: 'auditoria.view', path: '/admin/auditoria', label: 'Auditoria', icon: 'shield' },
  { key: 'subscription', permission: 'subscription.view', path: '/admin/assinatura', label: 'Minha assinatura', icon: 'money' },
  { key: 'team', permission: 'usuarios.view', path: '/admin/equipe', label: 'Equipe', icon: 'users' },
  { key: 'support', permission: 'support.view', path: '/admin/suporte', label: 'Suporte', icon: 'inbox' },
  { key: 'privacy', permission: 'privacy.manage', path: '/admin/privacidade', label: 'Privacidade', icon: 'shield' },
  { key: 'help', permission: 'dashboard.view', path: '/admin/ajuda', label: 'Ajuda', icon: 'inbox' },
  { key: 'saasops', permission: 'saas.manage', path: '/admin/saas/operacao', label: 'Operacao SaaS', icon: 'trend' },
];

export function getRole(user) {
  if (!user) return 'aluno';
  return user.papel_efetivo || user.papel || (user.is_staff || user.tipo === 'admin' ? 'dono' : user.tipo || 'aluno');
}

export function can(user, permission) {
  const role = getRole(user);
  if (permission.startsWith('saas.')) return role === 'superadmin_saas';
  const permissions = ROLE_PERMISSIONS[role] || [];
  return permissions.includes('*') || permissions.includes(permission);
}

export function adminMenuFor(user) {
  return ADMIN_MENU_ITEMS.filter((item) => can(user, item.permission));
}

export function adminNavigationFor(user, { terms, features, hasTenantContext = false } = {}) {
  const vocabulary = terms || {
    pessoa_plural: 'alunos',
    espaco_plural: 'quadras',
  };
  const modules = features || { classes: true, openAccess: false, store: true };

  return adminMenuFor(user)
    .filter((item) => getRole(user) !== 'superadmin_saas' || hasTenantContext || ['saas', 'saasops'].includes(item.key))
    .filter((item) => modules.classes || !['solicitacoes', 'fila', 'quadras'].includes(item.key))
    .filter((item) => modules.classes || modules.openAccess || item.key !== 'checkins')
    .filter((item) => modules.store || item.key !== 'estoque')
    .map((item) => {
      if (item.key === 'alunos') return { ...item, label: capitalize(vocabulary.pessoa_plural) };
      if (item.key === 'memberplans') return { ...item, label: `Planos dos ${vocabulary.pessoa_plural}` };
      if (item.key === 'quadras') return { ...item, label: capitalize(vocabulary.espaco_plural) };
      return item;
    });
}

export function defaultAdminPath(user) {
  if (getRole(user) === 'superadmin_saas') return '/admin/saas/arenas';
  if (can(user, 'dashboard.view')) return '/admin';
  return adminMenuFor(user)[0]?.path || '/';
}

export function hasAdminAccess(user) {
  return adminMenuFor(user).length > 0;
}

export function canUseStudentApp(user) {
  if (!user) return false;
  return user.tipo === 'aluno' || getRole(user) === 'professor' || user.tipo === 'admin' || user.tipo === 'admin_arena' || user.is_staff;
}

export function defaultStudentPath() {
  return '/app';
}

export function initialPathFor(user) {
  if (hasAdminAccess(user)) return defaultAdminPath(user);
  if (canUseStudentApp(user)) return defaultStudentPath();
  return '/acesso-negado';
}

function capitalize(value) {
  return value ? value.charAt(0).toUpperCase() + value.slice(1) : value;
}
