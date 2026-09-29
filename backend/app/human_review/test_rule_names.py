import logging

from app.human_review.rule_names import rule_names


def test_the_real_st0_module_gives_readable_names():
    names = rule_names("ST0", "v1")
    assert names["ST0-002"] == "At least one valid public dataset source link is present"
    assert len(names) == 8


def test_an_unknown_version_falls_back_to_codes_and_warns(caplog):
    caplog.set_level(logging.WARNING, logger="stress_test_review.human_review")
    assert rule_names("ST0", "v99") == {}
    assert "rule_names_unavailable" in caplog.text


def test_a_corrupt_module_falls_back_to_codes(tmp_path):
    (tmp_path / "ST0").mkdir()
    (tmp_path / "ST0" / "v1.json").write_text("{not json")
    assert rule_names("ST0", "v1", modules_dir=tmp_path) == {}
