'''Service layer for fetching and serving economic indices.

Module structure:

* `IBGEClient`  — fetches INPC / IPCA-E series from the IBGE aggregates API.
* `BCBClient`   — fetches SELIC / IGP-M (and other) series from BCB SGS.
* `CJFLoader`   — bulk-loads the Justiça Federal table from a CSV fixture.
* `IndexService` — orchestrates DB reads/writes and resilient fallback.

All indices are stored in the database (IndexValue model). There is no
separate cache layer — the database IS the source of truth. When an
index value is needed, we check the DB first; only on a miss do we
call the external API and persist the result.

The HTTP boundary is wrapped by `HttpClient` (see `indices/http.py`) so
unit tests can substitute it via constructor injection without monkey
patching stdlib internals.
'''

import calendar
import csv
import threading
from datetime import date
from decimal import Decimal, InvalidOperation
from io import StringIO
from pathlib import Path

from django.db import transaction

from .exceptions import (
    IndexDataUnavailable,
    IndexServiceError,
    IndexSourceUnavailable,
    IndexTypeNotFound,
)
from .http import HttpClient
from .models import IndexType, IndexValue


# ---------------------------------------------------------------------------
# Progress tracking for background import tasks
# ---------------------------------------------------------------------------

_import_progress: dict[int, dict] = {}
_import_locks: dict[int, threading.Lock] = {}


def get_import_progress(user_id: int) -> dict | None:
    return _import_progress.get(user_id)


def set_import_progress(user_id: int, data: dict) -> None:
    _import_progress[user_id] = data


def clear_import_progress(user_id: int) -> None:
    _import_progress.pop(user_id, None)


def get_import_lock(user_id: int) -> threading.Lock:
    if user_id not in _import_locks:
        _import_locks[user_id] = threading.Lock()
    return _import_locks[user_id]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def normalize_reference_date(reference_date):
    '''Collapse any in-month date to its first day.

    All economic series modelled here are monthly. Storing them anchored to
    the first of the month keeps the key well-defined.
    '''
    return reference_date.replace(day=1)


def _to_decimal(raw):
    if raw is None or raw == '':
        raise IndexServiceError('valor numérico ausente na resposta')
    if isinstance(raw, str):
        raw = raw.replace(',', '.')
    try:
        return Decimal(raw)
    except (InvalidOperation, TypeError) as exc:
        raise IndexServiceError(f'valor numérico inválido: {raw!r}') from exc


def _month_range(start: date, end: date):
    '''Yield the first day of every month from start to end inclusive.'''
    current = normalize_reference_date(start)
    final = normalize_reference_date(end)
    while current <= final:
        yield current
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)


# ---------------------------------------------------------------------------
# IBGE
# ---------------------------------------------------------------------------


class IBGEClient:
    '''Fetches monthly series exposed by the IBGE aggregates API.

    Endpoint shape::

        https://servicodados.ibge.gov.br/api/v3/agregados/{aggregate}
          /periodos/{yyyymm}/variaveis/{variable}?localidades=N1[all]

    A single endpoint can return one or many periods; the parser is
    tolerant to both shapes.
    '''

    BASE_URL = 'https://servicodados.ibge.gov.br/api/v3/agregados'

    def __init__(self, http=None):
        self.http = http or HttpClient()

    def fetch_value(self, index_type, reference_date):
        if not index_type.ibge_aggregate or not index_type.ibge_variable:
            raise IndexServiceError(
                f'{index_type.code} não está parametrizado para a API do IBGE.'
            )
        period = f'{reference_date.year:04d}{reference_date.month:02d}'
        url = (
            f'{self.BASE_URL}/{index_type.ibge_aggregate}'
            f'/periodos/{period}/variaveis/{index_type.ibge_variable}'
            f'?localidades=N1[all]'
        )
        payload = self.http.get_json(url)
        return self._parse(payload, period)

    @staticmethod
    def _parse(payload, period):
        if not isinstance(payload, list) or not payload:
            raise IndexServiceError('resposta vazia do IBGE')
        try:
            series = payload[0]['resultados'][0]['series'][0]['serie']
        except (KeyError, IndexError, TypeError) as exc:
            raise IndexServiceError(f'estrutura inesperada na resposta do IBGE: {exc}') from exc
        if period not in series:
            raise IndexDataUnavailable(f'período {period} ausente na série do IBGE')
        return _to_decimal(series[period])


# ---------------------------------------------------------------------------
# Banco Central (SGS)
# ---------------------------------------------------------------------------


class BCBClient:
    '''Fetches monthly series exposed by the BCB SGS public API.

    Endpoint shape::

        https://api.bcb.gov.br/dados/serie/bcdata.sgs.{series_id}/dados
          ?formato=json&dataInicial=dd/mm/yyyy&dataFinal=dd/mm/yyyy

    The series resolution can be daily or monthly depending on the code;
    for monthly series, the first business day of the month is returned.
    '''

    BASE_URL = 'https://api.bcb.gov.br/dados/serie'

    def __init__(self, http=None):
        self.http = http or HttpClient()

    def fetch_value(self, index_type, reference_date):
        if not index_type.sgs_series_id:
            raise IndexServiceError(
                f'{index_type.code} não está parametrizado para a SGS/BCB.'
            )
        anchored = normalize_reference_date(reference_date)
        last_day = self._month_last_day(anchored)
        url = (
            f'{self.BASE_URL}/bcdata.sgs.{index_type.sgs_series_id}/dados'
            f'?formato=json'
            f'&dataInicial={anchored:%d/%m/%Y}'
            f'&dataFinal={last_day:%d/%m/%Y}'
        )
        payload = self.http.get_json(url)
        return self._parse(payload, anchored)

    @staticmethod
    def _month_last_day(reference_date):
        last_day = calendar.monthrange(reference_date.year, reference_date.month)[1]
        return reference_date.replace(day=last_day)

    @staticmethod
    def _parse(payload, anchored):
        if not isinstance(payload, list) or not payload:
            raise IndexDataUnavailable(f'série BCB vazia para {anchored:%Y-%m}')
        first = payload[0]
        if 'valor' not in first:
            raise IndexServiceError(f'estrutura inesperada na SGS: {first!r}')
        return _to_decimal(first['valor'])


# ---------------------------------------------------------------------------
# Justiça Federal (CJF)
# ---------------------------------------------------------------------------


class CJFLoader:
    '''Loads the Justiça Federal factor table from a CSV file.

    The CSV must have a header `reference_date,value` where `reference_date`
    is `YYYY-MM-DD` (day is normalised to the first of the month) and
    `value` is a decimal using a dot as the separator.
    '''

    def __init__(self, index_type=None):
        self.index_type = index_type or IndexType.objects.get(code='CJF')

    def load_from_path(self, path):
        path = Path(path)
        with path.open(encoding='utf-8') as handle:
            return self.load_from_text(handle.read())

    def load_from_text(self, text):
        reader = csv.DictReader(StringIO(text))
        created, updated = 0, 0
        with transaction.atomic():
            for row in reader:
                reference = date.fromisoformat(row['reference_date'])
                anchored = normalize_reference_date(reference)
                value = _to_decimal(row['value'])
                _, was_created = IndexValue.objects.update_or_create(
                    index_type=self.index_type,
                    reference_date=anchored,
                    defaults={'value': value},
                )
                if was_created:
                    created += 1
                else:
                    updated += 1
        return {'created': created, 'updated': updated}


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


class IndexService:
    '''DB-first lookup with resilient fallback for monthly indices.

    Lookup policy:

    1. Return the stored `IndexValue` when present.
    2. Otherwise, dispatch to the source-specific client.
    3. Persist what the client returns (write-through).
    4. If the source is down (`IndexSourceUnavailable`) and a stale entry
       exists, return it (RNF15).
    5. Raise `IndexDataUnavailable` only when neither stored value nor source
       could satisfy the request.
    '''

    CODES = ('INPC', 'IPCA-E', 'IPCA', 'SELIC', 'IGP-M')
    MIN_YEAR = 1990

    def __init__(self, ibge_client=None, bcb_client=None):
        self.ibge_client = ibge_client or IBGEClient()
        self.bcb_client = bcb_client or BCBClient()

    def get_value(self, code, reference_date):
        anchored = normalize_reference_date(reference_date)
        try:
            index_type = IndexType.objects.get(code=code)
        except IndexType.DoesNotExist as exc:
            raise IndexTypeNotFound(f'IndexType {code!r} não cadastrado.') from exc

        cached = IndexValue.objects.filter(
            index_type=index_type,
            reference_date=anchored,
        ).first()
        if cached is not None:
            return cached.value

        try:
            value = self._fetch(index_type, anchored)
        except IndexSourceUnavailable:
            stale = self._latest_cached(index_type, anchored)
            if stale is not None:
                return stale.value
            raise IndexDataUnavailable(
                f'{code} {anchored:%Y-%m}: API indisponível e sem valor armazenado.'
            )

        return self._store_value(index_type, anchored, value).value

    def get_values_range(self, code, start, end):
        '''Return ``{month_first_day: value}`` for every month in [start, end].

        Reads all cached months for the series in a single query; only months
        missing from the cache fall back to the per-month `get_value` path
        (which fetches from the upstream source and persists). This keeps the
        common, fully-cached case to one database query instead of one per
        month.
        '''
        try:
            index_type = IndexType.objects.get(code=code)
        except IndexType.DoesNotExist as exc:
            raise IndexTypeNotFound(f'IndexType {code!r} não cadastrado.') from exc

        anchored_start = normalize_reference_date(start)
        anchored_end = normalize_reference_date(end)
        cached = dict(
            IndexValue.objects.filter(
                index_type=index_type,
                reference_date__gte=anchored_start,
                reference_date__lte=anchored_end,
            ).values_list('reference_date', 'value')
        )

        values = {}
        for month in _month_range(anchored_start, anchored_end):
            if month in cached:
                values[month] = cached[month]
            else:
                values[month] = self.get_value(code, month)
        return values

    def bulk_import(self, start: date, end: date, progress_callback=None):
        '''Import all missing index values for the given date range.

        Queries the DB first to find which (index_type, reference_date)
        pairs already exist, then only fetches missing values from
        external APIs. Progress is reported via callback if provided.

        Returns dict with keys: created, skipped, errors, total.
        '''
        index_types = {code: IndexType.objects.get(code=code) for code in self.CODES}

        months = list(_month_range(start, end))
        total = len(months) * len(self.CODES)

        existing = set(
            IndexValue.objects.filter(
                index_type__code__in=self.CODES,
                reference_date__gte=normalize_reference_date(start),
                reference_date__lte=normalize_reference_date(end),
            ).values_list('index_type__code', 'reference_date')
        )

        created = 0
        skipped = 0
        errors = 0
        processed = 0

        for month in months:
            for code in self.CODES:
                processed += 1
                if (code, month) in existing:
                    skipped += 1
                    if progress_callback:
                        progress_callback(processed, total, created, skipped, errors)
                    continue

                try:
                    value = self._fetch(index_types[code], month)
                    self._store_value(index_types[code], month, value)
                    created += 1
                    existing.add((code, month))
                except IndexServiceError:
                    # Expected failure modes (source down, missing period,
                    # bad payload) are tallied and skipped so one bad month
                    # never aborts a long import. Unexpected errors propagate.
                    errors += 1

                if progress_callback:
                    progress_callback(processed, total, created, skipped, errors)

        return {'created': created, 'skipped': skipped, 'errors': errors, 'total': total}

    def _fetch(self, index_type, anchored):
        if index_type.source == IndexType.SOURCE_IBGE:
            return self.ibge_client.fetch_value(index_type, anchored)
        if index_type.source == IndexType.SOURCE_BCB:
            return self.bcb_client.fetch_value(index_type, anchored)
        if index_type.source == IndexType.SOURCE_CJF:
            raise IndexDataUnavailable(
                f'{index_type.code} {anchored:%Y-%m}: a tabela CJF deve ser carregada via fixture.'
            )
        raise IndexServiceError(f'fonte desconhecida: {index_type.source!r}')

    @staticmethod
    def _store_value(index_type, anchored, value):
        obj, _ = IndexValue.objects.update_or_create(
            index_type=index_type,
            reference_date=anchored,
            defaults={'value': value},
        )
        return obj

    @staticmethod
    def _latest_cached(index_type, anchored):
        return (
            IndexValue.objects
            .filter(index_type=index_type, reference_date__lte=anchored)
            .order_by('-reference_date')
            .first()
        )

    def get_status(self):
        '''Return count of stored values per index code.'''
        from django.db.models import Count
        return dict(
            IndexValue.objects
            .filter(index_type__code__in=self.CODES)
            .values('index_type__code')
            .annotate(count=Count('pk'))
            .values_list('index_type__code', 'count')
        )