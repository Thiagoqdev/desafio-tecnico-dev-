'''Root URL configuration for the Juriscalc project.'''

from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', RedirectView.as_view(pattern_name='accounts:dashboard', permanent=False)),
    path('contas/', include('accounts.urls', namespace='accounts')),
    path('calculos/', include('calculations.urls', namespace='calculations')),
    path('interpretar/', include('interpreter.urls', namespace='interpreter')),
    path('indices/', include('indices.urls', namespace='indices')),
]
