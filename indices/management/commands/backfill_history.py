'''Backfill monthly index history from BCB/SGS continuous series.

The per-month `seed_index_values` command routes through each IndexType's
configured source, which for INPC/IPCA is the IBGE aggregates API — and those
aggregates are versioned by methodology era, so they cannot reach back to 1994.

BCB/SGS, by contrast, exposes each series as one continuous history that
republishes the official IBGE values. This command fetches the *whole* series in
a single request per index and stores every month from ``--start`` (default
1994-07, the Plano Real) onward. It is the historical-backfill counterpart of
`seed_index_values`; the BCB series ids are mapped here explicitly because
INPC/IPCA keep IBGE as their live source.

Usage::

    python manage.py backfill_history
    python manage.py backfill_history --start 1994-07
'''

from datetime import date

from django.core.management.base import BaseCommand, CommandError

from indices.http import HttpClient
from indices.models import IndexType, IndexValue
from indices.services import _to_decimal, normalize_reference_date


# code -> BCB/SGS series id (monthly variation %, except SELIC which is the
# monthly accumulated rate). These are the continuous historical equivalents of
# each IndexType, used only to warm the cache.
SGS_SERIES = {
    'INPC': 188,
    'IPCA': 433,
    'IPCA-E': 7478,
    'IGP-M': 189,
    'SELIC': 4390,
}

BCB_URL = 'https://api.bcb.gov.br/dados/serie/bcdata.sgs.{sid}/dados?formato=json'

DEFAULT_START = date(1994, 7, 1)


class Command(BaseCommand):
    help = 'Popula o histórico mensal dos índices a partir das séries contínuas do BCB/SGS.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--start',
            default='1994-07',
            help='Mês inicial no formato YYYY-MM (padrão: 1994-07, Plano Real).',
        )
        parser.add_argument(
            '--index',
            default='',
            help='Código específico (INPC, IPCA, IPCA-E, IGP-M, SELIC). Vazio = todos.',
        )

    def handle(self, *args, **options):
        start = self._parse_start(options['start'])
        index_filter = options['index'].strip().upper()
        codes = [index_filter] if index_filter else list(SGS_SERIES)

        http = HttpClient()
        grand_created = 0
        grand_updated = 0

        for code in codes:
            if code not in SGS_SERIES:
                raise CommandError(f'Índice desconhecido: {code!r}.')
            try:
                index_type = IndexType.objects.get(code=code)
            except IndexType.DoesNotExist as exc:
                raise CommandError(f'IndexType {code!r} não cadastrado.') from exc

            created, updated, earliest, latest = self._backfill_one(
                http, index_type, SGS_SERIES[code], start,
            )
            grand_created += created
            grand_updated += updated
            coverage = f'{earliest:%Y-%m} → {latest:%Y-%m}' if earliest else 'sem dados'
            self.stdout.write(self.style.SUCCESS(
                f'{code:7} {created:>4} criados, {updated:>4} atualizados | {coverage}'
            ))

        self.stdout.write(self.style.SUCCESS(
            f'Concluído: {grand_created} criados, {grand_updated} atualizados.'
        ))

    @staticmethod
    def _parse_start(raw):
        try:
            anchored = date.fromisoformat(raw + '-01')
        except ValueError as exc:
            raise CommandError(f'--start inválido: {raw!r} (use YYYY-MM).') from exc
        return max(normalize_reference_date(anchored), DEFAULT_START)

    def _backfill_one(self, http, index_type, sgs_id, start):
        payload = http.get_json(BCB_URL.format(sid=sgs_id))
        if not isinstance(payload, list):
            raise CommandError(f'Resposta inesperada da SGS para a série {sgs_id}.')

        created = updated = 0
        earliest = latest = None
        for point in payload:
            reference = self._parse_point_date(point.get('data'))
            if reference is None or reference < start:
                continue
            value = _to_decimal(point.get('valor'))
            _, was_created = IndexValue.objects.update_or_create(
                index_type=index_type,
                reference_date=reference,
                defaults={'value': value},
            )
            created += int(was_created)
            updated += int(not was_created)
            earliest = reference if earliest is None else min(earliest, reference)
            latest = reference if latest is None else max(latest, reference)
        return created, updated, earliest, latest

    @staticmethod
    def _parse_point_date(raw):
        '''Parse a BCB ``dd/mm/yyyy`` date, anchored to the first of the month.'''
        if not raw:
            return None
        try:
            day, month, year = (int(part) for part in raw.split('/'))
        except (ValueError, AttributeError):
            return None
        return date(year, month, 1)
