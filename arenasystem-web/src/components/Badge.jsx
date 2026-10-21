function Badge({ status, texto }) {
  // Mapeia o status para cores + ícone
  const estilos = {
    pago: 'bg-green-100 text-green-700 border-green-200',
    pendente: 'bg-cyan-100 text-cyan-700 border-cyan-200',
    atrasado: 'bg-red-100 text-red-700 border-red-200',
    cancelada: 'bg-gray-100 text-gray-700 border-gray-200',
    estornada: 'bg-slate-100 text-slate-700 border-slate-200',
    contestada: 'bg-red-100 text-red-700 border-red-200',
    aberta: 'bg-blue-100 text-blue-700 border-blue-200',
    paga: 'bg-green-100 text-green-700 border-green-200',
  };

  const icones = {
    pago: '✓',
    pendente: '⏳',
    atrasado: '⚠️',
    cancelada: '✕',
    aberta: '📋',
    paga: '✓',
  };

  const classe = estilos[status] || 'bg-gray-100 text-gray-700 border-gray-200';
  const icone = icones[status] || '•';

  return (
    <span className={`inline-flex items-center gap-1 text-xs font-semibold px-2.5 py-1 rounded-full border ${classe}`}>
      <span>{icone}</span>
      {texto}
    </span>
  );
}

export default Badge;
