"""Sign-in settings (STORY-014): missing values reported by name, bad values refused."""
import pytest

from app.auth.config import AuthConfigError, load_auth_config

FULL = {"AUTH_BASECAMP_CLIENT_ID": "id", "AUTH_BASECAMP_CLIENT_SECRET": "shh-value",
        "AUTH_BASECAMP_REDIRECT_URI": "https://review.example.com/auth/callback",
        "BASECAMP_ACCOUNT_ID": "42", "BASECAMP_USER_AGENT": "App (a@example.com)"}


def test_a_complete_configuration_is_ready():
    config = load_auth_config(FULL)
    assert config.missing_settings == [] and config.account_id == 42 and config.cookie_secure is True
    assert "shh-value" not in repr(config)


def test_missing_settings_are_named_not_raised():
    assert load_auth_config({}).missing_settings == [
        "AUTH_BASECAMP_CLIENT_ID", "AUTH_BASECAMP_CLIENT_SECRET", "AUTH_BASECAMP_REDIRECT_URI",
        "BASECAMP_ACCOUNT_ID", "BASECAMP_USER_AGENT"]


@pytest.mark.parametrize("uri", ["http://localhost:8000/auth/callback", "http://127.0.0.1:8000/auth/callback"])
def test_plain_http_is_allowed_on_this_machine_only(uri):
    assert load_auth_config({**FULL, "AUTH_BASECAMP_REDIRECT_URI": uri}).redirect_uri == uri


@pytest.mark.parametrize("uri", ["http://review.example.com/auth/callback", "https://review.example.com/other",
                                 "ftp://localhost/auth/callback", "not a url"])
def test_an_unsafe_redirect_uri_is_refused(uri):
    with pytest.raises(AuthConfigError, match="AUTH_BASECAMP_REDIRECT_URI"):
        load_auth_config({**FULL, "AUTH_BASECAMP_REDIRECT_URI": uri})


def test_cookie_secure_can_be_turned_off_for_localhost_only_by_saying_no():
    assert load_auth_config({**FULL, "AUTH_COOKIE_SECURE": "no"}).cookie_secure is False
    with pytest.raises(AuthConfigError, match="AUTH_COOKIE_SECURE"):
        load_auth_config({**FULL, "AUTH_COOKIE_SECURE": "maybe"})


@pytest.mark.parametrize("account", ["abc", "0", "-5"])
def test_a_bad_account_id_is_refused(account):
    with pytest.raises(AuthConfigError, match="BASECAMP_ACCOUNT_ID"):
        load_auth_config({**FULL, "BASECAMP_ACCOUNT_ID": account})
