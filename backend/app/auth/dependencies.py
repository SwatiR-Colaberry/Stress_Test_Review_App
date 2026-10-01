"""Process-wide sign-in objects, handed to routes via FastAPI Depends so tests
can override them (app.dependency_overrides).

AUTH_ROLES_PATH overrides the role list location; unset, it is the git-ignored
data/auth/roles.json at the repo root. Settings are read on first use, not at
import, so a malformed value shows as "sign-in is not configured correctly"
instead of stopping the whole app.
"""
import logging
import os
import threading
from functools import lru_cache
from pathlib import Path
from typing import Optional

from app.audit.dependencies import get_audit_trail
from app.auth.config import AuthConfig, AuthConfigError, load_auth_config
from app.auth.launchpad import LaunchpadClient
from app.auth.logs import log_event
from app.auth.roles import DEFAULT_ROLES_PATH, RoleStore
from app.auth.sessions import SessionStore

_lock = threading.Lock()
_roles: Optional[RoleStore] = None
_sessions: Optional[SessionStore] = None


@lru_cache(maxsize=1)
def get_auth_config() -> AuthConfig:
    """Raises AuthConfigError (names the variable, never its value) on every
    call until fixed: lru_cache never caches an exception."""
    try:
        return load_auth_config()
    except AuthConfigError as exc:
        log_event("auth_config_invalid", "auth-config", logging.ERROR, error_class=exc.error_class, problem=str(exc))
        raise


def get_role_store() -> RoleStore:
    global _roles
    with _lock:
        if _roles is None:
            path = Path(os.environ.get("AUTH_ROLES_PATH") or DEFAULT_ROLES_PATH)
            _roles = RoleStore(path, get_auth_config().bootstrap_admin_emails, get_audit_trail())
        return _roles


def get_session_store() -> SessionStore:
    global _sessions
    roles = get_role_store()
    with _lock:
        if _sessions is None:
            _sessions = SessionStore(roles)
        return _sessions


def get_launchpad_client() -> LaunchpadClient:
    return LaunchpadClient(get_auth_config())
