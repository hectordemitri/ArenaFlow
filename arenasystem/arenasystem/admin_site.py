from django import forms
import hashlib
from django.conf import settings
from django.core.cache import cache
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.admin.sites import AdminSite
from rest_framework.exceptions import AuthenticationFailed


class AdminMFAForm(AdminAuthenticationForm):
    otp_code = forms.CharField(label='Codigo do autenticador', required=False)

    def clean(self):
        identity = f"{self.request.META.get('REMOTE_ADDR', '')}:{self.data.get('username', '').lower()}"
        key = 'admin-login:' + hashlib.sha256(identity.encode()).hexdigest()
        if cache.get(key, 0) >= 20:
            raise forms.ValidationError('Muitas tentativas. Aguarde cinco minutos.')
        try:
            data = super().clean()
        except forms.ValidationError:
            if not cache.add(key, 1, timeout=300):
                cache.incr(key)
            raise
        cache.delete(key)
        return data

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if user.papel_efetivo != 'superadmin_saas':
            raise forms.ValidationError('Use o painel da sua arena no aplicativo.')
        from usuarios.models import UserMFA
        enabled = UserMFA.objects.filter(user=user, enabled=True).exists()
        if settings.SUPERADMIN_REQUIRE_MFA and not enabled:
            raise forms.ValidationError('Configure duas etapas pelo aplicativo antes de acessar este painel.')
        if enabled:
            from usuarios.mfa import verify_mfa
            try:
                verify_mfa(user, self.cleaned_data.get('otp_code', ''))
            except AuthenticationFailed as exc:
                raise forms.ValidationError('Codigo invalido ou ja utilizado.') from exc
            self.request.session['admin_mfa_verified'] = True


class ArenaFlowAdminSite(AdminSite):
    login_form = AdminMFAForm
    login_template = 'admin/secure_login.html'

    def has_permission(self, request):
        if not super().has_permission(request) or request.user.papel_efetivo != 'superadmin_saas':
            return False
        from usuarios.models import UserMFA
        enabled = UserMFA.objects.filter(user=request.user, enabled=True).exists()
        if settings.SUPERADMIN_REQUIRE_MFA and not enabled:
            return False
        return not enabled or bool(request.session.get('admin_mfa_verified'))


