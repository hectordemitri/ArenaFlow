from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import MovimentacaoEstoque


def record_change(product, quantity, kind, actor, *, lot=None, note='', cost=None):
    before = product.estoque
    if before + quantity < 0:
        raise ValidationError({'detail': 'Estoque insuficiente.'})
    product.estoque += quantity
    product.save(update_fields=['estoque'])
    return MovimentacaoEstoque.objects.create(
        arena_id=product.arena_id, produto=product, lote=lot, tipo=kind, quantidade=quantity,
        estoque_antes=before, estoque_depois=product.estoque, valor_unitario=product.preco,
        custo_unitario=cost if cost is not None else product.custo_unitario,
        criado_por=actor, observacao=note[:200],
    )


def remove_stock(product, quantity, kind, actor, note=''):
    # Callers hold the product lock and transaction throughout the operation.
    if quantity <= 0 or quantity > product.estoque:
        raise ValidationError({'detail': 'Estoque insuficiente.'})
    lots = list(product.lotes.select_for_update().filter(quantidade_atual__gt=0)
                .order_by(F('validade').asc(nulls_last=True), 'pk'))
    expired = sum(lot.quantidade_atual for lot in lots if lot.validade and lot.validade < timezone.localdate())
    if quantity > product.estoque - expired:
        raise ValidationError({'detail': 'Quantidade disponivel insuficiente: existem lotes vencidos.'})
    remaining = quantity
    for lot in lots:
        if not remaining:
            break
        if lot.validade and lot.validade < timezone.localdate():
            continue
        taken = min(lot.quantidade_atual, remaining)
        lot.quantidade_atual -= taken
        lot.save(update_fields=['quantidade_atual'])
        record_change(product, -taken, kind, actor, lot=lot, note=note, cost=lot.custo_unitario)
        remaining -= taken
    if remaining:
        record_change(product, -remaining, kind, actor, note=note)
