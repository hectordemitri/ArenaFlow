from datetime import datetime, time, timedelta

from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from arena.models import Matricula, Mensalidade, Quadra
from arena.tenant import get_user_arena
from arena.features import FeatureEnabledMixin
from aulas.models import CheckIn, SolicitacaoMatricula, Turma
from loja.models import Produto, Venda
from usuarios.permissions import require_permission, tem_permissao
from .audit import registrar_auditoria
from .models import AuditLog, BloqueioQuadra, ContaFinanceira, ContratoMatricula, FaixaPrecoReserva, Lead, ReservaQuadra
from .serializers import (
    AuditLogSerializer,
    BloqueioQuadraSerializer,
    ContaFinanceiraSerializer,
    ContratoMatriculaSerializer,
    FaixaPrecoReservaSerializer,
    LeadSerializer,
    ReservaQuadraSerializer,
)


def intervalos_sobrepostos(inicio_a, fim_a, inicio_b, fim_b):
    return inicio_a < fim_b and fim_a > inicio_b


def validar_intervalo(data):
    inicio = data.get('hora_inicio')
    fim = data.get('hora_fim')
    if not inicio or not fim or inicio >= fim:
        raise ValidationError({'detail': 'Horario inicial deve ser anterior ao horario final.'})


def calcular_valor_reserva(arena, quadra, data, hora_inicio, hora_fim):
    dia = data.weekday()
    faixa = (
        FaixaPrecoReserva.objects
        .filter(arena=arena, ativa=True, dia_semana=dia, hora_inicio__lte=hora_inicio, hora_fim__gte=hora_fim)
        .filter(Q(quadra=quadra) | Q(quadra__isnull=True))
        .order_by(F('quadra').desc(nulls_last=True), 'hora_inicio')
        .first()
    )
    return faixa.valor if faixa else 0


def validar_quadra_da_arena(arena, quadra):
    if quadra.arena_id != arena.id:
        raise ValidationError({'detail': 'Quadra nao pertence a arena atual.'})


def validar_conflito_reserva(arena, quadra, data, hora_inicio, hora_fim, reserva_id=None):
    Quadra.objects.select_for_update().get(pk=quadra.pk, arena=arena)
    reservas = ReservaQuadra.objects.select_for_update().filter(
        arena=arena,
        quadra=quadra,
        data=data,
    ).exclude(status='cancelada')
    if reserva_id:
        reservas = reservas.exclude(id=reserva_id)
    for reserva in reservas:
        if intervalos_sobrepostos(hora_inicio, hora_fim, reserva.hora_inicio, reserva.hora_fim):
            raise ValidationError({'detail': 'Ja existe reserva nesse intervalo.'})

    bloqueios = BloqueioQuadra.objects.select_for_update().filter(arena=arena, quadra=quadra, data=data)
    for bloqueio in bloqueios:
        if intervalos_sobrepostos(hora_inicio, hora_fim, bloqueio.hora_inicio, bloqueio.hora_fim):
            raise ValidationError({'detail': 'Horario bloqueado para esta quadra.'})


def parametro_verdadeiro(valor):
    return str(valor).lower() in {'1', 'true', 'sim', 'yes'}


class ReservaQuadraViewSet(FeatureEnabledMixin, viewsets.ModelViewSet):
    feature_key = 'reservations'
    serializer_class = ReservaQuadraSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        arena = get_user_arena(self.request.user)
        qs = ReservaQuadra.objects.filter(arena=arena).select_related('quadra', 'aluno')
        minhas = parametro_verdadeiro(self.request.query_params.get('minhas'))
        if minhas or not self._can_manage():
            qs = qs.filter(aluno=self.request.user)
        data = self.request.query_params.get('data')
        status_filtro = self.request.query_params.get('status')
        if data:
            qs = qs.filter(data=data)
        if status_filtro:
            qs = qs.filter(status=status_filtro)
        return qs

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        if self.action in ['confirmar', 'destroy', 'update', 'partial_update']:
            return [require_permission('reservas.manage')()]
        return [permissions.IsAuthenticated()]

    def _can_manage(self):
        return tem_permissao(self.request.user, 'reservas.manage')

    def perform_create(self, serializer):
        user = self.request.user
        arena = get_user_arena(user)
        quadra = serializer.validated_data['quadra']
        validar_intervalo(serializer.validated_data)
        validar_quadra_da_arena(arena, quadra)
        minhas = parametro_verdadeiro(self.request.query_params.get('minhas'))
        aluno = user if minhas or not self._can_manage() else None
        cliente_nome = serializer.validated_data.get('cliente_nome') or user.get_full_name() or user.username
        cliente_telefone = serializer.validated_data.get('cliente_telefone') or getattr(user, 'telefone', '')
        with transaction.atomic():
            validar_conflito_reserva(
                arena, quadra, serializer.validated_data['data'],
                serializer.validated_data['hora_inicio'], serializer.validated_data['hora_fim'],
            )
            valor = calcular_valor_reserva(
                arena, quadra, serializer.validated_data['data'],
                serializer.validated_data['hora_inicio'], serializer.validated_data['hora_fim'],
            )
            reserva = serializer.save(
                arena=arena,
                aluno=aluno,
                cliente_nome=cliente_nome,
                cliente_telefone=cliente_telefone,
                valor=valor or serializer.validated_data.get('valor', 0),
                criado_por=user,
                status=serializer.validated_data.get('status', 'pendente') if self._can_manage() else 'pendente',
            )
            registrar_auditoria(self.request, arena, 'reserva.criada', reserva, novos=ReservaQuadraSerializer(reserva).data)

    def perform_update(self, serializer):
        arena = get_user_arena(self.request.user)
        reserva = self.get_object()
        anteriores = ReservaQuadraSerializer(reserva).data
        quadra = serializer.validated_data.get('quadra', reserva.quadra)
        data = serializer.validated_data.get('data', reserva.data)
        inicio = serializer.validated_data.get('hora_inicio', reserva.hora_inicio)
        fim = serializer.validated_data.get('hora_fim', reserva.hora_fim)
        if inicio >= fim:
            raise ValidationError({'detail': 'Horario inicial deve ser anterior ao horario final.'})
        validar_quadra_da_arena(arena, quadra)
        with transaction.atomic():
            validar_conflito_reserva(arena, quadra, data, inicio, fim, reserva_id=reserva.id)
            valor = calcular_valor_reserva(arena, quadra, data, inicio, fim)
            reserva = serializer.save(arena=arena, valor=valor or serializer.validated_data.get('valor', reserva.valor))
            registrar_auditoria(self.request, arena, 'reserva.alterada', reserva, anteriores=anteriores, novos=ReservaQuadraSerializer(reserva).data)

    def destroy(self, request, *args, **kwargs):
        reserva = self.get_object()
        anteriores = ReservaQuadraSerializer(reserva).data
        response = super().destroy(request, *args, **kwargs)
        registrar_auditoria(request, get_user_arena(request.user), 'reserva.excluida', reserva, anteriores=anteriores)
        return response

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def confirmar(self, request, pk=None):
        reserva = self.get_object()
        validar_conflito_reserva(get_user_arena(request.user), reserva.quadra, reserva.data,
                                reserva.hora_inicio, reserva.hora_fim, reserva_id=reserva.pk)
        reserva = ReservaQuadra.objects.select_for_update().get(pk=reserva.pk)
        anterior = {'status': reserva.status}
        reserva.status = 'confirmada'
        reserva.save(update_fields=['status'])
        registrar_auditoria(request, get_user_arena(request.user), 'reserva.confirmada', reserva, anteriores=anterior, novos={'status': reserva.status})
        return Response({'detail': 'Reserva confirmada.'})

    @action(detail=True, methods=['post'])
    def cancelar(self, request, pk=None):
        reserva = self.get_object()
        if not self._can_manage() and reserva.aluno_id != request.user.id:
            return Response({'detail': 'Reserva indisponivel para este usuario.'}, status=status.HTTP_403_FORBIDDEN)
        anterior = {'status': reserva.status}
        reserva.status = 'cancelada'
        reserva.save(update_fields=['status'])
        registrar_auditoria(request, get_user_arena(request.user), 'reserva.cancelada', reserva, anteriores=anterior, novos={'status': reserva.status})
        return Response({'detail': 'Reserva cancelada.'})

    @action(detail=False, methods=['get'])
    def grade(self, request):
        arena = get_user_arena(request.user)
        data_txt = request.query_params.get('data') or timezone.localdate().isoformat()
        data = datetime.strptime(data_txt, '%Y-%m-%d').date()
        quadras = Quadra.objects.filter(arena=arena, ativa=True)
        quadra_id = request.query_params.get('quadra')
        if quadra_id:
            quadras = quadras.filter(id=quadra_id)
        reservas = self.get_queryset().filter(data=data)
        bloqueios = BloqueioQuadra.objects.filter(arena=arena, data=data, quadra__in=quadras)
        return Response({
            'data': data.isoformat(),
            'horarios': [f'{hora:02d}:00' for hora in range(6, 23)],
            'quadras': [{'id': q.id, 'nome': q.nome} for q in quadras],
            'reservas': ReservaQuadraSerializer(reservas, many=True).data,
            'bloqueios': BloqueioQuadraSerializer(bloqueios, many=True).data,
        })

    @action(detail=False, methods=['post'], url_path='recorrente')
    def recorrente(self, request):
        if not self._can_manage():
            return Response({'detail': 'Sem permissao para criar recorrencia.'}, status=status.HTTP_403_FORBIDDEN)
        arena = get_user_arena(request.user)
        quadra = Quadra.objects.filter(arena=arena, id=request.data.get('quadra')).first()
        if not quadra:
            return Response({'detail': 'Quadra invalida.'}, status=status.HTTP_400_BAD_REQUEST)
        ocorrencias = int(request.data.get('ocorrencias') or 0)
        if ocorrencias <= 0 or ocorrencias > 52:
            return Response({'detail': 'Informe entre 1 e 52 ocorrencias.'}, status=status.HTTP_400_BAD_REQUEST)
        data_inicial = datetime.strptime(request.data['data_inicial'], '%Y-%m-%d').date()
        inicio = datetime.strptime(request.data['hora_inicio'], '%H:%M').time()
        fim = datetime.strptime(request.data['hora_fim'], '%H:%M').time()
        if inicio >= fim:
            return Response({'detail': 'Horario inicial deve ser anterior ao horario final.'}, status=status.HTTP_400_BAD_REQUEST)
        conflitos = []
        datas = [data_inicial + timedelta(days=7 * i) for i in range(ocorrencias)]
        with transaction.atomic():
            for data in datas:
                try:
                    validar_conflito_reserva(arena, quadra, data, inicio, fim)
                except ValidationError as exc:
                    conflitos.append({'data': data.isoformat(), 'motivo': str(exc)})
            if conflitos:
                transaction.set_rollback(True)
                return Response({'detail': 'Recorrencia possui conflitos.', 'conflitos': conflitos}, status=status.HTTP_400_BAD_REQUEST)
            criadas = []
            for data in datas:
                reserva = ReservaQuadra.objects.create(
                    arena=arena,
                    quadra=quadra,
                    cliente_nome=request.data.get('cliente_nome', 'Reserva recorrente'),
                    cliente_telefone=request.data.get('cliente_telefone', ''),
                    data=data,
                    hora_inicio=inicio,
                    hora_fim=fim,
                    valor=calcular_valor_reserva(arena, quadra, data, inicio, fim),
                    status=request.data.get('status', 'confirmada'),
                    observacoes=request.data.get('observacoes', 'Reserva recorrente semanal'),
                    criado_por=request.user,
                )
                criadas.append(reserva)
            registrar_auditoria(request, arena, 'reserva.recorrente_criada', criadas[0], novos={'total': len(criadas)})
        return Response(ReservaQuadraSerializer(criadas, many=True).data, status=status.HTTP_201_CREATED)


class BloqueioQuadraViewSet(FeatureEnabledMixin, viewsets.ModelViewSet):
    feature_key = 'reservations'
    serializer_class = BloqueioQuadraSerializer
    permission_classes = [require_permission('reservas.manage')]

    def get_queryset(self):
        return BloqueioQuadra.objects.filter(arena=get_user_arena(self.request.user)).select_related('quadra')

    def perform_create(self, serializer):
        arena = get_user_arena(self.request.user)
        quadra = serializer.validated_data['quadra']
        validar_intervalo(serializer.validated_data)
        validar_quadra_da_arena(arena, quadra)
        with transaction.atomic():
            validar_conflito_reserva(
                arena, quadra, serializer.validated_data['data'],
                serializer.validated_data['hora_inicio'], serializer.validated_data['hora_fim'],
            )
            bloqueio = serializer.save(arena=arena, criado_por=self.request.user)
            registrar_auditoria(self.request, arena, 'bloqueio.criado', bloqueio, novos=BloqueioQuadraSerializer(bloqueio).data)

    def perform_destroy(self, instance):
        anteriores = BloqueioQuadraSerializer(instance).data
        arena = get_user_arena(self.request.user)
        instance_id = instance.id
        instance.delete()
        registrar_auditoria(self.request, arena, 'bloqueio.removido', instance, anteriores={**anteriores, 'id': instance_id})


class FaixaPrecoReservaViewSet(FeatureEnabledMixin, viewsets.ModelViewSet):
    feature_key = 'reservations'
    serializer_class = FaixaPrecoReservaSerializer
    permission_classes = [require_permission('reservas.manage')]

    def get_queryset(self):
        return FaixaPrecoReserva.objects.filter(arena=get_user_arena(self.request.user)).select_related('quadra')

    def perform_create(self, serializer):
        arena = get_user_arena(self.request.user)
        quadra = serializer.validated_data.get('quadra')
        if quadra:
            validar_quadra_da_arena(arena, quadra)
        inicio = serializer.validated_data['hora_inicio']
        fim = serializer.validated_data['hora_fim']
        if inicio >= fim:
            raise ValidationError({'detail': 'Horario inicial deve ser anterior ao horario final.'})
        conflito = self.get_queryset().filter(
            ativa=True,
            dia_semana=serializer.validated_data['dia_semana'],
            quadra=quadra,
            hora_inicio__lt=fim,
            hora_fim__gt=inicio,
        ).exists()
        if conflito:
            raise ValidationError({'detail': 'Ja existe faixa de preco sobreposta.'})
        faixa = serializer.save(arena=arena)
        registrar_auditoria(self.request, arena, 'faixa_preco.criada', faixa, novos=FaixaPrecoReservaSerializer(faixa).data)


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AuditLogSerializer
    permission_classes = [require_permission('auditoria.view')]

    def get_queryset(self):
        qs = AuditLog.objects.filter(arena=get_user_arena(self.request.user)).select_related('usuario', 'arena')
        acao = self.request.query_params.get('acao')
        entidade = self.request.query_params.get('entidade')
        usuario = self.request.query_params.get('usuario')
        search = self.request.query_params.get('search', '').strip()
        inicio = self.request.query_params.get('inicio')
        fim = self.request.query_params.get('fim')
        if acao:
            qs = qs.filter(acao__icontains=acao)
        if entidade:
            qs = qs.filter(entidade_tipo__icontains=entidade)
        if usuario:
            qs = qs.filter(usuario_id=usuario)
        if inicio:
            qs = qs.filter(criado_em__date__gte=inicio)
        if fim:
            qs = qs.filter(criado_em__date__lte=fim)
        if search:
            qs = qs.filter(
                Q(acao__icontains=search) |
                Q(entidade_tipo__icontains=search) |
                Q(entidade_id__icontains=search) |
                Q(usuario__username__icontains=search) |
                Q(usuario__first_name__icontains=search) |
                Q(usuario__last_name__icontains=search)
            )
        return qs


class LeadViewSet(viewsets.ModelViewSet):
    serializer_class = LeadSerializer
    permission_classes = [require_permission('crm.manage')]

    def get_queryset(self):
        qs = Lead.objects.filter(arena=get_user_arena(self.request.user)).select_related('responsavel')
        etapa = self.request.query_params.get('etapa')
        search = self.request.query_params.get('search', '').strip()
        if etapa:
            qs = qs.filter(etapa=etapa)
        if search:
            qs = qs.filter(
                Q(nome__icontains=search) |
                Q(telefone__icontains=search) |
                Q(email__icontains=search) |
                Q(modalidade_interesse__icontains=search)
            )
        return qs

    def perform_create(self, serializer):
        serializer.save(arena=get_user_arena(self.request.user), responsavel=self.request.user)

    @action(detail=True, methods=['post'])
    def mover(self, request, pk=None):
        lead = self.get_object()
        etapa = request.data.get('etapa')
        etapas_validas = [key for key, _ in Lead.ETAPAS]
        if etapa not in etapas_validas:
            return Response({'detail': 'Etapa invalida.'}, status=status.HTTP_400_BAD_REQUEST)
        lead.etapa = etapa
        if etapa != 'perdido':
            lead.motivo_perda = ''
        else:
            lead.motivo_perda = request.data.get('motivo_perda', lead.motivo_perda)
        lead.save(update_fields=['etapa', 'motivo_perda', 'atualizado_em'])
        return Response(LeadSerializer(lead).data)


class ContaFinanceiraViewSet(viewsets.ModelViewSet):
    serializer_class = ContaFinanceiraSerializer
    permission_classes = [require_permission('financeiro.manage')]

    def get_queryset(self):
        arena = get_user_arena(self.request.user)
        qs = ContaFinanceira.objects.filter(arena=arena)
        for conta in qs.filter(status='aberta', vencimento__lt=timezone.localdate()):
            conta.atualizar_vencida()
        tipo = self.request.query_params.get('tipo')
        status_filtro = self.request.query_params.get('status')
        if tipo:
            qs = qs.filter(tipo=tipo)
        if status_filtro:
            qs = qs.filter(status=status_filtro)
        return qs

    def perform_create(self, serializer):
        serializer.save(arena=get_user_arena(self.request.user), criado_por=self.request.user)

    @action(detail=True, methods=['post'])
    def pagar(self, request, pk=None):
        conta = self.get_object()
        conta.status = 'paga'
        conta.data_pagamento = request.data.get('data_pagamento') or timezone.localdate()
        conta.save(update_fields=['status', 'data_pagamento'])
        return Response({'detail': 'Conta marcada como paga.'})


class ContratoMatriculaViewSet(viewsets.ModelViewSet):
    serializer_class = ContratoMatriculaSerializer
    permission_classes = [require_permission('contratos.manage')]

    def get_queryset(self):
        return ContratoMatricula.objects.filter(
            arena=get_user_arena(self.request.user)
        ).select_related('matricula__aluno', 'matricula__plano')

    def perform_create(self, serializer):
        serializer.save(arena=get_user_arena(self.request.user))

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def aceitar(self, request, pk=None):
        contrato = self.get_object()
        if not tem_permissao(request.user, 'contratos.manage') and contrato.matricula.aluno_id != request.user.id:
            return Response({'detail': 'Contrato indisponivel para este usuario.'}, status=status.HTTP_403_FORBIDDEN)
        contrato.aceitar(request.META.get('REMOTE_ADDR'))
        return Response({'detail': 'Contrato aceito.'})


@api_view(['GET'])
@permission_classes([require_permission('dashboard.view')])
def resumo_executivo(request):
    arena = get_user_arena(request.user)
    hoje = timezone.localdate()
    inicio_mes = hoje.replace(day=1)
    proximos_30 = hoje + timedelta(days=30)

    mensalidades = Mensalidade.objects.filter(arena=arena, mes_referencia__gte=inicio_mes)
    receita_mensalidades = mensalidades.filter(status='pago').aggregate(total=Sum('valor'))['total'] or 0
    receita_loja = Venda.objects.filter(arena=arena, status='paga', data__date__gte=inicio_mes).aggregate(total=Sum('total'))['total'] or 0
    contas_pagar = ContaFinanceira.objects.filter(arena=arena, tipo='pagar', status__in=['aberta', 'vencida']).aggregate(total=Sum('valor'))['total'] or 0
    contas_receber = ContaFinanceira.objects.filter(arena=arena, tipo='receber', status__in=['aberta', 'vencida']).aggregate(total=Sum('valor'))['total'] or 0

    turmas = Turma.objects.filter(arena=arena, ativa=True).prefetch_related('alunos')
    vagas_total = sum(t.vagas for t in turmas)
    alunos_alocados = sum(t.alunos.count() for t in turmas)
    ocupacao = round((alunos_alocados / vagas_total) * 100, 1) if vagas_total else 0

    leads = Lead.objects.filter(arena=arena)
    leads_por_etapa = list(leads.values('etapa').annotate(total=Count('id')).order_by('etapa'))

    checkins_30 = CheckIn.objects.filter(arena=arena, data__gte=hoje - timedelta(days=30))
    faltas_30 = checkins_30.filter(presente=False).count()
    reservas_30 = ReservaQuadra.objects.filter(arena=arena, data__range=[hoje, proximos_30])

    alertas = []
    if mensalidades.filter(status='atrasado').exists():
        total_atrasado = mensalidades.filter(status='atrasado').aggregate(total=Sum('valor'))['total'] or 0
        alertas.append({'tipo': 'risco', 'titulo': 'Inadimplencia ativa', 'mensagem': f'R$ {total_atrasado:.2f} em mensalidades atrasadas neste periodo.'})
    if ocupacao < 60:
        alertas.append({'tipo': 'oportunidade', 'titulo': 'Ocupacao baixa', 'mensagem': f'Ocupacao media das turmas em {ocupacao}%. Vale acionar leads e fila de espera.'})
    produtos_baixos = Produto.objects.filter(arena=arena, estoque__lte=F('estoque_minimo')).count()
    if produtos_baixos:
        alertas.append({'tipo': 'estoque', 'titulo': 'Reposicao de estoque', 'mensagem': f'{produtos_baixos} produto(s) abaixo do minimo.'})

    return Response({
        'financeiro': {
            'receita_mensalidades': receita_mensalidades,
            'receita_loja': receita_loja,
            'contas_pagar': contas_pagar,
            'contas_receber': contas_receber,
            'resultado_previsto': receita_mensalidades + receita_loja + contas_receber - contas_pagar,
        },
        'operacao': {
            'alunos_ativos': Matricula.objects.filter(arena=arena, ativa=True).count(),
            'ocupacao_turmas': ocupacao,
            'faltas_30_dias': faltas_30,
            'reservas_30_dias': reservas_30.exclude(status='cancelada').count(),
            'solicitacoes_pendentes': SolicitacaoMatricula.objects.filter(arena=arena, status='pendente').count(),
        },
        'crm': {
            'leads_abertos': leads.exclude(etapa__in=['ganho', 'perdido']).count(),
            'leads_por_etapa': leads_por_etapa,
            'followups_hoje': leads.filter(proximo_contato__lte=hoje).exclude(etapa__in=['ganho', 'perdido']).count(),
        },
        'alertas': alertas,
    })
