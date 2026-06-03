'''Forms for the accounts module.'''

from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User


class RegistrationForm(UserCreationForm):
    '''Registration form built on top of Django's UserCreationForm.

    Adds an email field and renders all inputs using the design-system tokens
    expected by the templates.
    '''

    email = forms.EmailField(
        label='E-mail',
        required=True,
        widget=forms.EmailInput(attrs={'placeholder': 'voce@exemplo.com', 'autocomplete': 'email'}),
    )

    class Meta:
        model = User
        fields = ('username', 'email', 'password1', 'password2')
        labels = {
            'username': 'Nome de usuário',
        }
        widgets = {
            'username': forms.TextInput(attrs={'placeholder': 'seu.usuario', 'autocomplete': 'username'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['password1'].label = 'Senha'
        self.fields['password2'].label = 'Confirmação de senha'
        self.fields['password1'].widget.attrs.update({'placeholder': 'Crie uma senha', 'autocomplete': 'new-password'})
        self.fields['password2'].widget.attrs.update({'placeholder': 'Repita a senha', 'autocomplete': 'new-password'})

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        if commit:
            user.save()
        return user


class StyledAuthenticationForm(AuthenticationForm):
    '''Authentication form with placeholders and pt-BR labels.'''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].label = 'Nome de usuário'
        self.fields['password'].label = 'Senha'
        self.fields['username'].widget.attrs.update({'placeholder': 'seu.usuario', 'autocomplete': 'username'})
        self.fields['password'].widget.attrs.update({'placeholder': 'Sua senha', 'autocomplete': 'current-password'})
