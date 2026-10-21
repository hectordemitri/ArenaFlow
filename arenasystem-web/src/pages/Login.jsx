import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import api from '../api/client';
import { initialPathFor } from '../auth/permissions';
import { clearArenaContext, migrateLegacyArenaContext } from '../arena/contextStorage';
import Icon from '../components/Icon';

const DEMO_LOGIN_ENABLED = import.meta.env.VITE_DEMO_LOGIN_ENABLED === 'true';
const DEMO_ADMIN_USERNAME = import.meta.env.VITE_DEMO_ADMIN_USERNAME || 'demo.admin';
const DEMO_STUDENT_USERNAME = import.meta.env.VITE_DEMO_STUDENT_USERNAME || 'demo.ana';

function Login() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [otpCode, setOtpCode] = useState('');
  const [mfaRequired, setMfaRequired] = useState(false);
  const [erro, setErro] = useState('');
  const [carregando, setCarregando] = useState(false);
  const navigate = useNavigate();

  const autenticar = async (credenciais) => {
    setErro('');
    setCarregando(true);

    try {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
      clearArenaContext();
      migrateLegacyArenaContext();

      const payload = {
        ...credenciais,
        username: credenciais.username?.trim(),
        email: credenciais.email?.trim(),
        login: credenciais.login?.trim(),
        password: credenciais.password,
      };

      const { data } = await api.post('/auth/login/', payload);
      localStorage.setItem('access_token', data.access);
      localStorage.setItem('refresh_token', data.refresh);

      const { data: usuario } = await api.get('/usuarios/me/');
      navigate(data.mfa_setup_required ? '/seguranca' : initialPathFor(usuario));
    } catch (err) {
      const dados = err.response?.data;
      if (dados?.code === 'mfa_required') setMfaRequired(true);
      const detalhe = dados?.detail || dados?.username?.[0] || dados?.password?.[0];
      setErro(detalhe || (!err.response
        ? 'Nao foi possivel conectar ao servidor. Verifique sua conexao e tente novamente.'
        : err.response.status >= 500 ? 'O servidor esta indisponivel. Tente novamente em instantes.'
          : 'Nao foi possivel concluir o login. Confira os dados informados.'));
    } finally {
      setCarregando(false);
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    void autenticar({ username, password, otp_code: otpCode });
  };

  const prepararDemo = (tipo) => {
    setUsername(tipo === 'admin' ? DEMO_ADMIN_USERNAME : DEMO_STUDENT_USERNAME);
    setPassword('');
    setErro('Informe a senha demo fornecida pelo responsavel pela apresentacao.');
  };

  return (
    <div className="grid min-h-screen bg-teal-700 text-white lg:grid-cols-[1.1fr_0.9fr]">
      <section className="hidden flex-col justify-between p-12 lg:flex">
        <div className="flex items-center gap-3 text-2xl font-bold">
          <span className="grid h-11 w-11 place-items-center rounded-xl bg-white/15">
            <Icon name="court" className="h-6 w-6" />
          </span>
          ArenaFlow
        </div>

        <div className="max-w-xl">
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-green-200">
            Gestao completa para arenas esportivas
          </p>
          <h1 className="mt-4 text-5xl font-bold leading-tight">
            Reservas, alunos, financeiro e operacao em um so lugar.
          </h1>
          <p className="mt-5 text-lg text-white/80">
            Organize turmas, mensalidades, check-ins, quadras e estoque com uma experiencia pronta para apresentacao comercial.
          </p>
        </div>

        <div className="grid grid-cols-3 gap-3 text-sm text-white/80">
          <ResumoDemo titulo="Turmas" texto="Matriculas, fila e check-in" />
          <ResumoDemo titulo="Financeiro" texto="Mensalidades e indicadores" />
          <ResumoDemo titulo="Operacao" texto="Reservas, estoque e pedidos" />
        </div>
      </section>

      <main className="flex items-center justify-center bg-gray-50 px-6 py-10 text-gray-900">
        <div className="w-full max-w-md">
          <div className="mb-8 flex items-center gap-3 text-2xl font-bold text-teal-700 lg:hidden">
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-teal-700 text-white">
              <Icon name="court" className="h-6 w-6" />
            </span>
            ArenaFlow
          </div>

          <div className="rounded-xl border border-gray-100 bg-white p-8 shadow-xl">
            <div className="mb-7">
              <p className="text-sm font-semibold uppercase tracking-wide text-teal-700">Acesso</p>
              <h2 className="mt-1 text-3xl font-bold text-gray-900">Entrar no sistema</h2>
              <p className="mt-2 text-gray-500">Use sua conta ou entre em modo demo para apresentar o SaaS.</p>
            </div>

            {DEMO_LOGIN_ENABLED && <div className="mb-6 grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => prepararDemo('admin')}
                disabled={carregando}
                className="rounded-lg border border-gray-200 px-3 py-3 text-left transition hover:border-cyan-300 hover:bg-cyan-50 disabled:opacity-60"
              >
                <Icon name="settings" className="mb-2 h-5 w-5 text-teal-700" />
                <span className="block text-sm font-semibold">Demo admin</span>
                <span className="block text-xs text-gray-500">Painel completo</span>
              </button>
              <button
                type="button"
                onClick={() => prepararDemo('aluno')}
                disabled={carregando}
                className="rounded-lg border border-gray-200 px-3 py-3 text-left transition hover:border-cyan-300 hover:bg-cyan-50 disabled:opacity-60"
              >
                <Icon name="users" className="mb-2 h-5 w-5 text-teal-700" />
                <span className="block text-sm font-semibold">Demo aluno</span>
                <span className="block text-xs text-gray-500">App aluno</span>
              </button>
            </div>}

            <form onSubmit={handleSubmit} className="space-y-4">
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-gray-700">Usuario</span>
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-4 py-2.5 outline-none focus:border-transparent focus:ring-2 focus:ring-cyan-500"
                  required
                />
              </label>

              <div className="text-right">
                <Link to="/recuperar-senha" className="text-sm font-semibold text-teal-700 hover:underline">Esqueci minha senha</Link>
              </div>

              <label className="block">
                <span className="mb-1 block text-sm font-medium text-gray-700">Senha</span>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-4 py-2.5 outline-none focus:border-transparent focus:ring-2 focus:ring-cyan-500"
                  required
                />
              </label>

              {mfaRequired && <label className="block"><span className="mb-1 block text-sm font-medium text-gray-700">Codigo do autenticador ou de recuperacao</span>
                <input autoComplete="one-time-code" value={otpCode} onChange={(event) => setOtpCode(event.target.value)} required
                  className="w-full rounded-lg border border-gray-300 px-4 py-2.5" autoFocus /></label>}
              {erro && (
                <div className="rounded border-l-4 border-red-500 bg-red-50 p-3 text-sm text-red-700">
                  {erro}
                </div>
              )}

              <button
                type="submit"
                disabled={carregando}
                className="flex w-full items-center justify-center gap-2 rounded-lg bg-teal-700 py-3 font-semibold text-white transition hover:bg-teal-800 disabled:opacity-50"
              >
                <Icon name="logIn" className="h-5 w-5" />
                {carregando ? 'Entrando...' : 'Entrar'}
              </button>
            </form>

            <p className="mt-6 text-center text-sm text-gray-500">
              Nao tem conta?{' '}
              <Link to="/cadastro" className="font-semibold text-teal-700 hover:underline">
                Cadastre-se
              </Link>
            </p>
          </div>
        </div>
      </main>
    </div>
  );
}

function ResumoDemo({ titulo, texto }) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/10 p-4">
      <p className="font-semibold text-white">{titulo}</p>
      <p className="mt-1 text-xs leading-relaxed">{texto}</p>
    </div>
  );
}

export default Login;
