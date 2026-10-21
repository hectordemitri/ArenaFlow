from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
)
from dashboard.urls import api_urlpatterns as dashboard_api_urls
from usuarios.auth_views import ThrottledTokenObtainPairView, VersionedTokenRefreshView
from arenasystem.health_views import health, health_components, readiness

urlpatterns = [
    path('api/health/', health, name='health'),
    path('api/health/ready/', readiness, name='readiness'),
    path('api/health/components/', health_components, name='health-components'),
    # Painel admin
    path('admin/', admin.site.urls),

    # ───── API REST ─────
    # Autenticação
    path('api/auth/login/', ThrottledTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/auth/refresh/', VersionedTokenRefreshView.as_view(), name='token_refresh'),

    # Endpoints de cada app
    path('api/', include('usuarios.api_urls')),
    path('api/', include('arena.api_urls')),
    path('api/', include('aulas.api_urls')),
    path('api/', include('loja.api_urls')),
    path('api/', include('notificacoes.api_urls')),
    path('api/', include('manutencao.api_urls')),
    path('api/', include('gestao.api_urls')),
    path('api/', include('saas_billing.api_urls')),
    path('api/', include('saas_ops.api_urls')),
    path('api/dashboard/', include((dashboard_api_urls, 'dashboard_api'))),

    # Documentação
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
