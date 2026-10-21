from django.contrib.auth.models import AbstractUser
from django.db import models
import uuid
from common_validators import validate_image_upload

class Usuario(AbstractUser):
    TIPO_CHOICES = [
        ('aluno', 'Aluno'),
        ('professor', 'Professor'),
        ('admin', 'Administrador'),
        ('admin_arena', 'Administrador da arena'),
        ('funcionario', 'Funcionario'),
        ('superadmin_saas', 'Superadmin SaaS'),
    ]
    PAPEL_CHOICES = [
        ('superadmin_saas', 'Superadmin SaaS'),
        ('dono', 'Dono'),
        ('administrador', 'Administrador'),
        ('recepcao', 'Recepcao'),
        ('financeiro', 'Financeiro'),
        ('professor', 'Professor'),
        ('estoque', 'Estoque'),
        ('aluno', 'Aluno'),
    ]
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='aluno')
    papel = models.CharField(max_length=20, choices=PAPEL_CHOICES, blank=True)
    telefone = models.CharField(max_length=20, blank=True)
    data_nascimento = models.DateField(null=True, blank=True)
    foto = models.ImageField(upload_to='perfis/', null=True, blank=True, validators=[validate_image_upload])
    cpf = models.CharField(max_length=14, blank=True)
    arena = models.ForeignKey(
        'arena.Arena',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='usuarios',
    )
    token_version = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.get_tipo_display()})"

    @property
    def papel_efetivo(self):
        if self.is_superuser:
            return 'superadmin_saas'
        if self.papel:
            return self.papel
        if self.tipo in ['admin', 'admin_arena'] or self.is_staff:
            return 'dono'
        if self.tipo == 'professor':
            return 'professor'
        if self.tipo == 'funcionario':
            return 'recepcao'
        if self.tipo == 'superadmin_saas':
            return 'superadmin_saas'
        return 'aluno'


class UserPermissionOverride(models.Model):
    EFFECTS = [('allow', 'Permitir'), ('deny', 'Negar')]
    user = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='permission_overrides')
    permission = models.CharField(max_length=100)
    effect = models.CharField(max_length=10, choices=EFFECTS)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'permission'], name='unique_user_permission_override'),
        ]
        ordering = ['permission']


class UserMFA(models.Model):
    user = models.OneToOneField(Usuario, on_delete=models.CASCADE, related_name='mfa')
    secret_encrypted = models.TextField()
    enabled = models.BooleanField(default=False)
    last_step = models.BigIntegerField(default=-1)
    recovery_hashes = models.JSONField(default=list)
    setup_expires_at = models.DateTimeField(null=True, blank=True)


class UserInvitation(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    arena = models.ForeignKey('arena.Arena', on_delete=models.CASCADE, related_name='user_invitations')
    email = models.EmailField()
    role = models.CharField(max_length=20, choices=Usuario.PAPEL_CHOICES)
    token_hash = models.CharField(max_length=64)
    invited_by = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, null=True, related_name='sent_invitations',
    )
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    canceled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['arena', 'email'])]


class UserSession(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='active_sessions')
    session_id = models.UUIDField(unique=True)
    refresh_jti = models.CharField(max_length=255, blank=True, db_index=True)
    user_agent = models.CharField(max_length=500, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-last_seen_at']


class PasswordResetRequest(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='password_reset_requests')
    token_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class EmailChangeRequest(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='email_change_requests')
    new_email = models.EmailField()
    token_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['user', 'new_email'])]


class NotificationPreference(models.Model):
    user = models.OneToOneField(Usuario, on_delete=models.CASCADE, related_name='notification_preferences')
    app_classes = models.BooleanField(default=True)
    app_checkins = models.BooleanField(default=True)
    app_financial = models.BooleanField(default=True)
    app_reservations = models.BooleanField(default=True)
    email_classes = models.BooleanField(default=True)
    email_checkins = models.BooleanField(default=True)
    email_financial = models.BooleanField(default=True)
    email_reservations = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)
