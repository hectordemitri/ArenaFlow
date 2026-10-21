# ArenaFlow Deploy Runbook

## Build local validado

Backend:

```powershell
cd arenasystem
venv\Scripts\python.exe manage.py check
venv\Scripts\python.exe manage.py test
venv\Scripts\python.exe manage.py migrate
```

Frontend:

```powershell
cd arenasystem-web
npm run lint
npm run build
```

## Variaveis obrigatorias em producao

Para dados reais, use `render.production.yaml`. O `render.yaml` original continua
exclusivo para demonstracao. Nenhum recurso foi provisionado automaticamente.

Backend:

- `DEBUG=False`
- `SECRET_KEY`: segredo forte e exclusivo do ambiente
- `APP_ENCRYPTION_KEYS`: chaves Fernet separadas de SECRET_KEY, compartilhadas por web/worker/Beat
- `SUPERADMIN_REQUIRE_MFA=True` e `DEMO_MODE=False`
- `MEDIA_STORAGE_BUCKET` e credenciais/endpoint S3 para midias privadas persistentes
- `ALLOWED_HOSTS`: dominios reais, sem `*`
- `CORS_ALLOWED_ORIGINS`: frontend real, sem wildcard
- `CSRF_TRUSTED_ORIGINS`: origens HTTPS confiaveis
- `FRONTEND_URL` e `PUBLIC_BACKEND_URL`
- `SESSION_COOKIE_SECURE=True`
- `CSRF_COOKIE_SECURE=True`
- `SECURE_SSL_REDIRECT=True` quando houver HTTPS no Django/proxy
- `USE_X_FORWARDED_PROTO=True` quando houver proxy reverso HTTPS
- `REDIS_URL`: broker compartilhado por web, worker e scheduler
- `MERCADO_PAGO_SAAS_ACCESS_TOKEN` e `MERCADO_PAGO_SAAS_WEBHOOK_SECRET`
- SMTP: `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`
- `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend` (nao copiar o console do exemplo local)
- `SENTRY_DSN` opcional; PII permanece desabilitada

Frontend:

- `VITE_API_URL`: URL publica da API terminando em `/api`
- `VITE_BASE_PATH`: `/` salvo deploy em subpasta

## Banco

Desenvolvimento usa SQLite. Producao deve usar PostgreSQL ou banco provisionado pelo provedor. Antes de migrar:

1. Fazer backup do SQLite atual, se tiver dados reais.
2. Provisionar banco.
3. Configurar `DATABASE_URL`; o adapter PostgreSQL ja esta implementado.
4. Rodar migrações em ambiente de staging.
5. Validar rollback e restore.

### Demonstracao: Supabase + Render + Vercel

- Crie um projeto Supabase exclusivo para demo e use a connection string PostgreSQL do session pooler em `DATABASE_URL`.
- No Render, use o Blueprint `render.yaml` da raiz e preencha apenas as variaveis marcadas como `sync: false`.
- No Vercel, publique `arenasystem-web` com `VITE_API_URL=https://<servico-render>/api`, `VITE_DEMO_LOGIN_ENABLED=true` e somente usernames demo publicos.
- Execute `seed_demo`, `seed_gestao` e `seed_estoque` somente com `DEMO_MODE=True`; a senha vem de `DEMO_ADMIN_PASSWORD` e nunca deve entrar no bundle React.
- O filesystem do Render e efemero. Nao use uploads locais como fonte persistente no ambiente demo.

## HTTPS, dominio e proxy

Configurar:

- DNS do frontend.
- DNS/API do backend.
- Certificado HTTPS.
- Proxy reverso encaminhando `X-Forwarded-Proto`.
- `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS` e `CSRF_TRUSTED_ORIGINS` coerentes.

## Logs

Requisitos antes de producao:

- logs de erro do backend;
- logs de acesso do proxy;
- sem senhas/tokens em logs;
- retencao e rotacao definidas;
- monitoramento de 5xx e latencia.

O backend emite JSON estruturado e `X-Request-ID`. `/api/health/` e minimo; `/api/health/ready/` exige banco, Redis e heartbeat do worker. Detalhes dos componentes ficam restritos ao superadmin.

## Backup

O comando `python manage.py backup_database --output backups/antes-do-deploy.backup`
cria backup consistente sem sobrescrever destinos. SQLite passa por integrity_check;
PostgreSQL usa pg_dump em formato custom. Instale no worker um pg_dump compativel com
a versao do servidor antes de habilitar o agendamento. O runtime Python nativo do
provedor nao garante a disponibilidade desse executavel.

Com `BACKUP_STORAGE_BUCKET` e credenciais separadas, o Beat agenda um backup diario
e `python manage.py backup_database --upload` envia ao bucket privado. Configure no
provedor criptografia, versionamento, ciclo de vida/retencao e alerta de falha das
tarefas. A agenda so e registrada quando o bucket foi configurado.

Teste de restauracao SQLite faz parte da suite. A restauracao PostgreSQL e de
midias deve ser exercitada em ambiente isolado antes da entrada de dados reais.

Estrategia sugerida:

- backup automatico diario do banco;
- backup de midias enviadas;
- retencao minima de 7 diarios e 4 semanais;
- armazenamento externo criptografado;
- teste mensal de restauracao;
- RPO sugerido: 24h;
- RTO sugerido MVP: 4h.

## Assinatura SaaS e tarefas

- Web, Celery worker, Celery Beat e Redis devem usar o mesmo `SECRET_KEY`, `DATABASE_URL` e `REDIS_URL`.
- O webhook SaaS valida `x-signature`/`x-request-id`, consulta o recurso no Mercado Pago e usa idempotencia local.
- Planos nascem como rascunho sem preco. O superadmin precisa precificar e publicar antes do checkout.
- Execute `python manage.py reconcile_saas_subscriptions` como reconciliacao manual segura.
- Mensalidades agora usam OAuth por arena. O token global de alunos foi retirado do fluxo.
- Configure `MERCADO_PAGO_CLIENT_ID`, `MERCADO_PAGO_CLIENT_SECRET`,
  `MERCADO_PAGO_REDIRECT_URI` e `MERCADO_PAGO_WEBHOOK_SECRET`.
- Cadastre exatamente a URL `/api/mercado-pago/callback/` no Mercado Pago e habilite PKCE.
- O dono conecta a conta em Mensalidades. Uma mesma conta nao pode receber por duas arenas.
- A assinatura SaaS continua com suas credenciais separadas.
- O Beat gera mensalidades por hora e reconcilia pagamentos a cada dez minutos.
- Execute `python manage.py reconcile_student_payments` para reconciliar manualmente.

## Seguranca de acesso

O superadmin configura o autenticador em `/seguranca` (ou no perfil de seguranca).
Em producao, o primeiro login fica restrito a essa configuracao ate a ativacao.
Codigos de recuperacao aparecem uma vez e sao armazenados como hashes. Tokens
anteriores a ativacao sao revogados. Perder autenticador e todos os codigos exige
procedimento operacional de recuperacao de identidade; nao existe bypass publico.

O painel nativo `/admin/` do Django aceita somente superadmin e tambem pede o
segundo fator. As paginas antigas `/dashboard/` e `/aulas/`, que nao aplicavam
o isolamento atual, deixaram de ser publicadas. O painel React continua em `/admin`.

Chaves Fernet nao devem ser descartadas enquanto houver dados criptografados com
elas. Para rotacao, inclua a nova primeiro e mantenha as anteriores para leitura.
Backups devem preservar tambem as chaves em cofre externo, separado do banco.

## Restauracao

1. Criar um banco temporario isolado.
2. Restaurar o backup sem apontar a aplicacao de producao.
3. Rodar `manage.py migrate --plan` e `manage.py check`.
4. Conferir arenas, usuarios, assinaturas, faturas e auditoria por contagem e amostragem.
5. Executar smoke tests tenant A/tenant B.
6. Registrar data, RPO observado, tempo total e responsavel.
7. Promover o banco restaurado somente com autorizacao formal.

O teste real de restauracao continua pendente ate existirem projeto Supabase, backup e autorizacao.
