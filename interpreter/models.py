'''Models for the interpreter module.

`SentenceInterpretation` stores only the extraction result — never a
calculation result. This enforces the architectural separation:
LLM extracts, back-end calculates (RNF13).
'''

from django.conf import settings
from django.db import models

from core.models import TimeStampedModel


class SentenceInterpretation(TimeStampedModel):
    '''Stores a sentence text and the structured data extracted by the LLM.'''

    STATUS_EXTRACTED = 'extracted'
    STATUS_REVIEWED = 'reviewed'
    STATUS_DISCARDED = 'discarded'
    STATUS_CHOICES = [
        (STATUS_EXTRACTED, 'Extraído'),
        (STATUS_REVIEWED, 'Revisado'),
        (STATUS_DISCARDED, 'Descartado'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='interpretations',
    )
    source_text = models.TextField(help_text='Texto bruto da sentença colado pelo usuário.')
    extracted_payload = models.JSONField(
        default=dict,
        help_text='DTO do formulário extraído pela LLM (nunca resultado de cálculo).',
    )
    model_used = models.CharField(
        max_length=128,
        blank=True,
        help_text='Identificador do modelo de LLM utilizado.',
    )
    confidence_notes = models.TextField(
        blank=True,
        help_text='Anotações sobre o grau de confiança na extração.',
    )
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_EXTRACTED,
    )

    class Meta:
        ordering = ('-created_at',)
        verbose_name = 'Interpretação de sentença'
        verbose_name_plural = 'Interpretações de sentenças'

    def __str__(self):
        return f'Interpretação #{self.pk} ({self.get_status_display()})'
