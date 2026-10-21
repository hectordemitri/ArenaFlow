import { beforeEach, expect, test, vi } from 'vitest';
import axios from 'axios';

beforeEach(() => { vi.restoreAllMocks(); vi.resetModules(); localStorage.clear(); sessionStorage.clear(); });

test('simultaneous expired requests share one refresh and preserve rotated tokens', async () => {
  localStorage.setItem('access_token', 'old');
  localStorage.setItem('refresh_token', 'refresh-old');
  let resolveRefresh;
  const refresh = vi.spyOn(axios, 'post').mockImplementation(() => new Promise((resolve) => { resolveRefresh = resolve; }));
  const { default: api } = await import('./client');
  api.defaults.adapter = async (config) => {
    if (config.headers.Authorization === 'Bearer old') throw { config, response: { status: 401 } };
    return { config, status: 200, data: 'ok', headers: {} };
  };
  const first = api.get('/usuarios/me/');
  const second = api.get('/mensalidades/');
  await vi.waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
  resolveRefresh({ data: { access: 'new', refresh: 'refresh-new' } });
  const results = await Promise.all([first, second]);
  expect(results.every((result) => result.data === 'ok')).toBe(true);
  expect(localStorage.getItem('refresh_token')).toBe('refresh-new');
  expect(refresh).toHaveBeenCalledTimes(1);
});

test('a late refresh cannot restore a session after logout', async () => {
  localStorage.setItem('access_token', 'old'); localStorage.setItem('refresh_token', 'refresh-old');
  let resolveRefresh;
  vi.spyOn(axios, 'post').mockImplementation(() => new Promise((resolve) => { resolveRefresh = resolve; }));
  const { default: api } = await import('./client');
  api.defaults.adapter = async (config) => { throw { config, response: { status: 401 } }; };
  const pending = api.get('/usuarios/me/').catch((error) => error);
  await vi.waitFor(() => expect(resolveRefresh).toBeTypeOf('function'));
  localStorage.clear();
  resolveRefresh({ data: { access: 'new', refresh: 'refresh-new' } });
  await pending;
  expect(localStorage.getItem('access_token')).toBeNull();
});

test('public login does not send tokens or arena context', async () => {
  localStorage.setItem('access_token', 'private-access');
  const { default: api } = await import('./client');
  api.defaults.adapter = async (config) => {
    expect(config.headers.Authorization).toBeUndefined();
    expect(config.headers['X-Arena-ID']).toBeUndefined();
    return { config, status: 200, data: {}, headers: {} };
  };
  await api.post('/auth/login/', { username: 'example', password: 'example' });
});
