"""Concrete transport and sleeper implementations for the composition root.

The only ingestion module that can open a network connection, and it is never
imported by orchestration, parsing, mapping, or any test-exercised path —
orchestration sees only the :class:`~greenmachine.ingestion.capture.HttpTransport`
protocol. The developer runner composes these at its root; the test suite
composes fakes.

The User-Agent is honest and stable: it identifies the project and carries no
secret, machine name, or user identity.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request

from greenmachine.common.errors import ErrorContext

from .capture import HttpResponse
from .errors import ProviderTransportError

__all__ = ["USER_AGENT", "SystemSleeper", "UrllibTransport"]

USER_AGENT = "GreenMachine/0.2.0 (deterministic MLB research; single controlled capture)"


class UrllibTransport:
    """Synchronous GET transport over the standard library. No concurrency."""

    def request(self, url: str, timeout_seconds: int) -> HttpResponse:
        prepared = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(prepared, timeout=timeout_seconds) as response:
                body = response.read()
                headers = tuple((str(name), str(value)) for name, value in response.headers.items())
                return HttpResponse(status=int(response.status), headers=headers, body=body)
        except urllib.error.HTTPError as http_error:
            body = http_error.read()
            headers = tuple((str(name), str(value)) for name, value in http_error.headers.items())
            return HttpResponse(status=int(http_error.code), headers=headers, body=body)
        except urllib.error.URLError as url_error:
            raise ProviderTransportError(
                f"the provider could not be reached: {url_error.reason}",
                ErrorContext(observed=type(url_error.reason).__name__),
            ) from url_error
        except TimeoutError as timeout_error:
            raise ProviderTransportError(
                "the provider request timed out",
                ErrorContext(observed="TimeoutError"),
            ) from timeout_error


class SystemSleeper:
    """Real waiting for the composition root; tests inject a recording fake."""

    def sleep(self, seconds: int) -> None:
        if seconds > 0:
            time.sleep(seconds)
