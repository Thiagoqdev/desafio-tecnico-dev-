'''Seed canonical IndexType rows for the series covered by Sprint 2.

These rows are parametrizable data, not business rules. They identify
where each series is sourced from and how to address it on the upstream
API. New series can be added by writing additional data migrations or by
editing the rows through the admin.
'''

from django.db import migrations


SEEDS = [
    {
        'code': 'INPC',
        'name': 'INPC',
        'source': 'IBGE',
        'ibge_aggregate': '1736',
        'ibge_variable': '44',
        'description': 'Índice Nacional de Preços ao Consumidor (IBGE).',
    },
    {
        'code': 'IPCA-E',
        'name': 'IPCA-E',
        'source': 'IBGE',
        'ibge_aggregate': '1705',
        'ibge_variable': '44',
        'description': 'IPCA Especial (IBGE).',
    },
    {
        'code': 'IGP-M',
        'name': 'IGP-M',
        'source': 'BCB',
        'sgs_series_id': 189,
        'description': 'Índice Geral de Preços — Mercado (BCB/SGS série 189).',
    },
    {
        'code': 'SELIC',
        'name': 'SELIC',
        'source': 'BCB',
        'sgs_series_id': 4189,
        'description': 'Taxa SELIC acumulada no mês (BCB/SGS série 4189).',
    },
    {
        'code': 'CJF',
        'name': 'Tabela da Justiça Federal',
        'source': 'CJF',
        'description': 'Tabela de fatores do Manual de Cálculos da Justiça Federal.',
    },
]


def seed(apps, schema_editor):
    IndexType = apps.get_model('indices', 'IndexType')
    for entry in SEEDS:
        IndexType.objects.update_or_create(code=entry['code'], defaults=entry)


def unseed(apps, schema_editor):
    IndexType = apps.get_model('indices', 'IndexType')
    IndexType.objects.filter(code__in=[entry['code'] for entry in SEEDS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('indices', '0001_initial'),
    ]
    operations = [
        migrations.RunPython(seed, unseed),
    ]
