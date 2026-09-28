import pytest

from app.evaluation.config import EvaluationConfigError, load_evaluation_config

_KEY = "sk-ant-test-not-a-real-key-0000"


def test_defaults_apply_when_only_the_key_is_set():
    config = load_evaluation_config({"ANTHROPIC_API_KEY": _KEY})
    assert config.model == "claude-sonnet-5"
    assert (config.effort, config.timeout_s, config.max_retries) == ("low", 60, 2)
    assert (config.max_tokens, config.max_input_tokens, config.daily_token_limit) == (4000, 20000, 500000)


def test_settings_are_read_from_the_environment():
    config = load_evaluation_config({
        "ANTHROPIC_API_KEY": _KEY, "EVALUATION_MODEL": "claude-opus-5", "EVALUATION_EFFORT": "Medium",
        "EVALUATION_TIMEOUT_S": "30", "EVALUATION_MAX_RETRIES": "1", "EVALUATION_MAX_TOKENS": "2000",
        "EVALUATION_MAX_INPUT_TOKENS": "8000", "EVALUATION_DAILY_TOKEN_LIMIT": "100000",
    })
    assert (config.model, config.effort, config.timeout_s, config.max_retries) == ("claude-opus-5", "medium", 30, 1)
    assert (config.max_tokens, config.max_input_tokens, config.daily_token_limit) == (2000, 8000, 100000)


def test_a_missing_key_is_reported_by_name():
    with pytest.raises(EvaluationConfigError, match="ANTHROPIC_API_KEY is missing"):
        load_evaluation_config({})


@pytest.mark.parametrize(
    "var, value",
    [
        ("EVALUATION_EFFORT", "high"),  # only low or medium (token saving)
        ("EVALUATION_MAX_RETRIES", "3"),  # at most 2
        ("EVALUATION_TIMEOUT_S", "0"),
        ("EVALUATION_TIMEOUT_S", "abc"),
        ("EVALUATION_MAX_TOKENS", "100000"),
        ("EVALUATION_DAILY_TOKEN_LIMIT", "-5"),
    ],
)
def test_out_of_range_settings_are_rejected_by_name(var, value):
    with pytest.raises(EvaluationConfigError, match=var):
        load_evaluation_config({"ANTHROPIC_API_KEY": _KEY, var: value})


def test_all_problems_are_reported_together():
    with pytest.raises(EvaluationConfigError) as caught:
        load_evaluation_config({"EVALUATION_EFFORT": "max", "EVALUATION_MAX_RETRIES": "9"})
    message = str(caught.value)
    assert "ANTHROPIC_API_KEY" in message and "EVALUATION_EFFORT" in message and "EVALUATION_MAX_RETRIES" in message


def test_the_key_never_appears_in_repr_or_errors():
    config = load_evaluation_config({"ANTHROPIC_API_KEY": _KEY})
    assert _KEY not in repr(config) and _KEY not in str(config)
    with pytest.raises(EvaluationConfigError) as caught:
        load_evaluation_config({"ANTHROPIC_API_KEY": _KEY, "EVALUATION_EFFORT": "max"})
    assert _KEY not in str(caught.value)
