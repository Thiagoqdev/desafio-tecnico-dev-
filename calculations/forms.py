'''Forms for the calculations module.

`CalculationForm` exposes every parameter described in RF01–RF08 and
RF18. `InstallmentFormSet` handles the multi-installment sub-form when
the user chooses "múltiplas parcelas".

All labels, help texts and error messages are in pt-BR (RNF02).
'''

from django import forms

from indices.models import IndexType
from .models import Calculation


class CalculationForm(forms.Form):
    '''Principal form that collects all parameters for a calculation.'''

    base_value = forms.DecimalField(
        label='Valor base (R$)',
        min_value=0.01,
        max_digits=16,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'placeholder': '10.000,00', 'step': '0.01'}),
        help_text='Valor principal a ser atualizado (RF01).',
    )

    start_term = forms.DateField(
        label='Termo inicial',
        widget=forms.DateInput(attrs={'type': 'date'}),
        help_text='Data a partir da qual a correção incide.',
    )

    end_term = forms.DateField(
        label='Termo final',
        widget=forms.DateInput(attrs={'type': 'date'}),
        help_text='Data até a qual a correção é aplicada.',
    )

    index_selection_mode = forms.ChoiceField(
        label='Modo de seleção do índice',
        choices=Calculation.INDEX_CHOICES,
        initial=Calculation.INDEX_AUTO,
        widget=forms.RadioSelect,
        help_text='Automático aplica a legislação; manual usa o índice escolhido abaixo.',
    )

    manual_index = forms.ModelChoiceField(
        label='Índice manual',
        queryset=IndexType.objects.all(),
        required=False,
        empty_label='Selecione um índice...',
        help_text='Obrigatório apenas quando o modo manual está selecionado.',
    )

    interest_enabled = forms.BooleanField(
        label='Aplicar juros de mora',
        required=False,
        initial=True,
    )

    attorney_fee_percent = forms.DecimalField(
        label='Honorários advocatícios (%)',
        min_value=0,
        max_value=100,
        max_digits=5,
        decimal_places=2,
        initial=0,
        widget=forms.NumberInput(attrs={'placeholder': '10', 'step': '0.01'}),
        help_text='Percentual de honorários sobre a base definida (S5).',
    )

    installment_mode = forms.ChoiceField(
        label='Modo de parcelamento',
        choices=Calculation.INSTALLMENT_CHOICES,
        initial=Calculation.INSTALLMENT_SINGLE,
        widget=forms.RadioSelect,
    )

    rpv_issued = forms.BooleanField(
        label='RPV/Precatório emitido',
        required=False,
        initial=False,
        help_text='Marque se o RPV/Precatório já foi emitido (RF18).',
    )

    rpv_issue_date = forms.DateField(
        label='Data de emissão do RPV/Precatório',
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'}),
        help_text='Deve estar entre o termo inicial e o termo final (S11).',
    )

    def clean(self):
        cleaned = super().clean()

        start = cleaned.get('start_term')
        end = cleaned.get('end_term')
        if start and end and start > end:
            raise forms.ValidationError(
                'O termo inicial não pode ser posterior ao termo final.'
            )

        mode = cleaned.get('index_selection_mode')
        manual = cleaned.get('manual_index')
        if mode == Calculation.INDEX_MANUAL and not manual:
            self.add_error('manual_index', 'Selecione um índice para o modo manual.')

        rpv = cleaned.get('rpv_issued')
        rpv_date = cleaned.get('rpv_issue_date')
        if rpv and not rpv_date:
            self.add_error('rpv_issue_date', 'Informe a data de emissão do RPV/Precatório.')
        if rpv and rpv_date:
            if start and rpv_date < start:
                self.add_error(
                    'rpv_issue_date',
                    'A data de emissão não pode ser anterior ao termo inicial.',
                )
            if end and rpv_date > end:
                self.add_error(
                    'rpv_issue_date',
                    'A data de emissão não pode ser posterior ao termo final.',
                )

        return cleaned


class InstallmentForm(forms.Form):
    '''A single row of the dynamic installment formset.'''

    same_as_first = forms.BooleanField(
        label='Igual à primeira',
        required=False,
        initial=True,
    )

    value = forms.DecimalField(
        label='Valor (R$)',
        min_value=0.01,
        max_digits=16,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={'placeholder': '5.000,00', 'step': '0.01'}),
    )

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('same_as_first') and not cleaned.get('value'):
            self.add_error('value', 'Informe o valor ou marque "Igual à primeira".')
        return cleaned


InstallmentFormSet = forms.formset_factory(
    InstallmentForm,
    extra=1,
    min_num=0,
    max_num=24,
    can_delete=False,
)
