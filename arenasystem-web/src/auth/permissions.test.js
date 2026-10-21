import { describe, expect, it } from 'vitest';
import { adminNavigationFor, can } from './permissions';

const academyTerms = {
  pessoa_singular: 'membro',
  pessoa_plural: 'membros',
  espaco_singular: 'espaço',
  espaco_plural: 'espaços',
};

describe('adminNavigationFor', () => {
  it('reserva as telas SaaS ao superadmin mesmo quando o dono possui acesso total a arena', () => {
    expect(can({ papel_efetivo: 'dono' }, 'saas.manage')).toBe(false);
    expect(can({ papel_efetivo: 'superadmin_saas' }, 'saas.manage')).toBe(true);
    const items = adminNavigationFor({ papel_efetivo: 'dono' });
    expect(items.some((item) => ['saas', 'saasops'].includes(item.key))).toBe(false);
  });
  it('aplica terminologia da academia sem alterar as rotas legadas', () => {
    const items = adminNavigationFor(
      { papel_efetivo: 'dono' },
      {
        terms: academyTerms,
        features: { classes: true, openAccess: true, store: false },
        hasTenantContext: true,
      },
    );

    expect(items.find((item) => item.key === 'alunos')).toMatchObject({ path: '/admin/alunos', label: 'Membros' });
    expect(items.find((item) => item.key === 'memberplans')).toMatchObject({ path: '/admin/planos-membros', label: 'Planos dos membros' });
    expect(items.find((item) => item.key === 'quadras')).toMatchObject({ path: '/admin/turmas', label: 'Espaços' });
    expect(items.some((item) => item.key === 'estoque')).toBe(false);
  });

  it('preserva os rótulos de arena e esconde recursos desabilitados', () => {
    const items = adminNavigationFor(
      { papel_efetivo: 'dono' },
      {
        terms: { pessoa_plural: 'alunos', espaco_plural: 'quadras' },
        features: { classes: false, openAccess: true, store: true },
        hasTenantContext: true,
      },
    );

    expect(items.find((item) => item.key === 'alunos')?.label).toBe('Alunos');
    expect(items.some((item) => item.key === 'quadras')).toBe(false);
    expect(items.some((item) => item.key === 'checkins')).toBe(true);
  });
});
