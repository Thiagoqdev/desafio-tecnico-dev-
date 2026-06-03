'''URL routes for the accounts module.'''

from django.urls import path

from .views import AccountLoginView, AccountLogoutView, DashboardView, RegisterView


app_name = 'accounts'

urlpatterns = [
    path('entrar/', AccountLoginView.as_view(), name='login'),
    path('sair/', AccountLogoutView.as_view(), name='logout'),
    path('cadastro/', RegisterView.as_view(), name='register'),
    path('painel/', DashboardView.as_view(), name='dashboard'),
]
