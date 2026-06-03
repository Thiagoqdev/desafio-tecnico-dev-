'''Shared abstract models for the Juriscalc project.'''

from django.db import models


class TimeStampedModel(models.Model):
    '''Abstract base model providing creation and update timestamps.'''

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
