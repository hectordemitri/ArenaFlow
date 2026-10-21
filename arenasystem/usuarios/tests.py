from datetime import timedelta
from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image

from common_validators import validate_image_upload

from unittest.mock import patch

from django.utils import timezone
from rest_framework.test import APIClient

from arena.models import Arena
from saas_billing.models import SaasPlan, SaasSubscription
from usuarios.account_services import accept_invitation, create_invitation, create_password_reset
from usuarios.models import (
    EmailChangeRequest, NotificationPreference, UserInvitation, UserPermissionOverride,
    UserSession, Usuario,
)
from usuarios.permissions import tem_permissao
from gestao.models import AuditLog


class UploadSecurityTests(TestCase):
    def test_accepts_supported_images_and_preserves_file_position(self):
        for image_format, extension, mime in [
            ('PNG', 'png', 'image/png'),
            ('JPEG', 'jpg', 'image/jpeg'),
            ('WEBP', 'webp', 'image/webp'),
        ]:
            with self.subTest(image_format=image_format):
                buffer = BytesIO()
                Image.new('RGB', (8, 8), 'green').save(buffer, format=image_format)
                image = SimpleUploadedFile(f'perfil.{extension}', buffer.getvalue(), content_type=mime)
                validate_image_upload(image)
                self.assertEqual(image.tell(), 0)

    def test_rejeita_arquivo_falso_como_imagem(self):
        arquivo = SimpleUploadedFile(
            'perfil.jpg',
            b'isso nao e uma imagem real',
            content_type='image/jpeg',
        )

        with self.assertRaises(ValidationError):
            validate_image_upload(arquivo)


class AccountLifecycleTests(TestCase):
    def setUp(self):
        self.arena = Arena.objects.create(nome='Arena Contas', slug='arena-contas')
        plan = SaasPlan.objects.create(code='accounts', name='Accounts', max_admins=10, max_professors=10)
        SaasSubscription.objects.create(arena=self.arena, plan=plan, status='active')
        self.owner = Usuario.objects.create_user(
            username='owner-accounts', password='Password123!', email='owner@accounts.test',
            tipo='admin_arena', papel='dono', arena=self.arena,
        )
        self.admin = Usuario.objects.create_user(
            username='admin-accounts', password='Password123!', email='admin@accounts.test',
            tipo='admin_arena', papel='administrador', arena=self.arena,
        )
        self.client = APIClient()

    def test_login_creates_revocable_session(self):
        response = self.client.post('/api/auth/login/', {'username': self.owner.username, 'password': 'Password123!'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(UserSession.objects.filter(user=self.owner, revoked_at__isnull=True).count(), 1)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        logout = self.client.post('/api/auth/logout-all/')
        self.assertEqual(logout.status_code, 200)
        denied = self.client.get('/api/usuarios/me/')
        self.assertEqual(denied.status_code, 401)

    def test_permission_deny_override_precedes_role(self):
        self.assertTrue(tem_permissao(self.admin, 'alunos.manage'))
        UserPermissionOverride.objects.create(user=self.admin, permission='alunos.manage', effect='deny')
        self.assertFalse(tem_permissao(self.admin, 'alunos.manage'))

    @patch('usuarios.account_services.send_transactional_email.delay')
    def test_invitation_is_hashed_single_use_and_accepts(self, email_delay):
        invitation = create_invitation(self.arena, 'new-admin@example.test', 'administrador', self.owner)
        raw = invitation._raw_token
        self.assertNotEqual(invitation.token_hash, raw)
        user = accept_invitation(invitation, raw, 'Nova', 'Admin', 'StrongPassword123!')
        self.assertEqual(user.arena, self.arena)
        self.assertEqual(user.papel, 'administrador')
        with self.assertRaises(ValueError):
            accept_invitation(invitation, raw, 'Nova', 'Admin', 'StrongPassword123!')
        email_delay.assert_called_once()

    @patch('usuarios.account_services.send_transactional_email.delay')
    def test_expired_and_canceled_invitations_cannot_be_used(self, _email_delay):
        expired = create_invitation(self.arena, 'expired@example.test', 'recepcao', self.owner)
        expired.expires_at = timezone.now() - timedelta(seconds=1)
        expired.save(update_fields=['expires_at'])
        with self.assertRaises(ValueError):
            accept_invitation(expired, expired._raw_token, 'Convite', 'Expirado', 'StrongPassword123!')

        canceled = create_invitation(self.arena, 'canceled@example.test', 'financeiro', self.owner)
        canceled.canceled_at = timezone.now()
        canceled.save(update_fields=['canceled_at'])
        with self.assertRaises(ValueError):
            accept_invitation(canceled, canceled._raw_token, 'Convite', 'Cancelado', 'StrongPassword123!')
        self.assertFalse(UserInvitation.objects.filter(accepted_at__isnull=False).exists())

    @patch('usuarios.account_services.send_transactional_email.delay')
    def test_password_reset_revokes_sessions(self, email_delay):
        session = UserSession.objects.create(user=self.owner, session_id='0b72efc4-a61d-4474-8773-35a476683095')
        reset = create_password_reset(self.owner)
        response = self.client.post('/api/auth/password-reset/confirm/', {
            'request': str(reset.public_id), 'token': reset._raw_token,
            'password': 'AnotherStrong123!', 'password_confirm': 'AnotherStrong123!',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.owner.refresh_from_db()
        session.refresh_from_db()
        self.assertTrue(self.owner.check_password('AnotherStrong123!'))
        self.assertIsNotNone(session.revoked_at)

    def test_password_reset_request_does_not_enumerate_accounts(self):
        with patch('usuarios.account_views.create_password_reset') as create_reset:
            known = self.client.post('/api/auth/password-reset/request/', {'email': self.owner.email})
            unknown = self.client.post('/api/auth/password-reset/request/', {'email': 'missing@example.test'})
        self.assertEqual(known.status_code, 202)
        self.assertEqual(known.data, unknown.data)
        create_reset.assert_called_once()

    def test_owner_transfer_is_atomic_and_unique(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(f'/api/admin/team/users/{self.admin.id}/transfer_ownership/')
        self.assertEqual(response.status_code, 200)
        self.owner.refresh_from_db()
        self.admin.refresh_from_db()
        self.assertEqual(self.owner.papel, 'administrador')
        self.assertEqual(self.admin.papel, 'dono')
        self.assertEqual(Usuario.objects.filter(arena=self.arena, papel='dono').count(), 1)


class ProfileAccountApiTests(TestCase):
    def setUp(self):
        self.arena = Arena.objects.create(nome='Arena Perfil', slug='arena-perfil')
        plan = SaasPlan.objects.create(code='profile', name='Profile')
        SaasSubscription.objects.create(arena=self.arena, plan=plan, status='active')
        self.user = Usuario.objects.create_user(
            username='profile-user', password='CurrentPassword123!', email='old@profile.test',
            first_name='Nome', tipo='aluno', papel='aluno', arena=self.arena,
        )

    def login(self, user_agent='Mozilla/5.0 (Android) Chrome/120.0'):
        client = APIClient()
        response = client.post(
            '/api/auth/login/', {'username': self.user.username, 'password': 'CurrentPassword123!'},
            format='json', HTTP_USER_AGENT=user_agent,
        )
        self.assertEqual(response.status_code, 200)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        return client

    def test_profile_patch_updates_only_allowed_fields_and_audits(self):
        client = self.login()
        response = client.patch('/api/usuarios/me/', {
            'first_name': 'Novo', 'telefone': '(21) 99999-0000',
            'email': 'ignored@profile.test', 'papel': 'dono', 'arena': None,
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Novo')
        self.assertEqual(self.user.telefone, '(21) 99999-0000')
        self.assertEqual(self.user.email, 'old@profile.test')
        self.assertEqual(self.user.papel, 'aluno')
        self.assertEqual(self.user.arena, self.arena)
        self.assertTrue(AuditLog.objects.filter(usuario=self.user, acao='account.profile_updated').exists())

    def test_notification_preferences_are_private_and_persisted(self):
        client = self.login()
        initial = client.get('/api/auth/notification-preferences/')
        self.assertEqual(initial.status_code, 200)
        self.assertTrue(initial.data['app_checkins'])
        updated = client.patch('/api/auth/notification-preferences/', {
            'app_checkins': False, 'email_financial': False,
        }, format='json')
        self.assertEqual(updated.status_code, 200)
        preference = NotificationPreference.objects.get(user=self.user)
        self.assertFalse(preference.app_checkins)
        self.assertFalse(preference.email_financial)

    def test_password_change_requires_current_password_and_revokes_other_sessions(self):
        current = self.login('Mozilla/5.0 (iPhone) Safari/605.1')
        self.login('Mozilla/5.0 (Windows NT 10.0) Chrome/120.0')
        denied = current.post('/api/auth/password/change/', {
            'current_password': 'wrong', 'password': 'NewSecurePassword123!',
            'password_confirm': 'NewSecurePassword123!',
        }, format='json')
        self.assertEqual(denied.status_code, 400)
        response = current.post('/api/auth/password/change/', {
            'current_password': 'CurrentPassword123!', 'password': 'NewSecurePassword123!',
            'password_confirm': 'NewSecurePassword123!',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['other_sessions_revoked'], 1)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewSecurePassword123!'))
        self.assertEqual(UserSession.objects.filter(user=self.user, revoked_at__isnull=True).count(), 1)
        log = AuditLog.objects.get(usuario=self.user, acao='account.password_changed')
        self.assertNotIn('password', str(log.valores_novos).lower())
        self.assertNotIn('currentpassword', str(log.metadados).lower())

    @patch('usuarios.account_services.send_transactional_email.delay')
    def test_email_change_requires_password_is_hashed_and_single_use(self, email_delay):
        client = self.login()
        denied = client.post('/api/auth/email-change/request/', {
            'email': 'new@profile.test', 'current_password': 'wrong',
        }, format='json')
        self.assertEqual(denied.status_code, 400)
        response = client.post('/api/auth/email-change/request/', {
            'email': 'new@profile.test', 'current_password': 'CurrentPassword123!',
        }, format='json')
        self.assertEqual(response.status_code, 202)
        change = EmailChangeRequest.objects.get(user=self.user, used_at__isnull=True)
        self.assertEqual(len(change.token_hash), 64)
        self.assertNotIn('token', response.data)
        from usuarios.account_services import create_email_change
        replacement = create_email_change(self.user, 'confirmed@profile.test')
        confirmed = APIClient().post('/api/auth/email-change/confirm/', {
            'request': str(replacement.public_id), 'token': replacement._raw_token,
        }, format='json')
        self.assertEqual(confirmed.status_code, 200)
        repeated = APIClient().post('/api/auth/email-change/confirm/', {
            'request': str(replacement.public_id), 'token': replacement._raw_token,
        }, format='json')
        self.assertEqual(repeated.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'confirmed@profile.test')

    def test_sessions_identify_current_and_cannot_revoke_another_user_session(self):
        client = self.login('Mozilla/5.0 (iPhone) Safari/605.1')
        listed = client.get('/api/auth/sessions/')
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.data), 1)
        self.assertTrue(listed.data[0]['current'])
        self.assertEqual(listed.data[0]['device'], 'iPhone/iPad - Safari')
        other = Usuario.objects.create_user(username='other-profile', password='OtherPassword123!', arena=self.arena)
        other_session = UserSession.objects.create(user=other, session_id='8a346287-ff92-493e-ad0f-c9bc5472c54a')
        denied = client.post(f'/api/auth/sessions/{other_session.public_id}/revoke/')
        self.assertEqual(denied.status_code, 404)
