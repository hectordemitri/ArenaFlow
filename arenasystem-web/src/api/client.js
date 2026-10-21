import axios from 'axios';
import { arenaContextHeaders, clearArenaContext } from '../arena/contextStorage';

const API_BASE_URL = (import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000/api').replace(/\/$/, '');

// Cliente axios pre-configurado para falar com o Django.
const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 20000,
  headers: {
    'Content-Type': 'application/json',
  },
});
let refreshPromise = null;

const PUBLIC_ENDPOINTS = [
  '/auth/login/',
  '/auth/register/',
  '/auth/refresh/',
  '/auth/invitations/accept/',
  '/auth/password-reset/request/',
  '/auth/password-reset/confirm/',
  '/auth/email-change/confirm/',
  '/arenas/publicas/',
  '/saas/plans/',
];

function isPublicEndpoint(url = '') {
  return PUBLIC_ENDPOINTS.some((endpoint) => url.startsWith(endpoint));
}

// Adiciona automaticamente o token JWT em toda requisicao.
api.interceptors.request.use((config) => {
  if (!isPublicEndpoint(config.url)) {
    const token = localStorage.getItem('access_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    config.headers['X-Frontend-Route'] = typeof window !== 'undefined' ? window.location.pathname : '';
    Object.assign(config.headers, arenaContextHeaders(config.url));
  }
  return config;
});

// Se receber 401 por token expirado, tenta renovar antes de mandar ao login.
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;

    if (
      error.response?.status === 401
      && originalRequest && !originalRequest._retry
      && !isPublicEndpoint(originalRequest.url)
    ) {
      originalRequest._retry = true;
      const currentAccess = localStorage.getItem('access_token');
      if (currentAccess && originalRequest.headers.Authorization !== `Bearer ${currentAccess}`) {
        originalRequest.headers.Authorization = `Bearer ${currentAccess}`;
        return api(originalRequest);
      }
      const refresh = localStorage.getItem('refresh_token');

      if (refresh) {
        try {
          if (!refreshPromise) {
            refreshPromise = axios.post(`${API_BASE_URL}/auth/refresh/`, { refresh }, { timeout: 15000 })
              .then(({ data }) => {
                if (localStorage.getItem('refresh_token') !== refresh) throw new axios.CanceledError('A sessao foi alterada.');
                localStorage.setItem('access_token', data.access);
                if (data.refresh) localStorage.setItem('refresh_token', data.refresh);
                return data;
              }).finally(() => { refreshPromise = null; });
          }
          const data = await refreshPromise;
          originalRequest.headers.Authorization = `Bearer ${data.access}`;
          return api(originalRequest);
        } catch (refreshError) {
          if (!refreshError.response || refreshError.response.status >= 500) return Promise.reject(refreshError);
          localStorage.removeItem('access_token');
          localStorage.removeItem('refresh_token');
          clearArenaContext();
          window.location.href = '/login';
        }
      }
    }
    const contextoInvalido = [403, 404, 409].includes(error.response?.status)
      && originalRequest?.headers?.['X-Arena-ID']
      && /contexto de arena|selecione uma arena/i.test(error.response?.data?.detail || '');
    if (contextoInvalido) clearArenaContext();
    return Promise.reject(error);
  }
);

export default api;
