import { NavLink } from 'react-router-dom';
import { useEffect, useState } from 'react';
import api from '../../api/client';
import { adminNavigationFor } from '../../auth/permissions';
import Icon from '../Icon';
import useTerminology from '../../hooks/useTerminology';
import { useArenaContext } from '../../contexts/arenaContextStore';

function SidebarAdmin() {
  const { arena, terms, features } = useTerminology();
  const { contexto } = useArenaContext();
  const [usuario, setUsuario] = useState(null);

  useEffect(() => {
    let active = true;
    async function carregarUsuario() {
      try {
        const { data } = await api.get('/usuarios/me/');
        if (active) setUsuario(data);
      } catch {
        if (active) setUsuario(null);
      }
    }
    void carregarUsuario();
    return () => {
      active = false;
    };
  }, []);

  const itens = adminNavigationFor(usuario, { terms, features, hasTenantContext: Boolean(contexto) });

  return (
    <aside className="hidden min-h-screen w-64 shrink-0 flex-col border-r border-slate-900 bg-slate-950 text-slate-100 md:flex">
      <div className="border-b border-white/10 p-4">
        <h1 className="flex items-center gap-3 font-bold">
          <span className="brand-mark h-10 w-10 rounded-lg">
            {arena.logo ? (
              <img src={arena.logo} alt={arena.nome} className="h-full w-full object-cover" />
            ) : (
              <Icon name="court" className="h-5 w-5" />
            )}
          </span>
          <span className="sidebar-brand-name text-slate-100">{arena.nome}</span>
        </h1>
        <p className="mt-1 text-xs text-slate-400">Painel administrativo</p>
      </div>

      <div className="px-4 pt-4 text-[11px] font-bold uppercase tracking-wide text-slate-500">
        Operacao
      </div>
      <nav className="flex-1 px-3 py-2">
        {itens.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.exact}
            className={({ isActive }) =>
              `mb-1 flex items-center gap-3 rounded-md px-3 py-2.5 text-sm transition ${
                isActive
                  ? 'admin-nav-active font-bold'
                  : 'text-slate-400 hover:bg-white/10 hover:text-white'
              }`
            }
          >
            <Icon name={item.icon} className="h-5 w-5" />
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-white/10 p-4">
        <NavLink to="/app" className="flex items-center gap-2 rounded-md px-2 py-2 text-sm font-semibold text-slate-300 transition hover:bg-white/10 hover:text-white">
          <span>{'<'}</span>
          <span>App do {terms.pessoa_singular}</span>
        </NavLink>
        <p className="mt-3 px-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-600">
          Tecnologia ArenaFlow
        </p>
      </div>
    </aside>
  );
}

export default SidebarAdmin;
