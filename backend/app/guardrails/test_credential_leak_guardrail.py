import pytest

from app.guardrails.credential_leak_guardrail import (
    CredentialLeakError,
    assert_no_credential_leaks,
    scan_text_for_credentials,
)


def test_happy_path_config_read_from_env_vars_and_safe_prose_produces_no_findings():
    content = "\n".join(
        [
            "api_key = os.environ['ANTHROPIC_API_KEY']",
            'client_secret = os.environ["BASECAMP_CLIENT_SECRET"]',
            "# Never place API keys in source code, browser JavaScript, or plain-text SQL tables.",
            "ANTHROPIC_API_KEY=your-key-here",
            'password = "changeme"',
        ]
    )
    assert scan_text_for_credentials(content) == []
    assert assert_no_credential_leaks(content, "example.py") == {"safe": True}


def test_detects_an_aws_access_key_id_literal():
    findings = scan_text_for_credentials('aws_access_key_id = "AKIAIOSFODNN7EXAMPLE"')
    assert len(findings) == 1
    assert findings[0]["pattern"] == "AWS_ACCESS_KEY_ID"


def test_detects_an_anthropic_shaped_api_key_literal():
    findings = scan_text_for_credentials('key = "sk-ant-api03-abcdefghijklmnopqrstuvwx"')
    assert any(f["pattern"] == "ANTHROPIC_API_KEY" for f in findings)


def test_detects_a_github_token_literal():
    findings = scan_text_for_credentials("token: ghp_16C7e42F292c6912E7710c838347Ae178B4a")
    assert any(f["pattern"] == "GITHUB_TOKEN" for f in findings)


def test_detects_a_private_key_block():
    findings = scan_text_for_credentials(
        "-----BEGIN RSA PRIVATE KEY-----\nMIIB...\n-----END RSA PRIVATE KEY-----"
    )
    assert any(f["pattern"] == "PRIVATE_KEY_BLOCK" for f in findings)


def test_detects_a_generic_secret_shaped_assignment_with_a_real_looking_value():
    findings = scan_text_for_credentials('DB_PASSWORD="tr0ub4dor&3-actual-value"')
    assert any(f["pattern"] == "GENERIC_SECRET_ASSIGNMENT" for f in findings)


def test_throws_credential_leak_error_never_including_the_raw_secret_text():
    content = 'api_key = "AKIAIOSFODNN7EXAMPLE-LOOKS-REAL"'
    with pytest.raises(CredentialLeakError) as exc_info:
        assert_no_credential_leaks(content, "config.py")
    err = exc_info.value
    assert err.error_class == "ContractViolation"
    assert err.source_label == "config.py"
    assert "AKIAIOSFODNN7EXAMPLE-LOOKS-REAL" not in str(err)


def test_empty_content_produces_no_findings():
    assert scan_text_for_credentials("") == []


def test_does_not_flag_placeholder_values_assigned_to_secret_shaped_keys():
    content = "\n".join(
        [
            "API_KEY=YOUR_API_KEY_HERE",
            'client_secret: "<client-secret>"',
            'token = "xxxxxxxxxxxxxxxxxxxx"',
            'password: "${DB_PASSWORD}"',
        ]
    )
    assert scan_text_for_credentials(content) == []


def test_does_not_flag_short_generic_values_below_the_real_secret_length_threshold():
    assert scan_text_for_credentials('token = "abc123"') == []


def test_non_string_input_produces_no_findings_instead_of_raising():
    assert scan_text_for_credentials(None) == []
    assert scan_text_for_credentials(42) == []


def test_idempotent_scanning_the_same_content_twice_yields_identical_results():
    content = 'aws_access_key_id = "AKIAIOSFODNN7EXAMPLE"\napi_key="another-real-looking-secret-value"'
    assert scan_text_for_credentials(content) == scan_text_for_credentials(content)
