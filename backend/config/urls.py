"""
URL configuration for MyX project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('apps.health.urls')),  # Health check
    path('api/auth/', include('apps.accounts.urls')),
    path('api/servers/', include('apps.servers.urls')),
    path('api/proxies/', include('apps.proxies.urls')),
    path('api/subscriptions/', include('apps.subscriptions.urls')),
    path('api/deployments/', include('apps.deployments.urls')),
    path('api/agents/', include('apps.agents.urls')),
    path('api/settings/', include('apps.settings.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

