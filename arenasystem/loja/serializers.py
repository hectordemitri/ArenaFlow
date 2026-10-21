from rest_framework import serializers
from django.db import transaction

from arena.tenant import get_user_arena
from .models import Categoria, Fornecedor, ItemVenda, LoteEstoque, MovimentacaoEstoque, Produto, Venda


def arena_atual_serializer(serializer):
    request = serializer.context.get('request')
    if not request or not request.user.is_authenticated:
        return None
    return get_user_arena(request.user)


class CategoriaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Categoria
        fields = ['id', 'nome']


class FornecedorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Fornecedor
        fields = ['id', 'nome', 'contato', 'telefone', 'email', 'observacoes', 'ativo']


class LoteEstoqueSerializer(serializers.ModelSerializer):
    produto_nome = serializers.CharField(source='produto.nome', read_only=True)
    fornecedor_nome = serializers.CharField(source='fornecedor.nome', read_only=True)

    class Meta:
        model = LoteEstoque
        fields = [
            'id', 'produto', 'produto_nome', 'codigo_lote',
            'quantidade_inicial', 'quantidade_atual', 'custo_unitario',
            'validade', 'fornecedor', 'fornecedor_nome', 'criado_em',
        ]
        read_only_fields = ['criado_em']


class ProdutoSerializer(serializers.ModelSerializer):
    categoria_nome = serializers.CharField(source='categoria.nome', read_only=True)
    fornecedor_nome = serializers.CharField(source='fornecedor.nome', read_only=True)
    margem_percentual = serializers.DecimalField(max_digits=8, decimal_places=2, read_only=True)
    lucro_unitario = serializers.DecimalField(max_digits=8, decimal_places=2, read_only=True)
    validade_mais_proxima = serializers.DateField(read_only=True)
    vencimento_proximo = serializers.BooleanField(read_only=True)
    vencido = serializers.BooleanField(read_only=True)
    lotes_abertos = serializers.SerializerMethodField()

    class Meta:
        model = Produto
        fields = [
            'id', 'nome', 'descricao', 'sku', 'codigo_barras',
            'preco', 'custo_unitario', 'margem_percentual', 'lucro_unitario',
            'categoria', 'categoria_nome', 'fornecedor', 'fornecedor_nome',
            'estoque', 'estoque_minimo', 'estoque_baixo',
            'validade_mais_proxima', 'vencimento_proximo', 'vencido',
            'lotes_abertos', 'canal', 'imagem', 'ativo', 'is_aluguel',
        ]
        read_only_fields = [
            'estoque_baixo', 'margem_percentual', 'lucro_unitario',
            'validade_mais_proxima', 'vencimento_proximo', 'vencido',
            'lotes_abertos',
        ]

    def get_lotes_abertos(self, obj):
        lotes = obj.lotes.filter(quantidade_atual__gt=0).order_by('validade', 'criado_em')[:4]
        return LoteEstoqueSerializer(lotes, many=True).data

    def validate(self, attrs):
        arena = arena_atual_serializer(self)
        if self.instance and 'estoque' in attrs and attrs['estoque'] != self.instance.estoque:
            raise serializers.ValidationError({'estoque': 'Use a operacao de ajuste para alterar o saldo.'})
        if arena:
            categoria = attrs.get('categoria') or getattr(self.instance, 'categoria', None)
            fornecedor = attrs.get('fornecedor') or getattr(self.instance, 'fornecedor', None)
            if categoria and categoria.arena_id != arena.id:
                raise serializers.ValidationError({'categoria': 'Categoria nao pertence a arena atual.'})
            if fornecedor and fornecedor.arena_id != arena.id:
                raise serializers.ValidationError({'fornecedor': 'Fornecedor nao pertence a arena atual.'})
        return attrs


class ItemVendaSerializer(serializers.ModelSerializer):
    quantidade = serializers.IntegerField(min_value=1, max_value=10000)
    produto_nome = serializers.CharField(source='produto.nome', read_only=True)
    subtotal = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = ItemVenda
        fields = ['id', 'produto', 'produto_nome', 'quantidade', 'preco_unitario', 'subtotal']
        read_only_fields = ['preco_unitario']

    def validate(self, attrs):
        arena = arena_atual_serializer(self)
        produto = attrs.get('produto')
        if arena and produto and produto.arena_id != arena.id:
            raise serializers.ValidationError({'produto': 'Produto nao pertence a arena atual.'})
        return attrs


class VendaSerializer(serializers.ModelSerializer):
    itens = ItemVendaSerializer(many=True, allow_empty=False)
    cliente_nome = serializers.SerializerMethodField()

    class Meta:
        model = Venda
        fields = ['id', 'cliente', 'cliente_nome', 'data', 'status', 'total', 'observacoes', 'itens']
        read_only_fields = ['cliente', 'data', 'status', 'total']

    def get_cliente_nome(self, obj):
        return obj.cliente.get_full_name() or obj.cliente.username

    @transaction.atomic
    def create(self, validated_data):
        from usuarios.models import Usuario
        from .stock import remove_stock
        itens_data = validated_data.pop('itens')
        actor = validated_data['cliente']
        Usuario.objects.select_for_update().get(pk=actor.pk)
        request_key = self.context['request'].headers.get('X-Idempotency-Key', '')
        if len(request_key) > 80:
            raise serializers.ValidationError({'detail': 'Identificador de pedido invalido.'})
        if request_key:
            previous = Venda.objects.filter(arena=validated_data['arena'], cliente=actor, request_key=request_key).first()
            if previous:
                expected = sorted((item['produto'].pk, item['quantidade']) for item in itens_data)
                stored = sorted(previous.itens.values_list('produto_id', 'quantidade'))
                if expected != stored:
                    raise serializers.ValidationError({'detail': 'Identificador ja utilizado em outro pedido.'})
                return previous
        product_ids = [item['produto'].pk for item in itens_data]
        if len(product_ids) != len(set(product_ids)):
            raise serializers.ValidationError({'itens': 'Agrupe as quantidades de cada produto em um unico item.'})
        products = {p.pk: p for p in Produto.objects.select_for_update().filter(
            pk__in=product_ids, arena=validated_data['arena'], ativo=True, canal__in=['app', 'ambos'],
        ).order_by('pk')}
        if len(products) != len(product_ids):
            raise serializers.ValidationError({'itens': 'Um produto nao esta disponivel nesta loja.'})
        validated_data['request_key'] = request_key
        venda = Venda.objects.create(**validated_data)
        for item_data in itens_data:
            produto = products[item_data['produto'].pk]
            remove_stock(produto, item_data['quantidade'], 'venda_app', actor, f'Pedido #{venda.pk}')
            ItemVenda.objects.create(
                arena=venda.arena,
                venda=venda,
                produto=produto,
                quantidade=item_data['quantidade'],
                preco_unitario=produto.preco,
            )
        venda.calcular_total()
        return venda


class MovimentacaoEstoqueSerializer(serializers.ModelSerializer):
    produto_nome = serializers.CharField(source='produto.nome', read_only=True)
    tipo_display = serializers.CharField(source='get_tipo_display', read_only=True)
    criado_por_nome = serializers.SerializerMethodField()
    lote_codigo = serializers.CharField(source='lote.codigo_lote', read_only=True)

    class Meta:
        model = MovimentacaoEstoque
        fields = [
            'id', 'produto', 'produto_nome', 'lote', 'lote_codigo',
            'tipo', 'tipo_display', 'quantidade', 'estoque_antes', 'estoque_depois',
            'valor_unitario', 'custo_unitario', 'observacao', 'criado_por_nome', 'criado_em',
        ]

    def get_criado_por_nome(self, obj):
        if not obj.criado_por:
            return None
        return obj.criado_por.get_full_name() or obj.criado_por.username
