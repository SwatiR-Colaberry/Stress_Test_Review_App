import pytest

from app.posting.config import PostingConfigError, load_posting_config


def test_defaults_are_off_with_no_projects_allowed():
    config = load_posting_config({})
    assert config.enabled is False
    assert config.allowed_project_ids == frozenset()
    assert config.time_limit_s == 60.0


def test_reads_enabled_projects_and_time_limit():
    config = load_posting_config({
        "BASECAMP_POSTING_ENABLED": "YES",
        "BASECAMP_POSTING_PROJECT_IDS": " 111, 222 ,",
        "BASECAMP_POSTING_TIME_LIMIT_S": "30",
    })
    assert config.enabled is True
    assert config.allowed_project_ids == frozenset({111, 222})
    assert config.time_limit_s == 30.0


@pytest.mark.parametrize("env, variable", [
    ({"BASECAMP_POSTING_ENABLED": "true"}, "BASECAMP_POSTING_ENABLED"),
    ({"BASECAMP_POSTING_PROJECT_IDS": "111,abc"}, "BASECAMP_POSTING_PROJECT_IDS"),
    ({"BASECAMP_POSTING_PROJECT_IDS": "0"}, "BASECAMP_POSTING_PROJECT_IDS"),
    ({"BASECAMP_POSTING_TIME_LIMIT_S": "soon"}, "BASECAMP_POSTING_TIME_LIMIT_S"),
    ({"BASECAMP_POSTING_TIME_LIMIT_S": "4.5"}, "BASECAMP_POSTING_TIME_LIMIT_S"),
    ({"BASECAMP_POSTING_TIME_LIMIT_S": "301"}, "BASECAMP_POSTING_TIME_LIMIT_S"),
])
def test_bad_values_name_the_variable_but_not_the_value(env, variable):
    with pytest.raises(PostingConfigError) as caught:
        load_posting_config(env)
    assert variable in str(caught.value)
    assert list(env.values())[0] not in str(caught.value)


def test_all_problems_are_reported_together():
    with pytest.raises(PostingConfigError) as caught:
        load_posting_config({"BASECAMP_POSTING_ENABLED": "maybe", "BASECAMP_POSTING_TIME_LIMIT_S": "x"})
    assert "BASECAMP_POSTING_ENABLED" in str(caught.value)
    assert "BASECAMP_POSTING_TIME_LIMIT_S" in str(caught.value)
