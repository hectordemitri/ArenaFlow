from django.core.exceptions import ObjectDoesNotExist
from django.conf import settings
from rest_framework.authentication import SessionAuthentication
from rest_framework_simplejwt.authentication import JWTAuthentication

from usuarios.permissions import papel_usuario

from .exceptions import PaymentRequired


ALLOWED_WHEN_SUSPENDED = (
    '/api/auth/', '/api/health/', '/api/usuarios/me/', '/api/subscription/',
    '/api/support/', '/api/privacy/', '/api/saas/webhook/',
)


def enforce_subscription_access(request, user):
    if not user or not user.is_authenticated or not user.arena_id or papel_usuario(user) == 'superadmin_saas':
        return
    if any(request.path.startswith(prefix) for prefix in ALLOWED_WHEN_SUSPENDED):
        return
    try:
        status = user.arena.saas_subscription.status
    except (AttributeError, ObjectDoesNotExist):
        return
    if status in {'suspended', 'canceled'}:
        raise PaymentRequired({
            'code': 'subscription_inactive',
            'detail': 'A assinatura da arena esta suspensa. Acesse Minha assinatura para regularizar.',
            'status': status,
            'action': '/admin/assinatura',
        })


class SaasAwareJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result:
            user, token = result
            from usuarios.models import UserMFA
            enabled = UserMFA.objects.filter(user=user, enabled=True).exists()
            setup_required = settings.SUPERADMIN_REQUIRE_MFA and papel_usuario(user) == 'superadmin_saas'
            if ((enabled and not token.get('mfa_verified')) or (setup_required and not enabled)):
                if request.path not in {'/api/auth/mfa/', '/api/usuarios/me/', '/api/auth/logout/'}:
                    from rest_framework.exceptions import PermissionDenied
                    raise PermissionDenied({'detail': 'Configure a autenticacao em duas etapas.', 'code': 'mfa_setup_required'})
            if token.get('token_version', 0) != user.token_version:
                from rest_framework.exceptions import AuthenticationFailed
                raise AuthenticationFailed('Sessao revogada.')
            session_id = token.get('session_id')
            if session_id:
                from usuarios.models import UserSession
                if not UserSession.objects.filter(user=user, session_id=session_id, revoked_at__isnull=True).exists():
                    from rest_framework.exceptions import AuthenticationFailed
                    raise AuthenticationFailed('Sessao revogada.')
            enforce_subscription_access(request, result[0])
        return result


class SaasAwareSessionAuthentication(SessionAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result:
            from usuarios.models import UserMFA
            enabled = UserMFA.objects.filter(user=result[0], enabled=True).exists()
            required = settings.SUPERADMIN_REQUIRE_MFA and papel_usuario(result[0]) == 'superadmin_saas'
            if ((enabled and not request.session.get('admin_mfa_verified')) or (required and not enabled)):
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied('Entre com autenticacao em duas etapas.')
            enforce_subscription_access(request, result[0])
        return result
