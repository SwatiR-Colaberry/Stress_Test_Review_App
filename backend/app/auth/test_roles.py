"""RoleStore (STORY-014): add, change, remove, refusals, fail-closed, audit."""
import json

import pytest

from app.audit.trail import AuditTrail, AuditWriteError, InMemoryAuditTrail
from app.auth.config import AuthConfigError, InvalidEmail, load_auth_config, normalize_email
from app.auth.roles import RoleChangeRefused, RoleStore, RoleStoreUnavailable

BOOT = "boss@example.com"
CID = "corr-1"


@pytest.fixture
def audit():
    return InMemoryAuditTrail()


@pytest.fixture
def store(tmp_path, audit):
    return RoleStore(tmp_path / "auth" / "roles.json", frozenset({BOOT}), audit)


def test_people_on_neither_list_have_no_role(store):
    assert store.role_for("stranger@example.com") is None


def test_bootstrap_admins_are_admins_without_a_file(store):
    assert store.role_for(" Boss@Example.com ") == "admin"


def test_add_then_change_then_remove(store):
    assert store.set_role("Ann@Example.com", "reviewer", BOOT, CID) == "added"
    assert store.role_for("ann@example.com") == "reviewer"
    assert store.set_role("ann@example.com", "admin", BOOT, CID) == "changed"
    assert store.role_for("ann@example.com") == "admin"
    assert store.remove("ann@example.com", BOOT, CID) == "removed"
    assert store.role_for("ann@example.com") is None


def test_every_role_change_is_audited_with_who_whose_and_when(store, audit):
    store.set_role("ann@example.com", "reviewer", BOOT, CID)
    store.set_role("ann@example.com", "admin", BOOT, CID)
    store.remove("ann@example.com", BOOT, CID)
    events = audit.read_all()
    assert [e.action for e in events] == ["role_added", "role_changed", "role_removed"]
    for event, role in zip(events, ["reviewer", "admin", "admin"]):
        assert event.actor_id == BOOT and event.subject_id == "ann@example.com"
        assert event.role == role and event.outcome == "success"
        assert event.recorded_at.tzinfo is not None
    assert len({e.event_id for e in events}) == 3


def test_repeating_a_change_changes_nothing_and_records_nothing(store, audit):
    store.set_role("ann@example.com", "reviewer", BOOT, CID)
    assert store.set_role("ann@example.com", "reviewer", BOOT, CID) == "unchanged"
    store.remove("ann@example.com", BOOT, CID)
    assert store.remove("ann@example.com", BOOT, CID) == "not_found"
    assert [e.action for e in audit.read_all()] == ["role_added", "role_removed"]


def test_the_role_list_survives_a_new_store(tmp_path, audit):
    path = tmp_path / "roles.json"
    RoleStore(path, frozenset(), audit).set_role("ann@example.com", "admin", BOOT, CID)
    again = RoleStore(path, frozenset(), audit)
    assert again.role_for("ann@example.com") == "admin"
    assert [(r.email, r.role, r.bootstrap) for r in again.list_assignments()] == [("ann@example.com", "admin", False)]


def test_list_shows_bootstrap_admins_first(store):
    store.set_role("zed@example.com", "reviewer", BOOT, CID)
    rows = store.list_assignments()
    assert [(r.email, r.bootstrap) for r in rows] == [(BOOT, True), ("zed@example.com", False)]


@pytest.mark.parametrize("change", [
    lambda s: s.set_role(BOOT, "reviewer", BOOT, CID),
    lambda s: s.remove(BOOT, BOOT, CID),
])
def test_bootstrap_admins_cannot_be_changed_and_the_refusal_is_audited(store, audit, change):
    with pytest.raises(RoleChangeRefused) as refused:
        change(store)
    assert refused.value.reason_code == "BOOTSTRAP_ADMIN"
    (event,) = audit.read_all()
    assert event.outcome == "blocked" and event.reason_code == "BOOTSTRAP_ADMIN" and event.subject_id == BOOT


def test_the_last_admin_cannot_be_removed_or_demoted(tmp_path, audit):
    store = RoleStore(tmp_path / "roles.json", frozenset(), audit)
    store.set_role("ann@example.com", "admin", "ann@example.com", CID)
    with pytest.raises(RoleChangeRefused) as demote:
        store.set_role("ann@example.com", "reviewer", "ann@example.com", CID)
    with pytest.raises(RoleChangeRefused) as remove:
        store.remove("ann@example.com", "ann@example.com", CID)
    assert demote.value.reason_code == remove.value.reason_code == "LAST_ADMIN"
    assert store.role_for("ann@example.com") == "admin"
    assert [e.outcome for e in audit.read_all()] == ["success", "blocked", "blocked"]


def test_a_second_admin_can_be_removed(tmp_path, audit):
    store = RoleStore(tmp_path / "roles.json", frozenset(), audit)
    store.set_role("ann@example.com", "admin", "ann@example.com", CID)
    store.set_role("bob@example.com", "admin", "ann@example.com", CID)
    assert store.remove("ann@example.com", "bob@example.com", CID) == "removed"


@pytest.mark.parametrize("bad", ["", "not-an-email", "a@b", "a b@c.com", "x" * 120 + "@example.com"])
def test_a_bad_email_is_refused(store, bad):
    with pytest.raises(InvalidEmail):
        store.set_role(bad, "reviewer", BOOT, CID)


def test_a_corrupt_file_fails_closed_but_bootstrap_admins_still_get_in(tmp_path, audit):
    path = tmp_path / "roles.json"
    path.write_text("{ not json", encoding="utf-8")
    store = RoleStore(path, frozenset({BOOT}), audit)
    with pytest.raises(RoleStoreUnavailable):
        store.role_for("ann@example.com")
    with pytest.raises(RoleStoreUnavailable):
        store.set_role("ann@example.com", "reviewer", BOOT, CID)
    assert store.role_for(BOOT) == "admin"
    assert path.read_text(encoding="utf-8") == "{ not json"  # never overwritten
    assert audit.read_all() == []


def test_an_unreadable_file_is_logged_with_its_error_class(tmp_path, audit, caplog):
    path = tmp_path / "roles.json"
    path.mkdir()  # a directory where the file should be
    with pytest.raises(RoleStoreUnavailable):
        RoleStore(path, frozenset(), audit).role_for("ann@example.com")
    logged = [json.loads(r.message) for r in caplog.records if "role_store_unavailable" in r.message]
    assert logged and logged[0]["error_class"] in ("IsADirectoryError", "PermissionError")


class _FailingAudit(AuditTrail):
    def record(self, event):
        raise AuditWriteError("disk full")

    def read_all(self):
        return []


def test_a_change_that_cannot_be_audited_is_undone(tmp_path):
    path = tmp_path / "roles.json"
    RoleStore(path, frozenset(), InMemoryAuditTrail()).set_role("ann@example.com", "reviewer", BOOT, CID)
    store = RoleStore(path, frozenset(), _FailingAudit())
    with pytest.raises(AuditWriteError):
        store.set_role("ann@example.com", "admin", BOOT, CID)
    with pytest.raises(AuditWriteError):
        store.set_role("bob@example.com", "reviewer", BOOT, CID)
    assert store.role_for("ann@example.com") == "reviewer"
    assert store.role_for("bob@example.com") is None


def test_a_first_change_that_cannot_be_audited_leaves_no_file(tmp_path):
    path = tmp_path / "roles.json"
    with pytest.raises(AuditWriteError):
        RoleStore(path, frozenset(), _FailingAudit()).set_role("ann@example.com", "reviewer", BOOT, CID)
    assert not path.exists()


def test_emails_never_appear_in_log_lines(store, caplog):
    store.set_role("ann@example.com", "reviewer", BOOT, CID)
    with pytest.raises(RoleChangeRefused):
        store.remove(BOOT, BOOT, CID)
    assert caplog.records
    assert all("@" not in r.message for r in caplog.records)


# --- config ------------------------------------------------------------------

def test_bootstrap_admins_are_read_from_the_environment():
    config = load_auth_config({"AUTH_BOOTSTRAP_ADMIN_EMAILS": " A@Example.com, ,b@example.com "})
    assert config.bootstrap_admin_emails == frozenset({"a@example.com", "b@example.com"})


def test_no_bootstrap_admins_by_default():
    assert load_auth_config({}).bootstrap_admin_emails == frozenset()


def test_a_bad_bootstrap_entry_fails_without_repeating_it():
    with pytest.raises(AuthConfigError) as error:
        load_auth_config({"AUTH_BOOTSTRAP_ADMIN_EMAILS": "a@example.com,secret-looking-value"})
    assert "entry 2" in str(error.value) and "secret-looking-value" not in str(error.value)


def test_normalize_email_lowercases_and_trims():
    assert normalize_email("  Ann@Example.COM ") == "ann@example.com"
