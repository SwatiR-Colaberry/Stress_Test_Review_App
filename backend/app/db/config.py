"""SQL Server connection settings (REQ-013), read from environment variables.

Values come from the environment only (see .env.example); nothing here is
ever hard-coded. The password is held as a SecretStr, so it never appears in
repr(), logs or error messages. Errors name the variable that is wrong, never
its value.

Failure modes handled: a required variable missing or blank; a boolean or
timeout that doesn't parse or is out of range. All problems are reported
together in one DatabaseConfigError.
"""
import os
from typing import Dict, List, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

REQUIRED_VARS = ("DB_SERVER", "DB_DATABASE", "DB_USERNAME", "DB_PASSWORD")
_TRUE = {"yes", "true", "1"}
_FALSE = {"no", "false", "0"}


class DatabaseConfigError(Exception):
    """Configuration is missing or invalid. The message lists variable names only."""


class DatabaseConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    server: str = Field(min_length=1)
    database: str = Field(min_length=1)
    username: str = Field(min_length=1)
    password: SecretStr
    driver: str = "ODBC Driver 18 for SQL Server"
    encrypt: bool = True
    trust_server_certificate: bool = False
    connect_timeout_s: int = Field(default=30, ge=1, le=300)
    query_timeout_s: int = Field(default=120, ge=1, le=3600)


def load_database_config(environ: Optional[Mapping[str, str]] = None) -> DatabaseConfig:
    env = os.environ if environ is None else environ
    problems: List[str] = []
    values: Dict[str, object] = {}

    for var in REQUIRED_VARS:
        raw = env.get(var, "").strip()
        if not raw:
            problems.append(f"{var} is missing or blank")
        else:
            values[var[3:].lower()] = raw

    driver = env.get("DB_DRIVER", "").strip()
    if driver:
        values["driver"] = driver
    for var, field in (("DB_ENCRYPT", "encrypt"), ("DB_TRUST_SERVER_CERTIFICATE", "trust_server_certificate")):
        raw = env.get(var, "").strip().lower()
        if not raw:
            continue
        if raw in _TRUE or raw in _FALSE:
            values[field] = raw in _TRUE
        else:
            problems.append(f"{var} must be yes/no")
    for var, field, low, high in (
        ("DB_CONNECT_TIMEOUT_S", "connect_timeout_s", 1, 300),
        ("DB_QUERY_TIMEOUT_S", "query_timeout_s", 1, 3600),
    ):
        raw = env.get(var, "").strip()
        if not raw:
            continue
        if raw.isdigit() and low <= int(raw) <= high:
            values[field] = int(raw)
        else:
            problems.append(f"{var} must be a whole number of seconds between {low} and {high}")

    if problems:
        raise DatabaseConfigError("Database configuration invalid: " + "; ".join(problems))
    try:
        return DatabaseConfig(**values)
    except ValidationError as exc:
        # Report field names only; pydantic's own message would echo input values.
        fields = sorted({str(err["loc"][0]) for err in exc.errors() if err["loc"]})
        raise DatabaseConfigError(f"Database configuration invalid: {', '.join(fields)}") from None


def build_connection_string(config: DatabaseConfig) -> str:
    """ODBC connection string for pyodbc. Contains the password: pass it
    straight to pyodbc.connect and never log, print or store it."""
    parts = [
        ("DRIVER", config.driver),
        ("SERVER", config.server),
        ("DATABASE", config.database),
        ("UID", config.username),
        ("PWD", config.password.get_secret_value()),
        ("Encrypt", "yes" if config.encrypt else "no"),
        ("TrustServerCertificate", "yes" if config.trust_server_certificate else "no"),
        ("Connection Timeout", str(config.connect_timeout_s)),
        ("ApplicationIntent", "ReadOnly"),
    ]
    return ";".join(f"{key}={_odbc_value(value)}" for key, value in parts) + ";"


def _odbc_value(value: str) -> str:
    """Brace-quote values containing ODBC special characters, e.g. a password
    with ';' would otherwise end the attribute early and inject the rest."""
    if any(ch in value for ch in ";{}=") or value != value.strip():
        return "{" + value.replace("}", "}}") + "}"
    return value
