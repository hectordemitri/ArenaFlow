from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone
from common_validators import validate_image_upload


class Categoria(models.Model):
    arena = models.ForeignKey('arena.Arena', on_delete=models.CASCADE, related_name='categorias_loja')
    nome = models.CharField(max_length=50)

    class Meta:
        verbose_name = 'Categoria'
        verbose_name_plural = 'Categorias'
        ordering = ['nome']

    def __str__(self):
        return self.nome


class Fornecedor(models.Model):
    arena = models.ForeignKey('arena.Arena', on_delete=models.CASCADE, related_name='fornecedores')
    nome = models.CharField(max_length=120)
    contato = models.CharField(max_length=120, blank=True)
    telefone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    observacoes = models.TextField(blank=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Fornecedor'
        verbose_name_plural = 'Fornecedores'
        ordering = ['nome']

    def __str__(self):
        return self.nome


class Produto(models.Model):
    CANAL_CHOICES = [
        ('app', 'App'),
        ('balcao', 'Balcao'),
        ('ambos', 'App e balcao'),
    ]

    arena = models.ForeignKey('arena.Arena', on_delete=models.CASCADE, related_name='produtos')
    categoria = models.ForeignKey(Categoria, on_delete=models.PROTECT, related_name='produtos')
    fornecedor = models.ForeignKey(
        Fornecedor,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='produtos',
    )
    nome = models.CharField(max_length=100)
    descricao = models.TextField(blank=True)
    sku = models.CharField(max_length=60, blank=True, null=True)
    codigo_barras = models.CharField(max_length=80, blank=True, null=True)
    preco = models.DecimalField(max_digits=8, decimal_places=2)
    custo_unitario = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    estoque = models.PositiveIntegerField(default=0)
    estoque_minimo = models.PositiveIntegerField(default=0)
    canal = models.CharField(max_length=20, choices=CANAL_CHOICES, default='app')
    imagem = models.ImageField(upload_to='produtos/', null=True, blank=True, validators=[validate_image_upload])
    ativo = models.BooleanField(default=True)
    is_aluguel = models.BooleanField(
        default=False,
        help_text='Marque se for item de aluguel (bola, kit, etc.)',
    )

    class Meta:
        ordering = ['nome']
        constraints = [
            models.UniqueConstraint(
                fields=['arena', 'sku'],
                condition=Q(sku__isnull=False) & ~Q(sku=''),
                name='uniq_produto_sku_por_arena',
            ),
            models.UniqueConstraint(
                fields=['arena', 'codigo_barras'],
                condition=Q(codigo_barras__isnull=False) & ~Q(codigo_barras=''),
                name='uniq_produto_codigo_barras_por_arena',
            ),
        ]

    def __str__(self):
        tipo = 'Aluguel' if self.is_aluguel else 'Venda'
        return f'{tipo} - {self.nome} - R$ {self.preco}'

    @property
    def estoque_baixo(self):
        return self.estoque <= self.estoque_minimo

    @property
    def margem_percentual(self):
        if not self.preco or self.preco <= 0:
            return 0
        return round(((self.preco - self.custo_unitario) / self.preco) * 100, 2)

    @property
    def lucro_unitario(self):
        return self.preco - self.custo_unitario

    @property
    def validade_mais_proxima(self):
        lote = (
            self.lotes
            .filter(quantidade_atual__gt=0, validade__isnull=False)
            .order_by('validade')
            .first()
        )
        return lote.validade if lote else None

    @property
    def vencimento_proximo(self):
        validade = self.validade_mais_proxima
        if not validade:
            return False
        return validade <= timezone.localdate() + timezone.timedelta(days=30)

    @property
    def vencido(self):
        validade = self.validade_mais_proxima
        return bool(validade and validade < timezone.localdate())


class LoteEstoque(models.Model):
    arena = models.ForeignKey('arena.Arena', on_delete=models.CASCADE, related_name='lotes_estoque')
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE, related_name='lotes')
    codigo_lote = models.CharField(max_length=80, blank=True)
    quantidade_inicial = models.PositiveIntegerField(default=0)
    quantidade_atual = models.PositiveIntegerField(default=0)
    custo_unitario = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    validade = models.DateField(null=True, blank=True)
    fornecedor = models.ForeignKey(Fornecedor, on_delete=models.SET_NULL, null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Lote de estoque'
        verbose_name_plural = 'Lotes de estoque'
        ordering = ['validade', 'criado_em']

    def __str__(self):
        lote = self.codigo_lote or f'Lote #{self.id}'
        return f'{self.produto.nome} - {lote}'


class MovimentacaoEstoque(models.Model):
    TIPO_CHOICES = [
        ('entrada', 'Entrada'),
        ('venda_balcao', 'Venda de balcao'),
        ('venda_app', 'Venda pelo app'),
        ('ajuste', 'Ajuste'),
        ('perda', 'Perda'),
        ('devolucao', 'Devolucao'),
    ]

    arena = models.ForeignKey('arena.Arena', on_delete=models.CASCADE, related_name='movimentacoes_estoque')
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT, related_name='movimentacoes')
    lote = models.ForeignKey(LoteEstoque, on_delete=models.SET_NULL, null=True, blank=True, related_name='movimentacoes')
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    quantidade = models.IntegerField()
    estoque_antes = models.PositiveIntegerField()
    estoque_depois = models.PositiveIntegerField()
    valor_unitario = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    custo_unitario = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    observacao = models.CharField(max_length=200, blank=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-criado_em']

    def __str__(self):
        return f'{self.produto.nome} {self.tipo} {self.quantidade}'


class Venda(models.Model):
    STATUS = [
        ('aberta', 'Aberta'),
        ('paga', 'Paga'),
        ('cancelada', 'Cancelada'),
    ]
    arena = models.ForeignKey('arena.Arena', on_delete=models.CASCADE, related_name='vendas')
    cliente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    data = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS, default='aberta')
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    observacoes = models.TextField(blank=True)
    request_key = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ['-data']
        constraints = [models.UniqueConstraint(
            fields=['arena', 'cliente', 'request_key'], condition=~Q(request_key=''),
            name='unique_order_request_per_customer',
        )]

    def calcular_total(self):
        total = sum(item.subtotal() for item in self.itens.all())
        self.total = total
        self.save(update_fields=['total'])
        return total

    def __str__(self):
        return f'Venda #{self.id} - {self.cliente} - R$ {self.total}'


class ItemVenda(models.Model):
    arena = models.ForeignKey('arena.Arena', on_delete=models.CASCADE, related_name='itens_venda')
    venda = models.ForeignKey(Venda, on_delete=models.CASCADE, related_name='itens')
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT)
    quantidade = models.PositiveIntegerField(default=1)
    preco_unitario = models.DecimalField(max_digits=8, decimal_places=2)

    class Meta:
        verbose_name = 'Item da Venda'
        verbose_name_plural = 'Itens da Venda'

    def subtotal(self):
        return self.quantidade * self.preco_unitario

    def save(self, *args, **kwargs):
        if self.venda_id and not self.arena_id:
            self.arena = self.venda.arena
        if not self.preco_unitario:
            self.preco_unitario = self.produto.preco
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.quantidade}x {self.produto.nome}'
