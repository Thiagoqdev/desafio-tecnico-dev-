'''Add the IPCA IndexType required by the EC 136/2025 ipca_plus_capped mode.

IPCA-E (already seeded) and IPCA are distinct IBGE series. EC 136/2025
refers specifically to IPCA, so we need a dedicated IndexType row.
'''

from django.db import migrations


SEED = {
    'code': 'IPCA',
    'name': 'IPCA',
    'source': 'IBGE',
    'ibge_aggregate': '1737',
    'ibge_variable': '63',
    'description': 'Índice de Preços ao Consumidor Amplo (IBGE).',
}


def seed(apps, schema_editor):
    IndexType = apps.get_model('indices', 'IndexType')
    IndexType.objects.update_or_create(code=SEED['code'], defaults=SEED)


def unseed(apps, schema_editor):
    IndexType = apps.get_model('indices', 'IndexType')
    IndexType.objects.filter(code=SEED['code']).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('indices', '0002_seed_index_types'),
    ]
    operations = [
        migrations.RunPython(seed, unseed),
    ]
