'''Repoint IPCA-E to the BCB/SGS source for continuous history.

IPCA-E (judicial "IPCA Especial") equals the IBGE IPCA-15. The IBGE aggregates
that expose it are versioned by methodology era (1705 ends jan/2020, 7062 starts
fev/2020), so a single IBGE address cannot cover the historical range the
application now needs (from 1994). BCB/SGS series 7478 carries the same monthly
IPCA-15 variation in one continuous series (from maio/2000), republishing IBGE's
official values (verified: jan/2024 = 0.31 in both sources).

This repoints the IndexType so cache misses are served from BCB/SGS, and clears
the IBGE addressing that no longer applies. INPC and IPCA stay on IBGE.
'''

from django.db import migrations


def to_bcb(apps, schema_editor):
    IndexType = apps.get_model('indices', 'IndexType')
    try:
        ipcae = IndexType.objects.get(code='IPCA-E')
    except IndexType.DoesNotExist:
        return
    ipcae.source = 'BCB'
    ipcae.sgs_series_id = 7478
    ipcae.ibge_aggregate = ''
    ipcae.ibge_variable = ''
    ipcae.description = (
        'IPCA-15 / IPCA-E — variação mensal % (BCB/SGS série 7478, desde maio/2000).'
    )
    ipcae.save(update_fields=[
        'source', 'sgs_series_id', 'ibge_aggregate', 'ibge_variable', 'description',
    ])


def to_ibge(apps, schema_editor):
    IndexType = apps.get_model('indices', 'IndexType')
    try:
        ipcae = IndexType.objects.get(code='IPCA-E')
    except IndexType.DoesNotExist:
        return
    ipcae.source = 'IBGE'
    ipcae.sgs_series_id = None
    ipcae.ibge_aggregate = '7062'
    ipcae.ibge_variable = '355'
    ipcae.description = 'IPCA-15 / IPCA-E — variação mensal % (IBGE agregado 7062, variável 355).'
    ipcae.save(update_fields=[
        'source', 'sgs_series_id', 'ibge_aggregate', 'ibge_variable', 'description',
    ])


class Migration(migrations.Migration):
    dependencies = [
        ('indices', '0005_fix_ipcae_aggregate'),
    ]
    operations = [
        migrations.RunPython(to_bcb, to_ibge),
    ]
