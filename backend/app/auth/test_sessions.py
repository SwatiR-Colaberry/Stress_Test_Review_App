"""SessionStore (STORY-014): 8-hour sessions, sign-out, live role lookup."""
from datetime import datetime, timedelta, timezone

import pytest

from app.audit.trail import InMemoryAuditTrail
from app.auth.roles import RoleStore, RoleStoreUnavailable
from app.auth.sessions import SESSION_LIFETIME, SessionStore

BOOT = "boss@example.com"
T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def roles(tmp_path):
    store = RoleStore(tmp_path / "roles.json", frozenset({BOOT}), InMemoryAuditTrail())
    store.set_role("ann@example.com", "reviewer", BOOT, "c")
    return store


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def sessions(roles, clock):
    return SessionStore(roles, clock=clock)


def test_a_session_resolves_to_the_person_and_their_role(sessions):
    token, session = sessions.start("ann@example.com", "Ann Lee")
    who = sessions.resolve(token)
    assert (who.email, who.name, who.role, who.is_admin) == ("ann@example.com", "Ann Lee", "reviewer", False)
    assert session.expires_at == T0 + timedelta(hours=8) == who.expires_at


def test_the_lifetime_is_eight_hours():
    assert SESSION_LIFETIME == timedelta(hours=8)


def test_a_session_ends_when_eight_hours_pass(sessions, clock):
    token, _ = sessions.start("ann@example.com", "Ann")
    clock.now = T0 + timedelta(hours=8) - timedelta(seconds=1)
    assert sessions.resolve(token) is not None
    clock.now = T0 + timedelta(hours=8)
    assert sessions.resolve(token) is None
    clock.now = T0  # even a clock set back does not revive it
    assert sessions.resolve(token) is None


def test_activity_does_not_extend_a_session(sessions, clock):
    token, _ = sessions.start("ann@example.com", "Ann")
    for hour in range(1, 8):
        clock.now = T0 + timedelta(hours=hour)
        assert sessions.resolve(token) is not None
    clock.now = T0 + timedelta(hours=8, minutes=1)
    assert sessions.resolve(token) is None


def test_sign_out_ends_the_session_and_is_safe_to_repeat(sessions):
    token, _ = sessions.start("ann@example.com", "Ann")
    ended = sessions.end(token)
    assert ended.email == "ann@example.com"
    assert sessions.resolve(token) is None
    assert sessions.end(token) is None


def test_signing_out_one_session_leaves_another_alone(sessions):
    first, _ = sessions.start("ann@example.com", "Ann")
    second, _ = sessions.start("ann@example.com", "Ann")
    sessions.end(first)
    assert sessions.resolve(second) is not None


@pytest.mark.parametrize("token", [None, "", "made-up-token", "x" * 5000])
def test_a_missing_unknown_or_oversized_token_is_not_signed_in(sessions, token):
    sessions.start("ann@example.com", "Ann")
    assert sessions.resolve(token) is None
    assert sessions.end(token) is None


def test_a_tampered_token_is_not_signed_in(sessions):
    token, _ = sessions.start("ann@example.com", "Ann")
    assert sessions.resolve(token[:-1] + ("A" if token[-1] != "A" else "B")) is None


def test_the_raw_token_is_never_kept(sessions):
    token, _ = sessions.start("ann@example.com", "Ann")
    assert token not in repr(sessions.__dict__)


def test_tokens_are_unique_and_long(sessions):
    tokens = {sessions.start("ann@example.com", "Ann")[0] for _ in range(50)}
    assert len(tokens) == 50 and all(len(t) >= 43 for t in tokens)


def test_removing_someone_ends_their_session_at_once(sessions, roles):
    token, _ = sessions.start("ann@example.com", "Ann")
    roles.remove("ann@example.com", BOOT, "c")
    assert sessions.resolve(token) is None
    roles.set_role("ann@example.com", "reviewer", BOOT, "c")
    assert sessions.resolve(token) is None  # ended, not merely hidden


def test_a_role_change_shows_on_the_next_request(sessions, roles):
    token, _ = sessions.start("ann@example.com", "Ann")
    roles.set_role("ann@example.com", "admin", BOOT, "c")
    assert sessions.resolve(token).role == "admin"


def test_expired_sessions_are_dropped_when_new_ones_start(sessions, clock):
    sessions.start("ann@example.com", "Ann")
    clock.now = T0 + timedelta(hours=9)
    sessions.start("ann@example.com", "Ann")
    assert len(sessions._sessions) == 1


def test_an_unreadable_role_list_is_raised_not_read_as_signed_in(tmp_path, clock):
    path = tmp_path / "roles.json"
    roles = RoleStore(path, frozenset(), InMemoryAuditTrail())
    roles.set_role("ann@example.com", "admin", "ann@example.com", "c")
    sessions = SessionStore(roles, clock=clock)
    token, _ = sessions.start("ann@example.com", "Ann")
    path.write_text("broken", encoding="utf-8")
    with pytest.raises(RoleStoreUnavailable):
        sessions.resolve(token)


def test_a_very_long_name_is_cut_to_the_limit(sessions):
    token, session = sessions.start("ann@example.com", "A" * 500)
    assert len(session.name) == 200
