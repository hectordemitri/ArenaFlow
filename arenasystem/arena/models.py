from django.db import models
from django.conf import settings
from django.utils import timezone
import uuid
from common_validators import validate_image_upload


class Arena(models.Model):
    BUSINESS_TYPES = [('arena', 'Arena'), ('academia', 'Academia')]
    STATUS_CHOICES = [
        ('ativa', 'Ativa'),
        ('suspensa', 'Suspensa'),
        ('trial', 'Trial'),
        ('cancelada', 'Cancelada'),
    ]
    PLANO_CHOICES = [
        ('starter', 'Starter'),
        ('professional', 'Professional'),
        ('enterprise', 'Enterprise'),
    ]

    nome = models.CharField(max_length=120)
    tipo_negocio = models.CharField(max_length=20, choices=BUSINESS_TYPES, default='arena', db_index=True)
    slug = models.SlugField(unique=True)
    logo = models.ImageField(upload_to='arenas/logos/', null=True, blank=True, validators=[validate_image_upload])
    cor_primaria = models.CharField(max_length=20, default='#0F766E')
    cor_secundaria = models.CharField(max_length=20, default='#A3E635')
    cor_fundo = models.CharField(max_length=20, default='#ECFEFF')
    cor_texto = models.CharField(max_length=20, default='#071B26')
    dominio = models.CharField(max_length=120, blank=True)
    status_assinatura = models.CharField(max_length=20, choices=STATUS_CHOICES, default='trial')
    plano_contratado = models.CharField(max_length=30, choices=PLANO_CHOICES, default='starter')
    limite_alunos = models.PositiveIntegerField(default=150)
    limite_quadras = models.PositiveIntegerField(default=4)
    limite_admins = models.PositiveIntegerField(default=3)
    documento = models.CharField(max_length=30, blank=True)
    email_contato = models.EmailField(blank=True)
    telefone_contato = models.CharField(max_length=30, blank=True)
    endereco = models.CharField(max_length=200, blank=True)
    observacoes_comerciais = models.TextField(blank=True)
    checkin_minutes_before = models.PositiveSmallIntegerField(default=20)
    checkin_minutes_after = models.PositiveSmallIntegerField(default=10)
    delinquent_checkin_policy = models.CharField(
        max_length=20,
        choices=[('allow_with_warning', 'Permitir com alerta'), ('block', 'Bloquear')],
        default='allow_with_warning',
    )
    ativa = models.BooleanField(default=True)
    criada_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nome']

    def __str__(self):
        return self.nome

    @property
    def terminologia(self):
        if self.tipo_negocio == 'academia':
            return {
                'unidade_singular': 'unidade', 'unidade_plural': 'unidades',
                'pessoa_singular': 'membro', 'pessoa_plural': 'membros',
                'espaco_singular': 'espaço', 'espaco_plural': 'espaços',
            }
        return {
            'unidade_singular': 'arena', 'unidade_plural': 'arenas',
            'pessoa_singular': 'aluno', 'pessoa_plural': 'alunos',
            'espaco_singular': 'quadra', 'espaco_plural': 'quadras',
        }

    def get_operational_settings(self):
        settings, _ = ArenaOperationalSettings.objects.get_or_create(
            arena=self,
            defaults=ArenaOperationalSettings.defaults_for(self.tipo_negocio),
        )
        return settings


class ArenaOperationalSettings(models.Model):
    VALIDATION_MODES = [('reception', 'Validação pela recepção'), ('automatic', 'Automática')]

    arena = models.OneToOneField(Arena, on_delete=models.CASCADE, related_name='operational_settings')
    classes_enabled = models.BooleanField(default=True)
    open_access_enabled = models.BooleanField(default=False)
    reservations_enabled = models.BooleanField(default=True)
    store_enabled = models.BooleanField(default=True)
    open_access_validation = models.CharField(max_length=20, choices=VALIDATION_MODES, default='reception')
    open_access_pending_minutes = models.PositiveSmallIntegerField(default=10)
    updated_at = models.DateTimeField(auto_now=True)

    @staticmethod
    def defaults_for(business_type):
        if business_type == 'academia':
            return {
                'classes_enabled': True, 'open_access_enabled': True,
                'reservations_enabled': False, 'store_enabled': False,
                'open_access_validation': 'reception', 'open_access_pending_minutes': 10,
            }
        return {
            'classes_enabled': True, 'open_access_enabled': False,
            'reservations_enabled': True, 'store_enabled': True,
            'open_access_validation': 'reception', 'open_access_pending_minutes': 10,
        }

    @property
    def access_mode(self):
        if self.classes_enabled and self.open_access_enabled:
            return 'hybrid'
        if self.open_access_enabled:
            return 'open_access'
        return 'classes_only'

    def __str__(self):
        return f'Configuração operacional - {self.arena}'


class Quadra(models.Model):
    SPACE_TYPES = [
        ('court', 'Quadra'), ('gym_floor', 'Musculação'), ('martial_arts', 'Lutas'),
        ('spinning', 'Spinning'), ('pool', 'Piscina'), ('studio', 'Estúdio'),
        ('functional', 'Funcional'), ('other', 'Outro'),
    ]
    arena = models.ForeignKey(Arena, on_delete=models.CASCADE, related_name='quadras')
    nome = models.CharField(max_length=50)
    tipo_espaco = models.CharField(max_length=30, choices=SPACE_TYPES, default='court')
    tipo_areia = models.CharField(max_length=50, blank=True)
    ativa = models.BooleanField(default=True)
    observacoes = models.TextField(blank=True)

    def __str__(self):
        return self.nome


class Modalidade(models.Model):
    arena = models.ForeignKey(Arena, on_delete=models.CASCADE, related_name='modalidades')
    nome = models.CharField(max_length=80)
    cor = models.CharField(max_length=7, default='#0F766E')
    ativa = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['arena', 'nome'], name='unique_modalidade_name_per_arena'),
        ]
        ordering = ['nome']

    def __str__(self):
        return self.nome


class ArenaBusinessHours(models.Model):
    WEEKDAYS = [
        (0, 'Segunda'), (1, 'Terca'), (2, 'Quarta'), (3, 'Quinta'),
        (4, 'Sexta'), (5, 'Sabado'), (6, 'Domingo'),
    ]
    arena = models.ForeignKey(Arena, on_delete=models.CASCADE, related_name='business_hours')
    weekday = models.PositiveSmallIntegerField(choices=WEEKDAYS)
    opens_at = models.TimeField(null=True, blank=True)
    closes_at = models.TimeField(null=True, blank=True)
    closed = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['arena', 'weekday'], name='unique_business_hours_per_day'),
        ]
        ordering = ['weekday']


class ArenaOnboarding(models.Model):
    STEPS = [
        ('identification', 'Identificacao'), ('hours', 'Horarios'), ('courts', 'Quadras'),
        ('modalities', 'Modalidades'), ('professors', 'Professores'),
        ('students', 'Alunos'), ('review', 'Revisao'),
    ]
    arena = models.OneToOneField(Arena, on_delete=models.CASCADE, related_name='onboarding')
    current_step = models.CharField(max_length=30, choices=STEPS, default='identification')
    completed_steps = models.JSONField(default=list, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-started_at']


class Plano(models.Model):
    ACCESS_TYPES = [('classes_only', 'Aulas'), ('open_access', 'Acesso livre'), ('hybrid', 'Híbrido')]
    arena = models.ForeignKey(Arena, on_delete=models.CASCADE, related_name='planos')
    nome = models.CharField(max_length=100)
    valor = models.DecimalField(max_digits=8, decimal_places=2)
    frequencia_semanal = models.PositiveSmallIntegerField(help_text="Vezes por semana")
    tipo_acesso = models.CharField(max_length=20, choices=ACCESS_TYPES, default='classes_only')
    limite_acessos_dia = models.PositiveIntegerField(null=True, blank=True)
    limite_acessos_semana = models.PositiveIntegerField(null=True, blank=True)
    limite_acessos_mes = models.PositiveIntegerField(null=True, blank=True)
    descricao = models.TextField(blank=True)
    ativo = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.nome} - R$ {self.valor}"

    @property
    def permite_acesso_livre(self):
        return self.tipo_acesso in {'open_access', 'hybrid'}


class PlanAccessWindow(models.Model):
    WEEKDAYS = ArenaBusinessHours.WEEKDAYS
    plano = models.ForeignKey(Plano, on_delete=models.CASCADE, related_name='janelas_acesso')
    weekday = models.PositiveSmallIntegerField(choices=WEEKDAYS)
    starts_at = models.TimeField()
    ends_at = models.TimeField()

    class Meta:
        ordering = ['weekday', 'starts_at']
        constraints = [
            models.CheckConstraint(condition=models.Q(starts_at__lt=models.F('ends_at')), name='plan_access_start_before_end'),
            models.UniqueConstraint(fields=['plano', 'weekday', 'starts_at', 'ends_at'], name='unique_plan_access_window'),
        ]

    def __str__(self):
        return f'{self.plano} - {self.get_weekday_display()} {self.starts_at:%H:%M}'


class Matricula(models.Model):
    arena = models.ForeignKey(Arena, on_delete=models.CASCADE, related_name='matriculas')
    aluno = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        limit_choices_to={'tipo': 'aluno'}
    )
    plano = models.ForeignKey(Plano, on_delete=models.PROTECT)
    data_inicio = models.DateField()
    data_fim = models.DateField(null=True, blank=True)
    ativa = models.BooleanField(default=True)

    @property
    def dia_vencimento(self):
        return self.data_inicio.day

    def __str__(self):
        return f"{self.aluno} - {self.plano.nome}"


class AccessVisit(models.Model):
    STATUS = [
        ('pending', 'Aguardando validação'), ('confirmed', 'Confirmada'),
        ('rejected', 'Rejeitada'), ('checked_out', 'Encerrada'), ('expired', 'Expirada'),
    ]
    ORIGINS = [
        ('mobile', 'Aplicativo mobile'), ('manual', 'Manual'), ('reception', 'Recepção'),
        ('turnstile', 'Catraca'), ('integration', 'Integração'),
    ]
    CHECKOUT_ORIGINS = [
        ('member', 'Membro'), ('reception', 'Recepção'), ('automatic', 'Automático'),
        ('turnstile', 'Catraca'), ('integration', 'Integração'),
    ]

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    arena = models.ForeignKey(Arena, on_delete=models.CASCADE, related_name='access_visits')
    aluno = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='access_visits')
    matricula = models.ForeignKey(Matricula, on_delete=models.PROTECT, related_name='access_visits')
    plano = models.ForeignKey(Plano, on_delete=models.PROTECT, related_name='access_visits')
    status = models.CharField(max_length=20, choices=STATUS, default='pending', db_index=True)
    origem = models.CharField(max_length=20, choices=ORIGINS, default='mobile')
    solicitado_em = models.DateTimeField(default=timezone.now, db_index=True)
    expira_em = models.DateTimeField(null=True, blank=True)
    validado_em = models.DateTimeField(null=True, blank=True)
    entrada_em = models.DateTimeField(null=True, blank=True, db_index=True)
    saida_em = models.DateTimeField(null=True, blank=True)
    validado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='access_visits_validated',
    )
    checkout_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='access_visits_checked_out',
    )
    checkout_origem = models.CharField(max_length=20, choices=CHECKOUT_ORIGINS, blank=True)
    motivo = models.CharField(max_length=300, blank=True)
    inadimplente_no_momento = models.BooleanField(default=False)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-solicitado_em']
        constraints = [
            models.UniqueConstraint(
                fields=['arena', 'aluno'],
                condition=models.Q(status__in=['pending', 'confirmed']),
                name='unique_open_access_visit_per_member',
            ),
        ]
        indexes = [models.Index(fields=['arena', 'status', 'solicitado_em'])]

    def __str__(self):
        return f'{self.aluno} - {self.arena} - {self.status}'


class AccessPoint(models.Model):
    DIRECTIONS = [('entry', 'Entrada'), ('exit', 'Saída'), ('bidirectional', 'Bidirecional')]
    arena = models.ForeignKey(Arena, on_delete=models.CASCADE, related_name='access_points')
    nome = models.CharField(max_length=100)
    direction = models.CharField(max_length=20, choices=DIRECTIONS, default='entry')
    provider_key = models.SlugField(max_length=50, default='manual')
    external_id = models.CharField(max_length=120, blank=True)
    credential_reference = models.CharField(max_length=160, blank=True)
    ativa = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['arena', 'nome'], name='unique_access_point_name_per_arena')]


class AccessIntegrationEvent(models.Model):
    EVENT_TYPES = [('visit.confirmed', 'Visita confirmada'), ('visit.rejected', 'Visita rejeitada')]
    STATUSES = [('pending', 'Pendente'), ('processed', 'Processado'), ('failed', 'Falhou'), ('ignored', 'Ignorado')]
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    visit = models.ForeignKey(AccessVisit, on_delete=models.CASCADE, related_name='integration_events')
    event_type = models.CharField(max_length=40, choices=EVENT_TYPES)
    idempotency_key = models.CharField(max_length=160, unique=True)
    status = models.CharField(max_length=20, choices=STATUSES, default='pending', db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)


class Mensalidade(models.Model):
    STATUS = [
        ('pendente', 'Pendente'),
        ('pago', 'Pago'),
        ('atrasado', 'Atrasado'),
        ('cancelada', 'Cancelada'),
        ('estornada', 'Estornada'),
        ('contestada', 'Contestada'),
    ]
    arena = models.ForeignKey(
        Arena,
        on_delete=models.CASCADE,
        related_name='mensalidades',
    )
    matricula = models.ForeignKey(
        Matricula,
        on_delete=models.CASCADE,
        related_name='mensalidades'
    )
    mes_referencia = models.DateField(help_text="Use o dia 01 do mês")
    valor = models.DecimalField(max_digits=8, decimal_places=2)
    vencimento = models.DateField()
    data_pagamento = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS, default='pendente')
    mercado_pago_preference_id = models.CharField(max_length=120, blank=True)
    mercado_pago_payment_id = models.CharField(max_length=120, blank=True)
    mercado_pago_checkout_url = models.URLField(blank=True)
    checkout_expires_at = models.DateTimeField(null=True, blank=True)
    external_reference = models.CharField(max_length=120, blank=True, db_index=True)
    payment_provider = models.CharField(max_length=40, blank=True)
    external_status = models.CharField(max_length=80, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=120, blank=True, db_index=True)
    payment_checked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-mes_referencia']
        unique_together = ('matricula', 'mes_referencia')

    def __str__(self):
        return f"{self.matricula.aluno} - {self.mes_referencia.strftime('%m/%Y')} - {self.get_status_display()}"

    def save(self, *args, **kwargs):
        if self.matricula_id and not self.arena_id:
            self.arena = self.matricula.arena
        super().save(*args, **kwargs)

    @property
    def data_atraso(self):
        return self.vencimento + timezone.timedelta(days=5)

    def atualizar_status_atraso(self, hoje=None, salvar=True):
        hoje = hoje or timezone.localdate()
        if self.status == 'pendente' and hoje >= self.data_atraso:
            self.status = 'atrasado'
            if salvar:
                self.save(update_fields=['status'])
        return self.status


class PaymentWebhookEvent(models.Model):
    arena = models.ForeignKey(Arena, on_delete=models.CASCADE, related_name='payment_webhook_events')
    provider = models.CharField(max_length=40)
    external_id = models.CharField(max_length=160)
    event_type = models.CharField(max_length=80, blank=True)
    idempotency_key = models.CharField(max_length=160, blank=True, db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    processed = models.BooleanField(default=False)
    processed_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('provider', 'external_id')
        ordering = ['-received_at']

    def __str__(self):
        return f'{self.provider}:{self.external_id}'


class PaymentAccount(models.Model):
    arena = models.OneToOneField(Arena, on_delete=models.CASCADE, related_name='payment_account')
    collector_id = models.CharField(max_length=80, unique=True)
    access_token_encrypted = models.TextField()
    refresh_token_encrypted = models.TextField()
    expires_at = models.DateTimeField()
    connected_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    connected_at = models.DateTimeField(auto_now_add=True)
    disconnected_at = models.DateTimeField(null=True, blank=True)


class PaymentOAuthAttempt(models.Model):
    arena = models.ForeignKey(Arena, on_delete=models.CASCADE)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    state_hash = models.CharField(max_length=64, unique=True)
    verifier_encrypted = models.TextField()
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)


class StudentPayment(models.Model):
    mensalidade = models.ForeignKey(Mensalidade, on_delete=models.PROTECT, related_name='payments')
    provider_id = models.CharField(max_length=100, unique=True)
    status = models.CharField(max_length=40)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    refunded_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    provider_updated_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)
