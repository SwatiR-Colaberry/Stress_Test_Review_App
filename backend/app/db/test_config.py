import pytest

from app.db.config import DatabaseConfigError, build_connection_string, load_database_config

FAKE_PASSWORD = "fake-Pass;word}x"  # contains ODBC special characters on purpose
_BASE = {"DB_SERVER": "db.example.test", "DB_DATABASE": "ExampleDb", "DB_USERNAME": "reader", "DB_PASSWORD": FAKE_PASSWORD}


def _env(**overrides):
    env = dict(_BASE)
    env.update(overrides)
    return {k: v for k, v in env.items() if v is not None}


def test_loads_required_values_and_defaults():
    config = load_database_config(_env())
    assert (config.server, config.database, config.username) == ("db.example.test", "ExampleDb", "reader")
    assert config.driver == "ODBC Driver 18 for SQL Server"
    assert (config.encrypt, config.trust_server_certificate) == (True, False)
    assert (config.connect_timeout_s, config.query_timeout_s) == (30, 120)


def test_optional_values_override_defaults():
    config = load_database_config(_env(DB_ENCRYPT="no", DB_TRUST_SERVER_CERTIFICATE="YES", DB_CONNECT_TIMEOUT_S="10", DB_QUERY_TIMEOUT_S="600"))
    assert (config.encrypt, config.trust_server_certificate, config.connect_timeout_s, config.query_timeout_s) == (False, True, 10, 600)


def test_missing_required_values_are_all_named_in_one_error():
    with pytest.raises(DatabaseConfigError) as exc:
        load_database_config(_env(DB_SERVER=None, DB_PASSWORD="   "))
    assert "DB_SERVER" in str(exc.value) and "DB_PASSWORD" in str(exc.value)


def test_an_empty_environment_names_all_four_required_variables():
    with pytest.raises(DatabaseConfigError) as exc:
        load_database_config({})
    for var in ["DB_SERVER", "DB_DATABASE", "DB_USERNAME", "DB_PASSWORD"]:
        assert var in str(exc.value)


@pytest.mark.parametrize(
    "overrides",
    [{"DB_ENCRYPT": "maybe"}, {"DB_CONNECT_TIMEOUT_S": "0"}, {"DB_CONNECT_TIMEOUT_S": "abc"}, {"DB_QUERY_TIMEOUT_S": "99999"}, {"DB_QUERY_TIMEOUT_S": "-5"}],
)
def test_invalid_optional_values_are_rejected(overrides):
    with pytest.raises(DatabaseConfigError):
        load_database_config(_env(**overrides))


def test_password_never_appears_in_repr_or_errors():
    config = load_database_config(_env())
    assert FAKE_PASSWORD not in repr(config) and FAKE_PASSWORD not in str(config)
    with pytest.raises(DatabaseConfigError) as exc:
        load_database_config(_env(DB_SERVER=None))
    assert FAKE_PASSWORD not in str(exc.value)


def test_connection_string_braces_special_characters_and_is_read_only():
    conn = build_connection_string(load_database_config(_env()))
    assert "PWD={fake-Pass;word}}x};" in conn
    assert "DRIVER=ODBC Driver 18 for SQL Server;" in conn
    assert "Encrypt=yes;" in conn and "TrustServerCertificate=no;" in conn
    assert "Connection Timeout=30;" in conn
    assert "ApplicationIntent=ReadOnly;" in conn


def test_plain_values_are_not_braced():
    conn = build_connection_string(load_database_config(_env(DB_PASSWORD="plainvalue123")))
    assert "PWD=plainvalue123;" in conn
