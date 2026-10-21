from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .api_views import UsuarioViewSet, CadastroAlunoView
from .api_views import AdminAlunoViewSet
from .mfa_views import mfa_settings
from .account_views import (
    InvitationViewSet, TeamUserViewSet, accept_user_invitation, change_password,
    confirm_email_change, confirm_password_reset, logout_all, logout_current, logout_others,
    notification_preferences, request_email_change, request_password_reset, revoke_session, sessions,
)

router = DefaultRouter()
router.register(r'usuarios', UsuarioViewSet, basename='usuario')
router.register(r'admin/alunos', AdminAlunoViewSet, basename='admin-alunos')
router.register(r'admin/team/users', TeamUserViewSet, basename='team-users')
router.register(r'admin/team/invitations', InvitationViewSet, basename='team-invitations')

urlpatterns = [
    path('auth/mfa/', mfa_settings, name='mfa-settings'),
    path('auth/register/', CadastroAlunoView.as_view(), name='cadastro_aluno'),
    path('auth/invitations/accept/', accept_user_invitation, name='accept-user-invitation'),
    path('auth/password-reset/request/', request_password_reset, name='request-password-reset'),
    path('auth/password-reset/confirm/', confirm_password_reset, name='confirm-password-reset'),
    path('auth/password/change/', change_password, name='change-password'),
    path('auth/email-change/request/', request_email_change, name='request-email-change'),
    path('auth/email-change/confirm/', confirm_email_change, name='confirm-email-change'),
    path('auth/notification-preferences/', notification_preferences, name='notification-preferences'),
    path('auth/logout/', logout_current, name='logout-current'),
    path('auth/logout-all/', logout_all, name='logout-all'),
    path('auth/logout-others/', logout_others, name='logout-others'),
    path('auth/sessions/', sessions, name='user-sessions'),
    path('auth/sessions/<uuid:public_id>/revoke/', revoke_session, name='revoke-user-session'),
    path('', include(router.urls)),
]
