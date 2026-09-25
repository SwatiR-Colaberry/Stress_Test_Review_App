import pyodbc
import pytest

from app.db.config import load_database_config
from app.db.connection import DatabaseConnectionError, classify_error, connect_with_retry

_CONFIG = load_database_config({
    "DB_SERVER": "db.example.test", "DB_DATABASE": "ExampleDb", "DB_USERNAME": "reader",
    "DB_PASSWORD": "fake-password-123", "DB_CONNECT_TIMEOUT_S": "7", "DB_QUERY_TIMEOUT_S": "90",
})


class _FakeConnection:
    timeout = 0


class _FakeConnect:
    def __init__(self, errors=()):
        self.errors = list(errors)
        self.calls = []

    def __call__(self, connection_string, **kwargs):
        self.calls.append(kwargs)
        if self.errors:
            raise self.errors.pop(0)
        return _FakeConnection()


def test_connects_with_login_timeout_read_only_and_sets_query_timeout():
    connect = _FakeConnect()
    conn = connect_with_retry(_CONFIG, connect=connect, sleep=lambda s: None)
    assert connect.calls == [{"timeout": 7, "readonly": True}]
    assert conn.timeout == 90


def test_retries_a_transient_failure_then_succeeds():
    connect = _FakeConnect([pyodbc.OperationalError("08001", "server not found")])
    waits = []
    connect_with_retry(_CONFIG, connect=connect, sleep=waits.append)
    assert len(connect.calls) == 2 and waits == [1.0]


def test_gives_up_after_three_timeouts_with_a_classified_error():
    connect = _FakeConnect([pyodbc.OperationalError("HYT00", "timeout")] * 4)
    with pytest.raises(DatabaseConnectionError) as exc:
        connect_with_retry(_CONFIG, connect=connect, sleep=lambda s: None)
    assert (exc.value.error_class, exc.value.sqlstate, exc.value.attempts) == ("TimeoutError", "HYT00", 3)
    assert len(connect.calls) == 3


def test_login_failure_is_not_retried():
    connect = _FakeConnect([pyodbc.InterfaceError("28000", "Login failed for user 'reader'")])
    with pytest.raises(DatabaseConnectionError) as exc:
        connect_with_retry(_CONFIG, connect=connect, sleep=lambda s: None)
    assert exc.value.error_class == "AuthError" and len(connect.calls) == 1


def test_errors_never_carry_the_driver_message_or_password(caplog):
    connect = _FakeConnect([pyodbc.InterfaceError("28000", "Login failed for user 'reader' fake-password-123")])
    with pytest.raises(DatabaseConnectionError) as exc:
        connect_with_retry(_CONFIG, connect=connect, sleep=lambda s: None)
    assert "Login failed" not in str(exc.value) and "fake-password-123" not in str(exc.value)
    assert exc.value.__cause__ is None
    assert "fake-password-123" not in caplog.text and "Login failed" not in caplog.text


_CERT_MESSAGE = ("[Microsoft][ODBC Driver 18 for SQL Server]SSL Provider: [error:0A000086:SSL routines::"
                 "certificate verify failed:self-signed certificate]")


def test_untrusted_certificate_is_classified_and_not_retried(caplog):
    connect = _FakeConnect([pyodbc.OperationalError("08001", _CERT_MESSAGE)] * 3)
    with pytest.raises(DatabaseConnectionError) as exc:
        connect_with_retry(_CONFIG, connect=connect, sleep=lambda s: None)
    assert (exc.value.error_class, exc.value.sqlstate) == ("TlsCertificateError", "08001")
    assert len(connect.calls) == 1
    assert "self-signed" not in str(exc.value) and "self-signed" not in caplog.text


def test_plain_08001_without_certificate_wording_is_still_unreachable():
    assert classify_error(pyodbc.OperationalError("08001", "TCP Provider: No such host is known.")) == ("UpstreamUnavailable", "08001")


@pytest.mark.parametrize("sqlstate, expected", [
    ("08001", "UpstreamUnavailable"), ("HYT00", "TimeoutError"), ("28000", "AuthError"),
    ("01000", "DriverNotFound"), ("XXXXX", "DatabaseError"),
])
def test_classify_error(sqlstate, expected):
    assert classify_error(pyodbc.Error(sqlstate, "msg")) == (expected, sqlstate)


def test_classify_error_without_a_sqlstate():
    assert classify_error(pyodbc.Error()) == ("DatabaseError", None)
