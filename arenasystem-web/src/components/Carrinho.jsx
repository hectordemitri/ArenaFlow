import { useRef, useState } from 'react';
import { useCarrinho } from '../contexts/useCarrinho';
import { formatarMoeda } from '../utils/format';
import api from '../api/client';

function Carrinho({ aberto, onFechar, onPedidoCriado }) {
  const { itens, alterarQuantidade, remover, limpar, totalValor } = useCarrinho();
  const [enviando, setEnviando] = useState(false);
  const submission = useRef(null);
  const sending = useRef(false);

  const finalizar = async () => {
    if (itens.length === 0 || sending.current) return;
    sending.current = true;

    setEnviando(true);
    try {
      // Monta o payload no formato que a API espera
      const payload = {
        itens: itens.map((i) => ({
          produto: i.produto.id,
          quantidade: i.quantidade,
        })),
      };

      const fingerprint = JSON.stringify(payload);
      if (submission.current?.fingerprint !== fingerprint) {
        submission.current = { fingerprint, key: crypto.randomUUID() };
      }
      const { data } = await api.post('/vendas/', payload, {
        headers: { 'X-Idempotency-Key': submission.current.key },
      });
      submission.current = null;
      limpar();
      onFechar();
      onPedidoCriado?.(data);
    } catch (err) {
      const msg = err.response?.data?.detail || 'Erro ao finalizar pedido';
      onPedidoCriado?.({ erro: msg });
    } finally {
      sending.current = false;
      setEnviando(false);
    }
  };

  if (!aberto) return null;

  return (
    <>
      {/* Overlay escuro */}
      <div
        className="fixed inset-0 z-40 bg-black bg-opacity-40 animate-fade-in"
        onClick={onFechar}
      />

      {/* Drawer lateral */}
      <div className="fixed bottom-0 right-0 top-0 z-50 flex w-full flex-col bg-white shadow-2xl animate-slide-left sm:w-96">
        {/* Header */}
        <div className="brand-gradient flex items-center justify-between p-5 text-white">
          <h2 className="flex items-center gap-2 text-xl font-bold">
            🛒 Meu Carrinho
          </h2>
          <button
            onClick={onFechar}
            className="flex h-8 w-8 items-center justify-center rounded-full text-2xl leading-none text-white transition hover:bg-white/15"
          >
            ×
          </button>
        </div>

        {/* Lista de itens */}
        <div className="flex-1 overflow-y-auto p-4">
          {itens.length === 0 ? (
            <div className="text-center py-12">
              <div className="text-5xl mb-3">🛒</div>
              <p className="text-gray-600 font-medium">Carrinho vazio</p>
              <p className="text-gray-400 text-sm mt-1">
                Adicione produtos para continuar
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {itens.map((item) => (
                <div
                  key={item.produto.id}
                  className="flex gap-3 rounded-lg bg-gray-50 p-3"
                >
                  <div className="tenant-icon flex h-14 w-14 shrink-0 items-center justify-center rounded-lg text-2xl">
                    {item.produto.is_aluguel ? '🎾' : '🛒'}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="font-semibold text-sm text-gray-800 truncate">
                      {item.produto.nome}
                    </p>
                    <p className="text-xs text-gray-500">
                      {formatarMoeda(item.produto.preco)} cada
                    </p>
                    <div className="flex items-center justify-between mt-2">
                      <div className="flex items-center gap-1 bg-white rounded border">
                        <button
                          onClick={() => alterarQuantidade(item.produto.id, item.quantidade - 1)}
                          className="tenant-link h-7 w-7 font-bold hover:bg-gray-100"
                        >
                          −
                        </button>
                        <span className="text-sm font-semibold w-6 text-center">
                          {item.quantidade}
                        </span>
                        <button
                          onClick={() => alterarQuantidade(item.produto.id, item.quantidade + 1)}
                          disabled={item.quantidade >= item.produto.estoque}
                          className="tenant-link h-7 w-7 font-bold hover:bg-gray-100 disabled:opacity-30"
                        >
                          +
                        </button>
                      </div>
                      <button
                        onClick={() => remover(item.produto.id)}
                        className="text-red-500 text-xs hover:underline"
                      >
                        Remover
                      </button>
                    </div>
                  </div>
                  <div className="text-right shrink-0">
                    <p className="tenant-link font-bold">
                      {formatarMoeda(Number(item.produto.preco) * item.quantidade)}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer com total e finalizar */}
        {itens.length > 0 && (
          <div className="border-t p-5 bg-gray-50 space-y-3">
            <div className="flex justify-between items-center">
              <span className="text-gray-600">Total:</span>
              <span className="tenant-link text-2xl font-bold">
                {formatarMoeda(totalValor)}
              </span>
            </div>
            <button
              onClick={finalizar}
              disabled={enviando}
              className="btn-success w-full py-3 disabled:opacity-50"
            >
              {enviando ? 'Processando...' : '✓ Finalizar Pedido'}
            </button>
            <button
              onClick={limpar}
              className="w-full text-sm text-gray-500 hover:text-red-500 transition"
            >
              Limpar carrinho
            </button>
          </div>
        )}
      </div>
    </>
  );
}

export default Carrinho;
