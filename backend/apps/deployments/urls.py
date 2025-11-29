from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import DeploymentViewSet, quick_deploy

router = DefaultRouter()
router.register(r'', DeploymentViewSet, basename='deployment')

urlpatterns = [
    path('quick-deploy/', quick_deploy, name='quick-deploy'),
    path('', include(router.urls)),
]

