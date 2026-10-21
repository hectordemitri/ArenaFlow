import { useCallback, useEffect, useState } from 'react';
import api from '../../api/client';
import Toast from '../../components/Toast';
import useDebounce from '../../hooks/useDebounce';
import PaymentConnection from '../../components/admin/PaymentConnection';
import { formatarData, formatarMoeda } from '../../utils/format';

const filtros = [
  { key: 'todas', label: 'Todas' },
  { key: 'pendente', label: 'Pendentes' },
  { key: 'atrasado', label: 'Atrasadas' },
  { key: 'pago', label: 'Pagas' },
  { key: 'cancelada', label: 'Canceladas' },
  { key: 'estornada', label: 'Estornadas' },
  { key: 'contestada', label: 'Contestadas' },
];

const periodos = [
  { key: 'todos', label: 'Todos os meses' },
  { key: 'mes_atual', label: 'Mes atual' },
  { key: 'mes_passado', label: 'Mes passado' },
  { key: 'proximo_mes', label: 'Proximo mes' },
  { key: 'ano_atual', label: 'Ano atual' },
  { key: 'vencidas', label: 'Vencidas' },
];

function MensalidadesAdmin() {
  const [mensalidades, setMensalidades] = useState([]);
  const [carregando, setCarregando] = useState(true);
  const [statusFiltro, setStatusFiltro] = useState('todas');
  const [periodoFiltro, setPeriodoFiltro] = useState('mes_atual');
  const [mesFiltro, setMesFiltro] = useState('');
  const [pagina, setPagina] = useState(1);
  const [paginacao, setPaginacao] = useState({ count: 0, next: null, previous: null });
  const [busca, setBusca] = useState('');
  const [toast, setToast] = useState(null);

  const buscaDebounce = useDebounce(busca, 400);

  const carregar = useCallback(async () => {
    setCarregando(true);
    try {
      const params = new URLSearchParams({ status: statusFiltro, page: String(pagina) });
      if (mesFiltro) {
        params.set('mes', mesFiltro);
      } else {
        params.set('periodo', periodoFiltro);
      }
      if (buscaDebounce) params.set('search', buscaDebounce);

      const { data } = await api.get(`/admin/mensalidades/?${params.toString()}`);
      setMensalidades(Array.isArray(data) ? data : data.results || []);
      setPaginacao(Array.isArray(data) ? { count: data.length, next: null, previous: null } : {
        count: data.count || 0,
        next: data.next,
        previous: data.previous,
      });
    } catch {
      setToast({ mensagem: 'Erro ao carregar mensalidades', tipo: 'erro' });
    } finally {
      setCarregando(false);
    }
  }, [buscaDebounce, mesFiltro, pagina, periodoFiltro, statusFiltro]);

  useEffect(() => {
    const id = setTimeout(carregar, 0);
    return () => clearTimeout(id);
  }, [carregar]);

  const resetarPagina = (callback) => {
    setPagina(1);
    callback();
  };

  const alterarStatus = async (mensalidade, acao) => {
    try {
      const { data } = await api.post(`/admin/mensalidades/${mensalidade.id}/${acao}/`);
      setToast({ mensagem: data.detail, tipo: 'sucesso' });
      await carregar();
    } catch (err) {
      setToast({ mensagem: err.response?.data?.detail || 'Erro ao alterar mensalidade', tipo: 'erro' });
    }
  };

  const totais = mensalidades.reduce(
    (acc, mensalidade) => {
      const valor = Number(mensalidade.valor) || 0;
      acc.total += valor;
      if (mensalidade.status === 'pago') acc.pago += valor;
      if (mensalidade.status === 'pendente') acc.pendente += valor;
      if (mensalidade.status === 'atrasado') acc.atrasado += valor;
      if (mensalidade.status === 'cancelada') acc.cancelada += valor;
      return acc;
    },
    { total: 0, pago: 0, pendente: 0, atrasado: 0, cancelada: 0 },
  );

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="mb-1 text-3xl font-bold text-gray-800">Mensalidades</h2>
          <p className="text-sm text-gray-600">
            Acompanhe cobrancas por status, periodo e paginas. Total encontrado: {paginacao.count}
          </p>
        </div>
        <button
          type="button"
          onClick={carregar}
          className="rounded-lg bg-gray-100 px-4 py-2 text-sm font-semibold text-gray-700 transition hover:bg-gray-200"
        >
          Atualizar
        </button>
      </div>

      <PaymentConnection />
      <div className="mb-5 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <Resumo titulo="Total listado" valor={formatarMoeda(totais.total)} />
        <Resumo titulo="Pago" valor={formatarMoeda(totais.pago)} cor="green" />
        <Resumo titulo="Pendente" valor={formatarMoeda(totais.pendente)} cor="cyan" />
        <Resumo titulo="Atrasado" valor={formatarMoeda(totais.atrasado)} cor="red" />
        <Resumo titulo="Cancelado" valor={formatarMoeda(totais.cancelada)} />
      </div>

      <div className="mb-4 space-y-3 rounded-xl border border-gray-100 bg-white p-4 shadow-sm">
        <input
          type="text"
          value={busca}
          onChange={(event) => {
            setPagina(1);
            setBusca(event.target.value);
          }}
          placeholder="Buscar por aluno, email ou plano..."
          className="w-full rounded-lg border border-gray-300 px-3 py-2 outline-none focus:ring-2 focus:ring-cyan-500"
        />

        <div className="flex flex-wrap gap-2">
          {filtros.map((filtro) => (
            <button
              key={filtro.key}
              type="button"
              onClick={() => resetarPagina(() => setStatusFiltro(filtro.key))}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
                statusFiltro === filtro.key
                  ? 'bg-teal-700 text-white shadow-sm'
                  : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
              }`}
            >
              {filtro.label}
            </button>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {periodos.map((periodo) => (
            <button
              key={periodo.key}
              type="button"
              onClick={() => {
                setMesFiltro('');
                resetarPagina(() => setPeriodoFiltro(periodo.key));
              }}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
                !mesFiltro && periodoFiltro === periodo.key
                  ? 'bg-gray-900 text-white shadow-sm'
                  : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
              }`}
            >
              {periodo.label}
            </button>
          ))}

          <label className="ml-0 flex items-center gap-2 text-sm text-gray-600 sm:ml-2">
            Mes especifico
            <input
              type="month"
              value={mesFiltro}
              onChange={(event) => {
                setPagina(1);
                setMesFiltro(event.target.value);
              }}
              className="rounded-lg border border-gray-300 px-3 py-1.5 outline-none focus:ring-2 focus:ring-cyan-500"
            />
          </label>
        </div>
      </div>

      {carregando ? (
        <EstadoLista titulo="Carregando mensalidades..." />
      ) : mensalidades.length === 0 ? (
        <EstadoLista titulo="Nenhuma mensalidade encontrada" detalhe="Ajuste os filtros ou confira as matriculas." />
      ) : (
        <div className="overflow-hidden rounded-xl border border-gray-100 bg-white shadow-sm">
          <table className="w-full">
            <thead className="border-b border-gray-200 bg-gray-50">
              <tr>
                <Th>Aluno</Th>
                <Th className="hidden md:table-cell">Plano</Th>
                <Th className="hidden lg:table-cell">Referencia</Th>
                <Th>Valor</Th>
                <Th className="hidden md:table-cell">Vencimento</Th>
                <Th>Status</Th>
                <Th className="text-right">Origem</Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {mensalidades.map((mensalidade) => (
                <tr key={mensalidade.id} className="transition hover:bg-gray-50">
                  <td className="p-3">
                    <p className="font-semibold text-gray-800">{mensalidade.aluno_nome}</p>
                    <p className="text-xs text-gray-500">#{mensalidade.id}</p>
                  </td>
                  <td className="hidden p-3 text-sm text-gray-600 md:table-cell">{mensalidade.plano_nome}</td>
                  <td className="hidden p-3 text-sm text-gray-600 lg:table-cell">
                    {formatarData(mensalidade.mes_referencia)}
                  </td>
                  <td className="p-3 text-sm font-semibold text-gray-800">{formatarMoeda(mensalidade.valor)}</td>
                  <td className="hidden p-3 text-sm text-gray-600 md:table-cell">
                    {formatarData(mensalidade.vencimento)}
                  </td>
                  <td className="p-3">
                    <StatusBadge status={mensalidade.status} label={mensalidade.status_display} />
                  </td>
                  <td className="p-3">
                    <div className="flex flex-wrap justify-end gap-2">
                      <AcaoStatus disabled={mensalidade.status === 'pago'} onClick={() => alterarStatus(mensalidade, 'pagar')}>Pago</AcaoStatus>
                      <AcaoStatus disabled={mensalidade.status === 'pendente'} onClick={() => alterarStatus(mensalidade, 'pendente')}>Pendente</AcaoStatus>
                      <AcaoStatus disabled={mensalidade.status === 'atrasado'} onClick={() => alterarStatus(mensalidade, 'atrasar')}>Atrasar</AcaoStatus>
                      <AcaoStatus disabled={mensalidade.status === 'cancelada'} onClick={() => alterarStatus(mensalidade, 'cancelar')}>Cancelar</AcaoStatus>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-gray-100 bg-gray-50 px-4 py-3">
            <p className="text-sm text-gray-500">
              Pagina {pagina} · mostrando {mensalidades.length} de {paginacao.count}
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={!paginacao.previous}
                onClick={() => setPagina((atual) => Math.max(1, atual - 1))}
                className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm font-semibold text-gray-700 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Anterior
              </button>
              <button
                type="button"
                disabled={!paginacao.next}
                onClick={() => setPagina((atual) => atual + 1)}
                className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm font-semibold text-gray-700 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Proxima
              </button>
            </div>
          </div>
        </div>
      )}

      {toast && <Toast mensagem={toast.mensagem} tipo={toast.tipo} onClose={() => setToast(null)} />}
    </div>
  );
}

function Resumo({ titulo, valor, cor = 'gray' }) {
  const cores = {
    gray: 'border-gray-100 text-gray-800',
    green: 'border-green-100 text-green-700',
    cyan: 'border-cyan-100 text-cyan-700',
    red: 'border-red-100 text-red-700',
  };

  return (
    <div className={`rounded-xl border bg-white p-4 shadow-sm ${cores[cor]}`}>
      <p className="text-xs font-semibold uppercase text-gray-500">{titulo}</p>
      <p className="mt-1 text-2xl font-bold">{valor}</p>
    </div>
  );
}

function Th({ children, className = '' }) {
  return <th className={`p-3 text-left text-xs font-bold uppercase text-gray-600 ${className}`}>{children}</th>;
}

function StatusBadge({ status, label }) {
  const cores = {
    pago: 'bg-green-100 text-green-700',
    pendente: 'bg-cyan-100 text-cyan-700',
    atrasado: 'bg-red-100 text-red-700',
    cancelada: 'bg-gray-200 text-gray-700',
    estornada: 'bg-slate-100 text-slate-700',
    contestada: 'bg-red-100 text-red-700',
  };

  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-bold ${cores[status] || 'bg-gray-100 text-gray-700'}`}>
      {label || status}
    </span>
  );
}

function AcaoStatus({ children, disabled, onClick }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="rounded-md border border-gray-200 bg-white px-2 py-1 text-xs font-semibold text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"
    >
      {children}
    </button>
  );
}

function EstadoLista({ titulo, detalhe }) {
  return (
    <div className="rounded-xl bg-white py-14 text-center shadow-sm">
      <p className="text-lg font-semibold text-gray-700">{titulo}</p>
      {detalhe && <p className="mt-1 text-sm text-gray-400">{detalhe}</p>}
    </div>
  );
}

export default MensalidadesAdmin;
