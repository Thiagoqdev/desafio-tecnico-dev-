'''Models for the legislation module.

These three tables materialize Section 6 of the PRD as parametrizable
data. The motor de cálculo (Sprint 4) reads from them and must never
hardcode the legal periods.

Open-ended vigência is expressed with `end_date IS NULL`. The interval
covered by a row is `[start_date, end_date]` (inclusive on both ends).
'''

from django.db import models

from core.models import TimeStampedModel


class CorrectionRule(TimeStampedModel):
    '''Which monetary correction index applies in a given period.'''

    MODE_SINGLE_INDEX = 'single_index'
    MODE_IPCA_PLUS_CAPPED = 'ipca_plus_capped'
    MODE_CHOICES = [
        (MODE_SINGLE_INDEX, 'Índice único'),
        (MODE_IPCA_PLUS_CAPPED, 'IPCA + taxa, limitado à SELIC'),
    ]

    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    index_type = models.ForeignKey(
        'indices.IndexType',
        on_delete=models.PROTECT,
        related_name='correction_rules',
    )
    mode = models.CharField(max_length=32, choices=MODE_CHOICES, default=MODE_SINGLE_INDEX)
    extra_rate = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        null=True,
        blank=True,
        help_text='Taxa adicional anual (ex.: 0,020000 = 2% a.a.).',
    )
    selic_cap_index = models.ForeignKey(
        'indices.IndexType',
        on_delete=models.PROTECT,
        related_name='correction_rule_caps',
        null=True,
        blank=True,
        help_text='Índice usado como teto no modo ipca_plus_capped (geralmente SELIC).',
    )
    legal_basis = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ('start_date',)
        verbose_name = 'Regra de correção'
        verbose_name_plural = 'Regras de correção'

    def __str__(self):
        end = self.end_date.isoformat() if self.end_date else 'vigente'
        return f'Correção {self.start_date.isoformat()} → {end}: {self.index_type.code} ({self.mode})'


class InterestRule(TimeStampedModel):
    '''Monthly interest rate applicable in a given period.'''

    MODE_FIXED_MONTHLY = 'fixed_monthly'
    MODE_SELIC = 'selic'
    MODE_IPCA_PLUS_CAPPED = 'ipca_plus_capped'
    MODE_CHOICES = [
        (MODE_FIXED_MONTHLY, 'Taxa fixa mensal'),
        (MODE_SELIC, 'SELIC'),
        (MODE_IPCA_PLUS_CAPPED, 'IPCA + taxa, limitado à SELIC'),
    ]

    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    monthly_rate = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        null=True,
        blank=True,
        help_text='Taxa mensal (ex.: 0,010000 = 1% a.m.).',
    )
    uses_selic = models.BooleanField(default=False)
    mode = models.CharField(max_length=32, choices=MODE_CHOICES, default=MODE_FIXED_MONTHLY)
    legal_basis = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ('start_date',)
        verbose_name = 'Regra de juros'
        verbose_name_plural = 'Regras de juros'

    def __str__(self):
        end = self.end_date.isoformat() if self.end_date else 'vigente'
        return f'Juros {self.start_date.isoformat()} → {end}: {self.mode}'


class UnificationRule(TimeStampedModel):
    '''Periods in which correction and interest must not be cumulated.

    Section 6.3: from 09/12/2021 onwards the SELIC (or IPCA+2% capped)
    unifies correction and interest in a single rate.
    '''

    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    unifies_correction_and_interest = models.BooleanField(default=True)
    legal_basis = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ('start_date',)
        verbose_name = 'Regra de unificação'
        verbose_name_plural = 'Regras de unificação'

    def __str__(self):
        end = self.end_date.isoformat() if self.end_date else 'vigente'
        return f'Unificação {self.start_date.isoformat()} → {end}'
