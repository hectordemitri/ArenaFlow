import { expect, test } from '@playwright/test';

test('membro solicita, recepção confirma e membro encerra o acesso livre', async ({ page }) => {
  let role = 'member';
  let state = 'available';
  const publicId = '2a4cc734-e6e2-4c61-a159-e9030f812111';
  const member = { id: 10, username: 'membro.demo', first_name: 'Membro', nome_completo: 'Membro Demo', tipo: 'aluno', papel_efetivo: 'aluno', arena_id: 1 };
  const reception = { id: 20, username: 'recepcao.demo', nome_completo: 'Recepção Demo', tipo: 'funcionario', papel_efetivo: 'recepcao', arena_id: 1 };
  const arena = {
    id: 1, nome: 'Academia Demo', tipo_negocio: 'academia',
    terminologia: { unidade_singular: 'unidade', unidade_plural: 'unidades', pessoa_singular: 'membro', pessoa_plural: 'membros', espaco_singular: 'espaço', espaco_plural: 'espaços' },
    operational_settings: { classes_enabled: true, open_access_enabled: true, reservations_enabled: false, store_enabled: false, open_access_validation: 'reception', open_access_pending_minutes: 10 },
  };
  const visit = () => ({
    id: 1, public_id: publicId, aluno: 10, aluno_nome: 'Membro Demo', aluno_foto: null,
    plano: 1, plano_nome: 'Plano híbrido', status: state, origem: 'mobile',
    solicitado_em: new Date().toISOString(), entrada_em: state === 'confirmed' ? new Date().toISOString() : null,
    inadimplente_no_momento: false,
  });

  await page.addInitScript(() => {
    localStorage.setItem('access_token', 'e2e-access');
    localStorage.setItem('refresh_token', 'e2e-refresh');
  });
  await page.route('http://127.0.0.1:*/api/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const json = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (path.endsWith('/usuarios/me/')) return json(role === 'member' ? member : reception);
    if (path.endsWith('/arena/atual/')) return json(arena);
    if (path.endsWith('/mobile/home/')) return json({ arena, features: { classes: true, open_access: true, reservations: false, store: false }, access: { enabled: true, validation: 'reception', state, visit: ['pending', 'confirmed'].includes(state) ? visit() : null }, next_class: null, recent_checkins: [] });
    if (path.endsWith('/access-visits/check-in/')) { state = 'pending'; return json({ detail: 'Solicitação enviada para a recepção.', visit: visit() }, 202); }
    if (path.endsWith(`/access-visits/${publicId}/check-out/`)) { const body = { ...visit(), status: 'checked_out', saida_em: new Date().toISOString() }; state = 'available'; return json(body); }
    if (path.endsWith('/admin/access/settings/')) return json(arena.operational_settings);
    if (path.endsWith('/admin/access-visits/today/')) return json(['pending', 'confirmed'].includes(state) ? [visit()] : []);
    if (path.endsWith(`/admin/access-visits/${publicId}/confirm/`)) { state = 'confirmed'; return json(visit()); }
    if (path.endsWith('/notifications/admin/')) return json([]);
    return json([]);
  });

  await page.goto('/app');
  await expect(page.getByRole('heading', { name: 'Entrada disponível' })).toBeVisible();
  await page.getByRole('button', { name: 'Fazer check-in' }).click();
  await expect(page.getByRole('heading', { name: 'Aguardando validação' })).toBeVisible();

  role = 'reception';
  await page.goto('/admin/checkins');
  await page.getByRole('button', { name: 'Acesso livre' }).click();
  await expect(page.getByText('Membro Demo')).toBeVisible();
  await page.getByRole('button', { name: 'Confirmar', exact: true }).click();

  role = 'member';
  await page.goto('/app');
  await expect(page.getByRole('heading', { name: 'Acesso confirmado' })).toBeVisible();
  await page.getByRole('button', { name: 'Fazer check-out' }).click();
  await expect(page.getByRole('heading', { name: 'Entrada disponível' })).toBeVisible();
});
