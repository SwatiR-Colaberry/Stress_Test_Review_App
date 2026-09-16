from app.basecamp.critique_marker_detector import is_critique_marker, normalize_critique_marker


def test_accepts_the_four_documented_spacing_variants():
    for variant in ["##Critique##", "## Critique##", "##Critique ##", "## Critique ##"]:
        assert is_critique_marker(variant) is True, f'expected "{variant}" to trigger'
        assert normalize_critique_marker(variant) == "##Critique##"


def test_accepts_reasonable_case_variants_of_the_same_spacing_forms():
    for variant in ["##critique##", "##CRITIQUE##", "## CrItIqUe ##"]:
        assert is_critique_marker(variant) is True, f'expected "{variant}" to trigger'


def test_detects_the_marker_embedded_inside_a_larger_comment():
    assert is_critique_marker("Done with V2, ready for review. ##Critique##") is True


def test_rejects_plain_critique_with_no_delimiters():
    assert is_critique_marker("Critique") is False


def test_rejects_a_single_hash_critique():
    assert is_critique_marker("#Critique") is False


def test_rejects_double_hash_review():
    assert is_critique_marker("##Review##") is False


def test_rejects_ordinary_prose_containing_the_word_critique():
    assert is_critique_marker("Can you give this a quick critique when you have time?") is False


def test_rejects_non_string_input_without_raising():
    assert is_critique_marker(None) is False
    assert is_critique_marker(42) is False


def test_idempotent_evaluating_the_same_comment_twice_yields_the_same_result():
    body = "## Critique ##"
    assert is_critique_marker(body) == is_critique_marker(body)
    assert normalize_critique_marker(body) == normalize_critique_marker(body)
