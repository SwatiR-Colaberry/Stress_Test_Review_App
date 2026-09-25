import pytest

from app.basecamp.config import BasecampConfigError, load_basecamp_config

FAKE_TOKEN = "fake-oauth-token-for-tests-only"
VALID = {
    "BASECAMP_ACCOUNT_ID": "999999",
    "BASECAMP_ACCESS_TOKEN": FAKE_TOKEN,
    "BASECAMP_USER_AGENT": "Stress Test Review App (reviews@example.com)",
}


def test_loads_a_valid_config_with_default_timeout():
    config = load_basecamp_config(VALID)
    assert config.account_id == 999999
    assert config.base_url == "https://3.basecampapi.com/999999"
    assert config.timeout_s == 15.0


def test_auth_headers_use_oauth_bearer_token_and_user_agent():
    headers = load_basecamp_config(VALID).auth_headers()
    assert headers["Authorization"] == f"Bearer {FAKE_TOKEN}"
    assert headers["User-Agent"] == VALID["BASECAMP_USER_AGENT"]


def test_token_never_appears_in_repr_or_str():
    config = load_basecamp_config(VALID)
    assert FAKE_TOKEN not in repr(config)
    assert FAKE_TOKEN not in str(config)


def test_all_missing_variables_are_reported_together_by_name():
    with pytest.raises(BasecampConfigError) as exc:
        load_basecamp_config({})
    message = str(exc.value)
    for var in VALID:
        assert var in message


def test_blank_token_is_treated_as_missing():
    with pytest.raises(BasecampConfigError, match="BASECAMP_ACCESS_TOKEN"):
        load_basecamp_config({**VALID, "BASECAMP_ACCESS_TOKEN": "   "})


def test_non_numeric_account_id_is_rejected_without_echoing_the_token():
    with pytest.raises(BasecampConfigError) as exc:
        load_basecamp_config({**VALID, "BASECAMP_ACCOUNT_ID": "abc"})
    assert "BASECAMP_ACCOUNT_ID" in str(exc.value)
    assert FAKE_TOKEN not in str(exc.value)


@pytest.mark.parametrize("bad", ["0", "61", "ten", "-5"])
def test_out_of_range_timeout_is_rejected(bad):
    with pytest.raises(BasecampConfigError, match="BASECAMP_TIMEOUT_S"):
        load_basecamp_config({**VALID, "BASECAMP_TIMEOUT_S": bad})


def test_custom_timeout_is_used():
    assert load_basecamp_config({**VALID, "BASECAMP_TIMEOUT_S": "30"}).timeout_s == 30.0
