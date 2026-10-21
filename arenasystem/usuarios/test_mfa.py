import importlib.util
from unittest import skipUnless
from unittest.mock import patch

from django.contrib import admin
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APIClient

from arena.models import Arena
from arenasystem.secrets import encrypt_secret
from .mfa import recovery_codes, verify_mfa
from .models import UserMFA, Usuario
from .permissions import tem_permissao


class MFAPolicyTests(TestCase):
    def setUp(self):
        self.user = Usuario.objects.create_user(username='mfa-root', password='SafePassword123!', is_superuser=True, is_staff=True)
        self.client = APIClient()

    @override_settings(SUPERADMIN_REQUIRE_MFA=True)
    def test_unenrolled_superadmin_can_only_setup_mfa(self):
        login = self.client.post('/api/auth/login/', {'username': self.user.username, 'password': 'SafePassword123!'})
        self.assertEqual(login.status_code, 200)
        self.assertTrue(login.data['mfa_setup_required'])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        self.assertEqual(self.client.get('/api/auth/mfa/').status_code, 200)
        self.assertEqual(self.client.get('/api/saas/arenas/').status_code, 403)

    def test_login_requires_second_factor_before_returning_tokens(self):
        UserMFA.objects.create(user=self.user, enabled=True, secret_encrypted=encrypt_secret('example-secret'))
        response = self.client.post('/api/auth/login/', {'username': self.user.username, 'password': 'SafePassword123!'})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(str(response.data['code']), 'mfa_required')
        self.assertNotIn('access', response.data)

    @patch('usuarios.mfa.totp')
    def test_totp_time_step_cannot_be_reused(self, factory):
        record = UserMFA.objects.create(user=self.user, enabled=True, secret_encrypted=encrypt_secret('example-secret'))
        step = 10000
        factory.return_value.at.side_effect = lambda timestamp: '123456' if timestamp == step * 30 else '999999'
        with patch('usuarios.mfa.time.time', return_value=step * 30):
            verify_mfa(self.user, '123456')
            with self.assertRaises(AuthenticationFailed):
                verify_mfa(self.user, '123456')
        record.refresh_from_db()
        self.assertEqual(record.last_step, step)

    @patch('usuarios.mfa.totp')
    def test_recovery_code_is_single_use_and_stored_hashed(self, factory):
        factory.return_value.at.return_value = '654321'
        codes, hashes = recovery_codes()
        record = UserMFA.objects.create(user=self.user, enabled=True, secret_encrypted=encrypt_secret('example-secret'), recovery_hashes=hashes)
        self.assertNotIn(codes[0], str(record.recovery_hashes))
        verify_mfa(self.user, codes[0])
        with self.assertRaises(AuthenticationFailed):
            verify_mfa(self.user, codes[0])

    def test_internal_admin_rejects_arena_owner_even_with_staff_flag(self):
        arena = Arena.objects.create(nome='Private admin', slug='private-admin')
        owner = Usuario.objects.create_user(username='owner-internal', arena=arena, papel='dono', is_staff=True)
        request = RequestFactory().get('/admin/')
        request.user, request.session = owner, {}
        self.assertFalse(admin.site.has_permission(request))
        self.assertFalse(tem_permissao(owner, 'saas.manage'))
        self.assertTrue(tem_permissao(self.user, 'saas.manage'))

    def test_legacy_unscoped_dashboard_is_not_exposed(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get('/dashboard/').status_code, 404)

    @skipUnless(importlib.util.find_spec('pyotp'), 'pyotp unavailable in local runtime; exercised in CI')
    def test_real_authenticator_enrollment_and_login(self):
        import pyotp
        self.client.force_authenticate(self.user)
        response = self.client.post('/api/auth/mfa/', {'current_password': 'SafePassword123!'})
        self.assertEqual(response.status_code, 200)
        secret = response.data['secret']
        confirmation = self.client.put('/api/auth/mfa/', {
            'current_password': 'SafePassword123!', 'code': pyotp.TOTP(secret).now(),
        })
        self.assertEqual(confirmation.status_code, 200)
        code = confirmation.data['recovery_codes'][0]
        self.client.force_authenticate(user=None)
        login = self.client.post('/api/auth/login/', {'username': self.user.username, 'password': 'SafePassword123!', 'otp_code': code})
        self.assertEqual(login.status_code, 200)
