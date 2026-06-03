'''Fix the IPCA-E (IPCA-15) IBGE addressing.

The seed migration (0002) pointed IPCA-E at IBGE aggregate 1705 / variable 44.
Two problems:

* Variable 44 is not the IPCA-15 monthly variation; the correct variable is
  355 ("IPCA15 - Variação mensal %").
* Aggregate 1705 only covers fev/2012 to jan/2020. From fev/2020 onward the
  series lives in aggregate 7062.

Since the application's data window starts in 2020, we repoint IPCA-E to
aggregate 7062 / variable 355, which is the live source for the modern range.
No IPCA-E values were ever stored under the broken config, so there is nothing
to purge.
'''

from django.db import migrations


def fix(apps, schema_editor):
    IndexType = apps.get_model('indices', 'IndexType')
    try:
        ipcae = IndexType.objects.get(code='IPCA-E')
    except IndexType.DoesNotExist:
        return
    ipcae.ibge_aggregate = '7062'
    ipcae.ibge_variable = '355'
    ipcae.description = 'IPCA-15 / IPCA-E — variação mensal % (IBGE agregado 7062, variável 355).'
    ipcae.save(update_fields=['ibge_aggregate', 'ibge_variable', 'description'])


def unfix(apps, schema_editor):
    IndexType = apps.get_model('indices', 'IndexType')
    try:
        ipcae = IndexType.objects.get(code='IPCA-E')
    except IndexType.DoesNotExist:
        return
    ipcae.ibge_aggregate = '1705'
    ipcae.ibge_variable = '44'
    ipcae.description = 'IPCA Especial (IBGE).'
    ipcae.save(update_fields=['ibge_aggregate', 'ibge_variable', 'description'])


class Migration(migrations.Migration):
    dependencies = [
        ('indices', '0004_fix_selic_series'),
    ]
    operations = [
        migrations.RunPython(fix, unfix),
    ]
