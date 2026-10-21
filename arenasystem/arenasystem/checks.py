from django.conf import settings
from django.core.checks import Error, Tags, Warning, register


@register(Tags.security, deploy=True)
def production_readiness(app_configs, **kwargs):
    if settings.DEBUG:
        return []
    errors = []
    required = [
        (bool(settings.APP_ENCRYPTION_KEYS), 'Configure APP_ENCRYPTION_KEYS.', 'arenaflow.E001'),
        (bool(settings.CACHE_REDIS_URL), 'Configure cache Redis compartilhado para os limites de acesso.', 'arenaflow.E002'),
        (bool(settings.MEDIA_STORAGE_BUCKET), 'Configure armazenamento persistente para uploads.', 'arenaflow.E003'),
        (not settings.DEMO_MODE, 'Desative DEMO_MODE para operar com dados reais.', 'arenaflow.E004'),
        (settings.SUPERADMIN_REQUIRE_MFA, 'Exija duas etapas para superadmin em producao.', 'arenaflow.E005'),
    ]
    for valid, message, code in required:
        if not valid:
            errors.append(Error(message, id=code))
    if settings.APP_ENCRYPTION_KEYS:
        from .secrets import secret_cipher
        try:
            secret_cipher()
        except (ValueError, TypeError):
            errors.append(Error('APP_ENCRYPTION_KEYS contem uma chave Fernet invalida.', id='arenaflow.E006'))
    if not settings.EMAIL_HOST or settings.EMAIL_BACKEND.endswith('console.EmailBackend'):
        errors.append(Warning('Configure e valide o envio de emails transacionais.', id='arenaflow.W001'))
    return errors
