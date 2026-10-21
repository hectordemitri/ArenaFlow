from django.db import transaction
from django.db.models import Q
from rest_framework import viewsets, permissions, status, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Categoria, Fornecedor, LoteEstoque, MovimentacaoEstoque, Produto, Venda
from .serializers import (
    CategoriaSerializer,
    FornecedorSerializer,
    LoteEstoqueSerializer,
    MovimentacaoEstoqueSerializer,
    ProdutoSerializer,
    VendaSerializer,
)
from arena.tenant import get_user_arena
from arena.features import FeatureEnabledMixin
from gestao.audit import registrar_auditoria
from usuarios.permissions import require_permission
from .stock import record_change, remove_stock


class CategoriaViewSet(FeatureEnabledMixin, viewsets.ReadOnlyModelViewSet):
    feature_key = 'store'
    serializer_class = CategoriaSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Categoria.objects.filter(arena=get_user_arena(self.request.user))


class ProdutoViewSet(FeatureEnabledMixin, viewsets.ReadOnlyModelViewSet):
    feature_key = 'store'
    serializer_class = ProdutoSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        arena = get_user_arena(self.request.user)
        return Produto.objects.filter(
            arena=arena,
            ativo=True,
            canal__in=['app', 'ambos'],
        ).select_related('categoria')


class AdminProdutoViewSet(FeatureEnabledMixin, viewsets.ModelViewSet):
    feature_key = 'store'
    serializer_class = ProdutoSerializer
    permission_classes = [require_permission('estoque.manage')]

    def get_queryset(self):
        qs = Produto.objects.filter(arena=get_user_arena(self.request.user)).select_related('categoria', 'fornecedor').prefetch_related('lotes')
        canal = self.request.query_params.get('canal')
        if canal in ['app', 'balcao', 'ambos']:
            qs = qs.filter(canal=canal)
        search = self.request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(nome__icontains=search) |
                Q(sku__icontains=search) |
                Q(codigo_barras__icontains=search) |
                Q(categoria__nome__icontains=search) |
                Q(fornecedor__nome__icontains=search)
            )
        return qs.order_by('categoria__nome', 'nome')

    def perform_create(self, serializer):
        serializer.save(arena=get_user_arena(self.request.user))

    def _locked_product(self):
        product = self.get_object()
        return Produto.objects.select_for_update().get(pk=product.pk)

    @transaction.atomic
    def perform_update(self, serializer):
        product = Produto.objects.select_for_update().get(pk=serializer.instance.pk)
        if 'estoque' in serializer.validated_data and serializer.validated_data['estoque'] != product.estoque:
            raise serializers.ValidationError({'estoque': 'Use a operacao de ajuste para alterar o saldo.'})
        serializer.instance = product
        serializer.save()

    def _registrar_movimentacao(self, produto, tipo, quantidade, observacao='', lote=None, custo_unitario=None):
        estoque_antes = produto.estoque
        mov = record_change(produto, quantidade, tipo, self.request.user, lot=lote, note=observacao, cost=custo_unitario)
        registrar_auditoria(
            self.request,
            get_user_arena(self.request.user),
            'estoque.movimentacao',
            mov,
            anteriores={'estoque': estoque_antes},
            novos={'estoque': produto.estoque, 'quantidade': quantidade, 'tipo': tipo},
        )

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def entrada(self, request, pk=None):
        produto = self._locked_product()
        quantidade = serializers.IntegerField(min_value=1).run_validation(request.data.get('quantidade'))
        custo_unitario = serializers.DecimalField(max_digits=8, decimal_places=2, min_value=0).run_validation(
            request.data.get('custo_unitario', produto.custo_unitario))
        validade = serializers.DateField(allow_null=True).run_validation(request.data.get('validade') or None)
        fornecedor_id = request.data.get('fornecedor') or produto.fornecedor_id
        arena = get_user_arena(self.request.user)
        if fornecedor_id and not Fornecedor.objects.filter(arena=arena, id=fornecedor_id).exists():
            return Response({'detail': 'Fornecedor nao pertence a arena atual.'}, status=status.HTTP_400_BAD_REQUEST)
        lote = LoteEstoque.objects.create(
            arena=arena,
            produto=produto,
            codigo_lote=request.data.get('codigo_lote', ''),
            quantidade_inicial=quantidade,
            quantidade_atual=quantidade,
            custo_unitario=custo_unitario,
            validade=validade,
            fornecedor_id=fornecedor_id or None,
        )
        self._registrar_movimentacao(
            produto,
            'entrada',
            quantidade,
            request.data.get('observacao', 'Entrada de estoque'),
            lote=lote,
            custo_unitario=custo_unitario,
        )
        return Response({'detail': 'Entrada registrada.', 'estoque': produto.estoque})

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def ajuste(self, request, pk=None):
        produto = self._locked_product()
        novo_estoque = serializers.IntegerField(min_value=0).run_validation(request.data.get('estoque'))
        quantidade = novo_estoque - produto.estoque
        if quantidade < 0:
            # Inventory corrections may remove expired stock too.
            restante = -quantidade
            for lote in produto.lotes.select_for_update().filter(quantidade_atual__gt=0).order_by('pk'):
                baixa = min(lote.quantidade_atual, restante)
                lote.quantidade_atual -= baixa
                lote.save(update_fields=['quantidade_atual'])
                restante -= baixa
                if not restante:
                    break
        self._registrar_movimentacao(produto, 'ajuste', quantidade, request.data.get('observacao', 'Ajuste manual'))
        return Response({'detail': 'Estoque ajustado.', 'estoque': produto.estoque})

    @action(detail=True, methods=['post'], url_path='venda-balcao')
    @transaction.atomic
    def venda_balcao(self, request, pk=None):
        produto = self._locked_product()
        if produto.canal == 'app':
            return Response({'detail': 'Produto exclusivo do app.'}, status=status.HTTP_400_BAD_REQUEST)
        quantidade = serializers.IntegerField(min_value=1).run_validation(request.data.get('quantidade', 1))
        remove_stock(produto, quantidade, 'venda_balcao', request.user, 'Venda no balcao')
        registrar_auditoria(request, get_user_arena(request.user), 'estoque.venda_balcao', produto,
                            novos={'quantidade': quantidade, 'estoque': produto.estoque})
        return Response({'detail': 'Venda de balcao registrada.', 'estoque': produto.estoque})


class AdminFornecedorViewSet(FeatureEnabledMixin, viewsets.ModelViewSet):
    feature_key = 'store'
    serializer_class = FornecedorSerializer
    permission_classes = [require_permission('estoque.manage')]

    def get_queryset(self):
        return Fornecedor.objects.filter(arena=get_user_arena(self.request.user))

    def perform_create(self, serializer):
        serializer.save(arena=get_user_arena(self.request.user))


class AdminLoteEstoqueViewSet(FeatureEnabledMixin, viewsets.ReadOnlyModelViewSet):
    feature_key = 'store'
    serializer_class = LoteEstoqueSerializer
    permission_classes = [require_permission('estoque.view')]

    def get_queryset(self):
        qs = LoteEstoque.objects.filter(arena=get_user_arena(self.request.user)).select_related('produto', 'fornecedor')
        produto_id = self.request.query_params.get('produto')
        if produto_id:
            qs = qs.filter(produto_id=produto_id)
        return qs


class AdminMovimentacaoEstoqueViewSet(FeatureEnabledMixin, viewsets.ReadOnlyModelViewSet):
    feature_key = 'store'
    serializer_class = MovimentacaoEstoqueSerializer
    permission_classes = [require_permission('estoque.view')]

    def get_queryset(self):
        qs = MovimentacaoEstoque.objects.filter(arena=get_user_arena(self.request.user)).select_related('produto', 'criado_por')
        produto_id = self.request.query_params.get('produto')
        if produto_id:
            qs = qs.filter(produto_id=produto_id)
        return qs


class VendaViewSet(FeatureEnabledMixin, viewsets.ModelViewSet):
    feature_key = 'store'
    """
    POST /api/vendas/  ← cliente cria pedido
    GET /api/vendas/   ← lista os meus pedidos
    """
    serializer_class = VendaSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ['get', 'post', 'head', 'options']  # bloqueia PUT/DELETE

    def get_queryset(self):
        return (
            Venda.objects
            .filter(arena=get_user_arena(self.request.user))
            .filter(cliente=self.request.user)
            .select_related('cliente')
            .prefetch_related('itens__produto')
        )

    def perform_create(self, serializer):
        # Cliente é sempre o usuário logado (segurança)
        serializer.save(cliente=self.request.user, arena=get_user_arena(self.request.user))


class AdminVendaViewSet(FeatureEnabledMixin, viewsets.ReadOnlyModelViewSet):
    feature_key = 'store'
    serializer_class = VendaSerializer
    permission_classes = [require_permission('pedidos.view')]

    def get_queryset(self):
        qs = (
            Venda.objects
            .filter(arena=get_user_arena(self.request.user))
            .select_related('cliente')
            .prefetch_related('itens__produto')
        )
        status_filtro = self.request.query_params.get('status')
        if status_filtro in ['aberta', 'paga', 'cancelada']:
            qs = qs.filter(status=status_filtro)
        return qs
