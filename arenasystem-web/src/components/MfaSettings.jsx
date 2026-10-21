import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../api/client';
import { apiErrorMessage } from '../utils/apiErrors';

export default function MfaSettings() {
  const navigate = useNavigate();
  const [status, setStatus] = useState(null);
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [secret, setSecret] = useState('');
  const [codes, setCodes] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    api.get('/auth/mfa/').then(({ data }) => { if (active) setStatus(data); })
      .catch((err) => { if (active) setError(apiErrorMessage(err)); });
    return () => { active = false; };
  }, []);
  function loginAgain() {
    localStorage.removeItem('access_token'); localStorage.removeItem('refresh_token');
    navigate('/login', { replace: true });
  }
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const payload = { current_password: password, code };
      if (status.enabled) { await api.delete('/auth/mfa/', { data: payload }); loginAgain(); }
      else if (!secret) { const { data } = await api.post('/auth/mfa/', payload); setSecret(data.secret); }
      else { const { data } = await api.put('/auth/mfa/', payload); setCodes(data.recovery_codes); setPassword(''); setSecret(''); }
    } catch (err) { setError(apiErrorMessage(err)); }
    finally { setBusy(false); }
  }
  if (codes.length) return <section className="app-surface p-5"><h2 className="font-bold">Codigos de recuperacao</h2>
    <p className="mt-2 text-sm text-slate-600">Guarde estes codigos em um local seguro. Cada um permite um unico acesso sem o autenticador.</p>
    <ul className="my-4 grid grid-cols-2 gap-2 font-mono text-sm">{codes.map((value) => <li key={value}>{value}</li>)}</ul>
    <button className="btn-primary" type="button" onClick={loginAgain}>Concluir e entrar novamente</button></section>;
  return <form onSubmit={submit} className="app-surface space-y-4 p-5">
    <h2 className="font-bold">Autenticacao em duas etapas</h2>
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    {!status ? <p className="text-sm text-slate-500">Carregando...</p> : <>
      <p className="text-sm text-slate-600">{status.enabled ? 'Ativada' : status.required ? 'Obrigatoria para esta conta' : 'Desativada'}</p>
      {status.available === false && <p className="text-sm text-slate-600">Autenticador temporariamente indisponivel. Contate o suporte.</p>}
      {(!status.enabled || !status.required) && <>
        <label className="block text-sm">Senha atual<input type="password" autoComplete="current-password" required value={password}
          onChange={(event) => setPassword(event.target.value)} className="mt-1 w-full rounded-md border border-slate-300 p-2" /></label>
        {secret && <label className="block text-sm">Chave do autenticador<input readOnly value={secret} className="mt-1 w-full rounded-md border border-slate-300 p-2 font-mono text-xs" /></label>}
        {(secret || status.enabled) && <label className="block text-sm">Codigo do autenticador<input required autoComplete="one-time-code" value={code}
          onChange={(event) => setCode(event.target.value)} className="mt-1 w-full rounded-md border border-slate-300 p-2" /></label>}
        <button disabled={busy || status.available === false} className="btn-primary disabled:opacity-50">{busy ? 'Aguarde...' : status.enabled ? 'Desativar duas etapas' : secret ? 'Confirmar ativacao' : 'Configurar autenticador'}</button>
      </>}
    </>}
  </form>;
}
