'''LangGraph graph for sentence interpretation.

The graph has five nodes that execute sequentially:
  1. `ingest`    — normalizes the raw text
  2. `extract`   — prompts the LLM to extract structured fields
  3. `validate`  — checks coherence of the extracted payload
  4. `map_to_form` — converts the payload into the form DTO
  5. `finalize`  — persists SentenceInterpretation and returns the DTO

Architectural contract (RNF13):
    This module does NOT import any calculation engine. The LLM only
    extracts and structures data — it never executes a calculation.
'''

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from django.conf import settings
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph

from .models import SentenceInterpretation


MAX_SOURCE_LENGTH = 16_000


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

@dataclass
class GraphState:
    '''Mutable state that flows through the interpreter graph.'''

    source_text: str = ''
    source_text_original: str = ''
    raw_extraction: dict = field(default_factory=dict)
    payload: dict = field(default_factory=dict)
    dto: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    confidence_notes: str = ''
    interpretation_id: int | None = None


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------


def build_graph() -> StateGraph:
    '''Assemble and return a compiled LangGraph StateGraph.

    The caller is responsible for providing the LLM instance via the
    `llm` kwarg when invoking the graph. This keeps the provider
    configurable (S2).
    '''
    builder = StateGraph(GraphState)
    builder.add_node('ingest', _ingest)
    builder.add_node('extract', _extract)
    builder.add_node('validate', _validate)
    builder.add_node('map_to_form', _map_to_form)
    builder.add_node('finalize', _finalize)

    builder.set_entry_point('ingest')
    builder.add_edge('ingest', 'extract')
    builder.add_edge('extract', 'validate')
    builder.add_edge('validate', 'map_to_form')
    builder.add_edge('map_to_form', 'finalize')
    builder.set_finish_point('finalize')

    return builder.compile()


# ---------------------------------------------------------------------------
# Node implementations
# ---------------------------------------------------------------------------


def _ingest(state: GraphState) -> dict:
    '''Normalize and truncate raw text.'''
    text = state.source_text.strip()
    return {
        'source_text_original': text,
        'source_text': text[:MAX_SOURCE_LENGTH],
    }


def _extract(state: GraphState, config: RunnableConfig) -> dict:
    '''Invoke the LLM to extract structured data from the sentence.'''
    llm: BaseChatModel = config['configurable']['llm']
    model_name: str = config['configurable'].get('model_name', 'unknown')

    from langchain_core.messages import HumanMessage

    prompt = _build_extraction_prompt(state.source_text)
    response = llm.invoke([HumanMessage(content=prompt)])
    raw_text = response.content if hasattr(response, 'content') else str(response)

    raw_extraction = {}
    errors = []
    try:
        raw_extraction = _parse_json_block(raw_text)
    except (ValueError, json.JSONDecodeError):
        errors.append('A LLM não retornou JSON válido.')

    confidence_notes = (
        f'Modelo: {model_name}. '
        f'Campos extraídos: {len(raw_extraction)}.'
    )
    return {
        'raw_extraction': raw_extraction,
        'errors': errors,
        'confidence_notes': confidence_notes,
    }


def _validate(state: GraphState) -> dict:
    '''Coherence checks on the extracted payload — never calculates.'''
    payload = dict(state.raw_extraction)
    notes: list[str] = []
    errors = list(state.errors)

    if payload.get('start_term') and payload.get('end_term'):
        start = _to_date(payload['start_term'])
        end = _to_date(payload['end_term'])
        if start and end and start > end:
            errors.append('Termo inicial posterior ao termo final — ignorando datas.')
            payload.pop('start_term', None)
            payload.pop('end_term', None)

    if payload.get('rpv_issued') and not payload.get('rpv_issue_date'):
        notes.append('RPV/Precatório marcado mas data de emissão ausente.')

    bv = payload.get('base_value')
    if bv is not None:
        try:
            bv_dec = Decimal(str(bv))
            if bv_dec <= 0:
                payload.pop('base_value', None)
                notes.append('Valor base extraído é zero ou negativo — ignorado.')
        except (InvalidOperation, TypeError, ValueError):
            payload.pop('base_value', None)
            notes.append('Valor base extraído inválido — ignorado.')

    confidence_notes = state.confidence_notes
    if notes:
        confidence_notes += ' ' + ' '.join(notes)

    return {
        'payload': payload,
        'errors': errors,
        'confidence_notes': confidence_notes,
    }


def _map_to_form(state: GraphState) -> dict:
    '''Map the validated payload into the form DTO expected by the front-end.'''
    payload = state.payload

    return {'dto': {
        'base_value': _to_decimal_str(payload.get('base_value')),
        'start_term': _normalize_date_str(payload.get('start_term')),
        'end_term': _normalize_date_str(payload.get('end_term')),
        'index_selection_mode': payload.get('index_selection_mode'),
        'manual_index': payload.get('manual_index'),
        'interest_enabled': payload.get('interest_enabled', True),
        'attorney_fee_percent': _to_decimal_str(payload.get('attorney_fee_percent')),
        'installment_mode': payload.get('installment_mode'),
        'rpv_issued': bool(payload.get('rpv_issued', False)),
        'rpv_issue_date': _normalize_date_str(payload.get('rpv_issue_date')),
        'installments': payload.get('installments', []),
    }}


def _finalize(state: GraphState, config: RunnableConfig) -> dict:
    '''Persist the interpretation record (if user is available).'''
    user = config.get('configurable', {}).get('user')
    if user is not None and user.is_authenticated:
        SentenceInterpretation.objects.create(
            user=user,
            source_text=state.source_text_original,
            extracted_payload=state.dto,
            model_used=config.get('configurable', {}).get('model_name', ''),
            confidence_notes=state.confidence_notes,
            status=SentenceInterpretation.STATUS_EXTRACTED,
        )
    return {}


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


_EXTRACTION_PROMPT = '''\
Você é um assistente jurídico especializado em extrair dados de sentenças
judiciais brasileiras. Analise o texto da sentença abaixo e extraia as
informações solicitadas.

Retorne APENAS um objeto JSON válido com as seguintes chaves (use null
para campos não encontrados):

{{
  "base_value": number | null,
  "start_term": "YYYY-MM-DD" | null,
  "end_term": "YYYY-MM-DD" | null,
  "index_selection_mode": "auto" | "manual" | null,
  "manual_index": "INPC" | "IPCA-E" | "IPCA" | "IGP-M" | "SELIC" | "CJF" | null,
  "interest_enabled": true | false,
  "attorney_fee_percent": number | null,
  "installment_mode": "single" | "multiple" | null,
  "rpv_issued": true | false,
  "rpv_issue_date": "YYYY-MM-DD" | null,
  "installments": [
    {{"order": 1, "value": number, "same_as_first": true}},
    ...
  ]
}}

Regras de extração:
- base_value: o valor principal a ser atualizado.
- start_term / end_term: datas no formato YYYY-MM-DD.
- index_selection_mode: "auto" se a sentença menciona aplicação da
  legislação, "manual" se especifica um índice.
- manual_index: código do índice quando modo é manual.
- interest_enabled: false se a sentença menciona que NÃO há juros.
- attorney_fee_percent: percentual de honorários (ex.: 10, 15, 20).
- installment_mode: "multiple" se há mais de uma parcela.
- rpv_issued / rpv_issue_date: true e data YYYY-MM-DD se menciona
  emissão de RPV/Precatório.
- installments: array com valores de cada parcela (se múltiplas).

IMPORTANTE: retorne SOMENTE o JSON, sem explicações ou markdown.

Sentença:
{source_text}'''


def _build_extraction_prompt(source_text: str) -> str:
    return _EXTRACTION_PROMPT.format(source_text=source_text)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_json_block(raw: str) -> dict:
    '''Extract a JSON object from LLM output that may contain extra text.'''
    raw = raw.strip()
    json_match = re.search(r'\{.*\}', raw, re.DOTALL)
    if json_match:
        raw = json_match.group()
    return json.loads(raw)


def _to_date(value: Any) -> date | None:
    '''Coerce a value to a date, returning None on failure.'''
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%Y%m%d'):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
    return None


def _normalize_date_str(value: Any) -> str | None:
    '''Convert any date-like value to YYYY-MM-DD string, or None.'''
    d = _to_date(value)
    return d.isoformat() if d else None


def _to_decimal_str(value: Any) -> str | None:
    '''Convert to decimal string, returning None for invalid values.'''
    if value is None:
        return None
    try:
        d = Decimal(str(value))
        return str(d)
    except (InvalidOperation, TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class SentenceInterpreter:
    '''Public API for interpreting a sentence via the LangGraph graph.

    Usage::

        interpreter = SentenceInterpreter(llm=my_llm, model_name='gpt-4')
        dto = interpreter.interpret(sentence_text, user=request.user)
        # dto is a dict ready for the form pre-fill endpoint
    '''

    def __init__(self, llm: BaseChatModel, model_name: str = ''):
        self.llm = llm
        self.model_name = model_name
        self.graph = build_graph()

    def interpret(self, source_text: str, user=None) -> dict:
        '''Run the full graph and return the form DTO.'''
        initial = GraphState(source_text=source_text)
        config = {
            'configurable': {
                'llm': self.llm,
                'model_name': self.model_name,
                'user': user,
            }
        }
        final_state = self.graph.invoke(initial, config)
        return final_state['dto'] if isinstance(final_state, dict) else final_state.dto
