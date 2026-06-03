'''Tests for the indices module: clients, service and views.'''

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, Client

from .exceptions import (
    IndexDataUnavailable,
    IndexSourceUnavailable,
    IndexTypeNotFound,
)
from .models import IndexType, IndexValue
from .services import (
    BCBClient,
    IBGEClient,
    IndexService,
    clear_import_progress,
    get_import_progress,
    normalize_reference_date,
    set_import_progress,
    _month_range,
)


class _FakeHttp:
    '''Test double that returns a queued payload or raises a queued error.'''

    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    def get_json(self, url):
        self.calls.append(url)
        if self.error is not None:
            raise self.error
        return self.payload


# ---------------------------------------------------------------------------
# Seeded IndexType fixtures
# ---------------------------------------------------------------------------


class IndexTypeSeedTests(TestCase):
    '''The data migration must seed the five canonical IndexType rows.'''

    def test_canonical_types_are_seeded(self):
        codes = set(IndexType.objects.values_list('code', flat=True))
        self.assertEqual(codes, {'INPC', 'IPCA', 'IPCA-E', 'IGP-M', 'SELIC', 'CJF'})

    def test_seeded_bcb_series_ids_are_set(self):
        selic = IndexType.objects.get(code='SELIC')
        igpm = IndexType.objects.get(code='IGP-M')
        ipcae = IndexType.objects.get(code='IPCA-E')
        self.assertEqual(selic.sgs_series_id, 4390)
        self.assertEqual(igpm.sgs_series_id, 189)
        self.assertEqual(ipcae.source, 'BCB')
        self.assertEqual(ipcae.sgs_series_id, 7478)

    def test_seeded_ibge_aggregates_are_set(self):
        inpc = IndexType.objects.get(code='INPC')
        self.assertEqual(inpc.ibge_aggregate, '1736')


# ---------------------------------------------------------------------------
# IBGEClient
# ---------------------------------------------------------------------------


class IBGEClientTests(TestCase):
    def setUp(self):
        self.inpc = IndexType.objects.get(code='INPC')

    def _payload(self, period, value):
        return [{
            'id': '44',
            'variavel': 'INPC',
            'resultados': [{
                'series': [{
                    'localidade': {'id': '1', 'nivel': {'id': 'N1', 'nome': 'Brasil'}, 'nome': 'Brasil'},
                    'serie': {period: value},
                }],
            }],
        }]

    def test_fetches_and_parses_decimal_value(self):
        http = _FakeHttp(payload=self._payload('202404', '0.38'))
        client = IBGEClient(http=http)

        value = client.fetch_value(self.inpc, date(2024, 4, 15))

        self.assertEqual(value, Decimal('0.38'))
        self.assertIn('agregados/1736', http.calls[0])
        self.assertIn('periodos/202404', http.calls[0])
        self.assertIn('variaveis/44', http.calls[0])

    def test_missing_period_raises_data_unavailable(self):
        http = _FakeHttp(payload=self._payload('202403', '0.20'))
        client = IBGEClient(http=http)

        with self.assertRaises(IndexDataUnavailable):
            client.fetch_value(self.inpc, date(2024, 4, 1))

    def test_propagates_http_failure_as_source_unavailable(self):
        http = _FakeHttp(error=IndexSourceUnavailable('down'))
        client = IBGEClient(http=http)

        with self.assertRaises(IndexSourceUnavailable):
            client.fetch_value(self.inpc, date(2024, 4, 1))


# ---------------------------------------------------------------------------
# BCBClient
# ---------------------------------------------------------------------------


class BCBClientTests(TestCase):
    def setUp(self):
        self.selic = IndexType.objects.get(code='SELIC')

    def test_fetches_decimal_value_with_brazilian_date_range(self):
        http = _FakeHttp(payload=[{'data': '01/04/2024', 'valor': '0.89'}])
        client = BCBClient(http=http)

        value = client.fetch_value(self.selic, date(2024, 4, 15))

        self.assertEqual(value, Decimal('0.89'))
        url = http.calls[0]
        self.assertIn('bcdata.sgs.4390/dados', url)
        self.assertIn('dataInicial=01/04/2024', url)
        self.assertIn('dataFinal=30/04/2024', url)

    def test_february_uses_last_day_of_month(self):
        http = _FakeHttp(payload=[{'data': '01/02/2023', 'valor': '0.92'}])
        client = BCBClient(http=http)

        client.fetch_value(self.selic, date(2023, 2, 10))

        self.assertIn('dataFinal=28/02/2023', http.calls[0])

    def test_february_leap_year_uses_29(self):
        http = _FakeHttp(payload=[{'data': '01/02/2024', 'valor': '0.83'}])
        client = BCBClient(http=http)

        client.fetch_value(self.selic, date(2024, 2, 5))

        self.assertIn('dataFinal=29/02/2024', http.calls[0])

    def test_empty_payload_raises_data_unavailable(self):
        http = _FakeHttp(payload=[])
        client = BCBClient(http=http)

        with self.assertRaises(IndexDataUnavailable):
            client.fetch_value(self.selic, date(2024, 4, 1))


# ---------------------------------------------------------------------------
# CJFLoader
# ---------------------------------------------------------------------------


class CJFLoaderTests(TestCase):
    def test_loads_sample_fixture(self):
        fixture = Path(__file__).resolve().parent / 'fixtures' / 'cjf_sample.csv'

        from .services import CJFLoader
        report = CJFLoader().load_from_path(fixture)

        self.assertEqual(report['created'], 12)
        self.assertEqual(report['updated'], 0)
        self.assertEqual(IndexValue.objects.filter(index_type__code='CJF').count(), 12)

    def test_reloading_updates_existing_rows(self):
        from .services import CJFLoader
        loader = CJFLoader()
        loader.load_from_text('reference_date,value\n2024-01-15,1.0000\n')

        report = loader.load_from_text('reference_date,value\n2024-01-15,1.0050\n')

        self.assertEqual(report['updated'], 1)
        self.assertEqual(report['created'], 0)
        cached = IndexValue.objects.get(index_type__code='CJF', reference_date=date(2024, 1, 1))
        self.assertEqual(cached.value, Decimal('1.0050'))

    def test_normalizes_reference_date_to_first_of_month(self):
        from .services import CJFLoader
        CJFLoader().load_from_text('reference_date,value\n2024-03-22,1.0100\n')

        self.assertTrue(
            IndexValue.objects.filter(
                index_type__code='CJF', reference_date=date(2024, 3, 1)
            ).exists()
        )


# ---------------------------------------------------------------------------
# IndexService — DB lookup + fallback
# ---------------------------------------------------------------------------


class IndexServiceTests(TestCase):
    def setUp(self):
        self.inpc = IndexType.objects.get(code='INPC')
        self.selic = IndexType.objects.get(code='SELIC')
        self.reference = date(2024, 4, 1)

    def _ibge_payload(self, value='0.38'):
        return [{
            'resultados': [{
                'series': [{'serie': {'202404': value}}],
            }],
        }]

    def test_cache_hit_does_not_call_client(self):
        IndexValue.objects.create(
            index_type=self.inpc,
            reference_date=self.reference,
            value=Decimal('0.22'),
        )
        ibge_http = _FakeHttp(payload=self._ibge_payload())
        service = IndexService(
            ibge_client=IBGEClient(http=ibge_http),
            bcb_client=BCBClient(http=_FakeHttp(payload=[])),
        )

        value = service.get_value('INPC', date(2024, 4, 15))

        self.assertEqual(value, Decimal('0.22'))
        self.assertEqual(ibge_http.calls, [])

    def test_cache_miss_fetches_and_stores(self):
        ibge_http = _FakeHttp(payload=self._ibge_payload('0.45'))
        service = IndexService(
            ibge_client=IBGEClient(http=ibge_http),
            bcb_client=BCBClient(http=_FakeHttp(payload=[])),
        )

        value = service.get_value('INPC', self.reference)

        self.assertEqual(value, Decimal('0.45'))
        cached = IndexValue.objects.get(index_type=self.inpc, reference_date=self.reference)
        self.assertEqual(cached.value, Decimal('0.45'))
        self.assertEqual(len(ibge_http.calls), 1)

    def test_calls_bcb_for_bcb_sourced_index(self):
        bcb_http = _FakeHttp(payload=[{'data': '01/04/2024', 'valor': '0.92'}])
        service = IndexService(
            ibge_client=IBGEClient(http=_FakeHttp(payload=[])),
            bcb_client=BCBClient(http=bcb_http),
        )

        value = service.get_value('SELIC', self.reference)

        self.assertEqual(value, Decimal('0.92'))
        self.assertEqual(len(bcb_http.calls), 1)

    def test_fallback_returns_latest_cached_when_source_unavailable(self):
        IndexValue.objects.create(
            index_type=self.inpc,
            reference_date=date(2024, 3, 1),
            value=Decimal('0.30'),
        )
        ibge_http = _FakeHttp(error=IndexSourceUnavailable('down'))
        service = IndexService(
            ibge_client=IBGEClient(http=ibge_http),
            bcb_client=BCBClient(http=_FakeHttp(payload=[])),
        )

        value = service.get_value('INPC', date(2024, 4, 1))

        self.assertEqual(value, Decimal('0.30'))

    def test_raises_when_neither_cache_nor_source_has_data(self):
        ibge_http = _FakeHttp(error=IndexSourceUnavailable('down'))
        service = IndexService(
            ibge_client=IBGEClient(http=ibge_http),
            bcb_client=BCBClient(http=_FakeHttp(payload=[])),
        )

        with self.assertRaises(IndexDataUnavailable):
            service.get_value('INPC', self.reference)

    def test_unknown_code_raises(self):
        service = IndexService()

        with self.assertRaises(IndexTypeNotFound):
            service.get_value('DOES-NOT-EXIST', self.reference)

    def test_normalize_reference_date_anchors_to_first_of_month(self):
        self.assertEqual(normalize_reference_date(date(2024, 4, 15)), date(2024, 4, 1))

    def test_unique_constraint_prevents_duplicate_value(self):
        IndexValue.objects.create(
            index_type=self.inpc,
            reference_date=self.reference,
            value=Decimal('0.22'),
        )
        with self.assertRaises(Exception):
            IndexValue.objects.create(
                index_type=self.inpc,
                reference_date=self.reference,
                value=Decimal('0.99'),
            )


# ---------------------------------------------------------------------------
# IndexService — bulk_import
# ---------------------------------------------------------------------------


class BulkImportTests(TestCase):
    def setUp(self):
        self.inpc = IndexType.objects.get(code='INPC')
        self.selic = IndexType.objects.get(code='SELIC')

    def _ibge_payload(self, value='0.38'):
        return [{
            'resultados': [{
                'series': [{'serie': {'202404': value}}],
            }],
        }]

    def test_month_range_generates_all_months(self):
        months = list(_month_range(date(2024, 1, 1), date(2024, 3, 1)))
        self.assertEqual(len(months), 3)
        self.assertEqual(months[0], date(2024, 1, 1))
        self.assertEqual(months[2], date(2024, 3, 1))

    def test_month_range_crosses_year_boundary(self):
        months = list(_month_range(date(2023, 12, 1), date(2024, 2, 1)))
        self.assertEqual(len(months), 3)
        self.assertEqual(months[0], date(2023, 12, 1))
        self.assertEqual(months[1], date(2024, 1, 1))
        self.assertEqual(months[2], date(2024, 2, 1))

    def test_bulk_import_skips_existing_values(self):
        IndexValue.objects.create(
            index_type=self.inpc,
            reference_date=date(2024, 4, 1),
            value=Decimal('0.22'),
        )
        service = IndexService(
            ibge_client=IBGEClient(http=_FakeHttp(payload=self._ibge_payload('0.50'))),
            bcb_client=BCBClient(http=_FakeHttp(payload=[{'data': '01/04/2024', 'valor': '0.92'}])),
        )
        result = service.bulk_import(date(2024, 4, 1), date(2024, 4, 1))

        self.assertEqual(result['skipped'], 1)
        self.assertEqual(result['created'], 4)
        self.assertEqual(result['errors'], 0)

    def test_bulk_import_fetches_missing_values(self):
        service = IndexService(
            ibge_client=IBGEClient(http=_FakeHttp(payload=self._ibge_payload('0.45'))),
            bcb_client=BCBClient(http=_FakeHttp(payload=[{'data': '01/04/2024', 'valor': '0.92'}])),
        )
        result = service.bulk_import(date(2024, 4, 1), date(2024, 4, 1))

        self.assertEqual(result['created'], 5)
        self.assertEqual(result['skipped'], 0)
        self.assertEqual(result['total'], 5)

    def test_bulk_import_with_progress_callback(self):
        progress_calls = []

        def on_progress(processed, total, created, skipped, errors):
            progress_calls.append((processed, total, created, skipped, errors))

        service = IndexService(
            ibge_client=IBGEClient(http=_FakeHttp(payload=self._ibge_payload('0.45'))),
            bcb_client=BCBClient(http=_FakeHttp(payload=[{'data': '01/04/2024', 'valor': '0.92'}])),
        )
        service.bulk_import(date(2024, 4, 1), date(2024, 4, 1), progress_callback=on_progress)

        self.assertTrue(len(progress_calls) > 0)
        self.assertEqual(progress_calls[-1][0], 5)

    def test_get_status_returns_counts_per_code(self):
        IndexValue.objects.create(
            index_type=self.selic,
            reference_date=date(2024, 4, 1),
            value=Decimal('0.92'),
        )
        IndexValue.objects.create(
            index_type=self.selic,
            reference_date=date(2024, 5, 1),
            value=Decimal('0.95'),
        )
        service = IndexService()
        status = service.get_status()
        self.assertEqual(status.get('SELIC', 0), 2)
        self.assertEqual(status.get('INPC', 0), 0)


# ---------------------------------------------------------------------------
# Progress tracking
# ---------------------------------------------------------------------------


class ProgressTrackingTests(TestCase):
    def test_set_and_get_progress(self):
        set_import_progress(999, {'running': True, 'percent': 50})
        result = get_import_progress(999)
        self.assertEqual(result['percent'], 50)
        clear_import_progress(999)

    def test_clear_progress(self):
        set_import_progress(998, {'running': True})
        clear_import_progress(998)
        self.assertIsNone(get_import_progress(998))

    def test_get_nonexistent_progress(self):
        self.assertIsNone(get_import_progress(12345))


# ---------------------------------------------------------------------------
# ImportIndicesView
# ---------------------------------------------------------------------------


class ImportIndicesViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='testuser', password='testpass123')

    def test_login_required(self):
        response = self.client.get('/indices/importar/')
        self.assertEqual(response.status_code, 302)

    def test_get_returns_status(self):
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get('/indices/importar/')
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertFalse(data['running'])
        self.assertIn('INPC', data['status'])

    @patch('indices.views.IndexService')
    def test_post_starts_import_and_returns_running(self, MockService):
        self.client.login(username='testuser', password='testpass123')
        mock_service = MockService.return_value
        mock_service.bulk_import.return_value = {
            'created': 5, 'skipped': 0, 'errors': 0, 'total': 5
        }

        response = self.client.post(
            '/indices/importar/',
            data=json.dumps({'start': '2024-01', 'end': '2024-03'}),
            content_type='application/json',
        )
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertTrue(data['running'])

    def test_post_with_invalid_dates_returns_400(self):
        self.client.login(username='testuser', password='testpass123')
        response = self.client.post(
            '/indices/importar/',
            data=json.dumps({'start': 'invalid', 'end': '2024-03'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

    def test_get_while_running_returns_progress(self):
        self.client.login(username='testuser', password='testpass123')
        set_import_progress(self.user.pk, {
            'running': True,
            'processed': 10,
            'total': 100,
            'created': 8,
            'skipped': 1,
            'errors': 1,
            'percent': 10,
        })
        response = self.client.get('/indices/importar/')
        data = response.json()
        self.assertTrue(data['running'])
        self.assertEqual(data['percent'], 10)
        clear_import_progress(self.user.pk)