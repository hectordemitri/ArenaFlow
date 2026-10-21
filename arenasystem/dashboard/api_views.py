from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.db.models import Sum, Count
from django.db.models.functions import TruncMonth
from django.utils import timezone
from datetime import timedelta

from arena.models import Mensalidade, Matricula
from aulas.models import CheckIn, Turma
from loja.models import Venda
from manutencao.models import Manutencao
from arena.tenant import get_user_arena
from usuarios.permissions import require_permission


@api_view(['GET'])
@permission_classes([require_permission('dashboard.view')])
def metricas_gerais(request):
    hoje = timezone.localdate()
    arena = get_user_arena(request.user)
    inicio_mes = hoje.replace(day=1)
    ultimos_30 = hoje - timedelta(days=30)

    receita_mensalidades = Mensalidade.objects.filter(
        arena=arena,
        status='pago', data_pagamento__gte=inicio_mes
    ).aggregate(t=Sum('valor'))['t'] or 0

    receita_loja = Venda.objects.filter(
        arena=arena,
        status='paga', data__date__gte=inicio_mes
    ).aggregate(t=Sum('total'))['t'] or 0

    inadimplencia = Mensalidade.objects.filter(
        arena=arena,
        status__in=['pendente', 'atrasado'],
        vencimento__lt=hoje
    ).aggregate(t=Sum('valor'))['t'] or 0

    return Response({
        'receita_mensalidades': float(receita_mensalidades),
        'receita_loja': float(receita_loja),
        'receita_total': float(receita_mensalidades + receita_loja),
        'inadimplencia': float(inadimplencia),
        'alunos_ativos': Matricula.objects.filter(arena=arena, ativa=True).count(),
        'novos_alunos_mes': Matricula.objects.filter(arena=arena, data_inicio__gte=inicio_mes).count(),
        'checkins_30d': CheckIn.objects.filter(arena=arena, data__gte=ultimos_30, presente=True).count(),
        'turmas_ativas': Turma.objects.filter(arena=arena, ativa=True).count(),
        'manutencoes_pendentes': Manutencao.objects.filter(
            arena=arena,
            status__in=['agendada', 'em_andamento']
        ).count(),
    })


@api_view(['GET'])
@permission_classes([require_permission('dashboard.view')])
def receita_mensal(request):
    inicio = timezone.localdate() - timedelta(days=365)
    arena = get_user_arena(request.user)

    mensalidades = (
        Mensalidade.objects
        .filter(arena=arena, status='pago', data_pagamento__gte=inicio)
        .annotate(mes=TruncMonth('data_pagamento'))
        .values('mes')
        .annotate(total=Sum('valor'))
        .order_by('mes')
    )
    vendas = (
        Venda.objects
        .filter(arena=arena, status='paga', data__date__gte=inicio)
        .annotate(mes=TruncMonth('data'))
        .values('mes')
        .annotate(total=Sum('total'))
        .order_by('mes')
    )

    return Response({
        'mensalidades': [
            {'mes': m['mes'].strftime('%b/%Y'), 'total': float(m['total'] or 0)}
            for m in mensalidades
        ],
        'loja': [
            {'mes': v['mes'].strftime('%b/%Y'), 'total': float(v['total'] or 0)}
            for v in vendas
        ],
    })


@api_view(['GET'])
@permission_classes([require_permission('dashboard.view')])
def ranking_frequencia(request):
    ultimos_30 = timezone.now().date() - timedelta(days=30)
    arena = get_user_arena(request.user)
    dados = (
        CheckIn.objects
        .filter(arena=arena, data__gte=ultimos_30, presente=True)
        .values('aluno__first_name', 'aluno__last_name', 'aluno__username')
        .annotate(total=Count('id'))
        .order_by('-total')[:10]
    )

    resultado = [
        {
            'nome': f"{d['aluno__first_name']} {d['aluno__last_name']}".strip()
                    or d['aluno__username'],
            'total': d['total'],
        }
        for d in dados
    ]
    return Response(resultado)


@api_view(['GET'])
@permission_classes([require_permission('dashboard.view')])
def status_mensalidades(request):
    inicio_mes = timezone.now().date().replace(day=1)
    arena = get_user_arena(request.user)
    dados = (
        Mensalidade.objects
        .filter(arena=arena, mes_referencia=inicio_mes)
        .values('status')
        .annotate(total=Count('id'))
    )
    return Response(list(dados))


@api_view(['GET'])
@permission_classes([require_permission('dashboard.view')])
def ocupacao_quadras(request):
    ultimos_30 = timezone.now().date() - timedelta(days=30)
    arena = get_user_arena(request.user)
    dados = (
        CheckIn.objects
        .filter(arena=arena, data__gte=ultimos_30, presente=True)
        .values('turma__quadra__nome')
        .annotate(total=Count('id'))
        .order_by('-total')
    )

    resultado = [
        {'quadra': d['turma__quadra__nome'] or 'Sem quadra', 'total': d['total']}
        for d in dados
    ]
    return Response(resultado)
