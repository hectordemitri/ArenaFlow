# ArenaFlow QA Matrix

Data: 2026-07-30

| Fluxo | Perfil | Cenario | Resultado esperado | Resultado encontrado | Severidade | Correcao | Teste |
|---|---|---|---|---|---|---|---|
| Login | Aluno | Login demo aluno | Redireciona para App aluno | Redirecionava para `/` | Medio | Rotas pessoais movidas para `/app` e destino centralizado | Lint/build |
| Login | Admin | Login demo admin | Redireciona para Painel admin | Funcionava, mas logica estava espalhada | Baixo | `initialPathFor(user)` centraliza destino | Lint/build |
| App aluno vs Admin | Admin | Trocar para app pessoal | Troca explicita e visivel | Link apontava para `/` | Medio | Links agora apontam para `/app` | Lint |
| Reservas | Admin no App aluno | Ver "Minhas reservas" | Lista somente reservas do usuario | Listava reservas da arena | Alto | Endpoint aceita `?minhas=1` e frontend usa esse escopo | `gestao.tests` |
| Reservas | Admin no App aluno | Criar reserva pessoal | Reserva vinculada ao usuario | Podia virar reserva avulsa admin | Alto | `?minhas=1` vincula `aluno=request.user` | `gestao.tests` |
| Reservas | Aluno Arena A | Acessar reserva Arena B por ID | 404 | Protegido | Critico | Mantido queryset por arena/ownership | `gestao.tests` |
| Mensalidades | Financeiro | Cancelar mensalidade | Status cancelada auditado | Status inexistente | Medio | Novo status e action `cancelar` | `arena.tests` |
| Mensalidades | Financeiro | PATCH direto de valor/status | Campos protegidos nao mudam | Serializer permitia mass assignment | Alto | Campos financeiros read-only; transicoes por actions | `arena.tests` |
| Mensalidades | Aluno Arena A | Acessar mensalidade Arena B | 404 | Protegido | Critico | Mantido queryset por aluno/arena | `arena.tests` |
| Pedidos | Aluno | Listar pedidos | Apenas proprios | Protegido em `VendaViewSet` | Alto | Confirmado em revisao | Matriz endpoint |
| Estoque | Perfil financeiro | Acessar produtos admin | 403 | Protegido | Alto | Mantido `estoque.manage` | `gestao.tests` |
| Auditoria | Recepcao | Acessar logs | 403 | Protegido | Alto | Mantido `auditoria.view` dono | `gestao.tests` |
| Uploads | Usuario | Enviar falso JPG | Rejeita conteudo invalido | Protegido | Alto | Validador backend por MIME/extensao/conteudo | `usuarios.tests` |
| Deploy | Producao | `DEBUG=False` sem SECRET/hosts | Falha ao iniciar | Protegido parcialmente | Critico | Guards de SECRET, hosts, CORS e flags HTTPS configuraveis | `manage.py check` |

## Pendencias documentadas

Esta tabela registra o estado de julho/2026. PostgreSQL, Playwright, webhooks SaaS
e o webhook seguro de alunos ja possuem implementacao. Os testes atuais e as
pendencias externas estao descritos abaixo; nao usar a tabela historica como
estado atual de implementacao.

| Item | Motivo | Proximo passo |
|---|---|---|
| E2E automatizado | Nao existe infraestrutura E2E no projeto | Criar Playwright/Cypress em etapa propria |
| Mercado Pago real | Depende de credenciais e conta | Implementar webhook assinado/idempotente com ambiente real |
| PostgreSQL producao | Dependente de provisionamento | Adicionar adapter/config depois da escolha da infra |
| Observabilidade externa | Dependente de provedor | Definir logs/alertas no deploy |

## Validacao tecnica atual

- `python manage.py test --settings=arenasystem.settings_test`: suite isolada;
  CI usa PostgreSQL para validar a disputa pelo ultimo produto e por um horario vazio.
- `E2E_REAL_API=1 npm run test:e2e`: inicia Django em 8001 com banco `e2e.sqlite3`
  separado do banco local e Vite em 4173. Nunca executar `serve_e2e` com outro settings.
- Fluxos reais: login, renovacao de JWT, produtos por arena, baixa de estoque,
  pedidos pessoais, conexao de pagamentos no painel e layout desktop/mobile.
- Pagamentos: assinatura invalida nao consulta o provedor; valor, moeda e recebedor
  precisam conferir; duplicatas e estados antigos nao alteram o resultado; estorno,
  contestacao, nova tentativa e reconciliacao sao cobertos.
- MFA: login sem codigo nao devolve tokens; codigos TOTP e de recuperacao nao podem
  ser reutilizados; o teste com pyotp real exige a dependencia instalada.
- Backup SQLite e restauração dos dados sao cobertos automaticamente.

Antes do piloto: sandbox Mercado Pago, entrega SMTP, restore PostgreSQL e midias,
Redis/worker/Beat em homologacao, instalacao PWA em aparelhos fisicos e carga real.

Evidencias locais em 20/10/2026: 133 testes backend (3 pulados por falta de pyotp
e PostgreSQL no runtime local), 29 testes frontend e 16 cenarios de navegador
aprovados. A CI foi configurada para instalar pyotp e executar o backend em
PostgreSQL; esta execucao remota ainda nao foi disparada. A instalacao das novas
dependencias pela rede foi bloqueada no Windows. O teste com pyotp real e os dois
testes de disputa entre transacoes precisam passar nesse ambiente completo.

Backup local anterior as migracoes: `backups/before-technical-20261020.sqlite3`.
