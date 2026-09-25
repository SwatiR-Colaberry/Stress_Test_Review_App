"""Basecamp API settings (REQ-004, REQ-012), read from environment variables.

Authentication is OAuth 2.0 (REQ-012): Basecamp issues an access token through
its Launchpad authorization-code flow, and every API call sends it as
"Authorization: Bearer <token>". Obtaining and refreshing that token needs a
registered Basecamp app (client id/secret), which does not exist yet; until
then the token is supplied by the environment. Nothing here is hard-coded.

The token is held as a SecretStr, so it never appears in repr(), logs or error
messages. Errors name the variable that is wrong, never its value, and all
problems are reported together in one BasecampConfigError.

Basecamp requires a User-Agent that names the app and a contact, and rejects
requests without one, so it is required here too.
"""
import os
from typing import Dict, List, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

REQUIRED_VARS = ("BASECAMP_ACCOUNT_ID", "BASECAMP_ACCESS_TOKEN", "BASECAMP_USER_AGENT")
API_ROOT = "https://3.basecampapi.com"


class BasecampConfigError(Exception):
    """Configuration is missing or invalid. The message lists variable names only."""


class BasecampConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    account_id: int = Field(gt=0)
    access_token: SecretStr
    user_agent: str = Field(min_length=1)
    timeout_s: float = Field(default=15.0, ge=1, le=60)

    @property
    def base_url(self) -> str:
        return f"{API_ROOT}/{self.account_id}"

    def auth_headers(self) -> Dict[str, str]:
        """Headers for every API call. Never log the return value."""
        return {
            "Authorization": f"Bearer {self.access_token.get_secret_value()}",
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }


def load_basecamp_config(environ: Optional[Mapping[str, str]] = None) -> BasecampConfig:
    env = os.environ if environ is None else environ
    problems: List[str] = []
    values: Dict[str, object] = {}

    for var in REQUIRED_VARS:
        raw = env.get(var, "").strip()
        if not raw:
            problems.append(f"{var} is missing or blank")
        else:
            values[var[len("BASECAMP_"):].lower()] = raw

    account_id = values.get("account_id")
    if isinstance(account_id, str) and not (account_id.isdigit() and int(account_id) > 0):
        problems.append("BASECAMP_ACCOUNT_ID must be a positive whole number")

    raw_timeout = env.get("BASECAMP_TIMEOUT_S", "").strip()
    if raw_timeout:
        if raw_timeout.isdigit() and 1 <= int(raw_timeout) <= 60:
            values["timeout_s"] = float(raw_timeout)
        else:
            problems.append("BASECAMP_TIMEOUT_S must be a whole number of seconds between 1 and 60")

    if problems:
        raise BasecampConfigError("Basecamp configuration invalid: " + "; ".join(problems))
    try:
        return BasecampConfig(**values)
    except ValidationError as exc:
        # Report field names only; pydantic's own message would echo input values.
        fields = sorted({str(err["loc"][0]) for err in exc.errors() if err.get("loc")})
        raise BasecampConfigError("Basecamp configuration invalid: " + ", ".join(fields)) from None
