'''Thin HTTP boundary used by the indices clients.

Kept in its own module so unit tests can patch a single seam
(`HttpClient.get_json`) instead of monkey-patching stdlib internals.
'''

import json
import os
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .exceptions import IndexSourceUnavailable


DEFAULT_TIMEOUT_SECONDS = 15
USER_AGENT = 'Juriscalc/1.0 (+https://juriscalc.local)'


def _ssl_context():
    '''Return an SSL context for outbound API calls.

    Certificate verification is always enabled unless the environment
    variable JURISCALC_VERIFY_SSL is explicitly set to "0".

    When the `certifi` CA bundle is installed it is used explicitly. This
    avoids `CERTIFICATE_VERIFY_FAILED` on platforms (notably macOS) where the
    stock Python build cannot locate the system trust store.
    '''
    try:
        import certifi

        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
    if os.environ.get('JURISCALC_VERIFY_SSL', '1') == '0':
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


class HttpClient:
    '''Issues GET requests that return JSON.

    Network errors are converted to `IndexSourceUnavailable` so the
    orchestration layer can apply the cache fallback policy.
    '''

    def __init__(self, timeout=DEFAULT_TIMEOUT_SECONDS, user_agent=USER_AGENT):
        self.timeout = timeout
        self.user_agent = user_agent

    def get_json(self, url):
        request = Request(url, headers={'User-Agent': self.user_agent, 'Accept': 'application/json'})
        try:
            with urlopen(request, timeout=self.timeout, context=_ssl_context()) as response:
                payload = response.read().decode('utf-8')
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise IndexSourceUnavailable(f'falha ao consultar {url}: {exc}') from exc
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise IndexSourceUnavailable(f'resposta inválida de {url}: {exc}') from exc
