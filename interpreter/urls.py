'''URL routes for the interpreter module.'''

from django.urls import path

from .views import ImportSentenceView


app_name = 'interpreter'

urlpatterns = [
    path('importar/', ImportSentenceView.as_view(), name='import'),
]
