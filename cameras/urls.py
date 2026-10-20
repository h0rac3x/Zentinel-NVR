from django.urls import path
from . import views

urlpatterns = [
    # Auth Views
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('api/me/', views.current_user_api, name='current_user_api'),

    # Core NVR Views
    path('', views.dashboard_view, name='dashboard'),
    path('api/cameras/', views.camera_list_create, name='camera_list_create'),
    path('api/cameras/<int:pk>/', views.camera_detail_update_delete, name='camera_detail_update_delete'),
    path('api/cameras/probe/', views.camera_probe_api, name='camera_probe_api'),
]