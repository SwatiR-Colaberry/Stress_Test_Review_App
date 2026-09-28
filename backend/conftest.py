"""Test-wide safety nets.

STORY-011: no test may write to the real audit trail file under data/audit/.
Every test gets a fresh in-memory trail, both for the app's FastAPI dependency
and for the shared trail scripts use (get_audit_trail()); tests that need to
inspect it override it themselves.

STORY-004: no test may call the real, billed Claude API. ANTHROPIC_API_KEY
(and the other ways the SDK finds credentials) are removed for every test,
so an accidentally real client fails at once instead of spending money."""
import pytest

from app.audit import dependencies
from app.audit.dependencies import get_audit_trail
from app.audit.trail import InMemoryAuditTrail
from app.main import app


@pytest.fixture(autouse=True)
def _in_memory_audit_trail(monkeypatch):
    monkeypatch.setattr(dependencies, "_trail", InMemoryAuditTrail())
    app.dependency_overrides[get_audit_trail] = lambda: InMemoryAuditTrail()
    yield
    app.dependency_overrides.pop(get_audit_trail, None)


_ANTHROPIC_CREDENTIAL_VARS = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE", "ANTHROPIC_BASE_URL",
    "ANTHROPIC_FEDERATION_RULE_ID", "ANTHROPIC_IDENTITY_TOKEN", "ANTHROPIC_IDENTITY_TOKEN_FILE",
)


@pytest.fixture(autouse=True)
def _no_real_claude_credentials(monkeypatch, tmp_path):
    for var in _ANTHROPIC_CREDENTIAL_VARS:
        monkeypatch.delenv(var, raising=False)
    # The SDK also reads an `ant auth login` profile from the config folder.
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path / "no-anthropic-profile"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no-config"))
