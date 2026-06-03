'''Seed the legislation tables from PRD Sections 6.1, 6.2 and 6.3.

These rows are parametrizable: the calculation engine reads them at
runtime and never embeds dates or rates in code (RNF — Seção 6,
"Regra arquitetural").
'''

from datetime import date
from decimal import Decimal

from django.db import migrations


CORRECTION_SEEDS = [
    {
        'start_date': date(1984, 1, 1),
        'end_date': date(1991, 12, 31),
        'index_code': 'INPC',
        'mode': 'single_index',
        'extra_rate': None,
        'cap_code': None,
        'legal_basis': '',
    },
    {
        'start_date': date(1992, 1, 1),
        'end_date': date(2021, 12, 8),
        'index_code': 'IPCA-E',
        'mode': 'single_index',
        'extra_rate': None,
        'cap_code': None,
        'legal_basis': '',
    },
    {
        'start_date': date(2021, 12, 9),
        'end_date': date(2025, 9, 30),
        'index_code': 'SELIC',
        'mode': 'single_index',
        'extra_rate': None,
        'cap_code': None,
        'legal_basis': 'EC 113/2021',
    },
    {
        'start_date': date(2025, 10, 1),
        'end_date': None,
        'index_code': 'IPCA',
        'mode': 'ipca_plus_capped',
        'extra_rate': Decimal('0.020000'),
        'cap_code': 'SELIC',
        'legal_basis': 'EC 136/2025',
    },
]


INTEREST_SEEDS = [
    {
        'start_date': date(1984, 1, 1),
        'end_date': date(2009, 6, 30),
        'monthly_rate': Decimal('0.010000'),
        'uses_selic': False,
        'mode': 'fixed_monthly',
        'legal_basis': '',
    },
    {
        'start_date': date(2009, 7, 1),
        'end_date': date(2021, 12, 8),
        'monthly_rate': Decimal('0.005000'),
        'uses_selic': False,
        'mode': 'fixed_monthly',
        'legal_basis': '',
    },
    {
        'start_date': date(2021, 12, 9),
        'end_date': date(2025, 9, 30),
        'monthly_rate': None,
        'uses_selic': True,
        'mode': 'selic',
        'legal_basis': 'EC 113/2021',
    },
    {
        'start_date': date(2025, 10, 1),
        'end_date': None,
        'monthly_rate': None,
        'uses_selic': False,
        'mode': 'ipca_plus_capped',
        'legal_basis': 'EC 136/2025',
    },
]


UNIFICATION_SEEDS = [
    {
        'start_date': date(2021, 12, 9),
        'end_date': None,
        'unifies_correction_and_interest': True,
        'legal_basis': 'EC 113/2021',
    },
]


def seed(apps, schema_editor):
    IndexType = apps.get_model('indices', 'IndexType')
    CorrectionRule = apps.get_model('legislation', 'CorrectionRule')
    InterestRule = apps.get_model('legislation', 'InterestRule')
    UnificationRule = apps.get_model('legislation', 'UnificationRule')

    def index(code):
        return IndexType.objects.get(code=code) if code else None

    for entry in CORRECTION_SEEDS:
        CorrectionRule.objects.update_or_create(
            start_date=entry['start_date'],
            defaults={
                'end_date': entry['end_date'],
                'index_type': index(entry['index_code']),
                'mode': entry['mode'],
                'extra_rate': entry['extra_rate'],
                'selic_cap_index': index(entry['cap_code']),
                'legal_basis': entry['legal_basis'],
            },
        )

    for entry in INTEREST_SEEDS:
        InterestRule.objects.update_or_create(
            start_date=entry['start_date'],
            defaults={
                'end_date': entry['end_date'],
                'monthly_rate': entry['monthly_rate'],
                'uses_selic': entry['uses_selic'],
                'mode': entry['mode'],
                'legal_basis': entry['legal_basis'],
            },
        )

    for entry in UNIFICATION_SEEDS:
        UnificationRule.objects.update_or_create(
            start_date=entry['start_date'],
            defaults={
                'end_date': entry['end_date'],
                'unifies_correction_and_interest': entry['unifies_correction_and_interest'],
                'legal_basis': entry['legal_basis'],
            },
        )


def unseed(apps, schema_editor):
    apps.get_model('legislation', 'CorrectionRule').objects.all().delete()
    apps.get_model('legislation', 'InterestRule').objects.all().delete()
    apps.get_model('legislation', 'UnificationRule').objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ('legislation', '0001_initial'),
        ('indices', '0003_add_ipca'),
    ]
    operations = [
        migrations.RunPython(seed, unseed),
    ]
