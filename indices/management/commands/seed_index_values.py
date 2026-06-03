'''Management command to seed monthly index values for offline dev.

Usage::

    python manage.py seed_index_values

Fetches real monthly data from IBGE and BCB APIs for a date range,
persisting each month to `IndexValue` (cache). If a month already
exists in the database it is skipped.

This command lets you pre-warm the cache so the calculation engine
works without live API calls.
'''

from datetime import date
from decimal import Decimal
from time import sleep

from django.core.management.base import BaseCommand

from indices.models import IndexType, IndexValue
from indices.services import IndexService, normalize_reference_date


class Command(BaseCommand):
    help = 'Popula o cache local com valores mensais dos índices econômicos.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--start',
            default='2020-01',
            help='Mês inicial no formato YYYY-MM (padrão: 2020-01).',
        )
        parser.add_argument(
            '--end',
            default='2026-05',
            help='Mês final no formato YYYY-MM (padrão: 2026-05).',
        )
        parser.add_argument(
            '--index',
            default='',
            help='Código do índice específico (INPC, IPCA-E, IPCA, SELIC, IGP-M). '
                 'Deixe vazio para baixar todos.',
        )

    def handle(self, *args, **options):
        start = date.fromisoformat(options['start'] + '-01')
        end = date.fromisoformat(options['end'] + '-01')
        index_filter = options['index'].strip()

        codes = [index_filter] if index_filter else ['INPC', 'IPCA-E', 'IPCA', 'SELIC', 'IGP-M']

        service = IndexService()

        current = normalize_reference_date(start)
        final = normalize_reference_date(end)

        total_created = 0
        total_skipped = 0
        total_errors = 0

        while current <= final:
            for code in codes:
                if IndexValue.objects.filter(
                    index_type__code=code, reference_date=current
                ).exists():
                    total_skipped += 1
                    continue

                try:
                    value = service.get_value(code, current)
                    total_created += 1
                    self.stdout.write(
                        self.style.SUCCESS(f'{code} {current:%Y-%m} = {value}')
                    )
                except Exception as exc:
                    total_errors += 1
                    self.stdout.write(
                        self.style.WARNING(f'{code} {current:%Y-%m} ERRO: {exc}')
                    )
                sleep(0.15)  # Rate-limit: be gentle with public APIs

            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)

        self.stdout.write(
            self.style.SUCCESS(
                f'Concluído: {total_created} criados, '
                f'{total_skipped} já existentes, {total_errors} erros.'
            )
        )
