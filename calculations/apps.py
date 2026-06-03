'''App configuration for the calculations module.'''

from django.apps import AppConfig


class CalculationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'calculations'
    verbose_name = 'Cálculos'

    def ready(self):
        import calculations.signals  # noqa: F401
