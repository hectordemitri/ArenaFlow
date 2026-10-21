from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest import skipUnless

from django.db import connection, close_old_connections
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from arena.models import Arena, Quadra
from loja.models import Categoria, Produto
from usuarios.models import Usuario


@skipUnless(connection.vendor == 'postgresql', 'Row-lock contention requires PostgreSQL')
class RealConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.arena = Arena.objects.create(nome='Concurrent', slug='concurrent')
        self.users = [Usuario.objects.create_user(username=f'concurrent-{i}', arena=self.arena) for i in range(2)]
        self.court = Quadra.objects.create(arena=self.arena, nome='Court')
        category = Categoria.objects.create(arena=self.arena, nome='Uniforme')
        self.product = Produto.objects.create(arena=self.arena, categoria=category, nome='Last shirt', preco=50, estoque=1, canal='app')

    def race(self, endpoint, payload):
        barrier = Barrier(2)
        def submit(user):
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(user)
                barrier.wait(timeout=10)
                return client.post(endpoint, payload, format='json').status_code
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            return sorted(pool.map(submit, self.users))

    def test_only_one_customer_buys_last_product(self):
        statuses = self.race('/api/vendas/', {'itens': [{'produto': self.product.pk, 'quantidade': 1}]})
        self.assertEqual(statuses, [201, 400])
        self.product.refresh_from_db()
        self.assertEqual(self.product.estoque, 0)

    def test_only_one_customer_reserves_empty_slot(self):
        statuses = self.race('/api/reservas-quadra/', {
            'quadra': self.court.pk, 'data': (timezone.localdate() + timedelta(days=1)).isoformat(),
            'hora_inicio': '10:00', 'hora_fim': '11:00',
        })
        self.assertEqual(statuses, [201, 400])
