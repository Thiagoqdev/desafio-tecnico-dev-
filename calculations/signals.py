'''Signals for the calculations module.

Handles cascade cleanup when a Calculation is deleted.
'''

from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Calculation


@receiver(post_delete, sender=Calculation)
def cleanup_calculation_orphans(sender, instance, **kwargs):
    '''Ensure no orphaned steps remain after a calculation is deleted.

    Django's CASCADE on the FK already handles this, but the signal
    serves as documentation for the cleanup contract and a hook for
    future side-effects (e.g., deleting related SentenceInterpretation
    records when they are linked).
    '''
    pass
