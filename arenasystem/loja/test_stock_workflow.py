from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from arena.models import Arena
from usuarios.models import Usuario
from .models import Categoria, LoteEstoque, MovimentacaoEstoque, Produto, Venda


class StockWorkflowTests(TestCase):
    def setUp(self):
        self.arena = Arena.objects.create(nome='Stock', slug='stock-workflow')
        self.user = Usuario.objects.create_user(username='stock-user', arena=self.arena, papel='dono', tipo='admin_arena')
        self.category = Categoria.objects.create(arena=self.arena, nome='Uniforme')
        self.product = Produto.objects.create(arena=self.arena, categoria=self.category, nome='Camisa', preco=Decimal('50'), estoque=2, canal='ambos')
        self.lot = LoteEstoque.objects.create(arena=self.arena, produto=self.product, quantidade_inicial=2, quantidade_atual=2)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def order(self, quantity=1, key='request-1'):
        return self.client.post('/api/vendas/', {'itens': [{'produto': self.product.pk, 'quantidade': quantity}]},
                                format='json', HTTP_X_IDEMPOTENCY_KEY=key)

    def test_order_deducts_stock_and_retry_does_not_deduct_twice(self):
        first, retry = self.order(), self.order()
        self.assertEqual((first.status_code, retry.status_code), (201, 201))
        self.assertEqual(first.data['id'], retry.data['id'])
        self.product.refresh_from_db(); self.lot.refresh_from_db()
        self.assertEqual((self.product.estoque, self.lot.quantidade_atual), (1, 1))
        self.assertEqual(MovimentacaoEstoque.objects.filter(tipo='venda_app').count(), 1)

    def test_failed_order_does_not_leave_partial_records(self):
        self.assertEqual(self.order(3).status_code, 400)
        self.product.refresh_from_db(); self.lot.refresh_from_db()
        self.assertEqual((self.product.estoque, self.lot.quantidade_atual), (2, 2))
        self.assertFalse(Venda.objects.exists())

    def test_invalid_quantities_and_counter_only_products_are_rejected(self):
        for quantity in (0, -1, 'not-a-number'):
            self.assertEqual(self.order(quantity).status_code, 400)
        self.product.canal = 'balcao'; self.product.save()
        self.assertEqual(self.order().status_code, 400)

    def test_failed_counter_sale_preserves_lots(self):
        response = self.client.post(f'/api/admin/produtos/{self.product.pk}/venda-balcao/', {'quantidade': 3})
        self.assertEqual(response.status_code, 400)
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.quantidade_atual, 2)

    def test_expired_lot_is_not_sold(self):
        self.lot.validade = timezone.localdate() - timedelta(days=1)
        self.lot.save()
        self.assertEqual(self.order().status_code, 400)

    def test_inventory_correction_updates_lots_and_rejects_negative_stock(self):
        endpoint = f'/api/admin/produtos/{self.product.pk}/ajuste/'
        self.assertEqual(self.client.post(endpoint, {'estoque': -1}).status_code, 400)
        self.assertEqual(self.client.post(endpoint, {'estoque': 0}).status_code, 200)
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.quantidade_atual, 0)

    def test_reused_key_with_different_order_is_rejected(self):
        self.order()
        self.assertEqual(self.order(2).status_code, 400)
