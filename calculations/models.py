'''Models for the calculations module.

Calculation  — top-level entity for one correction calculation.
Installment — each parcel within a Calculation (single or multiple).
CalculationStep — one audit-trail entry (memory of calculation).

All models derive from `core.models.TimeStampedModel`.
'''

from django.conf import settings
from django.db import models

from core.models import TimeStampedModel


class Calculation(TimeStampedModel):
    '''Top-level entity holding the parameters and result of one correction.'''

    INDEX_MANUAL = 'manual'
    INDEX_AUTO = 'auto'
    INDEX_CHOICES = [
        (INDEX_MANUAL, 'Manual'),
        (INDEX_AUTO, 'Automático'),
    ]

    INSTALLMENT_SINGLE = 'single'
    INSTALLMENT_MULTIPLE = 'multiple'
    INSTALLMENT_CHOICES = [
        (INSTALLMENT_SINGLE, 'Parcela única'),
        (INSTALLMENT_MULTIPLE, 'Múltiplas parcelas'),
    ]

    STATUS_DRAFT = 'draft'
    STATUS_COMPUTED = 'computed'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Rascunho'),
        (STATUS_COMPUTED, 'Calculado'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='calculations',
    )
    base_value = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        help_text='Valor base da primeira parcela (ou da única).',
    )
    start_term = models.DateField(help_text='Termo inicial do cálculo.')
    end_term = models.DateField(help_text='Termo final do cálculo.')
    index_selection_mode = models.CharField(
        max_length=8,
        choices=INDEX_CHOICES,
        default=INDEX_AUTO,
    )
    manual_index = models.ForeignKey(
        'indices.IndexType',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='manual_calculations',
    )
    interest_enabled = models.BooleanField(
        default=True,
        help_text='Se verdadeiro, juros de mora são aplicados.',
    )
    attorney_fee_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text='Percentual de honorários (ex.: 10.00 = 10%).',
    )
    installment_mode = models.CharField(
        max_length=10,
        choices=INSTALLMENT_CHOICES,
        default=INSTALLMENT_SINGLE,
    )
    rpv_issued = models.BooleanField(
        default=False,
        help_text='Indica se o RPV/Precatório já foi emitido.',
    )
    rpv_issue_date = models.DateField(
        null=True,
        blank=True,
        help_text='Data de emissão do RPV/Precatório.',
    )
    result_total = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
    )

    class Meta:
        ordering = ('-created_at',)
        verbose_name = 'Cálculo'
        verbose_name_plural = 'Cálculos'

    def __str__(self):
        return f'Cálculo #{self.pk} ({self.get_status_display()})'


class Installment(TimeStampedModel):
    '''One parcel within a Calculation.

    `same_as_first` means the installment shares the value of the first
    parcel. When False the `value` field holds its own amount.
    '''

    calculation = models.ForeignKey(
        Calculation,
        on_delete=models.CASCADE,
        related_name='installments',
    )
    order = models.PositiveSmallIntegerField()
    value = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        help_text='Valor da parcela (ignorado se same_as_first for True).',
    )
    same_as_first = models.BooleanField(default=True)

    class Meta:
        ordering = ('calculation', 'order')
        constraints = [
            models.UniqueConstraint(
                fields=('calculation', 'order'),
                name='installment_unique_calculation_order',
            ),
        ]
        verbose_name = 'Parcela'
        verbose_name_plural = 'Parcelas'

    def __str__(self):
        return f'Parcela {self.order} de Cálculo #{self.calculation_id}'


class CalculationStep(TimeStampedModel):
    '''Audit trail: explains each step of the deterministic engine.

    Every numeric result in a Calculation must be traceable back to one
    or more CalculationStep rows (RNF14).
    '''

    calculation = models.ForeignKey(
        Calculation,
        on_delete=models.CASCADE,
        related_name='steps',
    )
    installment_order = models.PositiveSmallIntegerField(default=1)
    step_order = models.PositiveSmallIntegerField()
    description = models.TextField()
    period_start = models.DateField()
    period_end = models.DateField()
    applied_index = models.CharField(
        max_length=32,
        blank=True,
        help_text='Código do índice aplicado (ex.: INPC, SELIC).',
    )
    factor = models.DecimalField(
        max_digits=18,
        decimal_places=8,
        help_text='Fator acumulado do período.',
    )
    interest_amount = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=0,
    )
    base_value = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        help_text='Valor-base deste passo (após etapa anterior).',
    )
    subtotal = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        help_text='Resultado parcial após este passo.',
    )

    class Meta:
        ordering = ('calculation', 'installment_order', 'step_order')
        verbose_name = 'Etapa do cálculo'
        verbose_name_plural = 'Etapas do cálculo'

    def __str__(self):
        return f'Cálculo #{self.calculation_id} Etapa {self.step_order}: {self.description[:60]}'
