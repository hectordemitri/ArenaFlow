import { useState } from 'react';
import { Link } from 'react-router-dom';

import api from '../api/client';
import MfaSettings from '../components/MfaSettings';
import ProfilePage, { Field, InlineMessage } from '../components/profile/ProfilePage';
import { apiErrorMessage, apiFieldErrors } from '../utils/apiErrors';

const emptyForm = { current_password: '', password: '', password_confirm: '' };

export default function PerfilSeguranca() {
  const [form, setForm] = useState(emptyForm);
  const [busy, setBusy] = useState(false);
  const [otherBusy, setOtherBusy] = useState(false);
  const [message, setMessage] = useState(null);
  const [errors, setErrors] = useState({});

  const update = (field) => (event) => setForm((current) => ({ ...current, [field]: event.target.value }));
  async function changePassword(event) {
    event.preventDefault(); setBusy(true); setMessage(null); setErrors({});
    try {
      const { data } = await api.post('/auth/password/change/', form);
      setForm(emptyForm);
      setMessage({ type: 'success', text: `${data.detail} ${data.other_sessions_revoked ? 'As outras sessões foram encerradas.' : ''}` });
    } catch (error) { setErrors(apiFieldErrors(error)); setMessage({ type: 'error', text: apiErrorMessage(error) }); }
    finally { setBusy(false); }
  }

  async function endOtherSessions() {
    setOtherBusy(true); setMessage(null);
    try {
      const { data } = await api.post('/auth/logout-others/');
      setMessage({ type: 'success', text: `${data.sessions_revoked} outra(s) sessão(ões) encerrada(s).` });
    } catch (error) { setMessage({ type: 'error', text: apiErrorMessage(error) }); }
    finally { setOtherBusy(false); }
  }

  return (
    <ProfilePage title="Privacidade e segurança" subtitle="Proteja sua conta com uma senha exclusiva e encerre acessos que você não reconhece.">
      {message && <div className="mb-4"><InlineMessage type={message.type}>{message.text}</InlineMessage></div>}
      <div className="space-y-5">
        <MfaSettings />
        <form onSubmit={changePassword} className="app-surface space-y-4 p-5">
          <div><h2 className="font-black text-slate-950">Alterar senha</h2><p className="mt-1 text-xs leading-5 text-slate-500">A nova senha passa pelos validadores de segurança do ArenaFlow.</p></div>
          <Field label="Senha atual" type="password" value={form.current_password} onChange={update('current_password')} autoComplete="current-password" required error={errors.current_password} />
          <Field label="Nova senha" type="password" value={form.password} onChange={update('password')} autoComplete="new-password" minLength="8" required error={errors.password} hint="Use uma senha longa e diferente das suas outras contas." />
          <Field label="Confirmar nova senha" type="password" value={form.password_confirm} onChange={update('password_confirm')} autoComplete="new-password" minLength="8" required error={errors.password_confirm} />
          <button disabled={busy} className="btn-primary w-full disabled:cursor-wait disabled:opacity-60">{busy ? 'Alterando...' : 'Alterar senha'}</button>
        </form>

        <section className="app-surface p-5">
          <h2 className="font-black text-slate-950">Acessos da conta</h2>
          <p className="mt-1 text-xs leading-5 text-slate-500">Você pode consultar cada dispositivo ou encerrar todos os outros acessos de uma vez.</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <Link to="/app/perfil/sessoes" className="btn-secondary w-full">Ver sessões conectadas</Link>
            <button type="button" onClick={endOtherSessions} disabled={otherBusy} className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm font-black text-red-700 disabled:opacity-60">{otherBusy ? 'Encerrando...' : 'Encerrar outras sessões'}</button>
          </div>
        </section>

        <section className="app-surface p-5"><h2 className="font-black text-slate-950">Esqueceu sua senha?</h2><p className="mt-1 text-xs leading-5 text-slate-500">Use o fluxo de recuperação para receber um link seguro e temporário.</p><Link to="/recuperar-senha" className="mt-4 inline-flex text-sm font-black text-[var(--arena-primary)]">Iniciar recuperação de senha</Link></section>
      </div>
    </ProfilePage>
  );
}
