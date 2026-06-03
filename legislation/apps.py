'''App configuration for the legislation module (Sprint 3).'''

from django.apps import AppConfig


class LegislationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'legislation'
    verbose_name = 'Tabela de vigências'
