'''App configuration for the core module.

The `core` package doubles as the Django project (settings/urls) and as a
Django app that ships shared abstractions such as `TimeStampedModel`.
'''

from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'
    verbose_name = 'Núcleo'
