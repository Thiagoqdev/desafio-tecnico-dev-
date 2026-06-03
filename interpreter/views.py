'''Views for the interpreter module.

`ImportSentenceView` receives a sentence text via POST, runs the
LangGraph interpretation, persists the result, and returns the
extracted DTO to the front-end for form pre-fill.
'''

import os

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.views.generic import FormView

from .forms import SentenceForm
from .graph import SentenceInterpreter


class ImportSentenceView(LoginRequiredMixin, FormView):
    '''Receive a sentence, run LLM extraction, return DTO.

    GET  — renders the form (paste sentence).
    POST — invokes the LangGraph, persists, returns JSON with DTO.
    '''

    template_name = 'interpreter/import.html'
    form_class = SentenceForm

    def form_valid(self, form):
        source_text = form.cleaned_data['sentence_text']
        llm = self._get_llm()

        interpreter = SentenceInterpreter(
            llm=llm,
            model_name=settings.LLM_MODEL or 'unknown',
        )
        dto = interpreter.interpret(source_text, user=self.request.user)

        return JsonResponse({'ok': True, 'payload': dto})

    def form_invalid(self, form):
        return JsonResponse({'ok': False, 'errors': form.errors.get_json_data()}, status=400)

    @staticmethod
    def _get_llm():
        '''Instantiate the LLM client from Django settings (S2).

        Supports OpenAI, Anthropic, Google, DeepSeek and any
        OpenAI-compatible API via LLM_BASE_URL. Falls back to a
        mock for development.
        '''
        provider = settings.LLM_PROVIDER or os.environ.get('LLM_PROVIDER')
        api_key = settings.LLM_API_KEY or os.environ.get('LLM_API_KEY')
        model = settings.LLM_MODEL or os.environ.get('LLM_MODEL')
        base_url = settings.LLM_BASE_URL or os.environ.get('LLM_BASE_URL', '')
        timeout = settings.LLM_REQUEST_TIMEOUT_SECONDS

        if provider and api_key and model:
            if 'deepseek' in provider.lower():
                from langchain.chat_models import ChatOpenAI  # type: ignore[import-untyped]
                return ChatOpenAI(
                    model=model,
                    api_key=api_key,
                    base_url=base_url or 'https://api.deepseek.com',
                    request_timeout=timeout,
                )
            if 'anthropic' in provider.lower():
                from langchain.chat_models import ChatAnthropic  # type: ignore[import-untyped]
                return ChatAnthropic(model=model, api_key=api_key)
            if 'openai' in provider.lower() or provider.lower() in ('gpt', 'azure'):
                from langchain.chat_models import ChatOpenAI  # type: ignore[import-untyped]
                return ChatOpenAI(model=model, api_key=api_key)
            if provider.lower() == 'google':
                from langchain.chat_models import ChatGoogleGenerativeAI  # type: ignore[import-untyped]
                return ChatGoogleGenerativeAI(model=model, api_key=api_key)
            if base_url:
                from langchain.chat_models import ChatOpenAI  # type: ignore[import-untyped]
                return ChatOpenAI(model=model, api_key=api_key, base_url=base_url)

        from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
        return GenericFakeChatModel(
            messages=iter([
                '{"base_value": null, "start_term": null, '
                '"end_term": null, "index_selection_mode": null, '
                '"manual_index": null, "interest_enabled": true, '
                '"attorney_fee_percent": null, "installment_mode": null, '
                '"rpv_issued": false, "rpv_issue_date": null, "installments": []}'
            ])
        )
