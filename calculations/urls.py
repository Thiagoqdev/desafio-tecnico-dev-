'''URL routes for the calculations module.'''

from django.urls import path

from .views import CalculationCreateView, CalculationExportView, CalculationResultView


app_name = 'calculations'

urlpatterns = [
    path('novo/', CalculationCreateView.as_view(), name='create'),
    path('<int:pk>/', CalculationResultView.as_view(), name='result'),
    path('<int:pk>/exportar/', CalculationExportView.as_view(), name='export'),
]
