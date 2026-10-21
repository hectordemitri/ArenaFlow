from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.utils import timezone
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from .models import Arena, Mensalidade, Matricula, Plano, Quadra
from .serializers import (
    ArenaSerializer,
    MensalidadeSerializer,
    MatriculaSerializer,
    PlanoSerializer,
    QuadraSerializer,
    SaasArenaCreateSerializer,
    SaasArenaSerializer,
)
from .services import (
    MercadoPagoAPIError,
    MercadoPagoConfigError,
    criar_dados_iniciais_arena,
    criar_preferencia_mensalidade,
)
from .tenant import get_request_arena, get_user_arena
from gestao.audit import registrar_auditoria
from usuarios.permissions import IsSaasSuperAdmin, require_permission


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def arena_atual(request):
    serializer = ArenaSerializer(get_request_arena(request), context={'request': request})
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def arenas_publicas(request):
    arenas = Arena.objects.filter(ativa=True).order_by('nome')
    serializer = ArenaSerializer(arenas, many=True, context={'request': request})
    return Response(serializer.data)


def atualizar_mensalidades_atrasadas(qs=None):
    from .payments import update_overdue
    return update_overdue(qs)


class QuadraViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = QuadraSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Quadra.objects.filter(arena=get_user_arena(self.request.user), ativa=True)


class AdminQuadraViewSet(viewsets.ModelViewSet):
    serializer_class = QuadraSerializer
    permission_classes = [require_permission('reservas.manage')]

    def get_queryset(self):
        return Quadra.objects.filter(arena=get_user_arena(self.request.user)).prefetch_related('manutencoes')

    def perform_create(self, serializer):
        from saas_billing.services import assert_plan_capacity

        arena = get_user_arena(self.request.user)
        assert_plan_capacity(arena, 'courts')
        serializer.save(arena=arena)


class SaasArenaViewSet(viewsets.ModelViewSet):
    serializer_class = SaasArenaSerializer
    permission_classes = [IsSaasSuperAdmin]

    def get_queryset(self):
        return Arena.objects.annotate(
            total_alunos=Count('usuarios', filter=Q(usuarios__tipo='aluno'), distinct=True),
            total_admins=Count('usuarios', filter=Q(usuarios__tipo__in=['admin', 'admin_arena', 'funcionario']), distinct=True),
            total_quadras=Count('quadras', distinct=True),
        ).order_by('nome')

    def get_serializer_class(self):
        if self.action == 'create':
            return SaasArenaCreateSerializer
        return SaasArenaSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            arena = serializer.save()
            admin = criar_dados_iniciais_arena(arena, serializer.admin_data)
            from saas_billing.services import ensure_subscription
            ensure_subscription(arena, arena.plano_contratado)
            from arena.models import ArenaOnboarding
            ArenaOnboarding.objects.get_or_create(arena=arena)
            registrar_auditoria(
                request,
                arena,
                'saas.arena_created',
                arena,
                novos={'nome': arena.nome, 'slug': arena.slug, 'plano': arena.plano_contratado},
            )
        payload = {
            'arena': SaasArenaSerializer(arena, context={'request': request}).data,
            'admin_inicial': {
                'id': admin.id,
                'nome': admin.get_full_name() or admin.username,
                'email': admin.email,
                'papel': admin.papel_efetivo,
            },
        }
        return Response(payload, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def acessar(self, request, pk=None):
        from gestao.audit import sanitize_audit_text

        arena = self.get_object()
        if not arena.ativa or arena.status_assinatura in {'suspensa', 'cancelada'}:
            return Response({'detail': 'Arena inativa nao pode ser usada como contexto operacional.'}, status=status.HTTP_409_CONFLICT)

        motivo = sanitize_audit_text(request.data.get('motivo'))
        origem_id = request.headers.get('X-Arena-ID')
        origem = Arena.objects.filter(id=origem_id).first() if origem_id else None
        acao = 'superadmin.context_switched' if origem and origem.id != arena.id else 'superadmin.context_entered'
        registrar_auditoria(
            request,
            arena,
            acao,
            arena,
            metadados={
                'arena_anterior_id': origem.id if origem else None,
                'arena_anterior_nome': origem.nome if origem else '',
                'arena_nova_id': arena.id,
                'arena_nova_nome': arena.nome,
                'motivo': motivo,
                'user_agent': sanitize_audit_text(request.headers.get('User-Agent'), 500),
            },
        )
        return Response({'arena': ArenaSerializer(arena, context={'request': request}).data, 'motivo': motivo})

    @action(detail=True, methods=['get'])
    def resumo(self, request, pk=None):
        from gestao.models import ContaFinanceira, ReservaQuadra
        from loja.models import Produto, Venda
        from usuarios.models import Usuario

        arena = self.get_object()
        hoje = timezone.localdate()
        inicio_mes = hoje.replace(day=1)
        inicio_proximo_mes = (inicio_mes.replace(day=28) + timezone.timedelta(days=4)).replace(day=1)
        fim_mes = inicio_proximo_mes - timezone.timedelta(days=1)

        mensalidades_mes = Mensalidade.objects.filter(arena=arena, mes_referencia=inicio_mes)
        receita_prevista = mensalidades_mes.aggregate(total=Sum('valor'))['total'] or Decimal('0')
        mensalidades_recebidas = mensalidades_mes.filter(status='pago').aggregate(total=Sum('valor'))['total'] or Decimal('0')
        vendas_recebidas = Venda.objects.filter(
            arena=arena, status='paga', data__date__range=(inicio_mes, fim_mes),
        ).aggregate(total=Sum('total'))['total'] or Decimal('0')

        vencidas = Mensalidade.objects.filter(arena=arena).filter(
            Q(status='atrasado') | Q(status='pendente', vencimento__lte=hoje - timezone.timedelta(days=5))
        )
        valor_vencido = vencidas.aggregate(total=Sum('valor'))['total'] or Decimal('0')
        alunos_ativos = Matricula.objects.filter(arena=arena, ativa=True).values('aluno_id').distinct().count()
        alunos_inadimplentes = vencidas.values('matricula__aluno_id').distinct().count()
        taxa = (Decimal(alunos_inadimplentes) / Decimal(alunos_ativos) * 100) if alunos_ativos else Decimal('0')
        produtos = Produto.objects.filter(arena=arena, ativo=True)
        reservas = ReservaQuadra.objects.filter(arena=arena).exclude(status='cancelada')
        admins = Usuario.objects.filter(
            arena=arena, tipo__in=['admin', 'admin_arena', 'funcionario'],
        ).order_by('first_name', 'username')

        is_cross_tenant = not request.user.arena_id or request.user.arena_id != arena.id
        if is_cross_tenant:
            registrar_auditoria(
                request,
                arena,
                'superadmin.cross_tenant_access',
                arena,
                metadados={'action': 'resumo', 'status_code': 200, 'cross_tenant': True},
            )

        money = lambda value: format(value or Decimal('0'), '.2f')
        return Response({
            'arena': SaasArenaSerializer(arena, context={'request': request}).data,
            'periodos': {
                'financeiro': {'inicio': inicio_mes, 'fim': fim_mes},
                'reservas': {'inicio': hoje, 'fim': hoje + timezone.timedelta(days=30)},
            },
            'financeiro': {
                'receita_prevista': money(receita_prevista),
                'receita_recebida': money(mensalidades_recebidas + vendas_recebidas),
                'valores_vencidos': money(valor_vencido),
                'contas_pagar_abertas': money(ContaFinanceira.objects.filter(
                    arena=arena, tipo='pagar', status__in=['aberta', 'vencida'],
                ).aggregate(total=Sum('valor'))['total']),
            },
            'alunos': {'ativos': alunos_ativos, 'limite': arena.limite_alunos},
            'inadimplencia': {
                'quantidade': vencidas.count(),
                'alunos': alunos_inadimplentes,
                'valor': money(valor_vencido),
                'taxa_percentual': format(taxa.quantize(Decimal('0.01')), '.2f'),
            },
            'reservas': {
                'hoje': reservas.filter(data=hoje).count(),
                'proximos_30_dias': reservas.filter(data__range=(hoje, hoje + timezone.timedelta(days=30))).count(),
            },
            'estoque': {
                'produtos_ativos': produtos.count(),
                'estoque_baixo': produtos.filter(estoque__lte=F('estoque_minimo')).count(),
                'estoque_zerado': produtos.filter(estoque=0).count(),
            },
            'assinatura': {
                'status': arena.status_assinatura,
                'plano': arena.plano_contratado,
                'ativa': arena.ativa,
                'limites': {'alunos': arena.limite_alunos, 'quadras': arena.limite_quadras, 'admins': arena.limite_admins},
            },
            'admins': [{
                'id': admin.id,
                'nome': admin.get_full_name() or admin.username,
                'email': admin.email,
                'papel': admin.papel_efetivo,
                'ativo': admin.is_active,
            } for admin in admins],
        })

    @action(detail=True, methods=['post'])
    def suspender(self, request, pk=None):
        arena = self.get_object()
        anterior = {'ativa': arena.ativa, 'status_assinatura': arena.status_assinatura}
        arena.ativa = False
        arena.status_assinatura = 'suspensa'
        arena.save(update_fields=['ativa', 'status_assinatura'])
        from saas_billing.services import ensure_subscription, sync_legacy_arena
        subscription = ensure_subscription(arena)
        subscription.status = 'suspended'
        subscription.save(update_fields=['status', 'updated_at'])
        sync_legacy_arena(subscription)
        registrar_auditoria(request, arena, 'saas.arena_suspended', arena, anteriores=anterior, novos={'ativa': False, 'status_assinatura': 'suspensa'})
        return Response({'detail': 'Arena suspensa.'})

    @action(detail=True, methods=['post'])
    def reativar(self, request, pk=None):
        arena = self.get_object()
        anterior = {'ativa': arena.ativa, 'status_assinatura': arena.status_assinatura}
        arena.ativa = True
        arena.status_assinatura = 'ativa'
        arena.save(update_fields=['ativa', 'status_assinatura'])
        from saas_billing.services import ensure_subscription, sync_legacy_arena
        subscription = ensure_subscription(arena)
        subscription.status = 'active'
        subscription.grace_ends_at = None
        subscription.save(update_fields=['status', 'grace_ends_at', 'updated_at'])
        sync_legacy_arena(subscription)
        registrar_auditoria(request, arena, 'saas.arena_reactivated', arena, anteriores=anterior, novos={'ativa': True, 'status_assinatura': 'ativa'})
        return Response({'detail': 'Arena reativada.'})


class PlanoViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PlanoSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        if self.request.user.is_authenticated:
            return Plano.objects.filter(arena=get_user_arena(self.request.user), ativo=True)
        arena_slug = self.request.query_params.get('arena_slug', '').strip()
        if not arena_slug:
            return Plano.objects.none()
        return Plano.objects.filter(arena__slug=arena_slug, arena__ativa=True, ativo=True)


class AdminPlanoViewSet(viewsets.ModelViewSet):
    serializer_class = PlanoSerializer
    permission_classes = [require_permission('alunos.manage')]

    def get_queryset(self):
        return Plano.objects.filter(arena=get_user_arena(self.request.user)).prefetch_related('janelas_acesso')

    def perform_create(self, serializer):
        arena = get_user_arena(self.request.user)
        plan = serializer.save(arena=arena)
        registrar_auditoria(
            self.request, arena, 'member_plan.created', plan,
            novos={'nome': plan.nome, 'tipo_acesso': plan.tipo_acesso},
        )

    def perform_update(self, serializer):
        before = {
            'nome': serializer.instance.nome,
            'tipo_acesso': serializer.instance.tipo_acesso,
            'ativo': serializer.instance.ativo,
        }
        plan = serializer.save()
        registrar_auditoria(
            self.request, plan.arena, 'member_plan.updated', plan,
            anteriores=before,
            novos={'nome': plan.nome, 'tipo_acesso': plan.tipo_acesso, 'ativo': plan.ativo},
        )

    def perform_destroy(self, instance):
        if instance.matricula_set.exists():
            raise serializers.ValidationError({'detail': 'Desative o plano; ele possui matriculas vinculadas.'})
        arena = instance.arena
        plan_id = instance.id
        name = instance.nome
        instance.delete()
        registrar_auditoria(
            self.request, arena, 'member_plan.deleted', None,
            anteriores={'id': plan_id, 'nome': name},
        )


class MatriculaViewSet(viewsets.ModelViewSet):
    serializer_class = MatriculaSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        arena = get_user_arena(user)
        if require_permission('alunos.manage')().has_permission(self.request, self):
            return Matricula.objects.filter(arena=arena)
        return Matricula.objects.filter(arena=arena, aluno=user)

    def perform_create(self, serializer):
        from saas_billing.services import assert_plan_capacity

        arena = get_user_arena(self.request.user)
        plano = serializer.validated_data['plano']
        aluno = serializer.validated_data['aluno']
        if plano.arena_id != arena.id or aluno.arena_id != arena.id:
            raise serializers.ValidationError({'detail': 'Plano ou aluno nao pertence a arena atual.'})
        assert_plan_capacity(arena, 'students')
        serializer.save(arena=arena)


class MensalidadeViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = MensalidadeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = Mensalidade.objects.filter(
            arena=get_user_arena(self.request.user),
            matricula__aluno=self.request.user,
        ).select_related('matricula', 'matricula__aluno', 'matricula__plano')
        atualizar_mensalidades_atrasadas(qs)
        return qs

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def pagar(self, request, pk=None):
        mensalidade = self.get_object()
        mensalidade = Mensalidade.objects.select_for_update().get(pk=mensalidade.pk)
        if mensalidade.status == 'pago':
            return Response({'detail': 'Esta mensalidade ja esta paga.'})
        if mensalidade.status == 'cancelada':
            return Response({'detail': 'Esta mensalidade foi cancelada.'}, status=409)

        if (mensalidade.mercado_pago_checkout_url and mensalidade.checkout_expires_at
                and mensalidade.checkout_expires_at > timezone.now()
                and mensalidade.status not in {'estornada', 'contestada'}):
            return Response({
                'detail': 'Link de pagamento recuperado.',
                'checkout_url': mensalidade.mercado_pago_checkout_url,
            })

        try:
            checkout_url = criar_preferencia_mensalidade(mensalidade)
        except MercadoPagoConfigError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except MercadoPagoAPIError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response({
            'detail': 'Link de pagamento criado.',
            'checkout_url': checkout_url,
        })


class AdminMensalidadeViewSet(viewsets.ModelViewSet):
    serializer_class = MensalidadeSerializer
    permission_classes = [require_permission('mensalidades.manage')]

    def get_queryset(self):
        arena = get_user_arena(self.request.user)
        atualizar_mensalidades_atrasadas(Mensalidade.objects.filter(arena=arena))
        qs = Mensalidade.objects.select_related(
            'matricula',
            'matricula__aluno',
            'matricula__plano',
        ).filter(arena=arena)

        status_filtro = self.request.query_params.get('status', 'todas')
        if status_filtro in dict(Mensalidade.STATUS):
            qs = qs.filter(status=status_filtro)

        hoje = timezone.localdate()
        periodo = self.request.query_params.get('periodo', 'todos')
        mes_param = self.request.query_params.get('mes')

        if mes_param:
            try:
                ano, mes = [int(parte) for parte in mes_param.split('-', 1)]
                qs = qs.filter(mes_referencia__year=ano, mes_referencia__month=mes)
            except (TypeError, ValueError):
                qs = qs.none()
        elif periodo == 'mes_atual':
            qs = qs.filter(mes_referencia__year=hoje.year, mes_referencia__month=hoje.month)
        elif periodo == 'mes_passado':
            primeiro_mes_atual = hoje.replace(day=1)
            mes_passado = (primeiro_mes_atual - timezone.timedelta(days=1)).replace(day=1)
            qs = qs.filter(mes_referencia__year=mes_passado.year, mes_referencia__month=mes_passado.month)
        elif periodo == 'proximo_mes':
            if hoje.month == 12:
                proximo_mes = date(hoje.year + 1, 1, 1)
            else:
                proximo_mes = date(hoje.year, hoje.month + 1, 1)
            qs = qs.filter(mes_referencia__year=proximo_mes.year, mes_referencia__month=proximo_mes.month)
        elif periodo == 'ano_atual':
            qs = qs.filter(mes_referencia__year=hoje.year)
        elif periodo == 'vencidas':
            qs = qs.filter(vencimento__lt=hoje, status__in=['pendente', 'atrasado'])

        search = self.request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(matricula__aluno__username__icontains=search)
                | Q(matricula__aluno__email__icontains=search)
                | Q(matricula__aluno__first_name__icontains=search)
                | Q(matricula__aluno__last_name__icontains=search)
                | Q(matricula__plano__nome__icontains=search)
            )

        return qs.order_by('vencimento', 'matricula__aluno__first_name')

    @action(detail=True, methods=['post'])
    def pagar(self, request, pk=None):
        mensalidade = self.get_object()
        anterior = {'status': mensalidade.status, 'data_pagamento': str(mensalidade.data_pagamento)}
        mensalidade.status = 'pago'
        mensalidade.data_pagamento = timezone.localdate()
        mensalidade.save(update_fields=['status', 'data_pagamento'])
        registrar_auditoria(request, get_user_arena(request.user), 'mensalidade.paga_manual', mensalidade, anteriores=anterior, novos={'status': mensalidade.status, 'data_pagamento': str(mensalidade.data_pagamento)})
        return Response({'detail': 'Mensalidade marcada como paga.'})

    @action(detail=True, methods=['post'])
    def pendente(self, request, pk=None):
        mensalidade = self.get_object()
        anterior = {'status': mensalidade.status, 'data_pagamento': str(mensalidade.data_pagamento)}
        mensalidade.status = 'pendente'
        mensalidade.data_pagamento = None
        mensalidade.save(update_fields=['status', 'data_pagamento'])
        registrar_auditoria(request, get_user_arena(request.user), 'mensalidade.pendente_manual', mensalidade, anteriores=anterior, novos={'status': mensalidade.status})
        return Response({'detail': 'Mensalidade marcada como pendente.'})

    @action(detail=True, methods=['post'])
    def atrasar(self, request, pk=None):
        mensalidade = self.get_object()
        anterior = {'status': mensalidade.status, 'data_pagamento': str(mensalidade.data_pagamento)}
        mensalidade.status = 'atrasado'
        mensalidade.data_pagamento = None
        mensalidade.save(update_fields=['status', 'data_pagamento'])
        registrar_auditoria(request, get_user_arena(request.user), 'mensalidade.atrasada_manual', mensalidade, anteriores=anterior, novos={'status': mensalidade.status})
        return Response({'detail': 'Mensalidade marcada como atrasada.'})

    @action(detail=True, methods=['post'])
    def cancelar(self, request, pk=None):
        mensalidade = self.get_object()
        anterior = {'status': mensalidade.status, 'data_pagamento': str(mensalidade.data_pagamento)}
        mensalidade.status = 'cancelada'
        mensalidade.data_pagamento = None
        mensalidade.save(update_fields=['status', 'data_pagamento'])
        registrar_auditoria(request, get_user_arena(request.user), 'mensalidade.cancelada_manual', mensalidade, anteriores=anterior, novos={'status': mensalidade.status})
        return Response({'detail': 'Mensalidade cancelada.'})
