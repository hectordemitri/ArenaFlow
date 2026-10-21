import { expect, test } from '@playwright/test';

test.skip(process.env.E2E_REAL_API !== '1', 'Enable the isolated Django backend with E2E_REAL_API=1');

async function login(page, username) {
  await page.goto('/login');
  await page.getByRole('textbox', { name: 'Usuario', exact: true }).fill(username);
  await page.getByLabel('Senha', { exact: true }).fill('E2eOnly!Password123');
  await page.getByRole('button', { name: 'Entrar', exact: true }).click();
  await expect(page).toHaveURL(/\/(app|admin)/);
}

test('real browser login, tenant data and personal orders', async ({ page }) => {
  await login(page, 'e2e-a-aluno');
  await page.goto('/app/loja');
  await expect(page.getByText('Camisa A', { exact: true })).toBeVisible();
  await expect(page.getByText('Camisa B', { exact: true })).toHaveCount(0);
  const result = await page.evaluate(async () => {
    const headers = { Authorization: `Bearer ${localStorage.getItem('access_token')}`, 'Content-Type': 'application/json' };
    const base = 'http://127.0.0.1:8001/api';
    const products = await fetch(`${base}/produtos/`, { headers }).then((response) => response.json());
    const product = (products.results || products)[0];
    const created = await fetch(`${base}/vendas/`, { method: 'POST', headers: { ...headers, 'X-Idempotency-Key': crypto.randomUUID() },
      body: JSON.stringify({ itens: [{ produto: product.id, quantidade: 1 }] }) });
    return { status: created.status, order: await created.json() };
  });
  expect(result.status).toBe(201);
  await page.goto('/app/meus-pedidos');
  await page.getByRole('button', { name: `Pedido #${result.order.id} ` }).click();
  await expect(page.getByText('Camisa A', { exact: false }).first()).toBeVisible();
  await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });
  await login(page, 'e2e-b-aluno');
  await page.goto('/app/meus-pedidos');
  await expect(page.getByText('Você ainda não fez nenhum pedido', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: `Pedido #${result.order.id} ` })).toHaveCount(0);
  await expect(page.getByText('Camisa A', { exact: false })).toHaveCount(0);
});

test('real refresh recovers expired access token without logging out', async ({ page }) => {
  await login(page, 'e2e-a-aluno');
  await page.evaluate(() => localStorage.setItem('access_token', 'expired-access-token'));
  await page.reload();
  await expect(page).toHaveURL(/\/app/);
  await expect.poll(() => page.evaluate(() => localStorage.getItem('access_token'))).toMatch(/^[^.]+\.[^.]+\.[^.]+$/);
});

test('arena owner sees payment connection without horizontal overflow', async ({ page }, testInfo) => {
  await login(page, 'e2e-a-dono');
  await page.goto('/admin/mensalidades');
  await expect(page.getByRole('region', { name: 'Conta de recebimento' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Conectar Mercado Pago', exact: true })).toBeDisabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('mensalidades.png'), fullPage: true });
});
