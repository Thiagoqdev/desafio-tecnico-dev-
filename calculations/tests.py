'''Tests for the calculations module: models, engine, edge cases.

Determinism is tested by running the same inputs through the engine
twice and asserting identical outputs (RNF12).
'''

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from indices.models import IndexType, IndexValue
from .models import Calculation, CalculationStep, Installment
from .services import CalculationEngine, CalculationError


PRECISION = Decimal('0.01')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_index_values():
    '''Create a small range of monthly index values so the engine has data.'''
    ipca = IndexType.objects.get(code='IPCA')
    selic = IndexType.objects.get(code='SELIC')
    ipcae = IndexType.objects.get(code='IPCA-E')
    inpc = IndexType.objects.get(code='INPC')

    months = []
    for year in range(2021, 2026):
        for month in range(1, 13):
            months.append(date(year, month, 1))

    for m in months:
        IndexValue.objects.get_or_create(
            index_type=ipca,
            reference_date=m,
            defaults={'value': Decimal('0.39750000')},
        )
        IndexValue.objects.get_or_create(
            index_type=selic,
            reference_date=m,
            defaults={'value': Decimal('0.89000000')},
        )
        IndexValue.objects.get_or_create(
            index_type=ipcae,
            reference_date=m,
            defaults={'value': Decimal('0.35000000')},
        )
        IndexValue.objects.get_or_create(
            index_type=inpc,
            reference_date=m,
            defaults={'value': Decimal('0.42000000')},
        )


class _BaseCalculationTest(TestCase):
    '''Base class that seeds indices and sets up a user.'''

    @classmethod
    def setUpTestData(cls):
        _seed_index_values()
        cls.user = User.objects.create_user(username='testuser', password='test')
        cls.engine = CalculationEngine()

    def _basic_data(self, **overrides):
        defaults = {
            'base_value': Decimal('10000.00'),
            'start_term': date(2022, 1, 15),
            'end_term': date(2022, 12, 31),
            'index_selection_mode': Calculation.INDEX_AUTO,
            'manual_index': None,
            'interest_enabled': True,
            'attorney_fee_percent': Decimal('0'),
            'installment_mode': Calculation.INSTALLMENT_SINGLE,
            'rpv_issued': False,
            'rpv_issue_date': None,
            'installments': [],
        }
        for key, value in overrides.items():
            defaults[key] = value
        return defaults


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class CalculationModelTests(_BaseCalculationTest):

    def test_calculation_has_timestamps(self):
        calc = Calculation.objects.create(
            user=self.user,
            base_value=Decimal('1000'),
            start_term=date(2022, 1, 1),
            end_term=date(2022, 12, 31),
        )
        self.assertIsNotNone(calc.created_at)
        self.assertIsNotNone(calc.updated_at)

    def test_calculation_default_status_is_draft(self):
        calc = Calculation.objects.create(
            user=self.user,
            base_value=Decimal('1000'),
            start_term=date(2022, 1, 1),
            end_term=date(2022, 12, 31),
        )
        self.assertEqual(calc.status, Calculation.STATUS_DRAFT)

    def test_installment_ordering(self):
        calc = Calculation.objects.create(
            user=self.user,
            base_value=Decimal('1000'),
            start_term=date(2022, 1, 1),
            end_term=date(2022, 12, 31),
        )
        Installment.objects.create(calculation=calc, order=1, value=Decimal('1000'))
        Installment.objects.create(calculation=calc, order=2, value=Decimal('500'), same_as_first=False)

        installments = list(calc.installments.order_by('order'))
        self.assertEqual(len(installments), 2)
        self.assertEqual(installments[0].order, 1)
        self.assertEqual(installments[1].order, 2)
        self.assertFalse(installments[1].same_as_first)

    def test_calculation_step_is_created_with_all_fields(self):
        calc = Calculation.objects.create(
            user=self.user,
            base_value=Decimal('1000'),
            start_term=date(2022, 1, 1),
            end_term=date(2022, 12, 31),
        )
        step = CalculationStep.objects.create(
            calculation=calc,
            installment_order=1,
            step_order=1,
            description='Test step',
            period_start=date(2022, 1, 1),
            period_end=date(2022, 1, 31),
            applied_index='SELIC',
            factor=Decimal('1.00890000'),
            interest_amount=Decimal('0'),
            base_value=Decimal('1000.00'),
            subtotal=Decimal('1008.90'),
        )
        self.assertIsNotNone(step.created_at)
        self.assertEqual(step.calculation_id, calc.pk)


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


class CalculationValidationTests(_BaseCalculationTest):

    def test_rejects_start_after_end(self):
        data = self._basic_data(
            start_term=date(2023, 12, 31),
            end_term=date(2023, 1, 1),
        )
        with self.assertRaises(CalculationError):
            self.engine.calculate(self.user, data)

    def test_rejects_before_plano_real(self):
        data = self._basic_data(
            start_term=date(1994, 6, 1),
            end_term=date(1994, 12, 1),
        )
        with self.assertRaises(CalculationError):
            self.engine.calculate(self.user, data)

    def test_rejects_zero_base_value(self):
        data = self._basic_data(base_value=Decimal('0'))
        with self.assertRaises(CalculationError):
            self.engine.calculate(self.user, data)

    def test_rejects_negative_attorney_fee(self):
        data = self._basic_data(attorney_fee_percent=Decimal('-5'))
        with self.assertRaises(CalculationError):
            self.engine.calculate(self.user, data)

    def test_rejects_attorney_fee_over_100(self):
        data = self._basic_data(attorney_fee_percent=Decimal('150'))
        with self.assertRaises(CalculationError):
            self.engine.calculate(self.user, data)

    def test_rejects_rpv_without_date(self):
        data = self._basic_data(rpv_issued=True, rpv_issue_date=None)
        self.assertTrue(data.get('rpv_issued'), f'Expected True but got {data.get("rpv_issued")!r}')
        with self.assertRaises(CalculationError):
            self.engine.calculate(self.user, data)

    def test_rejects_rpv_date_outside_interval(self):
        data = self._basic_data(
            rpv_issued=True,
            rpv_issue_date=date(2020, 1, 1),
        )
        with self.assertRaises(CalculationError):
            self.engine.calculate(self.user, data)

    def test_rejects_manual_without_index(self):
        data = self._basic_data(
            index_selection_mode=Calculation.INDEX_MANUAL,
            manual_index=None,
        )
        with self.assertRaises(CalculationError):
            self.engine.calculate(self.user, data)


# ---------------------------------------------------------------------------
# Installment expansion tests
# ---------------------------------------------------------------------------


class InstallmentExpansionTests(_BaseCalculationTest):

    def test_single_installment(self):
        data = self._basic_data()
        result = CalculationEngine._expand_installments(data)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['value'], Decimal('10000.00'))
        self.assertEqual(result[0]['order'], 1)

    def test_multiple_equal(self):
        data = self._basic_data(
            installment_mode=Calculation.INSTALLMENT_MULTIPLE,
            installments=[
                {'order': 1, 'value': Decimal('10000'), 'same_as_first': True},
                {'order': 2, 'value': Decimal('10000'), 'same_as_first': True},
                {'order': 3, 'value': Decimal('10000'), 'same_as_first': True},
            ],
        )
        result = CalculationEngine._expand_installments(data)
        self.assertEqual(len(result), 3)
        for entry in result:
            self.assertEqual(entry['value'], Decimal('10000.00'))

    def test_multiple_distinct(self):
        data = self._basic_data(
            installment_mode=Calculation.INSTALLMENT_MULTIPLE,
            installments=[
                {'order': 1, 'value': Decimal('10000'), 'same_as_first': True},
                {'order': 2, 'value': Decimal('2500'), 'same_as_first': False},
                {'order': 3, 'value': Decimal('15000'), 'same_as_first': False},
            ],
        )
        result = CalculationEngine._expand_installments(data)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]['value'], Decimal('10000.00'))
        self.assertEqual(result[1]['value'], Decimal('2500.00'))
        self.assertEqual(result[2]['value'], Decimal('15000.00'))


# ---------------------------------------------------------------------------
# Computation tests (auto mode — full engine)
# ---------------------------------------------------------------------------


class CalculationEngineAutoModeTests(_BaseCalculationTest):

    def test_single_installment_produces_steps_and_total(self):
        data = self._basic_data(
            start_term=date(2022, 1, 1),
            end_term=date(2022, 12, 31),
        )
        result = self.engine.calculate(self.user, data)

        calc = result['calculation']
        self.assertEqual(calc.status, Calculation.STATUS_COMPUTED)
        self.assertIsNotNone(calc.result_total)
        self.assertGreater(calc.result_total, data['base_value'])

        steps = list(calc.steps.order_by('step_order'))
        self.assertGreater(len(steps), 0)
        for step in steps:
            self.assertIsNotNone(step.factor)
            self.assertGreater(step.factor, Decimal('0'))

    def test_same_input_produces_same_output(self):
        data = self._basic_data(
            start_term=date(2022, 1, 1),
            end_term=date(2022, 12, 31),
        )
        result1 = self.engine.calculate(self.user, data)
        result2 = self.engine.calculate(self.user, data)
        self.assertEqual(result1['total'], result2['total'])

    def test_can_create_multiple_calculations_for_same_user(self):
        data = self._basic_data(start_term=date(2022, 1, 1), end_term=date(2022, 3, 31))
        self.engine.calculate(self.user, data)
        self.engine.calculate(self.user, data)
        self.assertEqual(
            Calculation.objects.filter(user=self.user, status=Calculation.STATUS_COMPUTED).count(),
            2,
        )

    def test_non_cumulation_creates_unified_segments(self):
        data = self._basic_data(
            start_term=date(2022, 1, 1),
            end_term=date(2022, 12, 31),
        )
        result = self.engine.calculate(self.user, data)
        calc = result['calculation']

        has_unified = False
        for step in calc.steps.all():
            if 'unificados' in step.description.lower():
                has_unified = True
                self.assertEqual(step.interest_amount, Decimal('0'))
        self.assertTrue(has_unified, 'Deve haver segmentos unificados sem cobrança de juros.')

    def test_attorney_fees_applied(self):
        data = self._basic_data(
            start_term=date(2022, 1, 1),
            end_term=date(2022, 12, 31),
            attorney_fee_percent=Decimal('10'),
        )
        result = self.engine.calculate(self.user, data)
        calc = result['calculation']

        fee_steps = [
            step for step in calc.steps.all()
            if 'Honorários' in step.description
        ]
        self.assertEqual(len(fee_steps), 1)
        self.assertGreater(fee_steps[0].interest_amount, Decimal('0'))

    def test_no_attorney_fees_when_zero(self):
        data = self._basic_data(attorney_fee_percent=Decimal('0'))
        result = self.engine.calculate(self.user, data)
        calc = result['calculation']

        fee_steps = [
            step for step in calc.steps.all()
            if 'Honorários' in step.description
        ]
        self.assertEqual(len(fee_steps), 0)


# ---------------------------------------------------------------------------
# Manual mode tests
# ---------------------------------------------------------------------------


class CalculationEngineManualModeTests(_BaseCalculationTest):

    def test_manual_selic_produces_valid_result(self):
        selic = IndexType.objects.get(code='SELIC')
        data = self._basic_data(
            index_selection_mode=Calculation.INDEX_MANUAL,
            manual_index=selic,
            start_term=date(2022, 1, 1),
            end_term=date(2022, 12, 31),
            interest_enabled=False,
        )
        result = self.engine.calculate(self.user, data)

        self.assertIsNotNone(result['calculation'].result_total)
        self.assertGreater(result['calculation'].result_total, data['base_value'])

    def test_manual_mode_single_segment(self):
        selic = IndexType.objects.get(code='SELIC')
        data = self._basic_data(
            index_selection_mode=Calculation.INDEX_MANUAL,
            manual_index=selic,
            start_term=date(2022, 1, 1),
            end_term=date(2022, 6, 30),
            interest_enabled=False,
        )
        result = self.engine.calculate(self.user, data)
        calc = result['calculation']

        steps = list(calc.steps.order_by('step_order'))
        self.assertEqual(len(steps), 1)
        self.assertIn('manual', steps[0].description.lower())


# ---------------------------------------------------------------------------
# RPV / Precatório tests
# ---------------------------------------------------------------------------


class CalculationEngineRPVTests(_BaseCalculationTest):

    def test_rpv_issued_splits_segments(self):
        data = self._basic_data(
            start_term=date(2022, 1, 1),
            end_term=date(2022, 12, 31),
            rpv_issued=True,
            rpv_issue_date=date(2022, 6, 15),
        )
        result = self.engine.calculate(self.user, data)
        calc = result['calculation']

        has_rpv_step = False
        for step in calc.steps.order_by('step_order'):
            if 'RPV' in step.description:
                has_rpv_step = True
                self.assertIn('IPCA', step.description)
                self.assertIn('limitado', step.description.lower())
        self.assertTrue(has_rpv_step, 'Deve haver etapa de RPV/Precatório na memória.')

    def test_rpv_issue_date_at_start(self):
        data = self._basic_data(
            start_term=date(2022, 1, 1),
            end_term=date(2022, 12, 31),
            rpv_issued=True,
            rpv_issue_date=date(2022, 1, 1),
        )
        result = self.engine.calculate(self.user, data)
        self.assertIsNotNone(result['calculation'].result_total)

    def test_rpv_issue_date_at_end(self):
        data = self._basic_data(
            start_term=date(2022, 1, 1),
            end_term=date(2022, 12, 31),
            rpv_issued=True,
            rpv_issue_date=date(2022, 12, 31),
        )
        result = self.engine.calculate(self.user, data)
        self.assertIsNotNone(result['calculation'].result_total)

    def test_rpv_same_input_same_output(self):
        data = self._basic_data(
            start_term=date(2022, 1, 1),
            end_term=date(2022, 12, 31),
            rpv_issued=True,
            rpv_issue_date=date(2022, 6, 15),
        )
        result1 = self.engine.calculate(self.user, data)
        result2 = self.engine.calculate(self.user, data)
        self.assertEqual(result1['total'], result2['total'])


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


class CalculationEngineEdgeCaseTests(_BaseCalculationTest):

    def test_single_day_interval(self):
        data = self._basic_data(
            start_term=date(2022, 6, 15),
            end_term=date(2022, 6, 15),
            interest_enabled=False,
        )
        result = self.engine.calculate(self.user, data)
        self.assertIsNotNone(result['calculation'].result_total)

    def test_interest_disabled(self):
        data = self._basic_data(
            start_term=date(2022, 1, 1),
            end_term=date(2022, 12, 31),
            interest_enabled=False,
        )
        result = self.engine.calculate(self.user, data)
        calc = result['calculation']

        for step in calc.steps.all():
            self.assertEqual(step.interest_amount, Decimal('0'))

    def test_ec_113_to_ec_136_transition(self):
        data = self._basic_data(
            start_term=date(2025, 6, 1),
            end_term=date(2025, 12, 31),
        )
        result = self.engine.calculate(self.user, data)
        calc = result['calculation']

        steps = list(calc.steps.order_by('step_order'))
        codes = [step.applied_index for step in steps]
        self.assertIn('SELIC', codes)
        self.assertIn('IPCA', codes)

    def test_cross_ec_113_boundary(self):
        data = self._basic_data(
            start_term=date(2021, 6, 1),
            end_term=date(2022, 6, 30),
        )
        result = self.engine.calculate(self.user, data)
        calc = result['calculation']

        steps = list(calc.steps.order_by('step_order'))
        codes = {step.applied_index for step in steps}
        self.assertIn('IPCA-E', codes)
        self.assertIn('SELIC', codes)

    def test_multiple_installments_aggregate_correctly(self):
        selic = IndexType.objects.get(code='SELIC')
        data = self._basic_data(
            base_value=Decimal('5000'),
            index_selection_mode=Calculation.INDEX_MANUAL,
            manual_index=selic,
            start_term=date(2022, 1, 1),
            end_term=date(2022, 6, 30),
            installment_mode=Calculation.INSTALLMENT_MULTIPLE,
            interest_enabled=False,
            installments=[
                {'order': 1, 'value': Decimal('5000'), 'same_as_first': True},
                {'order': 2, 'value': Decimal('3000'), 'same_as_first': False},
                {'order': 3, 'value': Decimal('7000'), 'same_as_first': False},
            ],
        )
        result = self.engine.calculate(self.user, data)
        calc = result['calculation']

        installments = list(calc.installments.order_by('order'))
        self.assertEqual(len(installments), 3)
        self.assertEqual(installments[0].value, Decimal('5000'))
        self.assertEqual(installments[1].value, Decimal('3000'))
        self.assertEqual(installments[2].value, Decimal('7000'))

        self.assertIsNotNone(calc.result_total)
        self.assertGreater(calc.result_total, Decimal('15000'))


# ---------------------------------------------------------------------------
# CJF table factor test
# ---------------------------------------------------------------------------


class CJFFactorTests(TestCase):

    def setUp(self):
        self.cjf = IndexType.objects.get(code='CJF')

        self.engine = CalculationEngine()

    def test_cjf_factor_division(self):
        IndexValue.objects.create(
            index_type=self.cjf,
            reference_date=date(2023, 12, 1),
            value=Decimal('1.05000000'),
        )
        IndexValue.objects.create(
            index_type=self.cjf,
            reference_date=date(2024, 6, 1),
            value=Decimal('1.10000000'),
        )

        factor = self.engine._cjf_factor(date(2024, 1, 1), date(2024, 6, 1))
        self.assertEqual(factor, Decimal('1.10000000') / Decimal('1.05000000'))


# ---------------------------------------------------------------------------
# Integration tests — full HTTP flow
# ---------------------------------------------------------------------------


class CalculationFormIntegrationTests(TestCase):
    '''Test the full form → calculation → result HTTP lifecycle.'''

    @classmethod
    def setUpTestData(cls):
        _seed_index_values()
        cls.user = User.objects.create_user(username='inttest', password='test')

    def setUp(self):
        self.client.force_login(self.user)

    def _post_calculation(self, **overrides):
        '''Submit a valid calculation form and return the response.'''
        data = {
            'base_value': '10000.00',
            'start_term': '2022-01-01',
            'end_term': '2022-12-31',
            'index_selection_mode': 'auto',
            'manual_index': '',
            'interest_enabled': 'on',
            'attorney_fee_percent': '0',
            'installment_mode': 'single',
            'rpv_issued': '',

            'installments-TOTAL_FORMS': '1',
            'installments-INITIAL_FORMS': '0',
            'installments-MIN_NUM_FORMS': '0',
            'installments-MAX_NUM_FORMS': '24',
            'installments-0-same_as_first': 'on',
            'installments-0-value': '',
        }
        data.update(overrides)
        return self.client.post(reverse('calculations:create'), data, follow=False)

    def test_get_form_returns_200(self):
        response = self.client.get(reverse('calculations:create'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Valor base')
        self.assertContains(response, 'Termo inicial')

    def test_get_form_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse('calculations:create'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('contas/entrar/', response.url)

    def test_post_valid_shows_form_invalid_returns_200(self):
        '''Posting partial/invalid data re-renders the form.'''
        response = self.client.post(reverse('calculations:create'), {
            'base_value': '',
            'start_term': '',
            'end_term': '',
        })
        self.assertEqual(response.status_code, 200)

    def test_post_valid_calculation_redirects_to_result(self):
        response = self._post_calculation()
        self.assertRedirects(response, f'/calculos/{Calculation.objects.latest("pk").pk}/')

    def test_result_page_contains_total_and_steps(self):
        self._post_calculation()
        calc = Calculation.objects.latest('pk')
        response = self.client.get(reverse('calculations:result', args=[calc.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Total')
        self.assertContains(response, 'Etapas')
        self.assertContains(response, 'R$')

    def test_result_404_for_other_user(self):
        self._post_calculation()
        calc = Calculation.objects.latest('pk')

        self.client.logout()
        other_user = User.objects.create_user(username='other', password='test')
        self.client.force_login(other_user)

        response = self.client.get(reverse('calculations:result', args=[calc.pk]))
        self.assertEqual(response.status_code, 404)

    def test_dashboard_shows_calculation_after_compute(self):
        self._post_calculation()
        response = self.client.get(reverse('accounts:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Cálculo #')

    def test_post_with_attorney_fees(self):
        response = self._post_calculation(attorney_fee_percent='10')
        calc = Calculation.objects.latest('pk')
        response = self.client.get(reverse('calculations:result', args=[calc.pk]))
        self.assertContains(response, 'Honorários')

    def test_post_with_rpv_issued(self):
        response = self._post_calculation(
            rpv_issued='on',
            rpv_issue_date='2022-06-15',
        )
        calc = Calculation.objects.latest('pk')
        response = self.client.get(reverse('calculations:result', args=[calc.pk]))
        self.assertContains(response, 'RPV')

    def test_post_with_manual_index(self):
        selic = IndexType.objects.get(code='SELIC')
        response = self._post_calculation(
            index_selection_mode='manual',
            manual_index=str(selic.pk),
            interest_enabled='',
        )
        self.assertEqual(Calculation.objects.count(), 1)

    def test_post_with_multiple_installments(self):
        data = {
            'base_value': '5000.00',
            'start_term': '2022-01-01',
            'end_term': '2022-06-30',
            'index_selection_mode': 'auto',
            'manual_index': '',
            'interest_enabled': '',
            'attorney_fee_percent': '0',
            'installment_mode': 'multiple',
            'rpv_issued': '',

            'installments-TOTAL_FORMS': '3',
            'installments-INITIAL_FORMS': '0',
            'installments-MIN_NUM_FORMS': '0',
            'installments-MAX_NUM_FORMS': '24',

            'installments-0-same_as_first': 'on',
            'installments-0-value': '5000',
            'installments-1-same_as_first': '',
            'installments-1-value': '3000',
            'installments-2-same_as_first': '',
            'installments-2-value': '7000',
        }
        response = self.client.post(reverse('calculations:create'), data, follow=False)
        self.assertEqual(response.status_code, 302)

        calc = Calculation.objects.latest('pk')
        self.assertEqual(calc.installments.count(), 3)

    def test_empty_dashboard_shows_empty_state(self):
        response = self.client.get(reverse('accounts:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Você ainda não realizou cálculos')

    def test_export_csv(self):
        self._post_calculation()
        calc = Calculation.objects.latest('pk')
        response = self.client.get(reverse('calculations:export', args=[calc.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        self.assertIn('juriscalc-calculo', response['Content-Disposition'])

    def test_export_csv_404_for_other_user(self):
        self._post_calculation()
        calc = Calculation.objects.latest('pk')
        self.client.logout()
        other_user = User.objects.create_user(username='other2', password='test')
        self.client.force_login(other_user)
        response = self.client.get(reverse('calculations:export', args=[calc.pk]))
        self.assertEqual(response.status_code, 404)

    def test_calculation_signal_cleanup_registered(self):
        from django.db.models.signals import post_delete
        from calculations.signals import cleanup_calculation_orphans
        receivers = [r[1]() for r in post_delete.receivers]
        fn_names = [r.__name__ for r in receivers if hasattr(r, '__name__')]
        self.assertIn('cleanup_calculation_orphans', fn_names)


# ---------------------------------------------------------------------------
# End-to-end flow tests
# ---------------------------------------------------------------------------


class EndToEndFlowTests(TestCase):
    '''Full flow: import sentence → pre-fill form → calculate → view result.'''

    @classmethod
    def setUpTestData(cls):
        _seed_index_values()
        cls.user = User.objects.create_user(username='e2etest', password='test')

    def setUp(self):
        self.client.force_login(self.user)

    def test_full_flow_manual_calculation_to_result(self):
        form_url = reverse('calculations:create')

        calc_data = {
            'base_value': '25000.00',
            'start_term': '2022-03-01',
            'end_term': '2022-12-31',
            'index_selection_mode': 'auto',
            'manual_index': '',
            'interest_enabled': 'on',
            'attorney_fee_percent': '5',
            'installment_mode': 'single',
            'rpv_issued': '',
            'installments-TOTAL_FORMS': '1',
            'installments-INITIAL_FORMS': '0',
            'installments-MIN_NUM_FORMS': '0',
            'installments-MAX_NUM_FORMS': '24',
            'installments-0-same_as_first': 'on',
            'installments-0-value': '',
        }

        post_response = self.client.post(form_url, calc_data, follow=False)
        self.assertEqual(post_response.status_code, 302)

        calc = Calculation.objects.latest('pk')
        self.assertEqual(calc.status, 'computed')
        self.assertEqual(calc.base_value, Decimal('25000.00'))
        self.assertEqual(calc.attorney_fee_percent, Decimal('5'))
        self.assertGreater(calc.result_total, calc.base_value)

        result_response = self.client.get(reverse('calculations:result', args=[calc.pk]))
        self.assertEqual(result_response.status_code, 200)
        self.assertContains(result_response, '25000')
        self.assertContains(result_response, 'Etapas')

        export_response = self.client.get(reverse('calculations:export', args=[calc.pk]))
        self.assertEqual(export_response.status_code, 200)
        csv_content = export_response.content.decode('utf-8')
        self.assertIn('Parcela', csv_content)
        self.assertIn('TOTAL', csv_content)

    def test_full_flow_form_prefill_from_interpreter(self):
        '''Simulate the pre-fill from interpreter via query parameters.'''
        form_url = (
            reverse('calculations:create')
            + '?base_value=30000'
            + '&start_term=2023-01-01'
            + '&end_term=2023-06-30'
            + '&index_selection_mode=auto'
            + '&attorney_fee_percent=10'
            + '&installment_mode=single'
        )
        response = self.client.get(form_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '30000')
        self.assertContains(response, '2023-01-01')
        self.assertContains(response, '2023-06-30')

