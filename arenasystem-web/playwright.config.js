import { defineConfig, devices } from '@playwright/test';
const realApi = process.env.E2E_REAL_API === '1';

export default defineConfig({
  testDir: './e2e',
  workers: 1,
  use: { baseURL: 'http://127.0.0.1:4173', trace: 'retain-on-failure' },
  webServer: [{
    command: 'node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 4173',
    url: 'http://127.0.0.1:4173/login',
    reuseExistingServer: !process.env.CI && !realApi,
    env: realApi ? { VITE_API_URL: 'http://127.0.0.1:8001/api', VITE_DEMO_LOGIN_ENABLED: 'false' } : {},
  }, ...(realApi ? [{
    command: 'node e2e/start-backend.mjs',
    url: 'http://127.0.0.1:8001/api/health/', reuseExistingServer: false, timeout: 60000,
  }] : [])],
  projects: [
    { name: 'chromium-desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'chromium-mobile', use: { ...devices['Pixel 7'] } },
  ],
});
