'''Models for the indices module.

`IndexType` describes an economic series (INPC, IPCA-E, IGP-M, SELIC, CJF
table). `IndexValue` is the local cache of monthly values fetched from the
upstream sources. The combination (index_type, reference_date) is unique.
'''

from django.db import models

from core.models import TimeStampedModel


class IndexType(TimeStampedModel):
    '''Identifies an economic series and where it is sourced from.'''

    SOURCE_IBGE = 'IBGE'
    SOURCE_BCB = 'BCB'
    SOURCE_CJF = 'CJF'
    SOURCE_CHOICES = [
        (SOURCE_IBGE, 'IBGE'),
        (SOURCE_BCB, 'Banco Central'),
        (SOURCE_CJF, 'Justiça Federal'),
    ]

    name = models.CharField(max_length=64, unique=True)
    code = models.CharField(max_length=32, unique=True)
    source = models.CharField(max_length=8, choices=SOURCE_CHOICES)
    sgs_series_id = models.PositiveIntegerField(null=True, blank=True)
    ibge_aggregate = models.CharField(max_length=32, blank=True)
    ibge_variable = models.CharField(max_length=32, blank=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ('code',)
        verbose_name = 'Tipo de índice'
        verbose_name_plural = 'Tipos de índice'

    def __str__(self):
        return f'{self.code} ({self.get_source_display()})'


class IndexValue(TimeStampedModel):
    '''Local cache of a single monthly value for an `IndexType`.'''

    index_type = models.ForeignKey(
        IndexType,
        on_delete=models.CASCADE,
        related_name='values',
    )
    reference_date = models.DateField(
        help_text='Use o primeiro dia do mês de referência.',
    )
    value = models.DecimalField(max_digits=18, decimal_places=8)
    accumulated_factor = models.DecimalField(
        max_digits=18,
        decimal_places=8,
        null=True,
        blank=True,
    )
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('index_type__code', 'reference_date')
        constraints = [
            models.UniqueConstraint(
                fields=('index_type', 'reference_date'),
                name='indexvalue_unique_type_date',
            ),
        ]
        verbose_name = 'Valor do índice'
        verbose_name_plural = 'Valores dos índices'

    def __str__(self):
        return f'{self.index_type.code} {self.reference_date:%Y-%m}: {self.value}'
