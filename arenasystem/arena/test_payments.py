import hashlib
import hmac
from datetime import date
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from arenasystem.secrets import decrypt_secret, encrypt_secret
from gestao.models import AuditLog
from usuarios.models import Usuario
from .models import Arena, Matricula, Mensalidade, PaymentAccount, PaymentOAuthAttempt, PaymentWebhookEvent, Plano, StudentPayment
from .payment_accounts import access_token_for, finish_authorization, start_authorization
from .payments import apply_payment, generate_monthly_dues, reconcile_student_payments, update_overdue
from .services import MercadoPagoConfigError


@override_settings(MERCADO_PAGO_WEBHOOK_SECRET='student-secret', MERCADO_PAGO_CLIENT_ID='app',
                   MERCADO_PAGO_CLIENT_SECRET='client-secret', MERCADO_PAGO_REDIRECT_URI='https://api.test/api/mercado-pago/callback/')
class StudentPaymentTests(TestCase):
    def setUp(self):
        self.arena = Arena.objects.create(nome='Recebimentos A', slug='payments-a')
        self.other = Arena.objects.create(nome='Recebimentos B', slug='payments-b')
        self.owner = Usuario.objects.create_user(username='payment-owner', password='Password123!', arena=self.arena, papel='dono')
        self.student = Usuario.objects.create_user(username='payment-student', arena=self.arena)
        self.plan = Plano.objects.create(arena=self.arena, nome='Mensal', valor=200, frequencia_semanal=2)
        self.enrollment = Matricula.objects.create(arena=self.arena, aluno=self.student, plano=self.plan, data_inicio=date(2025, 1, 10))
        self.due = Mensalidade.objects.create(arena=self.arena, matricula=self.enrollment, mes_referencia=date(2026, 1, 1),
                                             vencimento=date(2026, 1, 10), valor=200, external_reference='private-reference')
        self.account = PaymentAccount.objects.create(arena=self.arena, collector_id='123',
            access_token_encrypted=encrypt_secret('seller-token'), refresh_token_encrypted=encrypt_secret('refresh'),
            expires_at=timezone.now() + timezone.timedelta(days=1))
        self.client = APIClient()
        self.payment = {'id': '789', 'status': 'approved', 'collector_id': '123', 'currency_id': 'BRL',
                        'transaction_amount': '200.00', 'external_reference': 'private-reference',
                        'date_last_updated': '2026-10-10T12:00:00-03:00'}

    def test_duplicate_notification_has_one_payment_and_audit(self):
        apply_payment(self.arena, self.payment)
        apply_payment(self.arena, self.payment)
        self.due.refresh_from_db()
        self.assertEqual(self.due.status, 'pago')
        self.assertEqual(StudentPayment.objects.count(), 1)
        self.assertEqual(PaymentWebhookEvent.objects.count(), 1)
        self.assertEqual(AuditLog.objects.filter(acao='mensalidade.pagamento_conciliado').count(), 1)

    def test_amount_currency_recipient_and_reference_must_match(self):
        for changes in [{'transaction_amount': 1}, {'transaction_amount': 'NaN'}, {'currency_id': 'USD'},
                        {'collector_id': '999'}, {'external_reference': 'other-reference'}]:
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                apply_payment(self.arena, {**self.payment, **changes})
        self.assertFalse(StudentPayment.objects.exists())

    def test_refund_and_chargeback_clear_paid_date(self):
        apply_payment(self.arena, self.payment)
        for day, provider_status, local_status in [(11, 'refunded', 'estornada'), (12, 'charged_back', 'contestada')]:
            apply_payment(self.arena, {**self.payment, 'status': provider_status, 'date_last_updated': f'2026-10-{day}T12:00:00-03:00'})
            self.due.refresh_from_db()
            self.assertEqual(self.due.status, local_status)
            self.assertIsNone(self.due.data_pagamento)

    def test_partial_refund_is_not_considered_fully_paid(self):
        apply_payment(self.arena, {**self.payment, 'transaction_amount_refunded': '50.00'})
        self.due.refresh_from_db()
        self.assertEqual(self.due.status, 'estornada')

    def test_old_approval_cannot_undo_refund(self):
        apply_payment(self.arena, {**self.payment, 'status': 'refunded', 'date_last_updated': '2026-10-11T12:00:00-03:00'})
        apply_payment(self.arena, self.payment)
        self.due.refresh_from_db()
        self.assertEqual(self.due.status, 'estornada')

    def test_declined_attempt_cannot_undo_another_approved_payment(self):
        apply_payment(self.arena, self.payment)
        apply_payment(self.arena, {**self.payment, 'id': '790', 'status': 'rejected'})
        self.due.refresh_from_db()
        self.assertEqual(self.due.status, 'pago')

    def test_cancelled_invoice_stays_cancelled_but_payment_is_recorded(self):
        self.due.status = 'cancelada'
        self.due.save()
        apply_payment(self.arena, self.payment)
        self.due.refresh_from_db()
        self.assertEqual(self.due.status, 'cancelada')
        self.assertTrue(StudentPayment.objects.exists())

    @patch('arena.payment_views.obter_pagamento')
    def test_invalid_signature_never_queries_provider(self, provider):
        response = self.client.post(f'/api/mercado-pago/webhook/{self.arena.pk}/?data.id=789', {}, format='json')
        self.assertEqual(response.status_code, 401)
        provider.assert_not_called()

    @patch('arena.payment_views.obter_pagamento')
    def test_signed_webhook_uses_tenant_account_and_provider_data(self, provider):
        provider.return_value = self.payment
        manifest = 'id:789;request-id:request-1;ts:12345;'
        signature = hmac.new(b'student-secret', manifest.encode(), hashlib.sha256).hexdigest()
        response = self.client.post(f'/api/mercado-pago/webhook/{self.arena.pk}/?data.id=789',
            {'type': 'payment', 'status': 'rejected'}, format='json', HTTP_X_REQUEST_ID='request-1',
            HTTP_X_SIGNATURE=f'ts=12345,v1={signature}')
        self.assertEqual(response.status_code, 200)
        provider.assert_called_once_with('789', self.arena)
        self.due.refresh_from_db()
        self.assertEqual(self.due.status, 'pago')

    def test_no_global_token_fallback_for_another_arena(self):
        with self.assertRaises(MercadoPagoConfigError):
            access_token_for(self.other)

    def test_only_owner_can_connect_and_response_never_contains_tokens(self):
        self.client.force_authenticate(self.student)
        self.assertEqual(self.client.post('/api/admin/payment-account/').status_code, 403)
        self.client.force_authenticate(self.owner)
        response = self.client.get('/api/admin/payment-account/')
        self.assertTrue(response.data['connected'])
        self.assertNotIn('seller-token', str(response.data))

    @patch('arena.payment_accounts.exchange_token')
    def test_oauth_state_single_use_pkce_and_encrypted_credentials(self, exchange):
        exchange.return_value = {'user_id': '123', 'access_token': 'new-token', 'refresh_token': 'new-refresh', 'expires_in': 3600}
        state, url = start_authorization(self.arena, self.owner)
        self.assertIn('code_challenge_method=S256', url)
        self.assertFalse(PaymentOAuthAttempt.objects.filter(state_hash=state).exists())
        account = finish_authorization(state, 'authorization-code')
        self.assertNotEqual(account.access_token_encrypted, 'new-token')
        self.assertEqual(decrypt_secret(account.access_token_encrypted), 'new-token')
        self.assertIn('code_verifier', exchange.call_args.args[0])
        with self.assertRaises(MercadoPagoConfigError):
            finish_authorization(state, 'authorization-code')

    @patch('arena.payment_accounts.exchange_token')
    def test_refresh_rotates_credentials_without_switching_collector(self, exchange):
        self.account.expires_at = timezone.now()
        self.account.save()
        exchange.return_value = {'user_id': '123', 'access_token': 'rotated', 'refresh_token': 'rotated-refresh', 'expires_in': 3600}
        self.assertEqual(access_token_for(self.arena), 'rotated')
        self.account.refresh_from_db()
        self.assertEqual(decrypt_secret(self.account.refresh_token_encrypted), 'rotated-refresh')

    def test_callback_requires_browser_binding(self):
        state, _ = start_authorization(self.arena, self.owner)
        self.assertEqual(self.client.get('/api/mercado-pago/callback/', {'state': state, 'code': 'x'}).status_code, 400)

    @patch('arena.payment_accounts.exchange_token')
    def test_owner_oauth_handoff_sets_cookie_and_completes_callback(self, exchange):
        exchange.return_value = {'user_id': '123', 'access_token': 'new-token', 'refresh_token': 'new-refresh', 'expires_in': 3600}
        self.client.force_authenticate(self.owner)
        start = self.client.post('/api/admin/payment-account/')
        target = urlsplit(start.data['authorization_url'])
        handoff = self.client.get(f'{target.path}?{target.query}')
        self.assertEqual(handoff.status_code, 302)
        self.assertTrue(handoff.cookies['mp_oauth_state']['httponly'])
        self.assertEqual(handoff.cookies['mp_oauth_state']['samesite'], 'Lax')
        state = parse_qs(urlsplit(handoff.url).query)['state'][0]
        callback = self.client.get('/api/mercado-pago/callback/', {'state': state, 'code': 'authorized-code'})
        self.assertEqual(callback.status_code, 302)
        self.assertIn('mercado_pago=connected', callback.url)
        self.assertTrue(AuditLog.objects.filter(acao='payment_account.connected').exists())

    def test_unlinked_authenticated_user_cannot_fall_back_to_demo_arena(self):
        orphan = Usuario.objects.create_user(username='unlinked-student')
        self.client.force_authenticate(orphan)
        self.assertEqual(self.client.get('/api/arena/atual/').status_code, 403)

    @patch('arena.services.buscar_pagamentos_por_referencia')
    def test_reconciliation_recovers_missing_notification(self, search):
        search.return_value = {'results': [self.payment]}
        self.assertEqual(reconcile_student_payments()['checked'], 1)
        self.due.refresh_from_db()
        self.assertEqual(self.due.status, 'pago')

    def test_overdue_empty_queryset_cannot_update_other_tenants(self):
        self.assertEqual(update_overdue(Mensalidade.objects.none()), 0)
        self.due.refresh_from_db()
        self.assertEqual(self.due.status, 'pendente')

    def test_monthly_generation_is_idempotent_and_clamps_end_of_month(self):
        self.enrollment.data_inicio = date(2026, 1, 31)
        self.enrollment.save()
        first = generate_monthly_dues(date(2026, 2, 20))
        second = generate_monthly_dues(date(2026, 2, 20))
        self.assertEqual((first['created'], second['created']), (1, 0))
        due = Mensalidade.objects.get(matricula=self.enrollment, mes_referencia=date(2026, 2, 1))
        self.assertEqual(due.vencimento, date(2026, 2, 28))

    def test_future_and_ended_enrollments_are_not_billed(self):
        self.enrollment.data_inicio = date(2027, 1, 1)
        self.enrollment.save()
        self.assertEqual(generate_monthly_dues(date(2026, 11, 1))['created'], 0)
        self.enrollment.data_inicio = date(2025, 1, 1)
        self.enrollment.data_fim = date(2026, 10, 31)
        self.enrollment.save()
        self.assertEqual(generate_monthly_dues(date(2026, 11, 1))['created'], 0)
