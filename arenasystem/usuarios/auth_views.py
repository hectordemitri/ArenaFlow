from rest_framework import serializers
import uuid
from django.conf import settings

from rest_framework_simplejwt.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .throttles import LoginRateThrottle
from .models import Usuario


class LoginTokenObtainPairSerializer(TokenObtainPairSerializer):
    otp_code = serializers.CharField(required=False, allow_blank=True, write_only=True)
    username = serializers.CharField(required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    login = serializers.CharField(required=False, allow_blank=True)

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['token_version'] = user.token_version
        token['session_id'] = str(uuid.uuid4())
        return token

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields[self.username_field].required = False
        self.fields[self.username_field].allow_blank = True

    def validate(self, attrs):
        login = (
            attrs.get(self.username_field)
            or attrs.get('username')
            or attrs.get('email')
            or attrs.get('login')
            or ''
        ).strip()

        if login:
            usuario = Usuario.objects.filter(username__iexact=login).first()
            if not usuario and '@' in login:
                usuario = Usuario.objects.filter(email__iexact=login).first()
            if usuario:
                attrs[self.username_field] = usuario.get_username()

        if not login:
            raise serializers.ValidationError({'username': 'Informe seu usuario ou email.'})
        data = super().validate(attrs)
        from .models import UserMFA
        enabled = UserMFA.objects.filter(user=self.user, enabled=True).exists()
        if enabled:
            if not attrs.get('otp_code'):
                raise AuthenticationFailed({'detail': 'Informe o codigo do autenticador.', 'code': 'mfa_required'})
            from .mfa import verify_mfa
            verify_mfa(self.user, attrs['otp_code'])
        refresh = RefreshToken(data['refresh'])
        refresh['mfa_verified'] = enabled
        data['access'], data['refresh'] = str(refresh.access_token), str(refresh)
        data['mfa_setup_required'] = (settings.SUPERADMIN_REQUIRE_MFA and self.user.papel_efetivo == 'superadmin_saas' and not enabled)
        request = self.context.get('request')
        forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '') if request else ''
        ip_address = forwarded.split(',')[0].strip() if forwarded else request.META.get('REMOTE_ADDR') if request else None
        from .models import UserSession
        UserSession.objects.create(
            user=self.user,
            session_id=refresh['session_id'],
            refresh_jti=refresh['jti'],
            user_agent=(request.headers.get('User-Agent', '')[:500] if request else ''),
            ip_address=ip_address,
        )
        data['usuario'] = {
            'id': self.user.id,
            'username': self.user.username,
            'nome': self.user.get_full_name() or self.user.username,
            'tipo': self.user.tipo,
            'papel': self.user.papel_efetivo,
            'arena': self.user.arena.nome if self.user.arena else None,
        }
        return data


class ThrottledTokenObtainPairView(TokenObtainPairView):
    serializer_class = LoginTokenObtainPairSerializer
    throttle_classes = [LoginRateThrottle]


class VersionedTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        refresh = RefreshToken(attrs['refresh'])
        from .models import UserSession, Usuario
        user = Usuario.objects.filter(id=refresh.get('user_id'), is_active=True).first()
        if not user or refresh.get('token_version', 0) != user.token_version:
            raise AuthenticationFailed('Sessao revogada.')
        session_id = refresh.get('session_id')
        if session_id and not UserSession.objects.filter(user=user, session_id=session_id, revoked_at__isnull=True).exists():
            raise AuthenticationFailed('Sessao revogada.')
        data = super().validate(attrs)
        if data.get('refresh') and session_id:
            rotated = RefreshToken(data['refresh'])
            rotated['token_version'] = user.token_version
            rotated['session_id'] = session_id
            data['refresh'] = str(rotated)
            UserSession.objects.filter(user=user, session_id=session_id).update(refresh_jti=rotated['jti'])
        return data


class VersionedTokenRefreshView(TokenRefreshView):
    serializer_class = VersionedTokenRefreshSerializer
