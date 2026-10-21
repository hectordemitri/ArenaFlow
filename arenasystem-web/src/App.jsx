import { BrowserRouter, Routes, Route, Navigate, Link } from 'react-router-dom';
import { lazy, Suspense } from 'react';
import { CarrinhoProvider } from './contexts/CarrinhoProvider';
import { ArenaContextProvider } from './contexts/ArenaContext';

// Públicas
import Login from './pages/Login';
import Cadastro from './pages/Cadastro';
import Precos from './pages/Precos';
import AceitarConvite from './pages/AceitarConvite';
import RecuperarSenha from './pages/RecuperarSenha';
import ConfirmarEmail from './pages/ConfirmarEmail';

// Aluno
import Home from './pages/Home';
import Turmas from './pages/Turmas';
import Mensalidades from './pages/Mensalidades';
import Loja from './pages/Loja';
import MeusPedidos from './pages/MeusPedidos';
import MinhasSolicitacoes from './pages/MinhasSolicitacoes';
import Reservas from './pages/Reservas';
import Checkins from './pages/Checkins';
import Acessos from './pages/Acessos';
import Notificacoes from './pages/Notificacoes';
import Perfil from './pages/Perfil';
import PerfilDados from './pages/PerfilDados';
import PerfilNotificacoes from './pages/PerfilNotificacoes';
import PerfilSeguranca from './pages/PerfilSeguranca';
import PerfilSessoes from './pages/PerfilSessoes';
import MfaSettings from './components/MfaSettings';
import ProfessorCheckins from './pages/ProfessorCheckins';

// Admin
import LayoutAdmin from './components/admin/LayoutAdmin';
import AdminSolicitacoes from './pages/admin/Solicitacoes';
import FilaEspera from './pages/admin/FilaEspera';
import Alunos from './pages/admin/Alunos';
import MensalidadesAdmin from './pages/admin/MensalidadesAdmin';
import TurmasQuadras from './pages/admin/TurmasQuadras';
import Auditoria from './pages/admin/Auditoria';
import SaasArenas from './pages/admin/SaasArenas';
import SaasArenaDetalhe from './pages/admin/SaasArenaDetalhe';
import MinhaAssinatura from './pages/admin/MinhaAssinatura';
import Onboarding from './pages/admin/Onboarding';
import Equipe from './pages/admin/Equipe';
import SaasOperacao from './pages/admin/SaasOperacao';
import Suporte from './pages/admin/Suporte';
import Privacidade from './pages/admin/Privacidade';
import Ajuda from './pages/admin/Ajuda';
import RotaAdminPermissao from './components/admin/RotaAdminPermissao';
import RotaAppAluno from './components/RotaAppAluno';
import CheckinsAdmin from './pages/admin/CheckinsAdmin';
import PlanosMembros from './pages/admin/PlanosMembros';

const DashboardAdmin = lazy(() => import('./pages/admin/DashboardAdmin'));
const Estoque = lazy(() => import('./pages/admin/Estoque'));
const GestaoAvancada = lazy(() => import('./pages/admin/GestaoAvancada'));

function App() {
  return (
    <CarrinhoProvider>
      <ArenaContextProvider>
        <BrowserRouter>
        <Suspense fallback={<p role="status" className="p-6 text-slate-500">Carregando...</p>}>
        <Routes>
          {/* Públicas */}
          <Route path="/login" element={<Login />} />
          <Route path="/cadastro" element={<Cadastro />} />
          <Route path="/precos" element={<Precos />} />
          <Route path="/aceitar-convite" element={<AceitarConvite />} />
          <Route path="/recuperar-senha" element={<RecuperarSenha />} />
          <Route path="/redefinir-senha" element={<RecuperarSenha confirm />} />
          <Route path="/confirmar-email" element={<ConfirmarEmail />} />
          <Route path="/seguranca" element={<main className="mx-auto max-w-xl px-4 py-12"><h1 className="mb-6 text-2xl font-bold">Seguranca da conta ArenaFlow</h1><MfaSettings /></main>} />

          {/* App do aluno */}
          <Route path="/" element={<Navigate to="/app" replace />} />
          <Route path="/app" element={<RotaAppAluno><Home /></RotaAppAluno>} />
          <Route path="/app/turmas" element={<RotaAppAluno><Turmas /></RotaAppAluno>} />
          <Route path="/app/minhas-solicitacoes" element={<RotaAppAluno><MinhasSolicitacoes /></RotaAppAluno>} />
          <Route path="/app/mensalidades" element={<RotaAppAluno><Mensalidades /></RotaAppAluno>} />
          <Route path="/app/loja" element={<RotaAppAluno><Loja /></RotaAppAluno>} />
          <Route path="/app/meus-pedidos" element={<RotaAppAluno><MeusPedidos /></RotaAppAluno>} />
          <Route path="/app/reservas" element={<RotaAppAluno><Reservas /></RotaAppAluno>} />
          <Route path="/app/checkins" element={<RotaAppAluno><Checkins /></RotaAppAluno>} />
          <Route path="/app/acessos" element={<RotaAppAluno><Acessos /></RotaAppAluno>} />
          <Route path="/app/notificacoes" element={<RotaAppAluno><Notificacoes /></RotaAppAluno>} />
          <Route path="/app/perfil" element={<RotaAppAluno><Perfil /></RotaAppAluno>} />
          <Route path="/app/perfil/dados" element={<RotaAppAluno><PerfilDados /></RotaAppAluno>} />
          <Route path="/app/perfil/notificacoes" element={<RotaAppAluno><PerfilNotificacoes /></RotaAppAluno>} />
          <Route path="/app/perfil/seguranca" element={<RotaAppAluno><PerfilSeguranca /></RotaAppAluno>} />
          <Route path="/app/perfil/sessoes" element={<RotaAppAluno><PerfilSessoes /></RotaAppAluno>} />
          <Route path="/app/professor" element={<RotaAppAluno><ProfessorCheckins /></RotaAppAluno>} />
          <Route path="/turmas" element={<Navigate to="/app/turmas" replace />} />
          <Route path="/minhas-solicitacoes" element={<Navigate to="/app/minhas-solicitacoes" replace />} />
          <Route path="/mensalidades" element={<Navigate to="/app/mensalidades" replace />} />
          <Route path="/loja" element={<Navigate to="/app/loja" replace />} />
          <Route path="/meus-pedidos" element={<Navigate to="/app/meus-pedidos" replace />} />
          <Route path="/reservas" element={<Navigate to="/app/reservas" replace />} />
          <Route path="/acesso-negado" element={<AcessoNegado />} />

          {/* Painel admin — UMA ÚNICA estrutura aninhada */}
          <Route path="/admin" element={<LayoutAdmin />}>
            <Route index element={<DashboardAdmin />} />
            <Route path="solicitacoes" element={<RotaAdminPermissao permission="alunos.manage"><AdminSolicitacoes /></RotaAdminPermissao>} />
            <Route path="fila-espera" element={<RotaAdminPermissao permission="alunos.manage"><FilaEspera /></RotaAdminPermissao>} />
            <Route path="alunos" element={<RotaAdminPermissao permission="alunos.manage"><Alunos /></RotaAdminPermissao>} />
            <Route path="planos-membros" element={<RotaAdminPermissao permission="alunos.manage"><PlanosMembros /></RotaAdminPermissao>} />
            <Route path="checkins" element={<RotaAdminPermissao permission="checkin.manage"><CheckinsAdmin /></RotaAdminPermissao>} />
            <Route path="mensalidades" element={<RotaAdminPermissao permission="mensalidades.manage"><MensalidadesAdmin /></RotaAdminPermissao>} />
            <Route path="estoque" element={<RotaAdminPermissao permission="estoque.manage"><Estoque /></RotaAdminPermissao>} />
            <Route path="turmas" element={<RotaAdminPermissao permission="turmas.manage"><TurmasQuadras /></RotaAdminPermissao>} />
            <Route path="gestao" element={<RotaAdminPermissao permission="financeiro.manage"><GestaoAvancada /></RotaAdminPermissao>} />
            <Route path="auditoria" element={<RotaAdminPermissao permission="auditoria.view"><Auditoria /></RotaAdminPermissao>} />
            <Route path="assinatura" element={<RotaAdminPermissao permission="subscription.view"><MinhaAssinatura /></RotaAdminPermissao>} />
            <Route path="onboarding" element={<RotaAdminPermissao permission="dashboard.view"><Onboarding /></RotaAdminPermissao>} />
            <Route path="equipe" element={<RotaAdminPermissao permission="usuarios.view"><Equipe /></RotaAdminPermissao>} />
            <Route path="suporte" element={<RotaAdminPermissao permission="support.view"><Suporte /></RotaAdminPermissao>} />
            <Route path="privacidade" element={<RotaAdminPermissao permission="privacy.manage"><Privacidade /></RotaAdminPermissao>} />
            <Route path="saas/operacao" element={<RotaAdminPermissao permission="saas.manage"><SaasOperacao /></RotaAdminPermissao>} />
            <Route path="ajuda" element={<RotaAdminPermissao permission="dashboard.view"><Ajuda /></RotaAdminPermissao>} />
            <Route path="saas/arenas" element={<RotaAdminPermissao permission="saas.manage"><SaasArenas /></RotaAdminPermissao>} />
            <Route path="saas/arenas/:arenaId" element={<RotaAdminPermissao permission="saas.manage"><SaasArenaDetalhe /></RotaAdminPermissao>} />
          </Route>
        </Routes>
        </Suspense>
        </BrowserRouter>
      </ArenaContextProvider>
    </CarrinhoProvider>
  );
}

function AcessoNegado() {
  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center p-6">
      <div className="max-w-md rounded-xl border border-gray-100 bg-white p-8 text-center shadow-sm">
        <h1 className="text-2xl font-bold text-gray-900">Acesso nao habilitado</h1>
        <p className="mt-2 text-gray-600">
          Seu perfil nao possui um contexto pessoal ou administrativo disponivel nesta arena.
        </p>
        <Link to="/login" className="mt-5 inline-flex rounded-lg bg-teal-700 px-4 py-2 font-semibold text-white hover:bg-teal-800">
          Voltar ao login
        </Link>
      </div>
    </div>
  );
}

export default App;
