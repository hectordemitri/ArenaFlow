import { expect, test } from '@playwright/test';

test('perfil abre as quatro áreas funcionais no mobile', async ({ page }) => {
  const user = {
    id: 10, username: 'aluna.demo', first_name: 'Aluna', last_name: 'Demo',
    nome_completo: 'Aluna Demo', email: 'aluna@example.test', telefone: '',
    tipo: 'aluno', papel_efetivo: 'aluno', arena_id: 1,
  };
  const preferences = {
    app_classes: true, app_checkins: true, app_financial: true, app_reservations: true,
    email_classes: true, email_checkins: true, email_financial: true, email_reservations: true,
  };
  await page.addInitScript(() => {
    localStorage.setItem('access_token', 'e2e-access');
    localStorage.setItem('refresh_token', 'e2e-refresh');
  });
  await page.route('http://127.0.0.1:*/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    const body = path.endsWith('/usuarios/me/') ? user
      : path.endsWith('/arena/atual/') ? { id: 1, nome: 'Arena Demo', slug: 'arena-demo', cor_primaria: '#0f766e', cor_secundaria: '#22c55e' }
        : path.endsWith('/auth/notification-preferences/') ? preferences : [];
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });

  await page.goto('/app/perfil');
  await page.getByRole('link', { name: /Dados pessoais/ }).click();
  await expect(page).toHaveURL(/\/app\/perfil\/dados$/);
  await expect(page.getByRole('heading', { name: 'Dados pessoais' })).toBeVisible();

  await page.getByRole('link', { name: 'Voltar ao perfil' }).click();
  await page.getByRole('link', { name: /^Notificações/ }).click();
  await expect(page).toHaveURL(/\/app\/perfil\/notificacoes$/);
  await expect(page.getByRole('button', { name: 'Salvar preferências' })).toBeVisible();

  await page.goto('/app/perfil');
  await expect(page.getByRole('link', { name: /Privacidade e segurança/ })).toHaveAttribute('href', '/app/perfil/seguranca');
  await expect(page.getByRole('link', { name: /Sessões conectadas/ })).toHaveAttribute('href', '/app/perfil/sessoes');
});
