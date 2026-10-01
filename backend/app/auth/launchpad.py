"""The three Basecamp Launchpad calls sign-in makes, bound to the sign-in app's
settings: where to send the browser, the code exchange, and the identity
lookup. A seam for tests: they pass an httpx MockTransport and a no-op sleep,
so no test ever reaches the real Basecamp.

The exchange reuses app.basecamp.oauth.exchange_code unchanged (POST retried
only when the request never left; see that module). The access token it
returns is used for one identity lookup and then dropped.
"""
import time
from typing import Callable, Optional

import httpx

from app.auth.basecamp_identity import BasecampIdentity, fetch_identity
from app.auth.config import AuthConfig
from app.basecamp.oauth import authorize_url, exchange_code


class LaunchpadClient:
    def __init__(self, config: AuthConfig, transport: Optional[httpx.BaseTransport] = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._config = config
        self._transport = transport
        self._sleep = sleep

    def authorize_url(self, state: str) -> str:
        return authorize_url(self._config.client_id, self._config.redirect_uri, state)

    def identify(self, code: str) -> BasecampIdentity:
        """Raises OAuthError (exchange) or IdentityError (lookup)."""
        tokens = exchange_code(self._config.client_id, self._config.client_secret, self._config.redirect_uri,
                               code, transport=self._transport, sleep=self._sleep)
        return fetch_identity(tokens.access_token, self._config.user_agent, transport=self._transport,
                              sleep=self._sleep)
