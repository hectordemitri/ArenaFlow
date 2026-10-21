import { expect, test } from '@playwright/test';

test('aluno solicita, recepcao confirma e aluno visualiza a confirmacao', async ({ page }) => {
  let role = 'student';
  let checkinState = 'available';
  const startsAt = new Date(Date.now() + 5 * 60_000).toISOString();
  const student = { id: 10, username: 'aluno.demo', first_name: 'Aluno', nome_completo: 'Aluno Demo', tipo: 'aluno', papel_efetivo: 'aluno', arena_id: 1 };
  const reception = { id: 20, username: 'recepcao.demo', nome_completo: 'Recepcao Demo', tipo: 'funcionario', papel_efetivo: 'recepcao', arena_id: 1 };
  const item = () => ({ id: 91, aluno: 10, aluno_nome: 'Aluno Demo', aluno_foto: null, turma: 1, turma_nome: 'Treino funcional', professor_nome: 'Prof Demo', horario_previsto: startsAt.slice(11, 19), solicitado_em: new Date().toISOString(), status: checkinState, inadimplente_no_momento: false });

  await page.addInitScript(() => {
    localStorage.setItem('access_token', 'e2e-access');
    localStorage.setItem('refresh_token', 'e2e-refresh');
  });
  await page.route('http://127.0.0.1:*/api/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const json = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (path.endsWith('/usuarios/me/')) return json(role === 'student' ? student : reception);
    if (path.endsWith('/arena/atual/')) return json({ id: 1, nome: 'Arena Demo', slug: 'arena-demo', cor_primaria: '#0f766e', cor_secundaria: '#22c55e', cor_fundo: '#f8fafc', cor_texto: '#0f172a' });
    if (path.endsWith('/mobile/home/')) return json({ arena: { id: 1, nome: 'Arena Demo' }, next_class: { starts_at: startsAt, turma: { id: 1, nome: 'Treino funcional', quadra_nome: 'Quadra 1', checkin_state: { state: checkinState } }, checkin: { state: checkinState, starts_at: startsAt } }, recent_checkins: checkinState === 'confirmed' ? [item()] : [] });
    if (path.endsWith('/turmas/1/checkin/') && request.method() === 'POST') { checkinState = 'pending'; return json({ detail: 'Check-in solicitado. Aguarde a validacao da arena.', checkin_id: 91, checkin: item() }, 202); }
    if (path.endsWith('/admin/checkins/settings/')) return json({ checkin_minutes_before: 20, checkin_minutes_after: 10, delinquent_checkin_policy: 'allow_with_warning' });
    if (path.endsWith('/admin/checkins/today/')) return json(checkinState === 'pending' ? [item()] : []);
    if (path.endsWith('/admin/checkins/91/confirm/')) { checkinState = 'confirmed'; return json(item()); }
    if (path.endsWith('/notifications/admin/')) return json([]);
    return json([]);
  });

  await page.goto('/app');
  const bottomNavigation = page.getByRole('navigation', { name: 'Navegação principal mobile' });
  const viewport = page.viewportSize();
  if (viewport.width < 1024) {
    await expect(bottomNavigation).toBeVisible();
    const navigationBox = await bottomNavigation.boundingBox();
    expect(navigationBox.y).toBeGreaterThan(viewport.height / 2);
    expect(Math.abs((navigationBox.y + navigationBox.height) - viewport.height)).toBeLessThanOrEqual(2);
  } else {
    await expect(bottomNavigation).toBeHidden();
  }
  await expect(page.getByRole('button', { name: 'Fazer check-in' })).toBeVisible();
  await page.getByRole('button', { name: 'Fazer check-in' }).click();
  await expect(page.getByRole('button', { name: 'Aguardando validação' })).toBeVisible();

  role = 'reception';
  await page.goto('/admin/checkins');
  await expect(page.getByText('Aluno Demo')).toBeVisible();
  await page.getByRole('button', { name: 'Confirmar', exact: true }).click();

  role = 'student';
  await page.goto('/app');
  await expect(page.getByRole('button', { name: 'Check-in confirmado' })).toBeVisible();
});
