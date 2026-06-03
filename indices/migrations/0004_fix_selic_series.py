'''Fix the SELIC SGS series id.

The seed migration (0002) pointed SELIC at SGS series 4189, which is the
*annualised* Selic rate ("Selic acumulada no mês anualizada base 252",
expressed in % a.a.). The calculation engine treats every stored value as a
monthly percentage change, so feeding it annualised figures (e.g. 9.15) made
the cumulative factor explode (~20x over two years).

The correct series for a monthly accumulated Selic rate (% a.m.) is
SGS 4390 ("Taxa de juros - Selic acumulada no mês"). This migration repoints
the IndexType and clears the contaminated IndexValue rows so they are
re-fetched from the correct series.
'''

from django.db import migrations


def fix(apps, schema_editor):
    IndexType = apps.get_model('indices', 'IndexType')
    IndexValue = apps.get_model('indices', 'IndexValue')
    try:
        selic = IndexType.objects.get(code='SELIC')
    except IndexType.DoesNotExist:
        return
    selic.sgs_series_id = 4390
    selic.description = 'Taxa SELIC acumulada no mês, % a.m. (BCB/SGS série 4390).'
    selic.save(update_fields=['sgs_series_id', 'description'])
    # Drop the annualised values seeded under series 4189 so they are
    # re-fetched with the correct monthly series.
    IndexValue.objects.filter(index_type=selic).delete()


def unfix(apps, schema_editor):
    IndexType = apps.get_model('indices', 'IndexType')
    IndexValue = apps.get_model('indices', 'IndexValue')
    try:
        selic = IndexType.objects.get(code='SELIC')
    except IndexType.DoesNotExist:
        return
    selic.sgs_series_id = 4189
    selic.description = 'Taxa SELIC acumulada no mês (BCB/SGS série 4189).'
    selic.save(update_fields=['sgs_series_id', 'description'])
    IndexValue.objects.filter(index_type=selic).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('indices', '0003_add_ipca'),
    ]
    operations = [
        migrations.RunPython(fix, unfix),
    ]
