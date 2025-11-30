from django.urls import path
from . import views

urlpatterns = [
    path('csrf/', views.csrf_token, name='csrf-token'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('user/', views.user_info, name='user-info'),
    path('user/update/', views.update_user, name='user-update'),
    path('user/change-password/', views.change_password, name='user-change-password'),
]

