from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import SubscriptionViewSet

router = DefaultRouter()
router.register(r'', SubscriptionViewSet, basename='subscription')

urlpatterns = [
    path('', include(router.urls)),
    # 支持 UUID 和字符串 token
    path('<str:pk>/', SubscriptionViewSet.as_view({'get': 'retrieve'}), name='subscription-detail'),
]

