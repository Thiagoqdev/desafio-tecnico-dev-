'''App configuration for the interpreter module (Sprint 6).

The interpreter app is forbidden from importing `calculations.services` to
preserve the architectural separation between interpretation (LLM) and
calculation (back-end).
'''

from django.apps import AppConfig


class InterpreterConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'interpreter'
    verbose_name = 'Intérprete de sentenças'
