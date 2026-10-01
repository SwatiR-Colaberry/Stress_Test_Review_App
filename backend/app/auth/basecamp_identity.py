"""Who just signed in with Basecamp (STORY-014, REQ-020).

After the OAuth code exchange (app.basecamp.oauth.exchange_code, reused
unchanged), Launchpad's authorization.json says who the token belongs to:
  {"identity": {"id", "first_name", "last_name", "email_address"},
   "accounts": [{"id", "product", ...}]}

The caller uses the result once and then drops the access token; it is never
stored or logged.

Failure handling: 15 s timeout per attempt; network errors and 5xx retried,
3 attempts in all with 1 s / 2 s pauses (a GET, safe to repeat). A 4xx, a
reply of the wrong shape, or a missing/invalid email raises IdentityError.
Messages carry the status code at most, never the token or the reply body.
"""
import time
from typing import Callable, FrozenSet, Optional, Sequence

import httpx
from pydantic import BaseModel, ConfigDict, SecretStr

from app.auth.config import InvalidEmail, normalize_email
from app.basecamp.oauth import LAUNCHPAD

# Same products the posting app accepts (see app.basecamp.oauth).
_BASECAMP_PRODUCTS = ("bc3", "bc4", "bc5")


class IdentityError(Exception):
    error_class = "UpstreamUnavailable"


class BasecampIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)

    email: str
    name: str
    account_ids: FrozenSet[int]


def fetch_identity(access_token: SecretStr, user_agent: str, transport: Optional[httpx.BaseTransport] = None,
                   timeout_s: float = 15.0, max_attempts: int = 3, backoff_s: Sequence[float] = (1.0, 2.0),
                   sleep: Callable[[float], None] = time.sleep) -> BasecampIdentity:
    headers = {"Authorization": f"Bearer {access_token.get_secret_value()}", "User-Agent": user_agent}
    response = None
    with httpx.Client(timeout=timeout_s, transport=transport, headers=headers) as http:
        for attempt in range(1, max_attempts + 1):
            try:
                response = http.get(f"{LAUNCHPAD}/authorization.json")
            except httpx.TransportError:
                response = None
            if response is not None and response.status_code < 500:
                break
            if attempt == max_attempts:
                raise IdentityError(f"Could not read the Basecamp identity after {attempt} attempts")
            sleep(backoff_s[min(attempt - 1, len(backoff_s) - 1)])
    if response.status_code != 200:
        raise IdentityError(f"Basecamp refused the identity lookup (HTTP {response.status_code})")
    return _parse(response)


def _parse(response: httpx.Response) -> BasecampIdentity:
    try:
        body = response.json()
        identity = body["identity"]
        email = normalize_email(str(identity["email_address"]))
        name = f"{identity.get('first_name') or ''} {identity.get('last_name') or ''}".strip() or email
        accounts = frozenset(int(a["id"]) for a in body.get("accounts", [])
                             if isinstance(a, dict) and a.get("product") in _BASECAMP_PRODUCTS)
    except InvalidEmail:
        raise IdentityError("Basecamp did not return a usable email address") from None
    except (ValueError, AttributeError, KeyError, TypeError):
        raise IdentityError("Basecamp identity reply was not the expected shape") from None
    return BasecampIdentity(email=email, name=name, account_ids=accounts)
