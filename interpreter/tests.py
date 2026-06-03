'''Tests for the interpreter module: graph, views and architectural
constraints.

All tests mock the LLM so no actual API call is performed. The tests
validate the DTO contract and verify the absence of calculation logic.
'''

import importlib
import json
from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

from .graph import (
    _build_extraction_prompt,
    _map_to_form,
    _parse_json_block,
    _to_date,
    _to_decimal_str,
    _validate,
    SentenceInterpreter,
)
from .models import SentenceInterpretation


# ---------------------------------------------------------------------------
# Mock LLM
# ---------------------------------------------------------------------------


def _mock_llm(response_text):
    '''Returns a GenericFakeChatModel that responds with `response_text`.'''
    from langchain_core.messages import AIMessage
    return GenericFakeChatModel(messages=iter([AIMessage(content=response_text)]))


# ---------------------------------------------------------------------------
# Unit tests — graph helpers
# ---------------------------------------------------------------------------


class ParseJsonBlockTests(TestCase):

    def test_plain_json(self):
        result = _parse_json_block('{"a": 1}')
        self.assertEqual(result, {'a': 1})

    def test_json_with_extra_text(self):
        result = _parse_json_block('Here is the data: {"b": 2}. Done.')
        self.assertEqual(result, {'b': 2})

    def test_invalid_json_raises(self):
        with self.assertRaises((ValueError, json.JSONDecodeError)):
            _parse_json_block('not json at all')


class DateHelperTests(TestCase):

    def test_to_date_iso_format(self):
        self.assertEqual(_to_date('2022-06-15'), date(2022, 6, 15))

    def test_to_date_br_format(self):
        self.assertEqual(_to_date('15/06/2022'), date(2022, 6, 15))

    def test_to_date_none(self):
        self.assertIsNone(_to_date(None))
        self.assertIsNone(_to_date(''))

    def test_to_decimal_str(self):
        self.assertEqual(_to_decimal_str('10000.50'), '10000.50')

    def test_to_decimal_str_none(self):
        self.assertIsNone(_to_decimal_str(None))
        self.assertIsNone(_to_decimal_str('abc'))


# ---------------------------------------------------------------------------
# Prompt tests
# ---------------------------------------------------------------------------


class PromptTests(TestCase):

    def test_prompt_includes_source_text(self):
        prompt = _build_extraction_prompt('Sentença de teste.')
        self.assertIn('Sentença de teste.', prompt)
        self.assertIn('base_value', prompt)
        self.assertIn('installments', prompt)


# ---------------------------------------------------------------------------
# Validate node tests (no LLM needed)
# ---------------------------------------------------------------------------


class ValidateNodeTests(TestCase):

    def test_inverted_dates_are_removed(self):
        from .graph import GraphState
        state = GraphState(source_text='test')
        state.raw_extraction = {
            'base_value': 1000,
            'start_term': '2024-12-31',
            'end_term': '2024-01-01',
        }
        _validate(state)
        self.assertNotIn('start_term', state.payload)
        self.assertNotIn('end_term', state.payload)

    def test_zero_base_value_removed(self):
        from .graph import GraphState
        state = GraphState(source_text='test')
        state.raw_extraction = {'base_value': 0}
        _validate(state)
        self.assertNotIn('base_value', state.payload)

    def test_valid_data_passes_through(self):
        from .graph import GraphState
        state = GraphState(source_text='test')
        state.raw_extraction = {
            'base_value': 10000,
            'start_term': '2022-01-01',
            'end_term': '2022-12-31',
        }
        result = _validate(state)
        payload = result['payload']
        self.assertEqual(payload['base_value'], 10000)
        self.assertEqual(payload['start_term'], '2022-01-01')


# ---------------------------------------------------------------------------
# Map-to-form tests
# ---------------------------------------------------------------------------


class MapToFormTests(TestCase):

    def test_dto_structure(self):
        from .graph import GraphState
        state = GraphState(source_text='test')
        state.payload = {
            'base_value': 10000,
            'start_term': '2022-01-01',
            'end_term': '2022-12-31',
            'index_selection_mode': 'auto',
            'interest_enabled': True,
            'attorney_fee_percent': 10,
            'installment_mode': 'single',
            'rpv_issued': False,
        }
        result = _map_to_form(state)
        dto = result['dto']

        self.assertEqual(dto['base_value'], '10000')
        self.assertEqual(dto['start_term'], '2022-01-01')
        self.assertEqual(dto['end_term'], '2022-12-31')
        self.assertEqual(dto['index_selection_mode'], 'auto')
        self.assertTrue(dto['interest_enabled'])
        self.assertEqual(dto['attorney_fee_percent'], '10')
        self.assertEqual(dto['installment_mode'], 'single')
        self.assertFalse(dto['rpv_issued'])
        self.assertIsNone(dto['rpv_issue_date'])

    def test_null_fields_become_none(self):
        from .graph import GraphState
        state = GraphState(source_text='test')
        state.payload = {}
        result = _map_to_form(state)
        dto = result['dto']

        self.assertIsNone(dto['base_value'])
        self.assertIsNone(dto['start_term'])
        self.assertIsNone(dto['end_term'])


# ---------------------------------------------------------------------------
# SentenceInterpreter tests (full graph with mocked LLM)
# ---------------------------------------------------------------------------


class SentenceInterpreterTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username='interpreter_test', password='test'
        )

    def test_interpret_returns_dto_with_mocked_llm(self):
        llm = _mock_llm(json.dumps({
            'base_value': 50000,
            'start_term': '2023-01-15',
            'end_term': '2023-12-31',
            'index_selection_mode': 'auto',
            'manual_index': None,
            'interest_enabled': True,
            'attorney_fee_percent': 10,
            'installment_mode': 'single',
            'rpv_issued': False,
            'rpv_issue_date': None,
            'installments': [],
        }))

        interpreter = SentenceInterpreter(llm=llm, model_name='test-mock')
        dto = interpreter.interpret('Condeno ao pagamento de R$ 50.000,00...')

        self.assertEqual(dto['base_value'], '50000')
        self.assertEqual(dto['start_term'], '2023-01-15')
        self.assertEqual(dto['end_term'], '2023-12-31')
        self.assertEqual(dto['index_selection_mode'], 'auto')
        self.assertTrue(dto['interest_enabled'])
        self.assertEqual(dto['attorney_fee_percent'], '10')
        self.assertEqual(dto['installment_mode'], 'single')

    def test_interpret_persists_record_for_authenticated_user(self):
        llm = _mock_llm(json.dumps({
            'base_value': 1000,
            'start_term': '2022-01-01',
            'end_term': '2022-06-30',
            'index_selection_mode': 'auto',
            'interest_enabled': True,
            'attorney_fee_percent': 0,
            'installment_mode': 'single',
            'rpv_issued': False,
            'installments': [],
        }))

        interpreter = SentenceInterpreter(llm=llm, model_name='test-mock')
        dto = interpreter.interpret('Texto de sentença.', user=self.user)

        self.assertIsNotNone(dto)
        record = SentenceInterpretation.objects.latest('pk')
        self.assertEqual(record.user, self.user)
        self.assertEqual(record.status, 'extracted')
        self.assertEqual(record.extracted_payload['base_value'], '1000')

    def test_interpret_with_rpv_fields(self):
        llm = _mock_llm(json.dumps({
            'base_value': 20000,
            'start_term': '2023-03-01',
            'end_term': '2024-03-01',
            'index_selection_mode': 'auto',
            'interest_enabled': True,
            'attorney_fee_percent': 0,
            'installment_mode': 'single',
            'rpv_issued': True,
            'rpv_issue_date': '2023-09-15',
            'installments': [],
        }))

        interpreter = SentenceInterpreter(llm=llm, model_name='test-mock')
        dto = interpreter.interpret('RPV emitido em 15/09/2023.')

        self.assertTrue(dto['rpv_issued'])
        self.assertEqual(dto['rpv_issue_date'], '2023-09-15')

    def test_interpret_invalid_json_handled_gracefully(self):
        llm = _mock_llm('This is not JSON at all.')
        interpreter = SentenceInterpreter(llm=llm, model_name='test-mock')
        dto = interpreter.interpret('Texto qualquer.')
        self.assertIsNotNone(dto)


# ---------------------------------------------------------------------------
# Architectural constraint tests
# ---------------------------------------------------------------------------


class ArchitecturalConstraintTests(TestCase):
    '''Verify that interpreter never imports calculation logic (RNF13).'''

    def test_interpreter_graph_does_not_import_calculation_engine(self):
        import importlib as _imp
        graph_module = _imp.import_module('interpreter.graph')
        source = _imp.import_module('inspect').getsource(graph_module)
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith(('#', '""')) or stripped.startswith("'"):
                continue
            if 'import' in stripped or 'from ' in stripped:
                self.assertNotIn('calculations.services', stripped)
                self.assertNotIn('CalculationEngine', stripped)

    def test_interpreter_views_does_not_import_calculation_engine(self):
        import importlib as _imp
        views_module = _imp.import_module('interpreter.views')
        source = _imp.import_module('inspect').getsource(views_module)
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith(('#', '""')) or stripped.startswith("'"):
                continue
            if 'import' in stripped or 'from ' in stripped:
                self.assertNotIn('calculations.services', stripped)
                self.assertNotIn('CalculationEngine', stripped)
        self.assertNotIn('calculations.models', source)

    def test_interpreter_views_does_not_import_calculation_engine(self):
        views_module = importlib.import_module('interpreter.views')
        source = importlib.import_module('inspect').getsource(views_module)
        self.assertNotIn('CalculationEngine', source)
        self.assertNotIn('calculations.services', source)


# ---------------------------------------------------------------------------
# View integration tests
# ---------------------------------------------------------------------------


class ImportSentenceViewTests(TestCase):
    '''HTTP-level tests for the import sentence view.'''

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='importtest', password='test')

    def setUp(self):
        self.client.force_login(self.user)

    def test_get_import_page_returns_200(self):
        response = self.client.get(reverse('interpreter:import'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Importar')

    def test_get_import_page_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse('interpreter:import'))
        self.assertEqual(response.status_code, 302)

    @override_settings(LLM_PROVIDER='', LLM_API_KEY='', LLM_MODEL='')
    def test_post_with_mock_llm_returns_dto(self):
        response = self.client.post(
            reverse('interpreter:import'),
            {'sentence_text': 'Condeno ao pagamento de R$ 10.000,00.'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertIn('payload', data)
        self.assertIsNotNone(data['payload'])

    def test_post_empty_text_returns_400(self):
        response = self.client.post(
            reverse('interpreter:import'),
            {'sentence_text': 'curto'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 400)

    def test_calculation_form_accepts_prefill_params(self):
        response = self.client.get(
            reverse('calculations:create')
            + '?base_value=50000&start_term=2023-01-01&end_term=2023-12-31'
            + '&index_selection_mode=auto&interest_enabled=true'
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '50000')
