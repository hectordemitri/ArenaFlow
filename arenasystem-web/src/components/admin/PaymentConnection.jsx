import { useEffect, useState } from 'react';
import api from '../../api/client';

export default function PaymentConnection() {
  const [account, setAccount] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    api.get('/admin/payment-account/').then(({ data }) => { if (active) setAccount(data); })
      .catch((err) => { if (active && err.response?.status !== 403) setError('Nao foi possivel consultar a conta de recebimento.'); });
    return () => { active = false; };
  }, []);
  async function connect() {
    setBusy(true); setError('');
    try {
      const { data } = await api.post('/admin/payment-account/', {}, { withCredentials: true });
      window.location.assign(data.authorization_url);
    } catch (err) { setError(err.response?.data?.detail || 'Nao foi possivel conectar a conta.'); setBusy(false); }
  }
  async function disconnect() {
    if (!window.confirm('Desconectar a conta de recebimento desta arena?')) return;
    setBusy(true); setError('');
    try { await api.delete('/admin/payment-account/'); setAccount((current) => ({ ...current, connected: false })); }
    catch { setError('Nao foi possivel desconectar a conta.'); }
    finally { setBusy(false); }
  }
  if (!account && !error) return null;
  const result = new URLSearchParams(window.location.search).get('mercado_pago');
  return <section className="mb-5 border-y border-slate-200 py-4" aria-label="Conta de recebimento">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h3 className="font-bold">Recebimentos pelo Mercado Pago</h3>
        <p className="text-sm text-slate-600">{account?.connected ? `Conta ${account.collector_id} conectada` : 'Nenhuma conta conectada'}</p></div>
      {account && <button type="button" disabled={busy || (!account.connected && !account.configured)}
        onClick={account.connected ? disconnect : connect} className="btn-secondary disabled:opacity-50">
        {busy ? 'Aguarde...' : account.connected ? 'Desconectar' : 'Conectar Mercado Pago'}</button>}
    </div>
    {account && !account.configured && <p className="mt-2 text-sm text-slate-500">Conexao aguardando configuracao pela equipe ArenaFlow.</p>}
    {(error || result === 'error') && <p role="alert" className="mt-2 text-sm text-red-700">{error || 'A autorizacao nao foi concluida. Tente novamente.'}</p>}
    {result === 'connected' && account?.connected && <p role="status" className="mt-2 text-sm text-emerald-700">Conta de recebimento conectada.</p>}
  </section>;
}
