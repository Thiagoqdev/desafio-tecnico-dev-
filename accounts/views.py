'''Class-based views for the accounts module.'''

from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView

from .forms import RegistrationForm, StyledAuthenticationForm


class AccountLoginView(LoginView):
    '''Sign in with Django's native authentication backend.'''

    template_name = 'accounts/login.html'
    authentication_form = StyledAuthenticationForm
    redirect_authenticated_user = True


class AccountLogoutView(LogoutView):
    '''Sign out and redirect to the login screen.'''

    next_page = reverse_lazy('accounts:login')


class RegisterView(CreateView):
    '''Self-service account creation that signs the new user in.'''

    template_name = 'accounts/register.html'
    form_class = RegistrationForm
    success_url = reverse_lazy('accounts:dashboard')

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return self.handle_already_authenticated()
        return super().dispatch(request, *args, **kwargs)

    def handle_already_authenticated(self):
        from django.shortcuts import redirect
        return redirect('accounts:dashboard')

    def form_valid(self, form):
        response = super().form_valid(form)
        login(self.request, self.object)
        return response


class DashboardView(LoginRequiredMixin, ListView):
    '''Painel of the user's calculations.'''

    template_name = 'accounts/dashboard.html'
    context_object_name = 'calculations'
    paginate_by = 10

    def get_queryset(self):
        from calculations.models import Calculation
        return Calculation.objects.filter(user=self.request.user).order_by('-created_at')
