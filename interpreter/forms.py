'''Forms for the interpreter module.'''

from django import forms


class SentenceForm(forms.Form):
    '''A single textarea for pasting a judicial sentence.'''

    sentence_text = forms.CharField(
        label='Texto da sentença',
        widget=forms.Textarea(attrs={
            'placeholder': 'Cole aqui o texto da sentença judicial...',
            'rows': 10,
        }),
        min_length=20,
        help_text='O texto será interpretado por um modelo de linguagem (LLM) '
                  'para preencher automaticamente o formulário de cálculo.',
    )
