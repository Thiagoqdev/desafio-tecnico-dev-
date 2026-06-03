'''Deterministic calculation engine for monetary correction.

`CalculationEngine` implements the 10-step flow described in PRD
Section 9. Its only mutable side-effect is persisting `Calculation`
and `CalculationStep` rows. The engine is pure otherwise — same input
always produces the same output (RNF12).

The engine *never* imports from `interpreter` (RNF13).
'''

from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, localcontext

from django.db import transaction

from indices.services import IndexService
from legislation.resolver import LegislationResolver
from legislation.services import apply_ipca_plus_capped, monthly_factor_from_annual

from .models import Calculation, CalculationStep, Installment


PERCENT_DIVISOR = Decimal('100')
ONE_HUNDRED = Decimal('100')
EARLIEST_REFERENCE = date(1994, 7, 1)


class CalculationError(ValueError):
    '''Raised when input data is invalid or out of legal coverage.'''


class CalculationEngine:
    '''Deterministic engine for monetary correction calculations.

    Usage::

        engine = CalculationEngine()
        result = engine.calculate(user, data)
        # result == {'calculation': Calculation, 'total': Decimal, 'steps': [...]}
    '''

    def __init__(self, index_service=None):
        self.index_service = index_service or IndexService()
        self.resolver = LegislationResolver()

    # -------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------

    def calculate(self, user, data):
        '''Validate, compute and persist a full calculation.'''
        self._validate_input(data)
        installments_data = self._expand_installments(data)

        calculation = self._create_calculation(user, data)
        result_total = Decimal('0')

        with transaction.atomic():
            self._persist_installments(calculation, installments_data)
            step_order = 0

            for inst in installments_data:
                step_order, installment_result = self._compute_installment(
                    calculation, inst, step_order, data,
                )
                result_total += installment_result

            if data['attorney_fee_percent'] > 0:
                result_total = self._apply_attorney_fees(
                    calculation,
                    result_total,
                    data['attorney_fee_percent'],
                    step_order,
                )
                step_order += 1

            result_total = result_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_EVEN)
            calculation.result_total = result_total
            calculation.status = Calculation.STATUS_COMPUTED
            calculation.save(update_fields=('result_total', 'status'))

        return {
            'calculation': calculation,
            'total': result_total,
        }

    # -------------------------------------------------------------------
    # Validation
    # -------------------------------------------------------------------

    @staticmethod
    def _validate_input(data):
        '''Reject invalid or out-of-coverage input upfront (S3, S11).'''
        if data['start_term'] > data['end_term']:
            raise CalculationError('O termo inicial não pode ser posterior ao termo final.')

        if data['start_term'] < EARLIEST_REFERENCE:
            raise CalculationError(
                f'Datas anteriores a {EARLIEST_REFERENCE:%m/%Y} não são cobertas (S3). '
                f'Termo inicial informado: {data["start_term"]:%d/%m/%Y}.'
            )

        if data.get('base_value', Decimal('0')) <= 0:
            raise CalculationError('O valor base deve ser maior que zero.')

        attorney = data.get('attorney_fee_percent', Decimal('0'))
        if attorney < 0 or attorney > ONE_HUNDRED:
            raise CalculationError('O percentual de honorários deve estar entre 0 e 100.')

        if data.get('installment_mode') == Calculation.INSTALLMENT_MULTIPLE:
            installments = data.get('installments', [])
            if not installments or len(installments) < 2:
                raise CalculationError('Múltiplas parcelas requerem ao menos duas parcelas.')

            for inst in installments:
                if not inst.get('same_as_first', True) and inst.get('value', Decimal('0')) <= 0:
                    raise CalculationError('Cada parcela distinta deve ter valor maior que zero.')

        if data.get('rpv_issued'):
            rpv_date = data.get('rpv_issue_date')
            if rpv_date is None:
                raise CalculationError(
                    'A data de emissão do RPV/Precatório é obrigatória '
                    'quando a opção está marcada.'
                )
            if rpv_date < data['start_term'] or rpv_date > data['end_term']:
                raise CalculationError(
                    f'A data de emissão do RPV/Precatório ({rpv_date:%d/%m/%Y}) '
                    f'deve estar entre o termo inicial ({data["start_term"]:%d/%m/%Y}) '
                    f'e o termo final ({data["end_term"]:%d/%m/%Y}).'
                )

        if data.get('index_selection_mode') == Calculation.INDEX_MANUAL:
            if not data.get('manual_index'):
                raise CalculationError('O índice manual é obrigatório no modo manual.')

    # -------------------------------------------------------------------
    # Installment expansion
    # -------------------------------------------------------------------

    @staticmethod
    def _expand_installments(data):
        '''Expand single/multiple installments into a uniform list.

        Each entry: {'order': int, 'value': Decimal}
        '''
        mode = data['installment_mode']
        base = data['base_value']
        installments = data.get('installments', [])

        result = []
        if mode == Calculation.INSTALLMENT_SINGLE:
            result.append({'order': 1, 'value': base})
        else:
            for inst in installments:
                order = inst.get('order', 0)
                if inst.get('same_as_first', True):
                    value = base
                else:
                    value = inst.get('value', base)
                result.append({'order': order, 'value': value})
        return result

    # -------------------------------------------------------------------
    # Calculation per installment
    # -------------------------------------------------------------------

    def _compute_installment(self, calculation, inst, step_order, data):
        '''Compute one installment across all time segments. Returns (step_order, final_value).'''
        segments = self._resolve_segments(data)
        current_value = inst['value']
        order = inst['order']

        for seg in segments:
            factor = self._correction_factor(seg, data)
            index_code = seg.get('effective_index_code', '?')

            corrected = (current_value * factor).quantize(
                Decimal('0.00000001'), rounding=ROUND_HALF_EVEN
            )

            interest = Decimal('0')
            if not seg.get('is_unified', False) and data['interest_enabled']:
                interest = self._compute_interest(current_value, seg)
                interest = interest.quantize(Decimal('0.01'), rounding=ROUND_HALF_EVEN)

            subtotal = (corrected + interest).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_EVEN
            )

            step_order += 1
            self._create_step(
                calculation=calculation,
                installment_order=order,
                step_order=step_order,
                description=seg['description'],
                period_start=seg['start_date'],
                period_end=seg['end_date'],
                applied_index=index_code,
                factor=factor.quantize(Decimal('0.00000001'), rounding=ROUND_HALF_EVEN),
                interest_amount=interest,
                base_value=current_value,
                subtotal=subtotal,
            )

            current_value = subtotal

        return step_order, current_value

    def _resolve_segments(self, data):
        '''Obtain time segments from legislation resolver, overlaying RPV rules.

        Each segment is enriched with a `description` and `effective_index_code`.
        '''
        start = data['start_term']
        end = data['end_term']
        mode = data['index_selection_mode']

        if mode == Calculation.INDEX_MANUAL:
            manual_index = data['manual_index']
            return [{
                'start_date': start,
                'end_date': end,
                'mode': 'single_index',
                'extra_rate': None,
                'selic_cap_index': None,
                'effective_index_code': manual_index.code if hasattr(manual_index, 'code') else manual_index,
                'is_unified': False,
                'interest_mode': 'fixed_monthly',
                'monthly_rate': None,
                'description': (
                    f'Correção manual pelo índice {manual_index.code if hasattr(manual_index, "code") else manual_index} '
                    f'de {start:%d/%m/%Y} a {end:%d/%m/%Y}.'
                ),
            }]

        legislation_segments = self.resolver.resolve(start, end)

        if not data.get('rpv_issued') or data.get('rpv_issue_date') is None:
            return self._segments_from_legislation(legislation_segments)

        return self._segments_with_rpv(legislation_segments, data)

    def _segments_from_legislation(self, legislation_segments):
        '''Convert resolved legislation segments into engine-internal format.'''
        result = []
        for seg in legislation_segments:
            corr_mode = seg.correction_rule.mode
            extra_rate = seg.correction_rule.extra_rate
            cap_index = seg.correction_rule.selic_cap_index
            index_code = seg.correction_rule.index_type.code
            interest_mode = seg.interest_rule.mode
            monthly_rate = seg.interest_rule.monthly_rate
            unified = seg.is_unified

            description = self._build_description(
                seg.start_date, seg.end_date,
                index_code, corr_mode, extra_rate,
                unified, seg.correction_rule.legal_basis,
            )

            result.append({
                'start_date': seg.start_date,
                'end_date': seg.end_date,
                'mode': corr_mode,
                'extra_rate': extra_rate,
                'selic_cap_index': cap_index,
                'effective_index_code': index_code,
                'is_unified': unified,
                'interest_mode': interest_mode,
                'monthly_rate': monthly_rate,
                'description': description,
            })
        return result

    def _segments_with_rpv(self, legislation_segments, data):
        '''Split segments at rpv_issue_date, overriding correction after cut.'''
        rpv_date = data['rpv_issue_date']
        primary_segments = self._segments_from_legislation(legislation_segments)

        before = []
        after = []
        for seg in primary_segments:
            if seg['end_date'] < rpv_date:
                before.append(seg)
            elif seg['start_date'] >= rpv_date:
                after.append(seg)
            else:
                before_seg = dict(seg)
                before_seg['end_date'] = rpv_date - timedelta(days=1)
                before_seg['description'] = self._build_description(
                    before_seg['start_date'], before_seg['end_date'],
                    before_seg['effective_index_code'], before_seg['mode'],
                    before_seg['extra_rate'], before_seg['is_unified'],
                    '',
                )
                if before_seg['start_date'] <= before_seg['end_date']:
                    before.append(before_seg)

                after_seg = dict(seg)
                after_seg['start_date'] = rpv_date
                after_seg['mode'] = 'ipca_plus_capped'
                after_seg['extra_rate'] = Decimal('0.020000')
                after_seg['effective_index_code'] = 'IPCA'
                after_seg['selic_cap_index'] = 'SELIC'
                after_seg['is_unified'] = True
                after_seg['interest_mode'] = 'ipca_plus_capped'
                after_seg['monthly_rate'] = None
                after_seg['description'] = (
                    f'RPV/Precatório emitido: IPCA + 2% a.a. limitado à SELIC '
                    f'de {rpv_date:%d/%m/%Y} a {after_seg["end_date"]:%d/%m/%Y} '
                    f'(EC 136/2025, S11).'
                )
                if after_seg['start_date'] <= after_seg['end_date']:
                    after.append(after_seg)

        return before + after

    @staticmethod
    def _build_description(start, end, index_code, mode, extra_rate, unified, legal_basis):
        '''Build a human-readable description for a segment (pt-BR).'''
        base = f'Correção por {index_code} de {start:%d/%m/%Y} a {end:%d/%m/%Y}'
        if mode == 'ipca_plus_capped':
            pct = f'{(extra_rate or Decimal("0")) * 100:.0f}%' if extra_rate else '?'
            base += f' (+ {pct} a.a. limitado à SELIC)'
        if unified:
            base += ' (correção e juros unificados)'
        if legal_basis:
            base += f' — {legal_basis}'
        return base

    # -------------------------------------------------------------------
    # Correction factor per segment
    # -------------------------------------------------------------------

    def _correction_factor(self, seg, data):
        '''Compute the cumulative correction factor for a single segment.'''
        start = seg['start_date']
        end = seg['end_date']
        mode = seg['mode']

        if mode == 'single_index':
            if data.get('index_selection_mode') == Calculation.INDEX_MANUAL:
                index_code = data['manual_index'].code if hasattr(data['manual_index'], 'code') else data['manual_index']
            else:
                index_code = seg['effective_index_code']
            return self._cumulative_factor(index_code, start, end)

        if mode == 'ipca_plus_capped':
            ipca_factor = self._cumulative_factor('IPCA', start, end)
            selic_factor = self._cumulative_factor('SELIC', start, end)
            months = self._months_between(start, end)
            extra_factor = monthly_factor_from_annual(seg['extra_rate'] or Decimal('0.02'), months)
            return apply_ipca_plus_capped(ipca_factor, selic_factor, extra_factor)

        raise CalculationError(f'Modo de correção desconhecido: {mode}')

    # -------------------------------------------------------------------
    # Cumulative factor helpers
    # -------------------------------------------------------------------

    def _cumulative_factor(self, index_code, start, end):
        '''Compute the multiplicative correction factor over [start, end].'''
        if index_code == 'CJF':
            return self._cjf_factor(start, end)

        product = Decimal('1')
        monthly_values = self.index_service.get_values_range(index_code, start, end)
        for value in monthly_values.values():
            product *= Decimal('1') + value / PERCENT_DIVISOR
        return product

    def _cjf_factor(self, start, end):
        '''For CJF, the `value` field already holds the accumulated factor.
        The factor from start to end = factor_at(end) / factor_at(start - 1 month).
        '''
        factor_end = self.index_service.get_value('CJF', end)
        prev_month = date(start.year, start.month, 1) - timedelta(days=1)
        prev_month = date(prev_month.year, prev_month.month, 1)
        factor_start = self.index_service.get_value('CJF', prev_month)
        if factor_start == 0:
            raise CalculationError('Fator CJF de referência é zero.')
        return factor_end / factor_start

    @staticmethod
    def _months_between(start, end):
        '''Count inclusive months between two dates.'''
        return (end.year - start.year) * 12 + (end.month - start.month) + 1

    # -------------------------------------------------------------------
    # Interest computation
    # -------------------------------------------------------------------

    def _compute_interest(self, base_value, seg):
        '''Compute interest for a segment based on its interest rule.'''
        mode = seg['interest_mode']
        months = self._months_between(seg['start_date'], seg['end_date'])

        if mode == 'fixed_monthly':
            rate = seg['monthly_rate'] or Decimal('0.01')
            factor = self._compound_monthly(rate, months)
            return base_value * factor - base_value

        if mode == 'selic':
            selic_factor = self._cumulative_factor('SELIC', seg['start_date'], seg['end_date'])
            return base_value * selic_factor - base_value

        if mode == 'ipca_plus_capped':
            ipca_factor = self._cumulative_factor('IPCA', seg['start_date'], seg['end_date'])
            selic_factor = self._cumulative_factor('SELIC', seg['start_date'], seg['end_date'])
            extra_factor = monthly_factor_from_annual(Decimal('0.02'), months)
            combined = apply_ipca_plus_capped(ipca_factor, selic_factor, extra_factor)
            return base_value * combined - base_value

        return Decimal('0')

    @staticmethod
    def _compound_monthly(rate, months):
        '''(1 + rate) ^ months using Decimal extended precision.'''
        if months <= 0:
            return Decimal('1')
        m = Decimal(months)
        r = Decimal(rate)
        with localcontext() as ctx:
            ctx.prec = 50
            base = Decimal('1') + r
            return (base.ln() * m).exp()

    # -------------------------------------------------------------------
    # Attorney fees
    # -------------------------------------------------------------------

    def _apply_attorney_fees(self, calculation, subtotal, percent, step_order):
        '''Apply attorney fee percentage (S5) and add a step.'''
        fee_percent = Decimal(percent) / ONE_HUNDRED
        fee_amount = (subtotal * fee_percent).quantize(Decimal('0.01'), rounding=ROUND_HALF_EVEN)
        total = subtotal + fee_amount

        self._create_step(
            calculation=calculation,
            installment_order=0,
            step_order=step_order,
            description=(
                f'Honorários advocatícios: {percent}% '
                f'sobre R$ {subtotal:,.2f} = R$ {fee_amount:,.2f}.'
            ),
            period_start=calculation.end_term,
            period_end=calculation.end_term,
            applied_index='',
            factor=Decimal('1'),
            interest_amount=fee_amount,
            base_value=subtotal,
            subtotal=total,
        )
        return total

    # -------------------------------------------------------------------
    # Persistence
    # -------------------------------------------------------------------

    @staticmethod
    def _create_calculation(user, data):
        manual_index = data.get('manual_index')
        if not (manual_index and hasattr(manual_index, 'pk')):
            manual_index = None

        return Calculation.objects.create(
            user=user,
            base_value=data['base_value'],
            start_term=data['start_term'],
            end_term=data['end_term'],
            index_selection_mode=data['index_selection_mode'],
            manual_index=manual_index,
            interest_enabled=data.get('interest_enabled', True),
            attorney_fee_percent=data.get('attorney_fee_percent', 0),
            installment_mode=data['installment_mode'],
            rpv_issued=data.get('rpv_issued', False),
            rpv_issue_date=data.get('rpv_issue_date'),
            status=Calculation.STATUS_DRAFT,
        )

    @staticmethod
    def _persist_installments(calculation, installments_data):
        for inst in installments_data:
            Installment.objects.create(
                calculation=calculation,
                order=inst['order'],
                value=inst['value'],
                same_as_first=inst.get('same_as_first', True),
            )

    @staticmethod
    def _create_step(
        calculation,
        installment_order,
        step_order,
        description,
        period_start,
        period_end,
        applied_index,
        factor,
        interest_amount,
        base_value,
        subtotal,
    ):
        return CalculationStep.objects.create(
            calculation=calculation,
            installment_order=installment_order,
            step_order=step_order,
            description=description,
            period_start=period_start,
            period_end=period_end,
            applied_index=applied_index,
            factor=factor,
            interest_amount=interest_amount,
            base_value=base_value,
            subtotal=subtotal,
        )
