'''Class-based views for the calculations module.

CalculationCreateView — renders the form and, on POST, runs the
deterministic engine (engine is only called on explicit user action,
never automatically — RF13). On GET, query parameters from the
interpreter can pre-fill the form (RF12 — revisão humana obrigatória).

CalculationResultView — displays the computed total and the detailed
memory of calculation table.

CalculationExportView — exports the memory of calculation as CSV.
'''

import csv
import json

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import DetailView, FormView, View

from .forms import CalculationForm, InstallmentFormSet
from .models import Calculation
from .services import CalculationEngine, CalculationError
from indices.exceptions import IndexDataUnavailable


class CalculationCreateView(LoginRequiredMixin, FormView):
    '''Render the calculation form and execute the engine on POST.

    The engine is *not* triggered by GET or by any external component.
    It runs only when the user explicitly submits the form (RF13).

    Query-parameter pre-fill (from interpreter):
        /calculos/novo/?base_value=10000&start_term=2022-01-01&...
    '''

    template_name = 'calculations/form.html'
    form_class = CalculationForm

    def get_initial(self):
        '''Pre-fill form from query parameters set by the interpreter.'''
        from datetime import date as dt_date
        initial = super().get_initial()
        params = self.request.GET
        date_fields = {'start_term', 'end_term', 'rpv_issue_date'}
        mapping = {
            'base_value': 'base_value',
            'start_term': 'start_term',
            'end_term': 'end_term',
            'index_selection_mode': 'index_selection_mode',
            'manual_index': 'manual_index',
            'interest_enabled': 'interest_enabled',
            'attorney_fee_percent': 'attorney_fee_percent',
            'installment_mode': 'installment_mode',
            'rpv_issued': 'rpv_issued',
            'rpv_issue_date': 'rpv_issue_date',
        }
        for param, field in mapping.items():
            if param in params:
                val = params[param]
                if field in date_fields and val:
                    try:
                        initial[field] = dt_date.fromisoformat(val)
                    except (ValueError, TypeError):
                        initial[field] = val
                else:
                    initial[field] = val

        if 'installments' in params:
            try:
                initial['installments_json'] = params['installments']
            except (ValueError, TypeError):
                pass

        return initial

    INSTALLMENT_PREFIX = 'installments'

    def _bound_formset(self):
        '''Build the installment formset bound to POST data (None on GET).'''
        return InstallmentFormSet(
            self.request.POST if self.request.method == 'POST' else None,
            prefix=self.INSTALLMENT_PREFIX,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        prefilled_installments = None
        installments_json = self.request.GET.get('installments', '')
        if installments_json:
            try:
                prefilled_installments = json.loads(installments_json)
            except (json.JSONDecodeError, ValueError):
                prefilled_installments = None

        if prefilled_installments:
            context['installment_formset'] = InstallmentFormSet(
                initial=[{'same_as_first': i.get('same_as_first', True),
                          'value': i.get('value', '')}
                         for i in prefilled_installments],
                prefix=self.INSTALLMENT_PREFIX,
            )
        else:
            context['installment_formset'] = self._bound_formset()
        return context

    def form_valid(self, form):
        cleaned = form.cleaned_data
        installment_mode = cleaned.get('installment_mode', Calculation.INSTALLMENT_SINGLE)

        installment_formset = self._bound_formset()

        if installment_mode == Calculation.INSTALLMENT_MULTIPLE:
            if not installment_formset.is_valid():
                return self.form_invalid(form)

        data = self._build_engine_data(form, installment_formset, installment_mode)

        engine = CalculationEngine()
        try:
            result = engine.calculate(self.request.user, data)
        except CalculationError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        except IndexDataUnavailable as exc:
            form.add_error(
                None,
                f'Não há índice econômico disponível para parte do período informado: '
                f'{exc}. Alguns índices não cobrem períodos muito antigos (o IPCA-E, '
                f'usado na correção até 2021, só existe a partir de 05/2000). '
                f'Verifique as datas; persistindo, confira sua conexão e tente novamente.'
            )
            return self.form_invalid(form)

        return redirect('calculations:result', pk=result['calculation'].pk)

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))

    @staticmethod
    def _build_engine_data(form, installment_formset, installment_mode):
        '''Map cleaned form data to the dict expected by CalculationEngine.'''
        cleaned = form.cleaned_data
        data = {
            'base_value': cleaned['base_value'],
            'start_term': cleaned['start_term'],
            'end_term': cleaned['end_term'],
            'index_selection_mode': cleaned['index_selection_mode'],
            'manual_index': cleaned.get('manual_index'),
            'interest_enabled': cleaned.get('interest_enabled', True),
            'attorney_fee_percent': cleaned.get('attorney_fee_percent', 0),
            'installment_mode': installment_mode,
            'rpv_issued': cleaned.get('rpv_issued', False),
            'rpv_issue_date': cleaned.get('rpv_issue_date'),
        }

        if installment_mode != Calculation.INSTALLMENT_MULTIPLE:
            data['installments'] = []
        else:
            data['installments'] = [
                {
                    'order': idx + 1,
                    'value': inst_form.cleaned_data.get('value', cleaned['base_value']),
                    'same_as_first': inst_form.cleaned_data.get('same_as_first', True),
                }
                for idx, inst_form in enumerate(installment_formset.forms)
                if inst_form.cleaned_data
            ]

        return data


class CalculationResultView(LoginRequiredMixin, DetailView):
    '''Display the result of a computed calculation with its memory table.'''

    template_name = 'calculations/result.html'
    context_object_name = 'calculation'

    def get_queryset(self):
        return Calculation.objects.filter(
            user=self.request.user,
            status=Calculation.STATUS_COMPUTED,
        ).prefetch_related('steps', 'installments')


class CalculationExportView(LoginRequiredMixin, View):
    '''Export a calculation's memory as CSV (RF — exportação).'''

    def get(self, request, pk):
        calculation = get_object_or_404(
            Calculation.objects.filter(user=request.user),
            pk=pk,
            status=Calculation.STATUS_COMPUTED,
        )

        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = (
            f'attachment; filename="juriscalc-calculo-{calculation.pk}.csv"'
        )
        response.write('\ufeff')  # BOM for Excel UTF-8 compatibility

        writer = csv.writer(response)
        writer.writerow([
            'Parcela', 'Etapa', 'Descrição',
            'Período Início', 'Período Fim',
            'Índice', 'Fator', 'Juros', 'Valor Base', 'Subtotal',
        ])

        for step in calculation.steps.order_by('installment_order', 'step_order'):
            writer.writerow([
                step.installment_order,
                step.step_order,
                step.description,
                step.period_start.isoformat(),
                step.period_end.isoformat(),
                step.applied_index,
                str(step.factor),
                str(step.interest_amount),
                str(step.base_value),
                str(step.subtotal),
            ])

        writer.writerow([])
        writer.writerow(['', '', '', '', '', '', '', '', 'TOTAL', str(calculation.result_total)])
        return response
