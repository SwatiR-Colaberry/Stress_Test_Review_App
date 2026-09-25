"""Test-wide safety net (STORY-011): no test may write to the real audit trail
file under data/audit/. Every test gets a fresh in-memory trail for the app's
audit dependency; tests that need to inspect it override it themselves."""
import pytest

from app.audit.dependencies import get_audit_trail
from app.audit.trail import InMemoryAuditTrail
from app.main import app


@pytest.fixture(autouse=True)
def _in_memory_audit_trail():
    app.dependency_overrides[get_audit_trail] = lambda: InMemoryAuditTrail()
    yield
    app.dependency_overrides.pop(get_audit_trail, None)
