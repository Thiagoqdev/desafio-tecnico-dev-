'''URL routes for the indices module.'''

from django.urls import path

from .views import ImportIndicesView


app_name = 'indices'

urlpatterns = [
    path('importar/', ImportIndicesView.as_view(), name='import'),
]
